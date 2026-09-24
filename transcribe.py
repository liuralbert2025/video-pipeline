"""
Step 4 of the pipeline: turn the audio into TIMESTAMPED text using Whisper.

Usage:
    python3 transcribe.py input_audio.mp3

Outputs (next to the audio file):
    <name>.txt    -> human-readable, one line per segment:
                     [ 12.34 -> 15.80 ]  the spoken text
    <name>.json   -> full structured data (start, end, text per segment)
                     -> this is what step 5 (picking highlights) will read

First run downloads the model (a few hundred MB) — that's normal, one time only.

Requires:
    pip install openai-whisper
    ffmpeg on PATH (you already have it)
"""

import json
import os
import ssl
import sys

# --- Network fix for TLS-inspecting networks (e.g. campus/research networks) ---
# Some networks re-sign HTTPS with their own certificate, which Python won't
# trust, causing "CERTIFICATE_VERIFY_FAILED" when Whisper downloads its model.
# We skip the cert check for downloads. This is safe because Whisper verifies
# the model's SHA-256 hash afterwards, so a tampered file is still rejected.
# If you're on a normal/home network you can delete this line.
ssl._create_default_https_context = ssl._create_unverified_context

try:
    import whisper
except ImportError:
    sys.exit(
        "Whisper isn't installed. Run:\n"
        "    pip install openai-whisper\n"
        "then try again."
    )

# Model size: "tiny" / "base" / "small" / "medium" / "large".
# Bigger = more accurate but slower. "small" is a good balance to start.
MODEL_SIZE = "small"

# Language: None = auto-detect. Set to "zh" for Chinese, "en" for English
# to make it faster and more accurate if you already know the language.
LANGUAGE = None


def transcribe(audio_path):
    if not os.path.exists(audio_path):
        sys.exit(f"File not found: {audio_path}")

    base, _ = os.path.splitext(audio_path)
    txt_out = f"{base}.txt"
    json_out = f"{base}.json"

    print(f"Loading Whisper model '{MODEL_SIZE}' (first run downloads it)...")
    model = whisper.load_model(MODEL_SIZE)

    print(f"Transcribing {audio_path} ... (this can take a while)")
    result = model.transcribe(audio_path, language=LANGUAGE, verbose=False)

    segments = [
        {"start": round(s["start"], 2),
         "end": round(s["end"], 2),
         "text": s["text"].strip()}
        for s in result["segments"]
    ]

    # human-readable transcript
    with open(txt_out, "w", encoding="utf-8") as f:
        for s in segments:
            f.write(f"[ {s['start']:7.2f} -> {s['end']:7.2f} ]  {s['text']}\n")

    # structured data for the next step
    with open(json_out, "w", encoding="utf-8") as f:
        json.dump(segments, f, ensure_ascii=False, indent=2)

    print(f"\nDone. {len(segments)} segments.")
    print("  readable:", txt_out)
    print("  data:    ", json_out)
    print("\nPreview:")
    for s in segments[:5]:
        print(f"  [{s['start']:.2f} -> {s['end']:.2f}] {s['text']}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: python3 transcribe.py <audio_file>")
    transcribe(sys.argv[1])
