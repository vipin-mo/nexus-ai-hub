# --- Stage 1: Build Engine ---
FROM ubuntu:22.04 AS builder

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    libcurl4-openssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build-src
COPY . .

RUN rm -rf build && mkdir build && cd build && cmake .. && make

# --- Stage 2: Minimalist Runtime Container ---
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y \
    libcurl4 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=builder /build-src/build/audio_processor .

ENTRYPOINT ["./audio_processor"]
