# Automated Short-Video Production Pipeline

An end-to-end system that turns a long-form video into publish-ready short-form
content: it transcribes the audio, works out *who is speaking*, rewrites and
re-voices the narration, cuts and reformats the video, generates a thumbnail,
and uploads the result — without a human in the loop.


---

## What it actually does

Given a ~6-minute source video, one command produces a finished, re-narrated
vertical video plus a matching thumbnail in **~3 minutes** on a single GPU.

Three pipelines share a common toolchain:

**1. Highlight reels** — finds the most interesting moments in a long video and
cuts them into a short reel.

**2. Commentary re-dubbing** — the most involved one. Chinese commentary videos
("解说") mix a narrator talking *over* clips of a TV drama. This pipeline
separates the narrator from the show's own dialogue, rewrites only the
narrator's script, re-voices it with TTS, and splices the new audio back into
the original timeline — leaving the drama untouched.

**3. Thumbnail generation** — samples frames, picks the best character close-up
via face detection, generates a title from the dialogue, and composites a
styled 9:16 cover.

---

## Architecture

```
source video
    │
    ├─ ffmpeg ──────────────► audio track
    │                              │
    │                        Whisper (GPU) ──► timestamped transcript
    │                              │
    │                     pyannote diarization ──► "who spoke when"
    │                              │
    │                     LLM reclassification ──► narrator vs. dialogue
    │                              │
    │                     ┌────────┴────────┐
    │                narration          drama audio
    │                     │             (untouched)
    │              LLM rewrite                │
    │                     │                   │
    │              neural TTS                 │
    │                     └────────┬──────────┘
    │                              │
    └──────────────────► ffmpeg reassembly ──► final video
                                   │
    frames ──► face detection ──► LLM title ──► composited thumbnail
```

---

## Technical decisions worth calling out

**Speaker separation needed two signals, not one.** Diarization alone assigns
speakers by *voice*, which misfired: actor lines were being labelled as the
narrator, so the pipeline muted real dialogue and dubbed over it. The fix was a
second pass that classifies each line by its *text* — narration is third-person
commentary, drama dialogue is first-person and in-scene — which corrects what
the acoustic model gets wrong. Voice and meaning disagree in different places,
so combining them beats either alone.

**Cuts snap to sentence boundaries.** The first version padded each clip by a
fixed number of seconds, which reliably sliced through words. Because Whisper
already emits timestamps at natural pauses, clips are now expanded *outward to
the nearest transcript boundary* — so a cut can only ever land in silence
between utterances.

**Audio crossfades belong on the drama side of the boundary.** Fading the
original audio down *as* the new narration faded in produced a moment where
both narrators were audible. Moving the fade to just *before* and *after* each
narration slot — keeping the slot itself hard-silent — gives smooth transitions
with only one voice at a time.

**Captions are rendered, not subtitled.** Most ffmpeg caption workflows need a
build with `libass`, which many installs lack. Instead each caption is drawn as
a transparent PNG with Pillow and overlaid with a timed ffmpeg filter — works on
any ffmpeg build, and gives full control over typography. Line wrapping measures
real pixel widths rather than guessing from character counts.

**Three interchangeable selection strategies** behind one interface, so they can
be compared on identical input: keyword scoring, TextRank extractive
summarisation (TF-IDF similarity graph + PageRank), and an LLM selector. All
emit the same `clips.json`, so everything downstream is agnostic.

**Provider-agnostic LLM layer.** All model calls speak the OpenAI API format, so
switching between DeepSeek, Qwen, Zhipu or OpenAI is two environment variables
and no code change — which mattered in practice when one provider was
unreachable mid-development.

---

## Engineering problems solved along the way

Most of these only showed up on real hardware and real footage:

- **GPU produced `NaN`s during transcription.** The GTX 16-series has a broken
  fp16 path in Whisper's decoder; forcing fp32 fixed it at a ~2× speed cost.
- **Diarization crashed on Windows** because pyannote 4.x decodes audio through
  `torchcodec`, which needs FFmpeg shared DLLs. Solved by decoding the WAV
  directly and handing pyannote a raw waveform tensor, bypassing the dependency.
- **A captioned reel rendered as 28 minutes instead of 30 seconds** — an ffmpeg
  `-t` flag placed after the input was being parsed as an option for the *next*
  input rather than as an output duration limit. Invisible in tests because the
  test clip was shorter than the bug's effect.
- **API calls could hang forever**, stalling the whole pipeline. All LLM calls
  now carry timeouts and automatic retries, which matters for unattended runs.

Both the caption-timing bug and the mid-word cuts were found by *watching the
output*, not by reading the code — the recurring lesson of the project.

---

## Performance

Measured end-to-end on a 6-minute source video (GTX 1650, 16 GB RAM):

| Stage | Time |
|---|---|
| Transcription (Whisper, GPU) | 44s |
| Speaker diarization (pyannote, GPU) | 40s |
| Frame sampling + face detection | 36s |
| Text-to-speech | 32s |
| LLM rewrite / classification / titling | 30s |
| ffmpeg cutting + reassembly | 13s |
| **Total** | **~196s** |

Profiling pointed at the obvious next wins: the frame sampler scans the whole
video to choose a single thumbnail, and the TTS calls are sequential when they
could run in parallel.

---

## Stack

`Python` · `ffmpeg` · `OpenAI Whisper` · `pyannote.audio` · `PyTorch (CUDA)` ·
`OpenCV` · `Pillow` · `scikit-learn` · `edge-tts` · `Selenium` ·
`YouTube Data API v3`

---

## Running it

```bash
pip install -r requirements.txt   # plus ffmpeg on your PATH
```

Credentials come from environment variables — no keys live in this repository:

```bash
export LLM_API_KEY="..."          # any OpenAI-compatible provider
export LLM_BASE_URL="https://api.deepseek.com"
export LLM_MODEL="deepseek-chat"
export HF_TOKEN="..."             # HuggingFace, for the diarization model
```

**Pipeline 1 — highlight reel** (one command, end to end):

```bash
python make_reel.py input.mp4 --selector extractive --captions --vertical
```

**Pipeline 2 — commentary re-dubbing:**

```bash
python split.py input.mp4                              # -> input_audio.mp3
python transcribe.py input_audio.mp3                   # -> input_audio.json
python diarize_test.py input.mp4 --transcript input_audio.json
python reclassify.py                                   # text-based label correction
python rewrite_narration.py
python tts_narration.py
python reassemble.py input.mp4 redubbed.mp4
```

**Pipeline 3 — thumbnail:**

```bash
python extract_face_frame.py input.mp4 --every 1.5     # -> cover_frame.jpg
python generate_title.py --chars 4                     # -> title.txt, subtitle.txt
python compose_thumbnail_pro.py -o thumbnail.jpg
```

---

## Notes

Source footage and generated media are intentionally excluded from this
repository; the code is the artifact. The pipeline was developed and tested
against publicly available video for research purposes.
