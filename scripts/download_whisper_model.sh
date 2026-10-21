#!/usr/bin/env bash
# Download a whisper.cpp GGML model into models/whisper/ (default: base.en, 148 MB).
set -euo pipefail
cd "$(dirname "$0")/.."
MODEL="${1:-base.en}"
DEST="models/whisper/ggml-${MODEL}.bin"
mkdir -p models/whisper
if [[ -f "$DEST" ]]; then echo "$DEST already present"; exit 0; fi
echo "Downloading ggml-${MODEL}.bin ..."
curl -fL --progress-bar -o "$DEST.part" "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-${MODEL}.bin"
mv "$DEST.part" "$DEST"
echo "Saved $DEST"
