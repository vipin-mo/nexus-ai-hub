# --- build: whisper.cpp + audio pipeline (CPU build for Linux containers) ---
FROM ubuntu:24.04 AS build
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential cmake git ca-certificates libcurl4-openssl-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
COPY CMakeLists.txt .
COPY src ./src
COPY tests ./tests
RUN cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DGGML_NATIVE=OFF \
    && cmake --build build -j"$(nproc)" \
    && ctest --test-dir build --output-on-failure

# --- runtime ---
FROM ubuntu:24.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends libcurl4t64 libgomp1 ca-certificates \
    && rm -rf /var/lib/apt/lists/* && useradd --create-home --uid 10001 nexus
WORKDIR /app
COPY --from=build /src/build/audio_processor /app/audio_processor
USER nexus
# The model (models/whisper/*.bin) and the inbox are mounted at runtime, not baked into the image.
ENV WHISPER_MODEL=/models/ggml-base.en.bin
ENTRYPOINT ["/app/audio_processor"]
CMD ["--watch", "/data/audio_inbox"]
