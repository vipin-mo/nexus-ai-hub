#pragma once

#include <cstdint>
#include <filesystem>
#include <stdexcept>
#include <vector>

namespace nexus {

constexpr int kTargetSampleRate = 16000;  // whisper.cpp expects 16 kHz mono

struct PcmAudio {
    int sample_rate = 0;
    std::vector<int16_t> samples;  // mono

    [[nodiscard]] double duration_ms() const {
        return sample_rate ? 1000.0 * static_cast<double>(samples.size()) / sample_rate : 0.0;
    }
};

class WavError : public std::runtime_error {
  public:
    using std::runtime_error::runtime_error;
};

// Reads a RIFF/WAVE file with 16-bit PCM samples (1 or 2 channels, any sample rate).
// Unknown chunks (LIST, fact, ...) are skipped. Stereo is averaged to mono.
PcmAudio read_wav(const std::filesystem::path& path);

// Writes 16-bit mono PCM (used by tests and tools).
void write_wav(const std::filesystem::path& path, const PcmAudio& audio);

// Linear-interpolation resampler; returns the input unchanged if rates match.
PcmAudio resample(const PcmAudio& in, int target_rate);

// Converts to the float [-1, 1) range whisper.cpp consumes.
std::vector<float> to_float(const std::vector<int16_t>& samples);

}  // namespace nexus
