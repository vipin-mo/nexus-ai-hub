#pragma once

#include <cstddef>
#include <cstdint>
#include <span>
#include <vector>

namespace nexus {

// Energy-based voice activity detection. Frames are std::span views into the decoded buffer,
// so framing an hour of audio allocates only the vector of views, never a copy of samples.

struct VadConfig {
    int frame_ms = 30;
    double threshold_dbfs = -40.0;  // frames louder than this count as speech
    int min_speech_ms = 200;        // shorter bursts (clicks) are ignored
    int hangover_ms = 300;          // keep this much audio after speech ends (trailing consonants)
};

struct Segment {
    size_t start = 0;  // sample index, inclusive
    size_t end = 0;    // sample index, exclusive
};

struct VadResult {
    std::vector<Segment> segments;
    size_t speech_samples = 0;
    size_t total_samples = 0;
    double peak_dbfs = -120.0;

    [[nodiscard]] double speech_ratio() const {
        return total_samples ? static_cast<double>(speech_samples) / static_cast<double>(total_samples) : 0.0;
    }
};

std::vector<std::span<const int16_t>> frame_views(std::span<const int16_t> samples, size_t frame_len);

// Root-mean-square level relative to full scale; silence is clamped to -120 dBFS.
double rms_dbfs(std::span<const int16_t> frame);

VadResult detect_speech(std::span<const int16_t> samples, int sample_rate, const VadConfig& config = {});

// Concatenates the speech segments (what is sent to the recogniser).
std::vector<int16_t> gather(std::span<const int16_t> samples, const std::vector<Segment>& segments);

}  // namespace nexus
