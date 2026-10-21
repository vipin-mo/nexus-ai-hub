// Unit tests for the DSP and protocol code (no model or network needed). Run with ctest.
#include <cmath>
#include <cstdio>
#include <filesystem>
#include <functional>
#include <iostream>
#include <numbers>
#include <string>
#include <vector>

#include "gateway_client.hpp"
#include "vad.hpp"
#include "wav.hpp"

namespace {

int g_failures = 0;
#define CHECK(cond)                                                                       \
    do {                                                                                  \
        if (!(cond)) {                                                                    \
            ++g_failures;                                                                 \
            std::cerr << "  FAILED " << __FILE__ << ":" << __LINE__ << "  " #cond "\n";   \
        }                                                                                 \
    } while (0)
#define CHECK_NEAR(a, b, eps) CHECK(std::fabs((a) - (b)) < (eps))

std::vector<int16_t> sine(double amplitude, double hz, int rate, double seconds) {
    std::vector<int16_t> out(static_cast<size_t>(rate * seconds));
    for (size_t i = 0; i < out.size(); ++i)
        out[i] = static_cast<int16_t>(std::lround(amplitude * 32767.0 * std::sin(2 * std::numbers::pi * hz * i / rate)));
    return out;
}

void test_rms_levels() {
    auto half = sine(0.5, 440, 16000, 0.5);
    CHECK_NEAR(nexus::rms_dbfs(half), 20 * std::log10(0.5 / std::sqrt(2.0)), 0.1);  // -9.03 dBFS
    std::vector<int16_t> square(1600);
    for (size_t i = 0; i < square.size(); ++i) square[i] = (i / 8) % 2 ? 32767 : -32767;
    CHECK_NEAR(nexus::rms_dbfs(square), 0.0, 0.01);
    std::vector<int16_t> silence(1600, 0);
    CHECK(nexus::rms_dbfs(silence) == -120.0);
}

void test_frame_views_do_not_copy() {
    std::vector<int16_t> samples(1000);
    auto frames = nexus::frame_views(samples, 300);
    CHECK(frames.size() == 4);
    CHECK(frames[0].data() == samples.data());
    CHECK(frames[1].data() == samples.data() + 300);
    CHECK(frames.back().size() == 100);
}

void test_vad_finds_tone_between_silence() {
    const int rate = 16000;
    std::vector<int16_t> audio(rate, 0);                     // 1 s silence
    auto tone = sine(0.3, 300, rate, 1.0);                  // 1 s "speech"
    audio.insert(audio.end(), tone.begin(), tone.end());
    audio.insert(audio.end(), static_cast<size_t>(rate), 0);  // 1 s silence
    auto result = nexus::detect_speech(audio, rate);
    CHECK(result.segments.size() == 1);
    if (!result.segments.empty()) {
        CHECK_NEAR(static_cast<double>(result.segments[0].start), rate, rate * 0.03);
        const double end_s = static_cast<double>(result.segments[0].end) / rate;
        CHECK(end_s > 2.0 && end_s < 2.4);                   // tone end + hangover
    }
    CHECK(result.speech_ratio() > 0.3 && result.speech_ratio() < 0.45);
    auto gathered = nexus::gather(audio, result.segments);
    CHECK(gathered.size() == result.speech_samples);
}

void test_vad_ignores_silence_and_clicks() {
    const int rate = 16000;
    std::vector<int16_t> audio(rate * 2, 0);
    for (int i = 0; i < 200; ++i) audio[8000 + i] = 20000;   // 12 ms click
    auto result = nexus::detect_speech(audio, rate);
    CHECK(result.segments.empty());
    CHECK(result.speech_ratio() == 0.0);
}

void test_wav_roundtrip_downmix_and_resample() {
    const auto dir = std::filesystem::temp_directory_path();
    nexus::PcmAudio mono{44100, sine(0.25, 440, 44100, 0.5)};
    nexus::write_wav(dir / "nexus_test_mono.wav", mono);
    auto read = nexus::read_wav(dir / "nexus_test_mono.wav");
    CHECK(read.sample_rate == 44100);
    CHECK(read.samples == mono.samples);

    auto resampled = nexus::resample(read, nexus::kTargetSampleRate);
    CHECK(resampled.sample_rate == 16000);
    CHECK(resampled.samples.size() == 8000);
    CHECK_NEAR(nexus::rms_dbfs(resampled.samples), nexus::rms_dbfs(read.samples), 0.2);

    // Hand-built stereo file: left = +1000, right = -3000 -> mono average -1000
    std::FILE* f = std::fopen((dir / "nexus_test_stereo.wav").string().c_str(), "wb");
    const unsigned char header[] = {'R', 'I', 'F', 'F', 44, 0, 0, 0, 'W', 'A', 'V', 'E', 'f', 'm', 't', ' ', 16, 0, 0, 0,
                                    1, 0, 2, 0, 0x80, 0x3E, 0, 0, 0, 0xFA, 0, 0, 4, 0, 16, 0,
                                    'd', 'a', 't', 'a', 8, 0, 0, 0};
    const int16_t frames[] = {1000, -3000, 1000, -3000};
    std::fwrite(header, 1, sizeof header, f);
    std::fwrite(frames, 2, 4, f);
    std::fclose(f);
    auto stereo = nexus::read_wav(dir / "nexus_test_stereo.wav");
    CHECK(stereo.sample_rate == 16000);
    CHECK(stereo.samples.size() == 2 && stereo.samples[0] == -1000);
}

void test_wav_rejects_bad_input() {
    const auto path = std::filesystem::temp_directory_path() / "nexus_test_bad.wav";
    std::FILE* f = std::fopen(path.string().c_str(), "wb");
    std::fputs("not a wav file at all", f);
    std::fclose(f);
    bool threw = false;
    try {
        nexus::read_wav(path);
    } catch (const nexus::WavError&) {
        threw = true;
    }
    CHECK(threw);
}

void test_json_escape() {
    CHECK(nexus::json_escape("say \"hi\"\n\tok\\") == "say \\\"hi\\\"\\n\\tok\\\\");
    CHECK(nexus::json_escape(std::string("a\x01" "b")) == "a\\u0001b");
    CHECK(nexus::json_escape("caf\xc3\xa9") == "caf\xc3\xa9");  // UTF-8 preserved
}

}  // namespace

int main() {
    const std::vector<std::pair<const char*, std::function<void()>>> tests = {
        {"rms levels", test_rms_levels},
        {"frame views do not copy", test_frame_views_do_not_copy},
        {"vad finds tone between silence", test_vad_finds_tone_between_silence},
        {"vad ignores silence and clicks", test_vad_ignores_silence_and_clicks},
        {"wav roundtrip, downmix, resample", test_wav_roundtrip_downmix_and_resample},
        {"wav rejects bad input", test_wav_rejects_bad_input},
        {"json escape", test_json_escape},
    };
    for (const auto& [name, fn] : tests) {
        const int before = g_failures;
        fn();
        std::cout << (g_failures == before ? "PASS " : "FAIL ") << name << "\n";
    }
    std::cout << (g_failures ? "FAILED" : "ALL PASSED") << " (" << g_failures << " failures)\n";
    return g_failures ? 1 : 0;
}
