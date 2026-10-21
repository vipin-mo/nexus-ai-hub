cmake_minimum_required(VERSION 3.20)
project(NexusAudioProcessor VERSION 2.0.0 LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)   # -O3; benchmarks assume Release
endif()

option(NEXUS_WITH_WHISPER "Build with whisper.cpp speech-to-text" ON)

find_package(CURL REQUIRED)

# Core library: WAV decoding, voice activity detection, gateway client (no ML dependency).
add_library(nexus_audio STATIC
  src/wav.cpp
  src/vad.cpp
  src/gateway_client.cpp
  src/transcriber.cpp)
target_include_directories(nexus_audio PUBLIC src)
target_link_libraries(nexus_audio PUBLIC CURL::libcurl)
if(CMAKE_CXX_COMPILER_ID MATCHES "GNU|Clang")
  target_compile_options(nexus_audio PRIVATE -Wall -Wextra -Wpedantic)
endif()

if(NEXUS_WITH_WHISPER)
  include(FetchContent)
  set(WHISPER_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
  set(WHISPER_BUILD_TESTS OFF CACHE BOOL "" FORCE)
  set(WHISPER_BUILD_SERVER OFF CACHE BOOL "" FORCE)
  set(BUILD_SHARED_LIBS OFF CACHE BOOL "" FORCE)
  FetchContent_Declare(whisper
    GIT_REPOSITORY https://github.com/ggml-org/whisper.cpp.git
    GIT_TAG v1.9.5
    GIT_SHALLOW TRUE)
  FetchContent_MakeAvailable(whisper)
  target_link_libraries(nexus_audio PUBLIC whisper)
  target_compile_definitions(nexus_audio PUBLIC NEXUS_WITH_WHISPER=1)
endif()

add_executable(audio_processor src/main.cpp)
target_link_libraries(audio_processor PRIVATE nexus_audio)

enable_testing()
add_executable(audio_tests tests/test_audio.cpp)
target_link_libraries(audio_tests PRIVATE nexus_audio)
add_test(NAME audio_tests COMMAND audio_tests)
