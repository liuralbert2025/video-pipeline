# PKU Video Pipeline — all scripts

Everything for the three tasks plus the Windows timing script, in one folder.
Keep all files together (the selectors import `clip_utils.py`, and the thumbnail
step needs `haarcascade_frontalface_default.xml` alongside it).

## Setup (Windows PC with the NVIDIA GPU)

    winget install ffmpeg
    pip install openai-whisper pyannote.audio openai edge-tts opencv-python pillow scikit-learn numpy
    # GPU build of PyTorch (makes Whisper + diarization use the 1070):
    pip uninstall -y torch
    pip install torch --index-url https://download.pytorch.org/whl/cu121
    python -c "import torch; print(torch.cuda.is_available())"   # must print True

In `transcribe.py` set `MODEL_SIZE = "medium"` and `LANGUAGE = "zh"`.

Set your keys in the PowerShell window (session-only):

    $env:HF_TOKEN     = "hf_..."      # HuggingFace, for diarization
    $env:LLM_API_KEY  = "sk-..."      # DeepSeek
    $env:LLM_BASE_URL = "https://api.deepseek.com/v1"
    $env:LLM_MODEL    = "deepseek-chat"

## Run the full pipeline + time it

    powershell -ExecutionPolicy Bypass -File run_and_time.ps1

Run it twice — the first run downloads the Whisper/pyannote models (that time
counts against those stages), so the second run is the real benchmark.

## Files

Task 1 — highlight reels:
    split.py               separate audio/video
    transcribe.py          audio -> timestamped text (Whisper)
    select_highlights.py   keyword selector
    select_extractive.py   TextRank selector
    select_llm.py          LLM selector
    clip_utils.py          shared boundary-snapping (REQUIRED by the selectors)
    cut_and_stitch.py      cut + stitch reel
    cut_and_stitch_pro.py  + captions + vertical 9:16
    make_reel.py           runs Task 1 end to end (--selector keyword|extractive|llm)

Task 2 — commentary re-dubbing:
    diarize_test.py        speaker diarization (GPU-aware)
    reclassify.py          LLM narration-vs-dialogue relabel
    rewrite_narration.py   rewrite narration (LLM)
    tts_narration.py       re-voice narration (edge-tts)
    reassemble.py          swap new narration into the video

Task 3 — thumbnail:
    extract_face_frame.py  pick best face frame
    generate_title.py      4/8-char title + description (LLM)
    compose_thumbnail_pro.py  9:16 cover with border + title
    haarcascade_frontalface_default.xml   face-detection data (REQUIRED)

Automation:
    run_and_time.ps1       runs the whole chain on Windows and times each stage

Note: put your source video in this folder as `task2.mp4` (or pass another name).
