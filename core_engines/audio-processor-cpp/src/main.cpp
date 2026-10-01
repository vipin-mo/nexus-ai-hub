#include <iostream>
#include <vector>
#include <string>
#include <chrono>
#include <thread>
#include <memory>
#include <utility>
#include <cstdlib>
#include <curl/curl.h>
#include "audio_chunker.hpp"

// Structure defining raw telemetry frame
struct AudioFrame {
    uint32_t frame_id;
    std::vector<int16_t> pcm_payload;
    double amplitude_db;
};

// Core Pipeline Processor Implementation
class IngestionPipeline {
private:
    std::string fallback_target_route;
    uint32_t total_processed_frames;

    // Helper method to dispatch payload safely via libcurl
    void dispatchToGateway(uint32_t frameId, double amplitude) {
        CURL* curl = curl_easy_init();
        if (!curl) {
            std::cerr << "❌ [C++ Core Engine] Failed to initialize libcurl handle." << std::endl;
            return;
        }

        // Construct a simple JSON payload manually to keep dependencies light
        std::string json_payload = "{\"frame_id\":" + std::to_string(frameId) +
                                   ",\"amplitude_db\":" + std::to_string(amplitude) +
                                   ",\"status\":\"SPEECH_DETECTED\"}";

        // Configure standard HTTP POST settings
        curl_easy_setopt(curl, CURLOPT_URL, fallback_target_route.c_str());
        curl_easy_setopt(curl, CURLOPT_POST, 1L);
        curl_easy_setopt(curl, CURLOPT_POSTFIELDS, json_payload.c_str());

        // Match network timeout metrics to guarantee low-latency processing bounds
        curl_easy_setopt(curl, CURLOPT_TIMEOUT, 5L);

        // Set structural HTTP header options
        struct curl_slist* headers = nullptr;
        headers = curl_slist_append(headers, "Content-Type: application/json");
        curl_easy_setopt(curl, CURLOPT_HTTPHEADER, headers);

        // Execute the synchronous network block frame transfer
        CURLcode res = curl_easy_perform(curl);
        if (res != CURLE_OK) {
            std::cerr << "⚠️ [Network Dispatched Drop] Gateway post failed: "
                      << curl_easy_strerror(res) << std::endl;
        } else {
            long response_code = 0;
            curl_easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &response_code);
            std::cout << "✅ [Network Dispatched Success] Gateway returned HTTP "
                      << response_code << std::endl;
        }

        // Clean up resources cleanly
        curl_slist_free_all(headers);
        curl_easy_cleanup(curl);
    }

public:
    explicit IngestionPipeline(std::string target)
        : fallback_target_route(std::move(target)), total_processed_frames(0) {}

    void processAudioStreamFrame(const std::shared_ptr<AudioFrame>& frame) {
        total_processed_frames++;

        std::cout << "🎙️  [C++ Core Engine] Processing Audio Frame ID: " << frame->frame_id
                  << " | Size: " << frame->pcm_payload.size() << " samples"
                  << " | Energy: " << frame->amplitude_db << " dB" << std::endl;

        std::this_thread::sleep_for(std::chrono::milliseconds(15));

        if (frame->amplitude_db > -20.0) {
            std::cout << "🚀 [C++ Core Engine] Human Speech Identified on Frame " << frame->frame_id
                      << ". Dispatching transcription tokens to Java Gateway REST endpoint ["
                      << fallback_target_route << "]..." << std::endl;

            // Fulfills the missing REST network dispatch logic
            dispatchToGateway(frame->frame_id, frame->amplitude_db);
        }
    }

    [[nodiscard]] uint32_t getProcessedFrameCount() const {
        return total_processed_frames;
    }
};

int main() {
    // Globally initialize curl environment state once upon initial engine execution
    curl_global_init(CURL_GLOBAL_ALL);

    std::cout << "========================================================================\n"
              << "Starting High-Performance NexusAI Audio Ingestion Node...\n"
              << "========================================================================" << std::endl;

    // Dynamically fetch target URL from environment or fallback to default service route
    const char* env_gateway = std::getenv("GATEWAY_URL");
    std::string gateway_url = (env_gateway != nullptr) ? std::string(env_gateway) : "http://gateway-service:8080/api/v1/gateway/dispatch";

    AudioChunker chunker;
    auto pipeline = std::make_unique<IngestionPipeline>(gateway_url);

    for (uint32_t i = 1; i <= 3; ++i) {
        std::vector<int16_t> mock_buffer(16000, 0);
        chunker.sliceRawBuffer(mock_buffer, 4000);

        auto mock_frame = std::make_shared<AudioFrame>();
        mock_frame->frame_id = i;
        mock_frame->pcm_payload = mock_buffer;
        mock_frame->amplitude_db = (i == 2) ? -12.5 : -45.0;

        pipeline->processAudioStreamFrame(mock_frame);
    }

    std::cout << "------------------------------------------------------------------------\n"
              << "Stream analysis complete. Total frame elements captured: "
              << pipeline->getProcessedFrameCount() << "\n"
              << "Entering background listener thread lifecycle loop..." << std::endl;

    while (true) {
        std::this_thread::sleep_for(std::chrono::hours(1));
    }

    // Clean up curl globally before process termination
    curl_global_cleanup();
    return 0;
}
