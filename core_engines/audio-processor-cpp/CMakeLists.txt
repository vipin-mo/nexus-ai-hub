cmake_minimum_required(VERSION 3.10)
project(NexusAudioProcessor VERSION 1.0.0 LANGUAGES CXX)

# Force standard C++17 optimization rules
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Source file locations
set(SOURCES
    src/main.cpp
)

# Core binary target definition
add_executable(audio_processor ${SOURCES})

# Include directory setups mapping to source files location context safely
target_include_directories(audio_processor PRIVATE src)
