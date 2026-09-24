"""
Step 6 (pro): cut the highlight ranges AND make them platform-ready —
burned-in captions + vertical 9:16 framing — then stitch into one reel.

Drop-in upgrade for cut_and_stitch.py. Same inputs (clips.json + the original
video), plus the transcript so it can draw captions.

Usage:
    python3 cut_and_stitch_pro.py input.mp4
    python3 cut_and_stitch_pro.py input.mp4 my_reel.mp4
    python3 cut_and_stitch_pro.py input.mp4 --no-captions
    python3 cut_and_stitch_pro.py input.mp4 --no-vertical
    python3 cut_and_stitch_pro.py input.mp4 --transcript other_audio.json

HOW CAPTIONS WORK HERE (no libass needed)
-----------------------------------------
Most ffmpeg caption tutorials use the `subtitles`/`ass` filter, which requires
ffmpeg to be built with libass. Many Homebrew builds are NOT, and rebuilding
from source is painful. So instead we render each caption ourselves with
Pillow (a Python image library): each line of text is drawn as a transparent
PNG with a thick outline, and ffmpeg simply OVERLAYS that PNG onto the video
for the moment it should appear. This works on ANY ffmpeg build and gives us
full control over the look.

What it does to each clip:
  1. Cuts it from the original (re-encoded, so cuts land exactly on time).
  2. VERTICAL: scales the frame to fit a 1080x1920 canvas and fills the empty
     space with a blurred, zoomed copy of the frame — nothing is cropped off.
  3. CAPTIONS: renders caption PNGs and overlays each at the right time.
Then all the clips are concatenated into the final reel.

Requires:  pip install pillow      (ffmpeg does NOT need libass)
"""

import argparse
import json
import os
import shutil
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

# ---- Look & feel you can tune ----
WIDTH, HEIGHT = 1080, 1920      # output canvas (9:16)
BLUR_SIGMA = 20                 # how soft the background fill is
FONT_RATIO = 1 / 22             # caption height as a fraction of frame height
MARGIN_RATIO = 0.20             # how far up from the bottom the text sits
OUTLINE_RATIO = 1 / 150         # black outline thickness (readability)
SIDE_MARGIN_RATIO = 0.08        # keep text this far in from each side edge
MAX_LINES = 2                   # wrap a caption onto at most this many lines
TEXT_COLOR = (255, 255, 255, 255)
OUTLINE_COLOR = (0, 0, 0, 255)

# Where to look for a bold TTF font (first that exists wins). Add your own path
# at the front if you want a specific font.
FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",       # macOS
    "/System/Library/Fonts/Helvetica.ttc",                     # macOS
    "/Library/Fonts/Arial Bold.ttf",                           # macOS
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",    # Linux
]
# ----------------------------------


def run(cmd, cwd=None):
    """Run a command; if it fails, show ffmpeg's actual error message."""
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if p.returncode != 0:
        print("\n--- ffmpeg failed ---")
        print((p.stderr or p.stdout or "").strip()[-2000:])
        print("--- command ---")
        print(" ".join(cmd))
        sys.exit(f"\nffmpeg exited with status {p.returncode} (see error above).")


def probe_size(video):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", video],
        capture_output=True, text=True, check=True).stdout.strip()
    w, h = out.split("x")[:2]
    return int(w), int(h)


def load_font(size):
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    print("! No TrueType font found — captions will use a small default font.\n"
          "  Add a .ttf path to FONT_CANDIDATES at the top of the script.")
    return ImageFont.load_default()


def _text_w(draw, text, font, outline):
    b = draw.textbbox((0, 0), text, font=font, stroke_width=outline)
    return b[2] - b[0]


def wrap_to_width(text, draw, font, outline, max_w):
    """Greedy word-wrap so each LINE fits within max_w pixels — measured, not
    guessed from character counts. Returns a list of lines."""
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if cur and _text_w(draw, trial, font, outline) > max_w:
            lines.append(cur)
            cur = w
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines or [text]


def split_into_captions(text, draw, font, outline, max_w):
    """Turn a whole sentence into caption chunks of at most MAX_LINES lines each,
    every line guaranteed to fit within max_w pixels. No words are dropped."""
    lines = wrap_to_width(text, draw, font, outline, max_w)
    return ["\n".join(lines[i:i + MAX_LINES])
            for i in range(0, len(lines), MAX_LINES)]


def render_caption_png(text, frame_w, frame_h, font, outline, path):
    """Draw one (possibly multi-line) caption as a transparent PNG the size of
    the video frame, centered horizontally at MARGIN_RATIO up from the bottom."""
    img = Image.new("RGBA", (frame_w, frame_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    bbox = draw.multiline_textbbox((0, 0), text, font=font,
                                   stroke_width=outline, align="center",
                                   spacing=int(outline * 2))
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (frame_w - tw) // 2 - bbox[0]
    y = frame_h - int(frame_h * MARGIN_RATIO) - th - bbox[1]

    draw.multiline_text((x, y), text, font=font, fill=TEXT_COLOR,
                        stroke_width=outline, stroke_fill=OUTLINE_COLOR,
                        align="center", spacing=int(outline * 2))
    img.save(path)


def build_captions(segments, start, end, frame_w, frame_h, tmp, idx):
    """Render every caption for one clip. Returns a list of
    (png_filename, appear_time, disappear_time) with times rebased to clip zero.

    Each transcript segment is split into chunks, and the segment's duration is
    shared between them in proportion to their length so captions stay in sync.
    """
    fontsize = max(16, int(frame_h * FONT_RATIO))
    outline = max(2, int(frame_h * OUTLINE_RATIO))
    font = load_font(fontsize)
    max_w = int(frame_w * (1 - 2 * SIDE_MARGIN_RATIO))
    measure = ImageDraw.Draw(Image.new("RGBA", (frame_w, frame_h)))

    events = []
    n = 0
    for s in segments:
        if s["end"] <= start or s["start"] >= end:
            continue
        a = max(s["start"], start) - start
        b = min(s["end"], end) - start
        text = s.get("text", "").strip()
        if b - a < 0.05 or not text:
            continue
        chunks = split_into_captions(text, measure, font, outline, max_w)
        total_chars = sum(len(c) for c in chunks) or 1
        t = a
        for c in chunks:
            share = (b - a) * (len(c) / total_chars)
            png = f"cap_{idx:03d}_{n:03d}.png"
            render_caption_png(c, frame_w, frame_h, font, outline,
                               os.path.join(tmp, png))
            events.append((png, t, min(t + share, b)))
            t += share
            n += 1
    return events


def build_cut_cmd(video, start, dur, vertical, captions, part):
    """Assemble the ffmpeg command for one clip.

    Inputs: [0] = the video. [1..] = one PNG per caption.
    We build a filter graph: (optional vertical framing) -> overlay each PNG
    only between its appear/disappear time using overlay's `enable` expression.
    """
    # -ss and -t BOTH go before -i video so they trim the VIDEO input. If -t
    # came after -i video, the caption PNG inputs that follow would make ffmpeg
    # read -t as an option for the first PNG instead of a length limit on the
    # clip — and every clip would run to the end of the source video.
    cmd = ["ffmpeg", "-y", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", video]
    for png, _, _ in captions:
        cmd += ["-i", png]

    steps = []
    if vertical:
        steps.append(
            f"[0:v]split=2[bg][fg];"
            f"[bg]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={WIDTH}:{HEIGHT},gblur=sigma={BLUR_SIGMA}[bgb];"
            f"[fg]scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease[fgs];"
            f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2[base]"
        )
        cur = "[base]"
    else:
        steps.append("[0:v]null[base]")
        cur = "[base]"

    for i, (png, a, b) in enumerate(captions):
        nxt = f"[v{i}]"
        # PNG input index is i+1 (input 0 is the video)
        steps.append(
            f"{cur}[{i+1}:v]overlay=0:0:enable='between(t,{a:.3f},{b:.3f})'{nxt}")
        cur = nxt

    filtergraph = ";".join(steps)
    # rename final label to [v]
    if filtergraph.endswith("[base]"):
        filtergraph = filtergraph[:-6] + "[v]"
        final = "[v]"
    else:
        # last label is cur; map it directly
        final = cur

    cmd += ["-filter_complex", filtergraph, "-map", final, "-map", "0:a?",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
            "-avoid_negative_ts", "make_zero", part, "-loglevel", "error"]
    return cmd


def main():
    ap = argparse.ArgumentParser(
        description="Cut highlights into a captioned vertical reel (no libass).")
    ap.add_argument("video")
    ap.add_argument("output", nargs="?", default="highlights_pro.mp4")
    ap.add_argument("--transcript", default=None,
                    help="transcript JSON (default: <video>_audio.json)")
    ap.add_argument("--no-captions", action="store_true")
    ap.add_argument("--no-vertical", action="store_true")
    args = ap.parse_args()

    video = os.path.abspath(args.video)
    if not os.path.exists(video):
        sys.exit(f"Video not found: {args.video}")
    if not os.path.exists("clips.json"):
        sys.exit("clips.json not found — run a selector first.")

    with open("clips.json", encoding="utf-8") as f:
        clips = json.load(f)
    if not clips:
        sys.exit("clips.json is empty.")

    captions = not args.no_captions
    vertical = not args.no_vertical

    segments = []
    if captions:
        tpath = args.transcript or f"{os.path.splitext(args.video)[0]}_audio.json"
        if not os.path.exists(tpath):
            print(f"! transcript '{tpath}' not found — continuing without "
                  f"captions (use --transcript to point at it).")
            captions = False
        else:
            with open(tpath, encoding="utf-8") as f:
                segments = json.load(f)

    frame_w, frame_h = (WIDTH, HEIGHT) if vertical else probe_size(video)

    tmp = os.path.abspath("_clips_tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp, exist_ok=True)

    print(f"Cutting {len(clips)} clip(s)  "
          f"[captions: {'on' if captions else 'off'}, "
          f"vertical: {'on' if vertical else 'off'}]")

    parts = []
    for i, c in enumerate(clips):
        start, end = float(c["start"]), float(c["end"])
        dur = end - start
        if dur <= 0:
            continue

        events = []
        if captions:
            events = build_captions(segments, start, end, frame_w, frame_h,
                                    tmp, i)

        part = f"clip_{i:03d}.mp4"
        cmd = build_cut_cmd(video, start, dur, vertical, events, part)
        run(cmd, cwd=tmp)
        parts.append(part)
        print(f"  clip {i+1}: {start:.1f}s -> {end:.1f}s  ({len(events)} captions)")

    if not parts:
        sys.exit("No valid clips to stitch.")

    with open(os.path.join(tmp, "list.txt"), "w", encoding="utf-8") as f:
        for p in parts:
            f.write(f"file '{p}'\n")

    out = os.path.abspath(args.output)
    print("Stitching ->", args.output)
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "list.txt",
         "-c", "copy", "-movflags", "+faststart", out, "-loglevel", "error"],
        cwd=tmp)

    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\nDone -> {args.output}")


if __name__ == "__main__":
    main()
