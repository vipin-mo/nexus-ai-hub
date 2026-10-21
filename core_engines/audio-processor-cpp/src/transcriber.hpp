#pragma once

#include <memory>
#include <string>
#include <vector>

struct whisper_context;

namespace nexus {

struct Transcript {
    std::string text;
    double latency_ms = 0.0;
    double audio_ms = 0.0;

    // Real-time factor: processing time / audio duration (< 1 is faster than real time).
    [[nodiscard]] double rtf() const { return audio_ms > 0 ? latency_ms / audio_ms : 0.0; }
};

// Owns a whisper.cpp context (RAII). Not thread-safe; use one instance per worker thread.
class Transcriber {
  public:
    Transcriber(const std::string& model_path, int threads, std::string language = "en");
    ~Transcriber();
    Transcriber(const Transcriber&) = delete;
    Transcriber& operator=(const Transcriber&) = delete;

    // samples: 16 kHz mono float PCM in [-1, 1)
    Transcript transcribe(const std::vector<float>& samples) const;

    static bool available();

  private:
    struct Deleter {
        void operator()(whisper_context* ctx) const;
    };
    std::unique_ptr<whisper_context, Deleter> ctx_;
    int threads_;
    std::string language_;
};

}  // namespace nexus
