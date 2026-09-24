"""
Task 2, step 4a: rewrite the narrator's commentary.

Reads narrator_blocks.json (from narrator_id.py) and rewrites each block's text
into fresh wording with an LLM — same meaning, similar length so the new
voiceover still fits its time slot. Writes rewritten_narration.json, which the
next steps (TTS + reassembly) consume.

Usage:
    python3 rewrite_narration.py
    python3 rewrite_narration.py --style 悬念        # nudge the rewrite style

Setup (same as select_llm.py — any OpenAI-compatible API, e.g. Qwen):
    export LLM_API_KEY="your-key"
    export LLM_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
    export LLM_MODEL="qwen-plus"
    pip install openai

Output: rewritten_narration.json — a list of
    {start, end, duration, original, rewritten, orig_chars, new_chars}
so you can eyeball how closely each rewrite matches the original length.
"""

import argparse
import json
import os
import sys

INPUT = "narrator_blocks.json"
OUTPUT = "rewritten_narration.json"

# Rough Mandarin speaking rate, used only to sanity-check length vs the time
# slot. ~4.5 characters per second is typical for narration.
CHARS_PER_SEC = 4.5


def cjk_len(text):
    """Count characters ignoring spaces/newlines (Chinese has no word spaces)."""
    return len(text.replace(" ", "").replace("\n", ""))


def get_client():
    try:
        from openai import OpenAI
    except ImportError:
        sys.exit("openai not installed. Run: pip install openai")
    key = os.environ.get("LLM_API_KEY")
    base = os.environ.get("LLM_BASE_URL")
    model = os.environ.get("LLM_MODEL")
    if not (key and base and model):
        sys.exit("Set LLM_API_KEY / LLM_BASE_URL / LLM_MODEL first "
                 "(see the top of this file).")
    return OpenAI(api_key=key, base_url=base), model


def rewrite_text(client, model, original, target_chars, style):
    style_note = f"，风格{style}" if style else ""
    prompt = (
        "你是一个短视频影视解说的文案改写助手。请把下面这段解说旁白改写成全新的表达"
        f"{style_note}，要求：\n"
        "1. 保持原意和关键信息不变；\n"
        f"2. 字数控制在约 {target_chars} 字（上下浮动15%以内），以便配音时长匹配；\n"
        "3. 语言自然、口语化、有吸引力；\n"
        "4. 只输出改写后的文本，不要加引号、编号或任何解释。\n\n"
        f"原文：{original}"
    )
    resp = client.chat.completions.create(
        model=model, messages=[{"role": "user", "content": prompt}],
        temperature=0.7)
    return resp.choices[0].message.content.strip()


def main():
    ap = argparse.ArgumentParser(description="Rewrite the narration (step 4a).")
    ap.add_argument("--input", default=INPUT)
    ap.add_argument("--style", default=None,
                    help="optional style hint, e.g. 悬念 / 幽默 / 正式")
    args = ap.parse_args()

    if not os.path.exists(args.input):
        sys.exit(f"{args.input} not found — run narrator_id.py first.")
    with open(args.input, encoding="utf-8") as f:
        blocks = json.load(f)
    if not blocks:
        sys.exit("No narration blocks to rewrite.")

    client, model = get_client()

    out = []
    print(f"Rewriting {len(blocks)} narration block(s) ...\n")
    for i, b in enumerate(blocks, 1):
        original = b.get("text", "").strip()
        if not original:
            continue
        dur = b["end"] - b["start"]
        # target length: match the original (it already fit the slot), but don't
        # exceed what the slot can hold at a natural speaking rate.
        target = min(cjk_len(original), int(dur * CHARS_PER_SEC) + 4)
        target = max(target, 4)

        new = rewrite_text(client, model, original, target, args.style)
        out.append({
            "start": b["start"], "end": b["end"], "duration": round(dur, 2),
            "original": original, "rewritten": new,
            "orig_chars": cjk_len(original), "new_chars": cjk_len(new),
        })
        print(f"[{i}/{len(blocks)}] {b['start']:.1f}-{b['end']:.1f}s  "
              f"({cjk_len(original)}->{cjk_len(new)} chars)")
        print(f"    old: {original[:45]}")
        print(f"    new: {new[:45]}\n")

    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"Wrote {OUTPUT}  ({len(out)} blocks)")

    # flag any rewrites that ran long — they may overflow their time slot
    longs = [o for o in out if o["new_chars"] > o["duration"] * CHARS_PER_SEC * 1.2]
    if longs:
        print(f"\nNote: {len(longs)} block(s) may be too long for their slot; "
              "the TTS step can speed them up slightly, or re-run to shorten.")


if __name__ == "__main__":
    main()
