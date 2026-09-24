"""
Task 2, step 4b: re-voice the rewritten narration (text-to-speech).

Reads rewritten_narration.json (from rewrite_narration.py), synthesizes each
block with edge-tts (free Microsoft neural voices, no API key), and fits each
clip to its original time slot. Writes one audio file per block plus
tts_manifest.json, which the reassembly step (4c) uses.

Usage:
    python3 tts_narration.py
    python3 tts_narration.py --voice zh-CN-YunxiNeural     # male voice
    python3 tts_narration.py --list-voices                 # see Chinese voices

Setup:
    pip install edge-tts        # the TTS engine (free, no account)
    # ffmpeg is already installed

Fitting: TTS rarely lands exactly on the slot length. If a clip is longer than
its slot, it's sped up (ffmpeg atempo) just enough to fit, capped at MAX_SPEED
so it still sounds natural. If it's shorter, it's left as-is (the gap stays
quiet). Everything is recorded in tts_manifest.json.

Output files (in ./tts/):
    narr_000.mp3 ... (raw TTS)   narr_000_fit.wav ... (length-fitted)
    ../tts_manifest.json
"""

import argparse
import json
import os
import shutil
import subprocess
import sys

VOICE = "zh-CN-XiaoxiaoNeural"   # default: natural female Mandarin
MAX_SPEED = 1.5                  # never speed a clip up beyond this (stays clear)
OUT_DIR = "tts"


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or p.stdout or "").strip()[-800:])


def duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True, check=True).stdout.strip()
    return float(out)


def tts(text, voice, out_mp3):
    """Synthesize one line with edge-tts (via its CLI)."""
    run(["edge-tts", "--voice", voice, "--text", text, "--write-media", out_mp3])


def fit_to_slot(in_path, slot, out_path):
    """Fit clip length to `slot` seconds. Returns (final_duration, speed)."""
    dur = duration(in_path)
    if slot > 0 and dur > slot * 1.02:
        speed = min(dur / slot, MAX_SPEED)          # only speed up, and cap it
    else:
        speed = 1.0
    if abs(speed - 1.0) < 0.01:
        # no change needed — just standardize to wav
        run(["ffmpeg", "-y", "-i", in_path, "-ar", "44100", "-ac", "2",
             out_path, "-loglevel", "error"])
    else:
        run(["ffmpeg", "-y", "-i", in_path, "-filter:a", f"atempo={speed:.4f}",
             "-ar", "44100", "-ac", "2", out_path, "-loglevel", "error"])
    return duration(out_path), speed


def list_voices():
    try:
        out = subprocess.run(["edge-tts", "--list-voices"],
                             capture_output=True, text=True, check=True).stdout
    except FileNotFoundError:
        sys.exit("edge-tts not installed. Run: pip install edge-tts")
    for line in out.splitlines():
        if line.startswith("zh-") or "Chinese" in line:
            print(line)


def main():
    ap = argparse.ArgumentParser(description="Re-voice the narration (step 4b).")
    ap.add_argument("--input", default="rewritten_narration.json")
    ap.add_argument("--voice", default=VOICE)
    ap.add_argument("--list-voices", action="store_true")
    args = ap.parse_args()

    if args.list_voices:
        list_voices()
        return

    if shutil.which("edge-tts") is None:
        sys.exit("edge-tts not installed. Run: pip install edge-tts")
    if not os.path.exists(args.input):
        sys.exit(f"{args.input} not found — run rewrite_narration.py first.")

    with open(args.input, encoding="utf-8") as f:
        blocks = json.load(f)
    if not blocks:
        sys.exit("Nothing to synthesize.")

    os.makedirs(OUT_DIR, exist_ok=True)

    manifest = []
    print(f"Synthesizing {len(blocks)} block(s) with voice {args.voice} ...\n")
    for i, b in enumerate(blocks):
        text = (b.get("rewritten") or "").strip()
        if not text:
            continue
        slot = round(b["end"] - b["start"], 2)
        raw = os.path.join(OUT_DIR, f"narr_{i:03d}.mp3")
        fit = os.path.join(OUT_DIR, f"narr_{i:03d}_fit.wav")

        tts(text, args.voice, raw)
        final_dur, speed = fit_to_slot(raw, slot, fit)

        manifest.append({
            "start": b["start"], "end": b["end"], "slot": slot,
            "file": fit, "tts_dur": round(duration(raw), 2),
            "final_dur": round(final_dur, 2), "speed": round(speed, 3),
        })
        flag = "  (sped up)" if speed > 1.01 else ""
        print(f"[{i+1}/{len(blocks)}] slot {slot:5.1f}s  "
              f"tts {duration(raw):5.1f}s -> {final_dur:5.1f}s{flag}")

    with open("tts_manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"\nWrote tts_manifest.json  ({len(manifest)} clips in ./{OUT_DIR}/)")

    maxed = [m for m in manifest if m["speed"] >= MAX_SPEED - 0.001]
    if maxed:
        print(f"\nNote: {len(maxed)} clip(s) hit the {MAX_SPEED}x speed cap and "
              "may still run past their slot. Re-run rewrite_narration.py to "
              "shorten those blocks if it sounds rushed.")


if __name__ == "__main__":
    main()
