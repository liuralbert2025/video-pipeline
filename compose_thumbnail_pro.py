"""
Task 3, pro compose: build a polished 9:16 thumbnail in the reference-account
style — centred subject, decorative gold border, a bottom gradient for
legibility, a big main title, and a smaller description line under it.

Usage:
    python3 compose_thumbnail_pro.py
    python3 compose_thumbnail_pro.py --title 天家父子 --subtitle 嘉靖敲打严嵩父子
    python3 compose_thumbnail_pro.py --border-overlay myframe.png   # use a PNG frame
    python3 compose_thumbnail_pro.py -o thumb.jpg

Reads:  cover_frame.jpg, cover_frame.json (face box), title.txt, subtitle.txt
Writes: thumbnail_pro.jpg  (1080x1920)

Requires: pip install pillow

Note on the border: without an art asset this draws a clean procedural gold
frame with corner accents. For a fully ornate frame (dragons/clouds like the
reference), save a transparent 1080x1920 PNG and pass it with --border-overlay;
it will be composited on top and the procedural frame is skipped.
"""

import argparse
import json
import os
import sys

from PIL import Image, ImageDraw, ImageFont

OUT_W, OUT_H = 1080, 1920

# subtitle band trim (remove burned-in captions), same idea as the basic version
CROP_BOTTOM = 0.12
CROP_TOP = 0.0

# text
TITLE_RATIO = 0.130         # main title height / frame height
SUB_RATIO = 0.052           # description line height / frame height
TITLE_CENTER_Y = 0.70       # vertical position of the title (fraction of height)
SIDE_MARGIN_RATIO = 0.07
TITLE_COLOR = (255, 255, 255)
SUB_COLOR = (247, 214, 130)     # warm gold, matches the border
OUTLINE_COLOR = (0, 0, 0)

# gold decorative frame
GOLD = (214, 178, 92)
BORDER_INSET = 30           # px from each edge to the outer gold line
BORDER_GAP = 12             # gap between the double lines
CORNER = 60                 # length of the corner accent

FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    "/System/Library/Fonts/STSong.ttf",
    "/Library/Fonts/Songti.ttc",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc",
    "/System/Library/Fonts/PingFang.ttc",
]


def load_font(size):
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    sys.exit("No usable CJK font found — add a .ttf/.ttc path to FONT_CANDIDATES.")


def crop_vertical(img, face):
    w, h = img.size
    tr = OUT_W / OUT_H
    if w / h > tr:
        new_w = int(round(h * tr))
        cx = (face[0] + face[2] / 2) if face else w / 2
        left = max(0, min(int(round(cx - new_w / 2)), w - new_w))
        box = (left, 0, left + new_w, h)
    else:
        new_h = int(round(w / tr))
        box = (0, 0, w, new_h)
    return img.crop(box).resize((OUT_W, OUT_H), Image.LANCZOS)


def add_bottom_gradient(img, frac=0.42, strength=190):
    """Darken the bottom `frac` of the image with a smooth top->bottom gradient,
    so white/gold text reads clearly over busy footage."""
    grad = Image.new("L", (1, OUT_H), 0)
    start = int(OUT_H * (1 - frac))
    for y in range(start, OUT_H):
        t = (y - start) / max(1, OUT_H - start)
        grad.putpixel((0, y), int(strength * (t ** 1.3)))
    alpha = grad.resize((OUT_W, OUT_H))
    black = Image.new("RGB", (OUT_W, OUT_H), (0, 0, 0))
    return Image.composite(black, img, alpha)


def draw_gold_frame(img):
    d = ImageDraw.Draw(img)
    o = BORDER_INSET
    i = BORDER_INSET + BORDER_GAP
    # double rectangle
    d.rectangle([o, o, OUT_W - o, OUT_H - o], outline=GOLD, width=3)
    d.rectangle([i, i, OUT_W - i, OUT_H - i], outline=GOLD, width=2)
    # thicker corner accents on the inner line
    for cx, cy, dx, dy in [(i, i, 1, 1), (OUT_W - i, i, -1, 1),
                           (i, OUT_H - i, 1, -1), (OUT_W - i, OUT_H - i, -1, -1)]:
        d.line([(cx, cy), (cx + dx * CORNER, cy)], fill=GOLD, width=6)
        d.line([(cx, cy), (cx, cy + dy * CORNER)], fill=GOLD, width=6)
        # small seal square just inside each corner
        s = 14
        sx, sy = cx + dx * (CORNER + 16), cy + dy * (CORNER + 16)
        d.rectangle([min(sx, sx + dx * s), min(sy, sy + dy * s),
                     max(sx, sx + dx * s), max(sy, sy + dy * s)], fill=GOLD)
    return img


def draw_centered(draw, text, cy, size, color, max_w):
    """Draw `text` centred horizontally, vertically centred on cy. Shrinks to
    fit max_w. Returns the text's bottom y."""
    outline = max(3, int(size / 20))
    while size > 18:
        font = load_font(size)
        outline = max(3, int(size / 20))
        b = draw.textbbox((0, 0), text, font=font, stroke_width=outline)
        if b[2] - b[0] <= max_w:
            break
        size = int(size * 0.92)
    font = load_font(size)
    b = draw.textbbox((0, 0), text, font=font, stroke_width=outline)
    tw, th = b[2] - b[0], b[3] - b[1]
    x = (OUT_W - tw) // 2 - b[0]
    y = int(cy - th / 2) - b[1]
    draw.text((x, y), text, font=font, fill=color,
              stroke_width=outline, stroke_fill=OUTLINE_COLOR)
    return y + th + b[1]


def main():
    ap = argparse.ArgumentParser(description="Compose a polished 9:16 thumbnail.")
    ap.add_argument("--frame", default="cover_frame.jpg")
    ap.add_argument("--meta", default="cover_frame.json")
    ap.add_argument("--title", default=None)
    ap.add_argument("--subtitle", default=None)
    ap.add_argument("--trim-bottom", type=float, default=CROP_BOTTOM)
    ap.add_argument("--trim-top", type=float, default=CROP_TOP)
    ap.add_argument("--border-overlay", default=None,
                    help="transparent PNG frame to composite instead of the "
                         "procedural gold border")
    ap.add_argument("--no-border", action="store_true")
    ap.add_argument("-o", "--output", default="thumbnail_pro.jpg")
    args = ap.parse_args()

    if not os.path.exists(args.frame):
        sys.exit(f"{args.frame} not found — run extract_face_frame.py first.")

    def read(name, val):
        if val is not None:
            return val
        return open(name, encoding="utf-8").read().strip() if os.path.exists(name) else ""
    title = read("title.txt", args.title)
    subtitle = read("subtitle.txt", args.subtitle)
    if not title:
        sys.exit("No title. Run generate_title.py, or pass --title.")

    face = None
    if os.path.exists(args.meta):
        with open(args.meta, encoding="utf-8") as f:
            face = json.load(f).get("face")

    img = Image.open(args.frame).convert("RGB")
    if args.trim_top > 0 or args.trim_bottom > 0:
        w, h = img.size
        top = int(h * args.trim_top)
        img = img.crop((0, top, w, int(h * (1 - args.trim_bottom))))
        if face:
            face = (face[0], max(0, face[1] - top), face[2], face[3])

    img = crop_vertical(img, face)
    img = add_bottom_gradient(img)

    draw = ImageDraw.Draw(img)
    max_w = int(OUT_W * (1 - 2 * SIDE_MARGIN_RATIO))
    title_cy = OUT_H * TITLE_CENTER_Y
    bottom = draw_centered(draw, title, title_cy,
                           int(OUT_H * TITLE_RATIO), TITLE_COLOR, max_w)
    if subtitle:
        sub_cy = bottom + int(OUT_H * SUB_RATIO * 0.9)
        draw_centered(draw, subtitle, sub_cy,
                      int(OUT_H * SUB_RATIO), SUB_COLOR, max_w)

    if args.border_overlay and os.path.exists(args.border_overlay):
        ov = Image.open(args.border_overlay).convert("RGBA").resize((OUT_W, OUT_H))
        img = Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")
    elif not args.no_border:
        img = draw_gold_frame(img)

    img.save(args.output, quality=92)
    print(f"Title: {title}")
    print(f"Subtitle: {subtitle or '(none)'}")
    print(f"Wrote {args.output}  ({OUT_W}x{OUT_H})")


if __name__ == "__main__":
    main()
