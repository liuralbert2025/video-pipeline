"""
Step 5 of the pipeline: pick the "highlight" segments from the transcript.

Reads the .json produced by transcribe.py, scores each segment with a simple
keyword-matching method, picks the best ones, pads and merges them into a few
clean clips, and writes clips.json (the list of time-ranges to cut in step 6).

Usage:
    python3 select_highlights.py input_audio.json

Output:
    clips.json  -> [{"start": 12.3, "end": 20.1, "text": "..."}, ...]

This is deliberately simple and meant to be tuned. Edit the KEYWORDS list and
the settings below to change what counts as a "highlight".
"""

import json
import re
import sys
import os

import clip_utils

# ---- Settings you can tune -------------------------------------------------

# High-value PHRASES that almost always mark the payoff moment in a how-to /
# coaching video. Weighted heavily. Lowercase. (Add Chinese phrases here too,
# e.g. "最重要的", "关键是", "秘诀是", "很多人都".)
PHRASES = [
    "the most important", "the key is", "the secret", "the trick is",
    "what you want to do", "here's the thing", "the biggest mistake",
    "most people", "make sure", "the best way", "the number one",
    "pay attention", "focus on",
]

# Single KEYWORDS — interesting but weaker on their own. Lowercase.
KEYWORDS = [
    "important", "key", "secret", "tip", "trick", "mistake", "mistakes",
    "never", "always", "remember", "avoid", "improve", "better", "best",
    "watch", "amazing", "win", "point", "technique", "drill",   # coaching/sport
]

# Imperative cue words: a segment that STARTS with one of these is usually
# the coach telling you what to do — a strong highlight signal.
IMPERATIVES = [
    "watch", "remember", "make", "try", "focus", "don't", "keep", "use",
    "notice", "look", "avoid", "stop", "start", "think",
]

TOP_N = 6          # how many highlight moments to seed
CONTEXT = 1        # extra transcript sentences to include either side of a pick
                   # (0 = just the sentence; 1 = one of lead-in and lead-out)
MERGE_GAP = 2.5    # merge two picks if they end up within this many seconds
MAX_TOTAL = 50     # optional cap on total highlight duration (seconds); 0 = off

# NOTE: clips are snapped to transcript segment boundaries (see clip_utils.py),
# so cuts always land in the pause between utterances — never mid-word.

# ---------------------------------------------------------------------------


def score(text):
    t = text.lower()
    s = 0
    for ph in PHRASES:
        s += t.count(ph) * 4          # phrases are the strongest signal
    for kw in KEYWORDS:
        s += t.count(kw) * 2          # keyword hits
    first_word = re.sub(r"[^a-z']", "", t.split(" ")[0]) if t.strip() else ""
    if first_word in IMPERATIVES:
        s += 3                        # coach giving an instruction
    s += 2 * len(re.findall(r"\b\w+est\b", t))   # superlatives: fastest, best..
    s += 2 * t.count("most ")                    # "most powerful", "most people"
    if "?" in text:
        s += 1                        # questions often hook the viewer
    if "!" in text:
        s += 2
    s += len(re.findall(r"\d+", text))  # numbers ("3 tips", "step 2")
    return s


def select(json_path):
    if not os.path.exists(json_path):
        sys.exit(f"File not found: {json_path}")

    with open(json_path, encoding="utf-8") as f:
        segments = json.load(f)

    if not segments:
        sys.exit("Transcript is empty.")

    # score every segment
    scored = [(score(s["text"]), s) for s in segments]

    # take the top N by score; if nothing scores, fall back to the longest
    picks = [s for sc, s in sorted(scored, key=lambda x: x[0], reverse=True)
             if sc > 0][:TOP_N]
    if not picks:
        print("No keywords matched — falling back to the longest segments.")
        picks = sorted(segments, key=lambda s: s["end"] - s["start"],
                       reverse=True)[:TOP_N]

    # snap to transcript boundaries, add context, merge and cap
    out = clip_utils.build_clips(picks, segments, context=CONTEXT,
                                 merge_gap=MERGE_GAP, max_total=MAX_TOTAL)

    with open("clips.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    total = sum(w["end"] - w["start"] for w in out)
    print(f"Selected {len(out)} highlight clip(s), {total:.1f}s total.")
    print("Wrote clips.json\n")
    for i, w in enumerate(out, 1):
        print(f"  {i}. [{w['start']:.1f} -> {w['end']:.1f}]  {w['text'][:70]}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: python3 select_highlights.py <transcript.json>")
    select(sys.argv[1])
