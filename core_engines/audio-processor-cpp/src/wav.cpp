#include "wav.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstring>
#include <fstream>

namespace nexus {
namespace {

uint32_t read_u32(const uint8_t* p) {
    return static_cast<uint32_t>(p[0]) | (static_cast<uint32_t>(p[1]) << 8) |
           (static_cast<uint32_t>(p[2]) << 16) | (static_cast<uint32_t>(p[3]) << 24);
}

uint16_t read_u16(const uint8_t* p) { return static_cast<uint16_t>(p[0] | (p[1] << 8)); }

void put_u32(std::ofstream& out, uint32_t v) {
    const std::array<char, 4> b{static_cast<char>(v & 0xff), static_cast<char>((v >> 8) & 0xff),
                                static_cast<char>((v >> 16) & 0xff), static_cast<char>((v >> 24) & 0xff)};
    out.write(b.data(), 4);
}

void put_u16(std::ofstream& out, uint16_t v) {
    const std::array<char, 2> b{static_cast<char>(v & 0xff), static_cast<char>((v >> 8) & 0xff)};
    out.write(b.data(), 2);
}

}  // namespace

PcmAudio read_wav(const std::filesystem::path& path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) throw WavError("cannot open " + path.string());
    std::vector<uint8_t> data((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
    if (data.size() < 12 || std::memcmp(data.data(), "RIFF", 4) != 0 || std::memcmp(data.data() + 8, "WAVE", 4) != 0)
        throw WavError(path.string() + " is not a RIFF/WAVE file");

    uint16_t format = 0, channels = 0, bits = 0;
    uint32_t rate = 0;
    const uint8_t* pcm = nullptr;
    size_t pcm_bytes = 0;
    for (size_t pos = 12; pos + 8 <= data.size();) {
        const uint8_t* chunk = data.data() + pos;
        const uint32_t size = read_u32(chunk + 4);
        const size_t body = pos + 8;
        if (body + size > data.size()) throw WavError("truncated chunk in " + path.string());
        if (std::memcmp(chunk, "fmt ", 4) == 0 && size >= 16) {
            format = read_u16(chunk + 8);
            channels = read_u16(chunk + 10);
            rate = read_u32(chunk + 12);
            bits = read_u16(chunk + 22);
            if (format == 0xFFFE && size >= 40) format = read_u16(chunk + 32);  // WAVE_FORMAT_EXTENSIBLE
        } else if (std::memcmp(chunk, "data", 4) == 0) {
            pcm = data.data() + body;
            pcm_bytes = size;
        }
        pos = body + size + (size & 1);  // chunks are word aligned
    }
    if (format != 1 || bits != 16) throw WavError("only 16-bit PCM WAV is supported");
    if (channels < 1 || channels > 2) throw WavError("only mono or stereo WAV is supported");
    if (rate == 0 || pcm == nullptr) throw WavError("missing fmt or data chunk");

    PcmAudio out;
    out.sample_rate = static_cast<int>(rate);
    const size_t frames = pcm_bytes / (2u * channels);
    out.samples.resize(frames);
    for (size_t i = 0; i < frames; ++i) {
        int sum = 0;
        for (int c = 0; c < channels; ++c) sum += static_cast<int16_t>(read_u16(pcm + 2 * (i * channels + c)));
        out.samples[i] = static_cast<int16_t>(sum / channels);
    }
    return out;
}

void write_wav(const std::filesystem::path& path, const PcmAudio& audio) {
    std::ofstream out(path, std::ios::binary);
    if (!out) throw WavError("cannot write " + path.string());
    const auto bytes = static_cast<uint32_t>(audio.samples.size() * 2);
    out.write("RIFF", 4);
    put_u32(out, 36 + bytes);
    out.write("WAVEfmt ", 8);
    put_u32(out, 16);
    put_u16(out, 1);
    put_u16(out, 1);
    put_u32(out, static_cast<uint32_t>(audio.sample_rate));
    put_u32(out, static_cast<uint32_t>(audio.sample_rate) * 2);
    put_u16(out, 2);
    put_u16(out, 16);
    out.write("data", 4);
    put_u32(out, bytes);
    out.write(reinterpret_cast<const char*>(audio.samples.data()), bytes);  // host is little-endian
}

PcmAudio resample(const PcmAudio& in, int target_rate) {
    if (in.sample_rate == target_rate || in.samples.empty()) return in;
    PcmAudio out;
    out.sample_rate = target_rate;
    const double ratio = static_cast<double>(in.sample_rate) / target_rate;
    const auto n = static_cast<size_t>(static_cast<double>(in.samples.size()) / ratio);
    out.samples.resize(n);
    for (size_t i = 0; i < n; ++i) {
        const double src = static_cast<double>(i) * ratio;
        const auto j = static_cast<size_t>(src);
        const double frac = src - static_cast<double>(j);
        const double a = in.samples[std::min(j, in.samples.size() - 1)];
        const double b = in.samples[std::min(j + 1, in.samples.size() - 1)];
        out.samples[i] = static_cast<int16_t>(std::lround(a + (b - a) * frac));
    }
    return out;
}

std::vector<float> to_float(const std::vector<int16_t>& samples) {
    std::vector<float> out(samples.size());
    std::transform(samples.begin(), samples.end(), out.begin(), [](int16_t s) { return static_cast<float>(s) / 32768.0f; });
    return out;
}

}  // namespace nexus
