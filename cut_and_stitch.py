"""
Step 6 (final): cut the highlight ranges from the ORIGINAL video (video+audio)
and stitch them into one highlight reel.

Reads clips.json (from step 5) and the original video, and writes highlights.mp4.

Usage:
    python3 cut_and_stitch.py input.mp4
    python3 cut_and_stitch.py input.mp4 my_reel.mp4      # custom output name

How it works:
  - Each clip is cut from the original and RE-ENCODED. Re-encoding (rather than
    a raw copy) makes every clip start cleanly on its own keyframe, so the final
    stitched video has no black frames or audio/video sync drift.
  - The clips are then concatenated into one file.

Requires ffmpeg on PATH (you have it).
"""

import json
import os
import shutil
import subprocess
import sys


def run(cmd):
    subprocess.run(cmd, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)


def main(video_path, out_path):
    if not os.path.exists(video_path):
        sys.exit(f"Video not found: {video_path}")
    if not os.path.exists("clips.json"):
        sys.exit("clips.json not found — run select_highlights.py first.")

    with open("clips.json", encoding="utf-8") as f:
        clips = json.load(f)
    if not clips:
        sys.exit("clips.json is empty — nothing to cut.")

    tmp = os.path.abspath("_clips_tmp")
    if os.path.exists(tmp):
        shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp, exist_ok=True)

    print(f"Cutting {len(clips)} clip(s) from {video_path} ...")
    parts = []
    for i, c in enumerate(clips):
        start = float(c["start"])
        dur = float(c["end"]) - start
        if dur <= 0:
            continue
        part = os.path.join(tmp, f"clip_{i:03d}.mp4")
        # -ss before -i = fast accurate seek; re-encode for clean cut points
        run(["ffmpeg", "-y", "-ss", f"{start:.3f}", "-i", video_path,
             "-t", f"{dur:.3f}",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
             "-c:a", "aac", "-b:a", "128k",
             "-avoid_negative_ts", "make_zero",
             part, "-loglevel", "error"])
        parts.append(part)
        print(f"  clip {i+1}: {start:.1f}s -> {c['end']:.1f}s")

    if not parts:
        sys.exit("No valid clips to stitch.")

    # concat list (paths in single quotes so spaces are fine)
    list_file = os.path.join(tmp, "list.txt")
    with open(list_file, "w", encoding="utf-8") as f:
        for p in parts:
            f.write(f"file '{p}'\n")

    print("Stitching into", out_path, "...")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_file,
         "-c", "copy", "-movflags", "+faststart",
         out_path, "-loglevel", "error"])

    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\nDone -> {out_path}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("Usage: python3 cut_and_stitch.py <original_video> [output.mp4]")
    video = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else "highlights.mp4"
    main(video, out)
