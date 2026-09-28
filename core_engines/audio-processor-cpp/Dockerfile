# --- Stage 1: Build and Compile Engine ---
FROM ubuntu:22.04 AS builder

# Prevent prompt blockages during installation packages
ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build-src
COPY . .

# Run CMake compilation steps natively
RUN rm -rf build && mkdir build && cd build && cmake .. && make

# --- Stage 2: Minimalist High-Performance Runtime Container ---
FROM ubuntu:22.04

WORKDIR /app
# Extract only the compiled production binary from the builder stage
COPY --from=builder /build-src/build/audio_processor .

ENTRYPOINT ["./audio_processor"]
