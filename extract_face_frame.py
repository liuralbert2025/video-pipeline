"""
Task 3, core step: extract frames from a video and pick the best one to use as
a thumbnail background — a clear, sharp, front-facing character shot.

This is the one genuinely new technique in Task 3 ("抽帧 + 人脸"): sample frames
with ffmpeg, run face detection on each, and score them so a big, sharp,
centred face wins. If no face is found anywhere, it falls back to the sharpest
frame overall so you always get something usable.

Usage:
    python3 extract_face_frame.py task2.mp4
    python3 extract_face_frame.py task2.mp4 --every 1.5 --start 20 --end 300
    python3 extract_face_frame.py task2.mp4 -o cover.jpg

Requires:
    pip install opencv-python
    ffmpeg on PATH

Output:
    cover_frame.jpg      the chosen frame (full, uncropped)
    cover_frame.json     {timestamp, face box, scores} for the composition step
"""

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys

import cv2

# ---- scoring weights (tune to taste) ----
MIN_FACE = 60          # ignore faces smaller than this many px tall (noise)
W_FACE = 1.0           # weight on face size (fraction of frame height)
W_SHARP = 0.35         # weight on sharpness
W_CENTER = 0.20        # weight on how horizontally centred the face is
SHARP_REF = 400.0      # sharpness (Laplacian variance) that counts as "sharp"
# -----------------------------------------

# OpenCV 5.0 removed the bundled Haar cascade files, so we ship one next to this
# script and prefer it; fall back to the bundled copy on older OpenCV (4.x).
_HERE = os.path.dirname(os.path.abspath(__file__))
_LOCAL = os.path.join(_HERE, "haarcascade_frontalface_default.xml")
CASCADE = _LOCAL if os.path.exists(_LOCAL) else (
    cv2.data.haarcascades + "haarcascade_frontalface_default.xml")


def cascade_classifier(path):
    """Build a CascadeClassifier, wherever this OpenCV version keeps it.

    OpenCV 5.0 moved CascadeClassifier into the cv2.objdetect submodule; 4.x has
    it at the top level. If neither is present, the build is missing objdetect
    and the simplest fix is to use OpenCV 4.x.
    """
    if hasattr(cv2, "CascadeClassifier"):
        return cv2.CascadeClassifier(path)
    try:
        from cv2 import objdetect
        return objdetect.CascadeClassifier(path)
    except Exception:
        sys.exit("This OpenCV build has no CascadeClassifier. Install 4.x:\n"
                 "    pip uninstall -y opencv-python\n"
                 "    pip install 'opencv-python==4.11.0.86'")


def run(cmd):
    subprocess.run(cmd, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)


def extract_frames(video, out_dir, every, start, end):
    """Sample one frame every `every` seconds into out_dir. Returns [(t, path)]."""
    os.makedirs(out_dir, exist_ok=True)
    cmd = ["ffmpeg", "-y"]
    if start:
        cmd += ["-ss", str(start)]
    cmd += ["-i", video]
    if end:
        cmd += ["-to", str(end - (start or 0))]
    fps = 1.0 / every
    cmd += ["-vf", f"fps={fps}", os.path.join(out_dir, "f_%04d.jpg"),
            "-loglevel", "error"]
    run(cmd)
    frames = sorted(glob.glob(os.path.join(out_dir, "f_*.jpg")))
    # frame i corresponds to time start + i*every
    return [((start or 0) + i * every, p) for i, p in enumerate(frames)]


def sharpness(gray):
    """Variance of the Laplacian — higher = sharper / more in focus."""
    return cv2.Laplacian(gray, cv2.CV_64F).var()


def score_frame(path, detector):
    """Return (score, face_box or None, sharpness). Higher score = better cover."""
    img = cv2.imread(path)
    if img is None:
        return -1, None, 0
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    faces = detector.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5,
                                      minSize=(MIN_FACE, MIN_FACE))
    sharp = sharpness(gray)
    sharp_n = min(sharp / SHARP_REF, 1.0)

    if len(faces) == 0:
        # no face: a weak score based only on sharpness (used for fallback)
        return W_SHARP * sharp_n * 0.5, None, sharp

    # pick the biggest face in this frame
    fx, fy, fw, fh = max(faces, key=lambda b: b[2] * b[3])
    face_ratio = fh / h                                   # face height vs frame
    face_cx = fx + fw / 2
    centeredness = 1.0 - abs(face_cx - w / 2) / (w / 2)   # 1 = dead centre
    score = (W_FACE * face_ratio + W_SHARP * sharp_n +
             W_CENTER * centeredness)
    return score, (int(fx), int(fy), int(fw), int(fh)), sharp


def main():
    ap = argparse.ArgumentParser(
        description="Pick the best face frame from a video for a thumbnail.")
    ap.add_argument("video")
    ap.add_argument("-o", "--output", default="cover_frame.jpg")
    ap.add_argument("--every", type=float, default=1.5,
                    help="sample a frame every N seconds (default 1.5)")
    ap.add_argument("--start", type=float, default=0)
    ap.add_argument("--end", type=float, default=0)
    args = ap.parse_args()

    if not os.path.exists(args.video):
        sys.exit(f"Video not found: {args.video}")
    if not os.path.exists(CASCADE):
        sys.exit("Face cascade not found. Put haarcascade_frontalface_default.xml "
                 "in the same folder as this script (OpenCV 5.0 no longer ships "
                 "it).")

    detector = cascade_classifier(CASCADE)
    tmp = os.path.abspath("_frames_tmp")
    shutil.rmtree(tmp, ignore_errors=True)

    print("Extracting frames ...")
    frames = extract_frames(args.video, tmp, args.every, args.start, args.end)
    if not frames:
        sys.exit("No frames extracted.")
    print(f"  {len(frames)} candidate frames")

    print("Scoring frames (face detection) ...")
    best = None
    faces_found = 0
    for t, path in frames:
        score, box, sharp = score_frame(path, detector)
        if box is not None:
            faces_found += 1
        if best is None or score > best[0]:
            best = (score, t, path, box, sharp)

    score, t, path, box, sharp = best
    shutil.copy(path, args.output)
    with open("cover_frame.json", "w", encoding="utf-8") as f:
        json.dump({"timestamp": round(t, 2), "score": round(score, 3),
                   "face": box, "sharpness": round(sharp, 1),
                   "frames_with_faces": faces_found,
                   "frames_total": len(frames)}, f, indent=2)

    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\nBest frame at {t:.1f}s "
          f"({'face found' if box else 'NO face — sharpest fallback'})")
    print(f"  -> {args.output}")
    print(f"  {faces_found}/{len(frames)} frames had a detectable face")
    if box:
        print(f"  face box (x,y,w,h) = {box}")


if __name__ == "__main__":
    main()
