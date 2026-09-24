"""
make_reel.py — the whole video-summary pipeline in one command.

    python3 make_reel.py input.mp4
    python3 make_reel.py input.mp4 my_reel.mp4     # custom output name

It runs all the steps end to end:
    1. extract the audio from the video            (ffmpeg)
    2. transcribe it into timestamped text         (Whisper)
    3. score & pick the "highlight" segments       (keyword matching)
    4. cut those ranges from the original & stitch  (ffmpeg)  -> highlights.mp4

Intermediate files (audio, transcript, clips.json) are written next to the
video so you can inspect or reuse them. Delete them anytime.

Requirements:
    pip install openai-whisper
    ffmpeg on PATH

The individual scripts (split.py, transcribe.py, select_highlights.py,
cut_and_stitch.py) still exist if you want to run one stage at a time or debug.
This file just chains the same logic together.
"""

import json
import os
import re
import shutil
import ssl
import subprocess
import sys

import clip_utils

# TLS fix for networks that inspect HTTPS (e.g. campus/research networks).
# Safe: Whisper verifies the model's SHA-256 hash after download.
ssl._create_default_https_context = ssl._create_unverified_context

# ======================= SETTINGS YOU CAN TUNE =============================

MODEL_SIZE = "small"     # tiny / base / small / medium / large
LANGUAGE = None          # None = auto; "en" English, "zh" Chinese (faster/better)

PHRASES = [              # strongest "highlight" signals (weight 4)
    "the most important", "the key is", "the secret", "the trick is",
    "what you want to do", "here's the thing", "the biggest mistake",
    "most people", "make sure", "the best way", "the number one",
    "pay attention", "focus on",
    # Chinese examples — uncomment/add for Douyin content:
    # "最重要的", "关键是", "秘诀", "很多人都", "一定要", "第一",
]
KEYWORDS = [            # weaker single-word signals (weight 2)
    "important", "key", "secret", "tip", "trick", "mistake", "mistakes",
    "never", "always", "remember", "avoid", "improve", "better", "best",
    "watch", "amazing", "win", "point", "technique", "drill",
]
IMPERATIVES = [         # a segment starting with one of these = an instruction
    "watch", "remember", "make", "try", "focus", "don't", "keep", "use",
    "notice", "look", "avoid", "stop", "start", "think",
]

TOP_N = 6               # how many highlight moments to seed
CONTEXT = 1             # extra transcript sentences either side of a pick
MERGE_GAP = 2.5         # merge picks that land within this many seconds
MAX_TOTAL = 50          # cap total highlight duration (seconds); 0 = off
# Clips snap to transcript segment boundaries (clip_utils.py), so cuts land in
# the pause between utterances instead of slicing through a word.

# ==========================================================================


def run(cmd):
    subprocess.run(cmd, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)


def extract_audio(video, audio_out):
    print("[1/4] Extracting audio ...")
    run(["ffmpeg", "-y", "-i", video, "-vn", "-q:a", "0", audio_out,
         "-loglevel", "error"])


def transcribe(audio, txt_out, json_out):
    print(f"[2/4] Transcribing with Whisper '{MODEL_SIZE}' (first run downloads "
          "the model) ...")
    try:
        import whisper
    except ImportError:
        sys.exit("Whisper not installed. Run: pip install openai-whisper")
    model = whisper.load_model(MODEL_SIZE)
    result = model.transcribe(audio, language=LANGUAGE, verbose=False)
    segments = [{"start": round(s["start"], 2), "end": round(s["end"], 2),
                 "text": s["text"].strip()} for s in result["segments"]]
    with open(txt_out, "w", encoding="utf-8") as f:
        for s in segments:
            f.write(f"[ {s['start']:7.2f} -> {s['end']:7.2f} ]  {s['text']}\n")
    with open(json_out, "w", encoding="utf-8") as f:
        json.dump(segments, f, ensure_ascii=False, indent=2)
    print(f"      {len(segments)} segments transcribed.")
    return segments


def score(text):
    t = text.lower()
    s = 0
    for ph in PHRASES:
        s += t.count(ph) * 4
    for kw in KEYWORDS:
        s += t.count(kw) * 2
    first = re.sub(r"[^a-z']", "", t.split(" ")[0]) if t.strip() else ""
    if first in IMPERATIVES:
        s += 3
    s += 2 * len(re.findall(r"\b\w+est\b", t))
    s += 2 * t.count("most ")
    if "?" in text:
        s += 1
    if "!" in text:
        s += 2
    s += len(re.findall(r"\d+", text))
    return s


def _build_clips(picks, segments):
    """Snap to transcript boundaries, add context, merge and cap.

    Cuts land in the pause between utterances rather than a fixed number of
    seconds either side, so clips never start or end mid-word.
    """
    return clip_utils.build_clips(picks, segments, context=CONTEXT,
                                  merge_gap=MERGE_GAP, max_total=MAX_TOTAL)


def _pick_keyword(segments):
    scored = [(score(s["text"]), s) for s in segments]
    picks = [s for sc, s in sorted(scored, key=lambda x: x[0], reverse=True)
             if sc > 0][:TOP_N]
    if not picks:
        print("      No keywords matched — using the longest segments.")
        picks = sorted(segments, key=lambda s: s["end"] - s["start"],
                       reverse=True)[:TOP_N]
    return _build_clips(picks, segments)


def _pick_extractive(segments):
    try:
        import numpy as np
        import select_extractive as se
    except ImportError as e:
        sys.exit(f"'extractive' needs select_extractive.py + scikit-learn/numpy "
                 f"({e}). Run: pip install scikit-learn numpy")
    texts = [s["text"] for s in segments]
    if len(segments) <= TOP_N:
        picks = segments
    else:
        scores = se.textrank(texts)
        order = np.argsort(scores)[::-1][:TOP_N]
        picks = [segments[i] for i in sorted(order)]
    return _build_clips(picks, segments)


def _pick_llm(segments):
    try:
        import select_llm as sl
    except ImportError as e:
        sys.exit(f"'llm' needs select_llm.py + the openai package ({e}). "
                 "Run: pip install openai")
    raw = sl.call_llm(sl.build_prompt(segments))
    ranges = sl.parse_ranges(raw)
    out = sl.clamp_merge_cap(ranges, segments)
    for w in out:                       # keep the same dict shape (add text)
        w.setdefault("text", "")
    return out


def select_highlights(segments, clips_out, selector="keyword"):
    print(f"[3/4] Selecting highlights (selector: {selector}) ...")
    picker = {"keyword": _pick_keyword,
              "extractive": _pick_extractive,
              "llm": _pick_llm}[selector]
    out = picker(segments)
    with open(clips_out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    total = sum(w["end"] - w["start"] for w in out)
    print(f"      {len(out)} clip(s), {total:.1f}s total:")
    for i, w in enumerate(out, 1):
        label = w.get("text", "")[:60]
        print(f"        {i}. [{w['start']:.1f}->{w['end']:.1f}] {label}")
    return out


def cut_and_stitch(video, clips, out_path):
    print("[4/4] Cutting & stitching ...")
    tmp = os.path.abspath("_clips_tmp")
    if os.path.exists(tmp):
        shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp, exist_ok=True)

    parts = []
    for i, c in enumerate(clips):
        start = float(c["start"])
        dur = float(c["end"]) - start
        if dur <= 0:
            continue
        part = os.path.join(tmp, f"clip_{i:03d}.mp4")
        run(["ffmpeg", "-y", "-ss", f"{start:.3f}", "-i", video,
             "-t", f"{dur:.3f}",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
             "-c:a", "aac", "-b:a", "128k",
             "-avoid_negative_ts", "make_zero", part, "-loglevel", "error"])
        parts.append(part)
    if not parts:
        sys.exit("No valid clips to stitch.")

    list_file = os.path.join(tmp, "list.txt")
    with open(list_file, "w", encoding="utf-8") as f:
        for p in parts:
            f.write(f"file '{p}'\n")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_file,
         "-c", "copy", "-movflags", "+faststart", out_path, "-loglevel", "error"])
    shutil.rmtree(tmp, ignore_errors=True)


def main(video, out_path, selector="keyword", captions=False, vertical=False):
    if not os.path.exists(video):
        sys.exit(f"Video not found: {video}")
    base, _ = os.path.splitext(video)
    audio = f"{base}_audio.mp3"
    txt = f"{base}_audio.txt"
    js = f"{base}_audio.json"

    extract_audio(video, audio)
    segments = transcribe(audio, txt, js)
    if not segments:
        sys.exit("Nothing was transcribed (is there speech in the audio?).")
    clips = select_highlights(segments, "clips.json", selector)

    if captions or vertical:
        # hand off to the "pro" cutter for burned-in captions / 9:16 framing
        if not os.path.exists("cut_and_stitch_pro.py"):
            sys.exit("--captions/--vertical need cut_and_stitch_pro.py in this "
                     "folder.")
        print("[4/4] Cutting & stitching (pro) ...")
        cmd = [sys.executable, "cut_and_stitch_pro.py", video, out_path,
               "--transcript", js]
        if not captions:
            cmd.append("--no-captions")
        if not vertical:
            cmd.append("--no-vertical")
        subprocess.run(cmd, check=True)
    else:
        cut_and_stitch(video, clips, out_path)
    print(f"\nDone -> {out_path}")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(
        description="Turn a talking video into a highlight reel.")
    p.add_argument("video", help="source video, e.g. input.mp4")
    p.add_argument("output", nargs="?", default="highlights.mp4",
                   help="output file name (default: highlights.mp4)")
    p.add_argument("--selector", choices=["keyword", "extractive", "llm"],
                   default="keyword",
                   help="how to pick highlights: keyword (default), "
                        "extractive (TextRank), or llm")
    p.add_argument("--captions", action="store_true",
                   help="burn subtitles onto the reel")
    p.add_argument("--vertical", action="store_true",
                   help="format as 1080x1920 with a blurred background fill")
    args = p.parse_args()
    main(args.video, args.output, args.selector, args.captions, args.vertical)
