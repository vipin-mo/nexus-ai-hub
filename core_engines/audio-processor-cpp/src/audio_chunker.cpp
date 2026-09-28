#ifndef AUDIO_CHUNKER_HPP
#define AUDIO_CHUNKER_HPP

#include <iostream>
#include <vector>
#include <cstdint>

class AudioChunker {
public:
    void sliceRawBuffer(const std::vector<int16_t>& buffer, size_t chunkSize) {
        std::cout << "⚡ [C++ Audio Chunker] Slicing buffer of size " << buffer.size()
                  << " into segments of " << chunkSize << " samples." << std::endl;
    }
};

#endif // AUDIO_CHUNKER_HPP
