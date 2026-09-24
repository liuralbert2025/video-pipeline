"""
Task 2, step 3 fix: re-label each line as narration vs. in-character dialogue
by its TEXT, correcting the voice-based mistakes diarization made.

Diarization guesses speakers from voice timbre, which is imperfect — so some
actor lines end up tagged as the narrator (and later get muted + re-voiced,
cutting the actor). But the text makes the distinction obvious: narration is
third-person commentary about the story; drama dialogue is first-person, spoken
in-character. This step asks the LLM to classify every line, then rebuilds the
narrator/drama split from those corrected labels.

Usage:
    python3 reclassify.py
    # then continue the pipeline as normal:
    python3 rewrite_narration.py
    python3 tts_narration.py
    python3 reassemble.py task2.mp4

Reads:  labeled_transcript.json (from diarize_test.py)
Writes: narrator_blocks.json, drama_blocks.json  (corrected)
        labeled_reclassified.json  (per-line labels, for inspection)

Setup: same LLM_API_KEY / LLM_BASE_URL / LLM_MODEL as the other LLM steps.
"""

import argparse
import json
import os
import re
import sys

INPUT = "labeled_transcript.json"
BATCH = 40                      # lines per LLM call


def get_client():
    try:
        from openai import OpenAI
    except ImportError:
        sys.exit("openai not installed. Run: pip install openai")
    key = os.environ.get("LLM_API_KEY")
    base = os.environ.get("LLM_BASE_URL")
    model = os.environ.get("LLM_MODEL")
    if not (key and base and model):
        sys.exit("Set LLM_API_KEY / LLM_BASE_URL / LLM_MODEL first.")
    from openai import OpenAI
    return OpenAI(api_key=key, base_url=base), model


def classify_batch(client, model, texts):
    """Return a list of 'N'/'D' labels, one per input text.

    N = narration/commentary (third-person, explains the story).
    D = in-character drama dialogue (first-person, spoken in-scene).
    """
    numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(texts))
    prompt = (
        "下面是一个影视解说视频的逐句字幕。请判断每一句是：\n"
        "N = 解说旁白（作者用第三人称讲解剧情、人物或做评论）\n"
        "D = 剧中台词（剧中人物第一人称、在剧情场景里说的话）\n\n"
        "只输出一个 JSON 对象，键是句子的序号（字符串），值是 \"N\" 或 \"D\"，"
        "不要输出任何解释。例如：{\"1\":\"D\",\"2\":\"N\"}\n\n"
        + numbered)
    resp = client.chat.completions.create(
        model=model, messages=[{"role": "user", "content": prompt}],
        temperature=0)
    raw = resp.choices[0].message.content
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        # couldn't parse — default everything to drama (safe: won't be muted)
        return ["D"] * len(texts)
    data = json.loads(m.group(0))
    out = []
    for i in range(len(texts)):
        v = str(data.get(str(i + 1), "D")).strip().upper()
        out.append("N" if v.startswith("N") else "D")
    return out


def build_blocks(segs):
    """Merge consecutive same-label segments into blocks."""
    blocks = []
    for s in segs:
        side = "narrator" if s["label"] == "N" else "drama"
        text = s.get("text", "").strip()
        if blocks and blocks[-1]["side"] == side:
            blocks[-1]["end"] = s["end"]
            if text:
                blocks[-1]["text"] = (blocks[-1]["text"] + " " + text).strip()
        else:
            blocks.append({"side": side, "start": s["start"],
                           "end": s["end"], "text": text})
    return blocks


def main():
    ap = argparse.ArgumentParser(description="Reclassify lines by text (step 3 fix).")
    ap.add_argument("--input", default=INPUT)
    args = ap.parse_args()

    if not os.path.exists(args.input):
        sys.exit(f"{args.input} not found — run diarize_test.py first.")
    with open(args.input, encoding="utf-8") as f:
        segs = json.load(f)
    if not segs:
        sys.exit("Transcript is empty.")

    client, model = get_client()

    texts = [s.get("text", "").strip() for s in segs]
    labels = []
    print(f"Classifying {len(texts)} lines in batches of {BATCH} ...")
    for i in range(0, len(texts), BATCH):
        chunk = texts[i:i + BATCH]
        labels.extend(classify_batch(client, model, chunk))
        print(f"  {min(i + BATCH, len(texts))}/{len(texts)}")

    # attach labels; count how many flipped away from the diarization guess
    flipped = 0
    for s, lab in zip(segs, labels):
        s["label"] = lab
        s["was_narrator"] = None  # (diarization speaker isn't a clean N/D, skip)
    for s in segs:
        s.pop("was_narrator", None)

    with open("labeled_reclassified.json", "w", encoding="utf-8") as f:
        json.dump(segs, f, ensure_ascii=False, indent=2)

    blocks = build_blocks(segs)
    narrator_blocks = [{"start": round(b["start"], 2), "end": round(b["end"], 2),
                        "text": b["text"]}
                       for b in blocks if b["side"] == "narrator"]
    drama_blocks = [{"start": round(b["start"], 2), "end": round(b["end"], 2)}
                    for b in blocks if b["side"] == "drama"]

    with open("narrator_blocks.json", "w", encoding="utf-8") as f:
        json.dump(narrator_blocks, f, ensure_ascii=False, indent=2)
    with open("drama_blocks.json", "w", encoding="utf-8") as f:
        json.dump(drama_blocks, f, ensure_ascii=False, indent=2)

    n_lines = sum(1 for lab in labels if lab == "N")
    n_time = sum(b["end"] - b["start"] for b in narrator_blocks)
    d_time = sum(b["end"] - b["start"] for b in drama_blocks)
    print(f"\n{n_lines}/{len(labels)} lines = narration.")
    print(f"{len(narrator_blocks)} narration blocks ({n_time:.0f}s) "
          f"-> narrator_blocks.json")
    print(f"{len(drama_blocks)} drama blocks ({d_time:.0f}s) -> drama_blocks.json")
    print("\nFirst few narration blocks (these get rewritten + re-voiced):")
    for b in narrator_blocks[:5]:
        print(f"  [{b['start']:6.1f}-{b['end']:6.1f}] {b['text'][:50]}")


if __name__ == "__main__":
    main()
