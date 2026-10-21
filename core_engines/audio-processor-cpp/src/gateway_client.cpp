#include "gateway_client.hpp"

#include <curl/curl.h>

#include <cstdio>
#include <iostream>
#include <thread>

namespace nexus {
namespace {

struct CurlDeleter {
    void operator()(CURL* h) const { curl_easy_cleanup(h); }
};
struct SlistDeleter {
    void operator()(curl_slist* l) const { curl_slist_free_all(l); }
};
using CurlPtr = std::unique_ptr<CURL, CurlDeleter>;
using SlistPtr = std::unique_ptr<curl_slist, SlistDeleter>;

size_t collect(char* data, size_t size, size_t n, void* out) {
    static_cast<std::string*>(out)->append(data, size * n);
    return size * n;
}

bool retryable(const HttpResult& r) { return r.status == 0 || r.status == 429 || r.status >= 500; }

}  // namespace

std::string json_escape(const std::string& in) {
    std::string out;
    out.reserve(in.size() + 8);
    for (unsigned char c : in) {
        switch (c) {
            case '"': out += "\\\""; break;
            case '\\': out += "\\\\"; break;
            case '\n': out += "\\n"; break;
            case '\r': out += "\\r"; break;
            case '\t': out += "\\t"; break;
            default:
                if (c < 0x20) {
                    char buf[8];
                    std::snprintf(buf, sizeof buf, "\\u%04x", c);
                    out += buf;
                } else {
                    out += static_cast<char>(c);  // UTF-8 bytes pass through unchanged
                }
        }
    }
    return out;
}

CurlGlobal::CurlGlobal() { curl_global_init(CURL_GLOBAL_DEFAULT); }
CurlGlobal::~CurlGlobal() { curl_global_cleanup(); }

GatewayClient::GatewayClient(std::string url, std::string api_key, std::chrono::seconds timeout, int max_attempts)
    : url_(std::move(url)), api_key_(std::move(api_key)), timeout_(timeout), max_attempts_(max_attempts) {}

HttpResult GatewayClient::post_json(const std::string& body) const {
    HttpResult result;
    auto backoff = std::chrono::milliseconds(500);
    for (int attempt = 1; attempt <= max_attempts_; ++attempt) {
        result = HttpResult{};
        result.attempts = attempt;
        CurlPtr curl(curl_easy_init());
        if (!curl) {
            result.error = "curl_easy_init failed";
            return result;
        }
        SlistPtr headers(curl_slist_append(nullptr, "Content-Type: application/json"));
        const std::string key_header = "X-API-Key: " + api_key_;
        headers.reset(curl_slist_append(headers.release(), key_header.c_str()));
        char error_buf[CURL_ERROR_SIZE] = {0};

        curl_easy_setopt(curl.get(), CURLOPT_URL, url_.c_str());
        curl_easy_setopt(curl.get(), CURLOPT_HTTPHEADER, headers.get());
        curl_easy_setopt(curl.get(), CURLOPT_POSTFIELDS, body.c_str());
        curl_easy_setopt(curl.get(), CURLOPT_POSTFIELDSIZE, static_cast<long>(body.size()));
        curl_easy_setopt(curl.get(), CURLOPT_TIMEOUT, static_cast<long>(timeout_.count()));
        curl_easy_setopt(curl.get(), CURLOPT_CONNECTTIMEOUT, 5L);
        curl_easy_setopt(curl.get(), CURLOPT_WRITEFUNCTION, collect);
        curl_easy_setopt(curl.get(), CURLOPT_WRITEDATA, &result.body);
        curl_easy_setopt(curl.get(), CURLOPT_ERRORBUFFER, error_buf);
        curl_easy_setopt(curl.get(), CURLOPT_NOSIGNAL, 1L);

        const CURLcode code = curl_easy_perform(curl.get());
        if (code == CURLE_OK) {
            curl_easy_getinfo(curl.get(), CURLINFO_RESPONSE_CODE, &result.status);
        } else {
            result.error = error_buf[0] ? error_buf : curl_easy_strerror(code);
        }
        if (!retryable(result) || attempt == max_attempts_) break;
        std::cerr << "[gateway] attempt " << attempt << " failed ("
                  << (result.status ? "HTTP " + std::to_string(result.status) : result.error)
                  << "), retrying in " << backoff.count() << " ms\n";
        std::this_thread::sleep_for(backoff);
        backoff = std::min(backoff * 2, std::chrono::milliseconds(8000));
    }
    return result;
}

}  // namespace nexus
