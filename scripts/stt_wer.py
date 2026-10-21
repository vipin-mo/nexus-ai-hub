"""Word error rate of the C++ whisper.cpp pipeline on samples/audio (reference text in manifest.json).

    python scripts/stt_wer.py [--binary core_engines/audio-processor-cpp/build/audio_processor]
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def words(text: str) -> list[str]:
    return re.sub(r"[^a-z0-9' ]", " ", text.lower()).split()


def wer(reference: str, hypothesis: str) -> tuple[int, int]:
    """(edit distance in words, reference length)."""
    ref, hyp = words(reference), words(hypothesis)
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i] + [0] * len(hyp)
        for j, h in enumerate(hyp, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h))
        prev = cur
    return prev[-1], len(ref)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", default=str(ROOT / "core_engines/audio-processor-cpp/build/audio_processor"))
    parser.add_argument("--model", default=str(ROOT / "models/whisper/ggml-base.en.bin"))
    args = parser.parse_args()
    manifest = json.loads((ROOT / "samples/audio/manifest.json").read_text())
    errors = total = 0
    print(f"{'file':32s} {'WER':>6s}  {'speech':>6s}  {'stt ms':>7s}  transcript")
    for name, reference in manifest.items():
        cmd = [args.binary, "--file", str(ROOT / "samples/audio" / name), "--no-send", "--model", args.model]
        out = subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603 - local binary
        result = json.loads(out.stdout.strip().splitlines()[-1])
        if not reference:
            status = "skipped (no speech)" if result.get("error") == "no speech detected" else "UNEXPECTED SPEECH"
            print(f"{name:32s} {'-':>6s}  {result['speech_ratio']:6.2f}  {'-':>7s}  {status}")
            continue
        e, n = wer(reference, result["transcript"])
        errors, total = errors + e, total + n
        print(f"{name:32s} {e / n:6.1%}  {result['speech_ratio']:6.2f}  {result['stt_ms']:7.1f}  "
              f"{result['transcript']}")
    print(f"\ncorpus WER: {errors}/{total} words = {errors / total:.1%}"
          "  (TTS-generated speech; real voices will be worse)")


if __name__ == "__main__":
    main()
