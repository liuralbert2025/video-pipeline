"""
Step 5 (alternative B): pick highlights with an LLM.

Drop-in replacement for select_highlights.py — same input, same output
(clips.json). Instead of keyword scoring, it sends the timestamped transcript
to a large language model and asks it to choose the most engaging moments. The
LLM reads *meaning*, so it catches good moments regardless of wording.

Works with any OpenAI-compatible API (Qwen/DashScope, OpenAI, DeepSeek, etc.).
You configure it with environment variables so no keys live in the code:

    export LLM_API_KEY="your-key"
    export LLM_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"   # Qwen example
    export LLM_MODEL="qwen-plus"                                              # model name

Then:
    python3 select_llm.py input_audio.json

Requires:
    pip install openai
"""

import json
import os
import re
import sys

import clip_utils

# ---- Settings ----
TOP_N = 6            # target number of highlight moments
MIN_LEN = 4          # ask the model for clips at least this many seconds
MAX_LEN = 15         # ...and at most this many
MERGE_GAP = 1.5      # merge picks that end up within this many seconds
MAX_TOTAL = 50       # cap total highlight duration (seconds); 0 = off
# ------------------


def build_prompt(segments):
    lines = [f"[{s['start']:.1f}-{s['end']:.1f}] {s['text']}" for s in segments]
    transcript = "\n".join(lines)
    return (
        "You are an expert short-video editor. Below is a timestamped "
        "transcript of a video. Choose the "
        f"{TOP_N} MOST engaging, self-contained moments to turn into a short "
        "highlight reel (hooks, key tips, surprising or emphatic statements, "
        "payoffs). Avoid intros, filler, and sign-offs.\n\n"
        f"Each chosen clip must be between {MIN_LEN} and {MAX_LEN} seconds long "
        "and must not overlap. Use the timestamps from the transcript.\n\n"
        "Respond with ONLY a JSON array, no prose, in exactly this form:\n"
        '[{"start": 12.3, "end": 20.1}, {"start": 45.0, "end": 52.4}]\n\n'
        f"TRANSCRIPT:\n{transcript}"
    )


def call_llm(prompt):
    try:
        from openai import OpenAI
    except ImportError:
        sys.exit("openai not installed. Run: pip install openai")

    key = os.environ.get("LLM_API_KEY")
    base = os.environ.get("LLM_BASE_URL")
    model = os.environ.get("LLM_MODEL")
    if not (key and base and model):
        sys.exit("Set LLM_API_KEY, LLM_BASE_URL and LLM_MODEL environment "
                 "variables first (see the top of this file).")

    client = OpenAI(api_key=key, base_url=base)
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
    )
    return resp.choices[0].message.content


def parse_ranges(raw):
    """Pull a JSON array of {start,end} out of the model's reply, robustly."""
    match = re.search(r"\[.*\]", raw, re.DOTALL)   # find the JSON array
    if not match:
        sys.exit("Could not find a JSON array in the model reply:\n" + raw)
    data = json.loads(match.group(0))
    ranges = []
    for d in data:
        try:
            ranges.append((float(d["start"]), float(d["end"])))
        except (KeyError, TypeError, ValueError):
            continue
    return ranges


def clamp_merge_cap(ranges, segments):
    """Keep the model honest.

    The model returns its own start/end times, which may land mid-sentence. We
    clamp them to the video, SNAP them outward to real transcript segment
    boundaries, then merge and cap. Snapping makes the cut points deterministic
    instead of trusting the model to choose sensible ones.
    """
    return clip_utils.build_clips_from_ranges(
        ranges, segments, merge_gap=MERGE_GAP, max_total=MAX_TOTAL)


def select(json_path):
    if not os.path.exists(json_path):
        sys.exit(f"File not found: {json_path}")
    with open(json_path, encoding="utf-8") as f:
        segments = json.load(f)
    if not segments:
        sys.exit("Transcript is empty.")

    print("Asking the LLM to pick highlights ...")
    raw = call_llm(build_prompt(segments))
    ranges = parse_ranges(raw)
    out = clamp_merge_cap(ranges, segments)
    if not out:
        sys.exit("Model returned no usable clips.")

    with open("clips.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    total = sum(w["end"] - w["start"] for w in out)
    print(f"LLM selected {len(out)} clip(s), {total:.1f}s total.")
    print("Wrote clips.json\n")
    for i, w in enumerate(out, 1):
        print(f"  {i}. [{w['start']:.1f} -> {w['end']:.1f}]")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: python3 select_llm.py <transcript.json>")
    select(sys.argv[1])
