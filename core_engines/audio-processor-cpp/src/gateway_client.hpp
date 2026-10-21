#pragma once

#include <chrono>
#include <memory>
#include <string>

namespace nexus {

std::string json_escape(const std::string& in);

struct HttpResult {
    long status = 0;      // 0 = no HTTP response (connection error)
    std::string body;
    std::string error;    // libcurl error text when status == 0
    int attempts = 0;
};

// Process-wide libcurl initialisation (RAII). Construct once in main().
class CurlGlobal {
  public:
    CurlGlobal();
    ~CurlGlobal();
    CurlGlobal(const CurlGlobal&) = delete;
    CurlGlobal& operator=(const CurlGlobal&) = delete;
};

// POSTs JSON to the gateway with the ingest API key. Retries with exponential backoff on
// connection errors, 429 and 5xx (the gateway may still be starting); 4xx are not retried.
class GatewayClient {
  public:
    GatewayClient(std::string url, std::string api_key, std::chrono::seconds timeout, int max_attempts = 6);
    HttpResult post_json(const std::string& body) const;

  private:
    std::string url_;
    std::string api_key_;
    std::chrono::seconds timeout_;
    int max_attempts_;
};

}  // namespace nexus
