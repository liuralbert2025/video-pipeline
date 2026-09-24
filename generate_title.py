"""
Task 3, title step: generate a short punchy cover title from the dialogue.

Reads the transcript and asks the LLM for a 4- or 8-character Chinese title in
the style of popular 影视解说 thumbnails (e.g. 逐出内阁, 公忠体国). Writes it to
title.txt, which the compose step overlays on the cover frame.

Usage:
    python3 generate_title.py                       # 4 chars, from task2_audio.json
    python3 generate_title.py --chars 8
    python3 generate_title.py --input task2_audio.json

Setup: same LLM_API_KEY / LLM_BASE_URL / LLM_MODEL as the other LLM steps.
"""

import argparse
import json
import os
import re
import sys

INPUT = "task2_audio.json"
MAX_CONTEXT = 1200          # cap how much transcript text we send


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
    return OpenAI(api_key=key, base_url=base), model


def load_text(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        parts = [d.get("text") or d.get("rewritten") or "" for d in data]
        text = " ".join(p.strip() for p in parts if p)
    else:
        text = str(data)
    return text[:MAX_CONTEXT]


def make_title(client, model, text, chars):
    """Return (title, subtitle): a `chars`-character headline plus a short
    descriptive line, like the reference thumbnails (big title + smaller line)."""
    prompt = (
        "你是短视频影视解说的封面文案助手。根据下面的字幕内容，生成封面文案：\n"
        f"1. title：恰好{chars}个汉字的主标题，概括核心看点、有戏剧张力"
        "（例如：逐出内阁、公忠体国、师徒情深）；\n"
        "2. subtitle：一句更具体的看点说明，8到14个汉字，点出人物或事件"
        "（例如：严世蕃高拱张居正出阁）。\n"
        '只输出 JSON：{"title":"...","subtitle":"..."}，不要其它内容。\n\n字幕：'
        + text)
    resp = client.chat.completions.create(
        model=model, messages=[{"role": "user", "content": prompt}],
        temperature=0.8)
    raw = resp.choices[0].message.content.strip()
    title, subtitle = "", ""
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(0))
            title = str(data.get("title", "")).strip()
            subtitle = str(data.get("subtitle", "")).strip()
        except json.JSONDecodeError:
            pass
    if not title:                       # fallback: first Chinese chars of reply
        title = re.sub(r"[^一-鿿]", "", raw)
    title = re.sub(r"[^一-鿿]", "", title)[:chars]
    subtitle = re.sub(r"[^一-鿿，、]", "", subtitle)[:16]
    return title, subtitle


def main():
    ap = argparse.ArgumentParser(description="Generate a cover title (Task 3).")
    ap.add_argument("--input", default=INPUT)
    ap.add_argument("--chars", type=int, default=4, choices=[4, 8])
    ap.add_argument("--output", default="title.txt")
    args = ap.parse_args()

    if not os.path.exists(args.input):
        sys.exit(f"{args.input} not found — need the transcript from Task 2.")
    text = load_text(args.input)
    if not text.strip():
        sys.exit("Transcript is empty.")

    client, model = get_client()
    title, subtitle = make_title(client, model, text, args.chars)

    with open(args.output, "w", encoding="utf-8") as f:
        f.write(title)
    with open("subtitle.txt", "w", encoding="utf-8") as f:
        f.write(subtitle)
    print(f"Title    ({len(title)} chars): {title}")
    print(f"Subtitle ({len(subtitle)} chars): {subtitle}")
    print(f"Wrote {args.output} and subtitle.txt")


if __name__ == "__main__":
    main()
