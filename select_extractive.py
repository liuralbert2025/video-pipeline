"""
Step 5 (alternative A): pick highlights with a REAL extractive summarization
algorithm — TextRank.

This is a drop-in replacement for select_highlights.py. Same input, same
output (clips.json), so cut_and_stitch.py / make_reel.py work unchanged.

How TextRank works (this is the "text summarization 算法" from the brief):
  1. Turn every transcript segment into a TF-IDF vector (how characteristic each
     word is of that segment vs. the whole video).
  2. Measure similarity between every pair of segments (cosine similarity).
  3. Treat segments as nodes in a graph, similarities as edge weights, and run
     PageRank. Segments that are similar to many *other* important segments
     score highest — i.e. the ones most central to what the video is about.
  4. Take the top-scoring segments as the summary/highlights.
Unlike keyword matching, this needs no word list — it discovers importance from
the content itself.

Usage:
    python3 select_extractive.py input_audio.json

Requires:
    pip install scikit-learn numpy

Note: TF-IDF here tokenizes on English words. For Chinese, segment the text
first with jieba (pip install jieba) and join tokens with spaces before scoring.
"""

import json
import os
import sys

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

import clip_utils

# ---- Settings (same knobs as the keyword version) ----
TOP_N = 6
CONTEXT = 1         # extra transcript sentences either side of a pick
MERGE_GAP = 2.5
MAX_TOTAL = 50
DAMPING = 0.85      # PageRank damping factor (standard value)
# Clips are snapped to transcript segment boundaries (see clip_utils.py) so
# cuts land in the pause between utterances, never mid-word.
# ------------------------------------------------------


def textrank(texts):
    """Return an importance score per text using TF-IDF + PageRank."""
    vec = TfidfVectorizer(stop_words="english")
    try:
        X = vec.fit_transform(texts)
    except ValueError:
        # empty vocabulary (e.g. all stop words) -> flat scores
        return np.ones(len(texts))

    sim = cosine_similarity(X)          # n x n similarity matrix
    np.fill_diagonal(sim, 0.0)          # no self-links

    row_sums = sim.sum(axis=1, keepdims=True)
    row_sums[row_sums == 0] = 1.0       # avoid divide-by-zero for lone nodes
    M = sim / row_sums                  # row-normalised transition matrix

    n = len(texts)
    r = np.ones(n) / n                  # start uniform
    for _ in range(100):                # power iteration until convergence
        r_new = (1 - DAMPING) / n + DAMPING * (M.T @ r)
        if np.abs(r_new - r).sum() < 1e-8:
            r = r_new
            break
        r = r_new
    return r


def build_clips(picks, segments):
    """Snap to transcript boundaries, add context, merge and cap."""
    return clip_utils.build_clips(picks, segments, context=CONTEXT,
                                  merge_gap=MERGE_GAP, max_total=MAX_TOTAL)


def select(json_path):
    if not os.path.exists(json_path):
        sys.exit(f"File not found: {json_path}")
    with open(json_path, encoding="utf-8") as f:
        segments = json.load(f)
    if not segments:
        sys.exit("Transcript is empty.")

    texts = [s["text"] for s in segments]

    if len(segments) <= TOP_N:
        picks = segments                        # too few to summarise; keep all
    else:
        scores = textrank(texts)
        order = np.argsort(scores)[::-1][:TOP_N]  # indices of top TOP_N
        picks = [segments[i] for i in sorted(order)]  # keep chronological

    out = build_clips(picks, segments)
    with open("clips.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    total = sum(w["end"] - w["start"] for w in out)
    print(f"TextRank selected {len(out)} clip(s), {total:.1f}s total.")
    print("Wrote clips.json\n")
    for i, w in enumerate(out, 1):
        print(f"  {i}. [{w['start']:.1f} -> {w['end']:.1f}]  {w['text'][:65]}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: python3 select_extractive.py <transcript.json>")
    select(sys.argv[1])
