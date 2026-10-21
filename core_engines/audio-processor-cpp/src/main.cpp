// NexusAI audio ingestion: WAV -> voice activity detection -> whisper.cpp speech-to-text ->
// transcript POSTed to the Java gateway (which authenticates, audits and forwards it to the agent).
//
//   audio_processor --file question.wav [--no-send]        process one file, print JSON
//   audio_processor --watch data/audio_inbox               service mode: process files as they arrive
//   audio_processor --bench question.wav [--runs 5]        timing breakdown and real-time factor
//
// Environment: WHISPER_MODEL, GATEWAY_URL, NEXUS_INGEST_API_KEY, WHISPER_THREADS.

#include <atomic>
#include <chrono>
#include <csignal>
#include <cstdlib>
#include <algorithm>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <optional>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

#include "gateway_client.hpp"
#include "transcriber.hpp"
#include "vad.hpp"
#include "wav.hpp"

namespace fs = std::filesystem;
using Clock = std::chrono::steady_clock;

namespace {

std::atomic<bool> g_stop{false};
void on_signal(int) { g_stop = true; }

std::string env_or(const char* name, const std::string& fallback) {
    const char* v = std::getenv(name);
    return v && *v ? std::string(v) : fallback;
}

double ms_since(Clock::time_point t) { return std::chrono::duration<double, std::milli>(Clock::now() - t).count(); }

struct FileResult {
    std::string file;
    double duration_ms = 0, speech_ratio = 0, peak_dbfs = -120;
    double decode_ms = 0, vad_ms = 0, stt_ms = 0, rtf = 0;
    std::string transcript;
    long http_status = 0;
    std::string gateway_reply;
    std::string error;

    [[nodiscard]] std::string to_json() const {
        std::ostringstream o;
        o << std::fixed << std::setprecision(2) << "{\"file\":\"" << nexus::json_escape(file) << "\""
          << ",\"duration_ms\":" << duration_ms << ",\"speech_ratio\":" << speech_ratio
          << ",\"peak_dbfs\":" << peak_dbfs << ",\"decode_ms\":" << decode_ms << ",\"vad_ms\":" << vad_ms
          << ",\"stt_ms\":" << stt_ms << ",\"rtf\":" << std::setprecision(4) << rtf
          << ",\"transcript\":\"" << nexus::json_escape(transcript) << "\",\"http_status\":" << http_status;
        if (!error.empty()) o << ",\"error\":\"" << nexus::json_escape(error) << "\"";
        if (!gateway_reply.empty()) o << ",\"gateway_reply\":" << gateway_reply;
        o << "}";
        return o.str();
    }
};

class Pipeline {
  public:
    Pipeline(const nexus::Transcriber& stt, const nexus::GatewayClient* gateway) : stt_(stt), gateway_(gateway) {}

    FileResult process(const fs::path& path) const {
        FileResult r;
        r.file = path.filename().string();
        auto t = Clock::now();
        const nexus::PcmAudio audio = nexus::resample(nexus::read_wav(path), nexus::kTargetSampleRate);
        r.decode_ms = ms_since(t);
        r.duration_ms = audio.duration_ms();

        t = Clock::now();
        const nexus::VadResult vad = nexus::detect_speech(audio.samples, audio.sample_rate);
        r.vad_ms = ms_since(t);
        r.speech_ratio = vad.speech_ratio();
        r.peak_dbfs = vad.peak_dbfs;
        if (vad.segments.empty()) {
            r.error = "no speech detected";  // nothing sent: silence never reaches the models
            return r;
        }

        const auto transcript = stt_.transcribe(nexus::to_float(nexus::gather(audio.samples, vad.segments)));
        r.transcript = transcript.text;
        r.stt_ms = transcript.latency_ms;
        r.rtf = r.duration_ms > 0 ? r.stt_ms / r.duration_ms : 0;
        if (r.transcript.empty()) {
            r.error = "empty transcript";
            return r;
        }
        if (gateway_) {
            std::ostringstream body;
            body << std::fixed << std::setprecision(3) << "{\"transcript\":\"" << nexus::json_escape(r.transcript)
                 << "\",\"audioFile\":\"" << nexus::json_escape(r.file) << "\",\"durationMs\":"
                 << static_cast<long>(r.duration_ms) << ",\"speechRatio\":" << r.speech_ratio
                 << ",\"sttLatencyMs\":" << static_cast<long>(r.stt_ms) << "}";
            const auto reply = gateway_->post_json(body.str());
            r.http_status = reply.status;
            if (reply.status == 0) r.error = reply.error;
            else if (!reply.body.empty() && reply.body.front() == '{') r.gateway_reply = reply.body;
        }
        return r;
    }

  private:
    const nexus::Transcriber& stt_;
    const nexus::GatewayClient* gateway_;
};

int watch(const Pipeline& pipeline, const fs::path& inbox) {
    const fs::path done = inbox.parent_path() / "audio_processed";
    const fs::path failed = inbox.parent_path() / "audio_failed";
    fs::create_directories(inbox);
    fs::create_directories(done);
    fs::create_directories(failed);
    std::cerr << "[watch] listening for .wav files in " << inbox << "\n";
    while (!g_stop) {
        std::vector<fs::path> pending;
        for (const auto& entry : fs::directory_iterator(inbox))
            if (entry.is_regular_file() && entry.path().extension() == ".wav") pending.push_back(entry.path());
        std::sort(pending.begin(), pending.end());
        for (const auto& path : pending) {
            if (g_stop) break;
            // Skip files that are still being written (size changing).
            const auto size = fs::file_size(path);
            std::this_thread::sleep_for(std::chrono::milliseconds(200));
            if (!fs::exists(path) || fs::file_size(path) != size) continue;
            FileResult r;
            try {
                r = pipeline.process(path);
            } catch (const std::exception& e) {
                r.file = path.filename().string();
                r.error = e.what();
            }
            const bool ok = r.error.empty() && r.http_status >= 200 && r.http_status < 300;
            const fs::path dest = (ok || r.error == "no speech detected" ? done : failed) / path.filename();
            fs::rename(path, dest);
            std::ofstream(fs::path(dest).replace_extension(".json")) << r.to_json() << "\n";
            std::cout << r.to_json() << std::endl;
        }
        std::this_thread::sleep_for(std::chrono::seconds(1));
    }
    std::cerr << "[watch] stopping\n";
    return 0;
}

int bench(const nexus::Transcriber& stt, const fs::path& file, int runs) {
    Pipeline pipeline(stt, nullptr);
    pipeline.process(file);  // warm-up (model weights into cache, GPU kernels compiled)
    double decode = 0, vad = 0, total_stt = 0, duration = 0;
    for (int i = 0; i < runs; ++i) {
        const auto r = pipeline.process(file);
        decode += r.decode_ms;
        vad += r.vad_ms;
        total_stt += r.stt_ms;
        duration = r.duration_ms;
    }
    std::cout << std::fixed << std::setprecision(3) << "{\"file\":\"" << nexus::json_escape(file.filename().string())
              << "\",\"runs\":" << runs << ",\"audio_ms\":" << duration << ",\"decode_ms\":" << decode / runs
              << ",\"vad_ms\":" << vad / runs << ",\"stt_ms\":" << total_stt / runs
              << ",\"rtf\":" << (total_stt / runs) / duration << "}" << std::endl;
    return 0;
}

void usage() {
    std::cerr << "usage: audio_processor (--file F.wav [--no-send] | --watch DIR | --bench F.wav [--runs N])"
                 " [--model PATH]\n";
}

}  // namespace

int main(int argc, char** argv) {
    std::signal(SIGINT, on_signal);
    std::signal(SIGTERM, on_signal);
    nexus::CurlGlobal curl;

    std::optional<std::string> file, watch_dir, bench_file;
    std::string model = env_or("WHISPER_MODEL", "models/whisper/ggml-base.en.bin");
    bool send = true;
    int runs = 5;
    for (int i = 1; i < argc; ++i) {
        const std::string a = argv[i];
        auto next = [&]() -> std::string {
            if (i + 1 >= argc) throw std::invalid_argument(a + " needs a value");
            return argv[++i];
        };
        try {
            if (a == "--file") file = next();
            else if (a == "--watch") watch_dir = next();
            else if (a == "--bench") bench_file = next();
            else if (a == "--model") model = next();
            else if (a == "--runs") runs = std::stoi(next());
            else if (a == "--no-send") send = false;
            else { usage(); return 2; }
        } catch (const std::exception& e) {
            std::cerr << e.what() << "\n";
            return 2;
        }
    }
    if (!file && !watch_dir && !bench_file) {
        usage();
        return 2;
    }

    const int threads = std::stoi(env_or("WHISPER_THREADS", std::to_string(std::max(1u, std::thread::hardware_concurrency() / 2))));
    std::unique_ptr<nexus::Transcriber> stt;
    try {
        stt = std::make_unique<nexus::Transcriber>(model, threads);
    } catch (const std::exception& e) {
        std::cerr << "error: " << e.what() << "\n  download the model with scripts/download_whisper_model.sh\n";
        return 1;
    }
    if (bench_file) return bench(*stt, *bench_file, runs);

    std::optional<nexus::GatewayClient> gateway;
    if (send) {
        const std::string key = env_or("NEXUS_INGEST_API_KEY", "");
        if (key.empty()) {
            std::cerr << "error: NEXUS_INGEST_API_KEY is not set (use --no-send to only transcribe)\n";
            return 1;
        }
        gateway.emplace(env_or("GATEWAY_URL", "http://localhost:8080/api/v1/audio/transcripts"), key,
                        std::chrono::seconds(150));
    }
    Pipeline pipeline(*stt, gateway ? &*gateway : nullptr);
    if (watch_dir) return watch(pipeline, *watch_dir);
    try {
        const auto r = pipeline.process(*file);
        std::cout << r.to_json() << std::endl;
        return r.error.empty() ? 0 : 1;
    } catch (const std::exception& e) {
        std::cerr << "error: " << e.what() << "\n";
        return 1;
    }
}
