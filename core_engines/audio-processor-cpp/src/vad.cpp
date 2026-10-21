#include "vad.hpp"

#include <algorithm>
#include <cmath>

namespace nexus {

std::vector<std::span<const int16_t>> frame_views(std::span<const int16_t> samples, size_t frame_len) {
    std::vector<std::span<const int16_t>> frames;
    if (frame_len == 0) return frames;
    frames.reserve(samples.size() / frame_len + 1);
    for (size_t pos = 0; pos < samples.size(); pos += frame_len)
        frames.push_back(samples.subspan(pos, std::min(frame_len, samples.size() - pos)));
    return frames;
}

double rms_dbfs(std::span<const int16_t> frame) {
    if (frame.empty()) return -120.0;
    double sum = 0.0;
    for (int16_t s : frame) {
        const double v = static_cast<double>(s) / 32768.0;
        sum += v * v;
    }
    const double rms = std::sqrt(sum / static_cast<double>(frame.size()));
    return rms > 1e-6 ? std::max(-120.0, 20.0 * std::log10(rms)) : -120.0;
}

VadResult detect_speech(std::span<const int16_t> samples, int sample_rate, const VadConfig& config) {
    VadResult result;
    result.total_samples = samples.size();
    const auto frame_len = static_cast<size_t>(sample_rate) * static_cast<size_t>(config.frame_ms) / 1000;
    const auto frames = frame_views(samples, frame_len);
    const size_t hangover = static_cast<size_t>(config.hangover_ms / config.frame_ms);
    const size_t min_frames = std::max<size_t>(1, static_cast<size_t>(config.min_speech_ms / config.frame_ms));

    size_t run_start = 0, run_voiced = 0, silent_since = 0;
    bool in_speech = false;
    auto close_segment = [&](size_t end_frame) {
        if (run_voiced >= min_frames) {
            Segment seg{run_start * frame_len, std::min(samples.size(), end_frame * frame_len)};
            result.speech_samples += seg.end - seg.start;
            result.segments.push_back(seg);
        }
        in_speech = false;
        run_voiced = 0;
    };

    for (size_t i = 0; i < frames.size(); ++i) {
        const double level = rms_dbfs(frames[i]);
        result.peak_dbfs = std::max(result.peak_dbfs, level);
        const bool voiced = level > config.threshold_dbfs;
        if (voiced) {
            if (!in_speech) {
                in_speech = true;
                run_start = i;
            }
            ++run_voiced;
            silent_since = i + 1;
        } else if (in_speech && i - silent_since >= hangover) {
            close_segment(silent_since + hangover);
        }
    }
    if (in_speech) close_segment(std::min(frames.size(), silent_since + hangover));
    return result;
}

std::vector<int16_t> gather(std::span<const int16_t> samples, const std::vector<Segment>& segments) {
    std::vector<int16_t> out;
    size_t total = 0;
    for (const auto& s : segments) total += s.end - s.start;
    out.reserve(total);
    for (const auto& s : segments) out.insert(out.end(), samples.begin() + s.start, samples.begin() + s.end);
    return out;
}

}  // namespace nexus
