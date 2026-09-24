"""
Task 2, step 4c (final): rebuild the video with the new narration.

Keeps the original video track and the drama segments' audio exactly as they
are, but MUTES the original narrator during each narration slot and drops the
new TTS clip in its place. The video length is unchanged; if a new clip is a
little shorter than its slot, the tail is simply quiet.

Usage:
    python3 reassemble.py task2.mp4
    python3 reassemble.py task2.mp4 new_commentary.mp4

Reads:  tts_manifest.json (from tts_narration.py) + the original video
Writes: task2_redubbed.mp4  (or your chosen name)

How the audio is built (one ffmpeg pass):
  * [0:a] original audio, with volume forced to 0 during every narration slot
    (so the old narrator is removed but the drama audio stays);
  * each TTS clip delayed to start exactly at its slot's start time;
  * all mixed together (no overlap, so the sum is clean).
"""

import argparse
import json
import os
import subprocess
import sys


# Diarization sometimes marks a narration slot starting a moment too early,
# while the previous actor is still finishing a word. LEAD_IN holds off the
# mute and the new voice by this many seconds so the actor's tail plays out.
# Raise it if actors still get clipped; lower it toward 0 if you hear a sliver
# of the old narrator before the new voice.
# The original audio is faded down over this many seconds JUST BEFORE each
# narration slot and faded back up JUST AFTER it — i.e. the crossfade happens in
# the drama on either side, while the slot interior stays fully silent. That way
# the transitions are smooth but the OLD narrator is never audible under the new
# one (no double-voice). Raise it for longer, gentler crossfades.
FADE = 0.60
# Fade-in and fade-out on each new narration clip so the voice eases in and out.
FADE_IN = 0.25
FADE_OUT = 0.35


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        print("\n--- ffmpeg failed ---")
        print((p.stderr or p.stdout or "").strip()[-1500:])
        print("--- command ---\n" + " ".join(cmd))
        sys.exit(f"ffmpeg exited {p.returncode}")


def main():
    ap = argparse.ArgumentParser(description="Reassemble the re-dubbed video.")
    ap.add_argument("video")
    ap.add_argument("output", nargs="?", default="task2_redubbed.mp4")
    ap.add_argument("--manifest", default="tts_manifest.json")
    ap.add_argument("--fade", type=float, default=FADE,
                    help="seconds to fade the original audio out/in at each "
                         f"narration boundary (default {FADE})")
    args = ap.parse_args()

    if not os.path.exists(args.video):
        sys.exit(f"Video not found: {args.video}")
    if not os.path.exists(args.manifest):
        sys.exit(f"{args.manifest} not found — run tts_narration.py first.")

    with open(args.manifest, encoding="utf-8") as f:
        clips = json.load(f)
    clips = [c for c in clips if os.path.exists(c["file"])]
    if not clips:
        sys.exit("No TTS clips found (check the paths in the manifest).")

    # inputs: the video first, then every TTS clip
    cmd = ["ffmpeg", "-y", "-i", args.video]
    for c in clips:
        cmd += ["-i", c["file"]]

    fade = max(0.05, args.fade)

    # Time-varying volume for the ORIGINAL audio. For each narration slot [s,e]
    # it is fully 0 from s to e, and ramps between 1 and 0 in the `fade` seconds
    # OUTSIDE the slot (in the neighbouring drama), so the slot interior is
    # always silent (no old narrator under the new one) while the transitions
    # stay smooth. Per slot:
    #     factor = max( clamp((s - t)/fade, 0, 1), clamp((t - e)/fade, 0, 1) )
    #   = 1 before s-fade, ramps 1->0 over [s-fade, s], 0 in [s, e],
    #     ramps 0->1 over [e, e+fade], 1 after.
    # All slots' factors are multiplied. Commas are escaped (\,) for ffmpeg.
    terms = []
    for c in clips:
        s, e = c["start"], c["end"]
        left = f"max(0\\,min(1\\,({s:.3f}-t)/{fade}))"
        right = f"max(0\\,min(1\\,(t-{e:.3f})/{fade}))"
        terms.append(f"max({left}\\,{right})")
    vol_expr = "*".join(terms)
    parts = [f"[0:a]volume=volume='{vol_expr}':eval=frame[base]"]

    # place each TTS clip at its slot start, easing in and out
    mix_labels = ["[base]"]
    for i, c in enumerate(clips):
        delay_ms = int(round(c["start"] * 1000))
        clip_dur = c.get("final_dur") or (c["end"] - c["start"])
        out_st = max(0.0, clip_dur - FADE_OUT)
        parts.append(f"[{i+1}:a]afade=t=in:st=0:d={FADE_IN},"
                     f"afade=t=out:st={out_st:.3f}:d={FADE_OUT},"
                     f"adelay={delay_ms}:all=1[d{i}]")
        mix_labels.append(f"[d{i}]")
    parts.append("".join(mix_labels) +
                 f"amix=inputs={len(mix_labels)}:normalize=0:duration=longest[aout]")

    filtergraph = ";".join(parts)

    cmd += ["-filter_complex", filtergraph,
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy",                 # keep the original video untouched
            "-c:a", "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            args.output, "-loglevel", "error"]

    print(f"Rebuilding with {len(clips)} new narration clip(s) ...")
    run(cmd)
    print(f"\nDone -> {args.output}")
    print("Original video + drama audio kept; narration slots replaced.")


if __name__ == "__main__":
    main()
