"""
Step 3 of the pipeline: separate a video's audio and video tracks with ffmpeg.

Usage:
    python3 split.py input.mp4

Outputs (next to the input file):
    <name>_audio.mp3   -> audio only (feed this to the transcriber in step 4)
    <name>_video.mp4   -> video only, no sound (kept for reference)

Requires ffmpeg installed and on your PATH (check with: ffmpeg -version).
"""

import subprocess
import sys
import os


def run(cmd):
    print("  $", " ".join(cmd))
    subprocess.run(cmd, check=True)


def split(input_path):
    if not os.path.exists(input_path):
        sys.exit(f"File not found: {input_path}")

    base, _ = os.path.splitext(input_path)
    audio_out = f"{base}_audio.mp3"
    video_out = f"{base}_video.mp4"

    print("Extracting audio ->", audio_out)
    # -vn = drop video, -q:a 0 = best VBR quality
    run(["ffmpeg", "-y", "-i", input_path, "-vn", "-q:a", "0", audio_out,
         "-loglevel", "error"])

    print("Extracting video (no audio) ->", video_out)
    # -an = drop audio, -c:v copy = keep video as-is (fast, no re-encode)
    run(["ffmpeg", "-y", "-i", input_path, "-an", "-c:v", "copy", video_out,
         "-loglevel", "error"])

    print("\nDone.")
    print("  audio:", audio_out)
    print("  video:", video_out)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: python3 split.py <input_video>")
    split(sys.argv[1])
