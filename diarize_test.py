"""
Task 2, step 3c (feasibility test): can we separate the NARRATOR from the
TV-drama dialogue in a commentary video?

This runs speaker diarization ("who spoke when") on the audio and prints the
speaker turns. If you also pass the Whisper transcript, it prints who said what,
so you can read down the list and spot which speaker is the narrator.

    # 1. make the audio + transcript first (reuse Task 1 scripts):
    python3 split.py task2.mp4                       # -> task2_audio.mp3
    python3 transcribe.py task2_audio.mp3            # -> task2_audio.json  (set LANGUAGE="zh")

    # 2. then run this:
    python3 diarize_test.py task2.mp4 --transcript task2_audio.json

Setup (one time):
    pip install pyannote.audio
    # pyannote's models are gated but free:
    #   - make a HuggingFace account, create a token (Settings -> Access Tokens)
    #   - visit and accept the terms on these two model pages:
    #       https://huggingface.co/pyannote/speaker-diarization-3.1
    #       https://huggingface.co/pyannote/segmentation-3.0
    export HF_TOKEN="hf_xxx"

What to look for in the output:
    * A small number of speakers (2-4), with ONE speaker dominating the total
      talk time and appearing in regular chunks = probably the narrator.
    * If instead you see many speakers scattered in short bursts, the drama
      dialogue and narration may be too tangled to separate by voice alone, and
      we'd add a second signal (background music/SFX detection) to help.
"""

import argparse
import json
import os
import ssl
import subprocess
import sys

# TLS fix for networks that inspect HTTPS (same as the Whisper download).
ssl._create_default_https_context = ssl._create_unverified_context


def run(cmd):
    subprocess.run(cmd, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)


def extract_wav(video, wav_out):
    """pyannote wants 16 kHz mono WAV."""
    run(["ffmpeg", "-y", "-i", video, "-vn", "-ac", "1", "-ar", "16000",
         wav_out, "-loglevel", "error"])


# ---------- pure logic (unit-testable, no heavy deps) ----------

def summarize_speakers(turns):
    """turns = list of (start, end, speaker). Return {speaker: total_seconds}
    sorted most-talkative first."""
    totals = {}
    for start, end, spk in turns:
        totals[spk] = totals.get(spk, 0.0) + (end - start)
    return dict(sorted(totals.items(), key=lambda kv: kv[1], reverse=True))


def assign_speaker(seg_start, seg_end, turns):
    """Which speaker overlaps this [seg_start, seg_end] the most?"""
    best, best_overlap = None, 0.0
    for start, end, spk in turns:
        overlap = min(seg_end, end) - max(seg_start, start)
        if overlap > best_overlap:
            best, best_overlap = spk, overlap
    return best


def align(asr_segments, turns):
    """Attach a speaker label to every transcript segment."""
    out = []
    for s in asr_segments:
        spk = assign_speaker(s["start"], s["end"], turns)
        out.append({"start": s["start"], "end": s["end"],
                    "speaker": spk or "?", "text": s.get("text", "").strip()})
    return out

# ---------------------------------------------------------------


def diarize(wav_path):
    """Run pyannote and return a list of (start, end, speaker) turns."""
    try:
        from pyannote.audio import Pipeline
    except ImportError:
        sys.exit("pyannote not installed. Run: pip install pyannote.audio")

    token = os.environ.get("HF_TOKEN")
    if not token:
        sys.exit("Set HF_TOKEN first (see the setup notes at the top of this file).")

    print("Loading diarization model (first run downloads it) ...")
    # pyannote renamed this arg: newer versions use `token=`, older ones
    # `use_auth_token=`. Try the new name first, fall back to the old one.
    try:
        pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1", token=token)
    except TypeError:
        pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-3.1", use_auth_token=token)

    # Move the pipeline onto the GPU if one is available — this is the biggest
    # speedup for diarization. Falls back to CPU automatically.
    try:
        import torch
        if torch.cuda.is_available():
            pipeline.to(torch.device("cuda"))
            print(f"Using GPU: {torch.cuda.get_device_name(0)}")
        else:
            print("No CUDA GPU detected — running diarization on CPU.")
    except Exception as e:
        print(f"(Could not move pipeline to GPU: {e}; using CPU.)")

    print("Diarizing ...")
    result = pipeline(wav_path)

    # pyannote 3.x returns an Annotation directly (it has .itertracks).
    # pyannote 4.x returns a DiarizeOutput wrapper with the Annotation under
    # .speaker_diarization. Handle both.
    annotation = result
    if not hasattr(annotation, "itertracks"):
        for attr in ("speaker_diarization", "diarization", "annotation"):
            cand = getattr(result, attr, None)
            if cand is not None and hasattr(cand, "itertracks"):
                annotation = cand
                break
    if not hasattr(annotation, "itertracks"):
        avail = [a for a in dir(result) if not a.startswith("_")]
        sys.exit(f"Unexpected diarization output type '{type(result).__name__}'.\n"
                 f"Available attributes: {avail}\n"
                 "Send this list to Claude so the script can be adapted.")

    turns = [(round(t.start, 2), round(t.end, 2), spk)
             for t, _, spk in annotation.itertracks(yield_label=True)]
    turns.sort(key=lambda x: x[0])
    return turns


def main():
    ap = argparse.ArgumentParser(
        description="Test whether the narrator separates from the drama.")
    ap.add_argument("video", help="the commentary video (or a wav/mp3)")
    ap.add_argument("--transcript", default=None,
                    help="Whisper transcript JSON, to show who-said-what")
    args = ap.parse_args()

    if not os.path.exists(args.video):
        sys.exit(f"Not found: {args.video}")

    base, ext = os.path.splitext(args.video)
    if ext.lower() in (".wav",):
        wav = args.video
    else:
        wav = f"{base}_16k.wav"
        print("Extracting 16 kHz mono audio ...")
        extract_wav(args.video, wav)

    turns = diarize(wav)
    if not turns:
        sys.exit("No speech detected.")

    totals = summarize_speakers(turns)
    grand = sum(totals.values()) or 1.0

    print(f"\n=== {len(totals)} speaker(s) found, {len(turns)} turns ===")
    for spk, secs in totals.items():
        print(f"  {spk}: {secs:6.1f}s  ({100*secs/grand:4.1f}% of speech)")

    # save the raw turns so later steps can reuse them
    with open("diarization.json", "w", encoding="utf-8") as f:
        json.dump([{"start": s, "end": e, "speaker": spk}
                   for s, e, spk in turns], f, ensure_ascii=False, indent=2)
    print("\nWrote diarization.json")

    if args.transcript and os.path.exists(args.transcript):
        with open(args.transcript, encoding="utf-8") as f:
            asr = json.load(f)
        labeled = align(asr, turns)
        print("\n=== who said what (read this to spot the narrator) ===")
        for r in labeled:
            print(f"  [{r['start']:6.1f}-{r['end']:6.1f}] {r['speaker']:>12} | "
                  f"{r['text'][:60]}")
        with open("labeled_transcript.json", "w", encoding="utf-8") as f:
            json.dump(labeled, f, ensure_ascii=False, indent=2)
        print("\nWrote labeled_transcript.json")
    else:
        print("\n(Tip: pass --transcript task2_audio.json to see who said what.)")


if __name__ == "__main__":
    main()
