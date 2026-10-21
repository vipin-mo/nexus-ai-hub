#include "transcriber.hpp"

#include <chrono>
#include <stdexcept>

#include "wav.hpp"

#ifdef NEXUS_WITH_WHISPER
#include "whisper.h"
#endif

namespace nexus {

#ifdef NEXUS_WITH_WHISPER

namespace {
void quiet_log(ggml_log_level level, const char* text, void*) {
    if (level >= GGML_LOG_LEVEL_WARN) fputs(text, stderr);
}
}  // namespace

void Transcriber::Deleter::operator()(whisper_context* ctx) const { whisper_free(ctx); }

Transcriber::Transcriber(const std::string& model_path, int threads, std::string language)
    : threads_(threads), language_(std::move(language)) {
    whisper_log_set(quiet_log, nullptr);
    whisper_context_params params = whisper_context_default_params();
    ctx_.reset(whisper_init_from_file_with_params(model_path.c_str(), params));
    if (!ctx_) throw std::runtime_error("failed to load whisper model " + model_path);
}

Transcriber::~Transcriber() = default;

Transcript Transcriber::transcribe(const std::vector<float>& samples) const {
    Transcript out;
    out.audio_ms = 1000.0 * static_cast<double>(samples.size()) / kTargetSampleRate;
    if (samples.empty()) return out;

    whisper_full_params params = whisper_full_default_params(WHISPER_SAMPLING_GREEDY);
    params.n_threads = threads_;
    params.language = language_.c_str();
    params.no_timestamps = true;
    params.print_progress = false;
    params.print_realtime = false;
    params.print_special = false;
    params.print_timestamps = false;
    params.suppress_blank = true;
    params.no_context = true;

    const auto started = std::chrono::steady_clock::now();
    if (whisper_full(ctx_.get(), params, samples.data(), static_cast<int>(samples.size())) != 0)
        throw std::runtime_error("whisper_full failed");
    out.latency_ms = std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - started).count();

    for (int i = 0, n = whisper_full_n_segments(ctx_.get()); i < n; ++i) out.text += whisper_full_get_segment_text(ctx_.get(), i);
    const auto first = out.text.find_first_not_of(" \t\n");
    const auto last = out.text.find_last_not_of(" \t\n");
    out.text = first == std::string::npos ? "" : out.text.substr(first, last - first + 1);
    return out;
}

bool Transcriber::available() { return true; }

#else  // built without whisper.cpp (NEXUS_WITH_WHISPER=OFF): DSP and gateway code still work

void Transcriber::Deleter::operator()(whisper_context*) const {}
Transcriber::Transcriber(const std::string&, int threads, std::string language)
    : threads_(threads), language_(std::move(language)) {
    throw std::runtime_error("built without whisper.cpp; reconfigure with -DNEXUS_WITH_WHISPER=ON");
}
Transcriber::~Transcriber() = default;
Transcript Transcriber::transcribe(const std::vector<float>&) const { return {}; }
bool Transcriber::available() { return false; }

#endif

}  // namespace nexus
