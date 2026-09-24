# run_and_time.ps1  —  run the full pipeline on Windows and time each stage.
#
# Usage (PowerShell, from your PKU Research folder):
#     .\run_and_time.ps1                 # uses task2.mp4
#     .\run_and_time.ps1 -video mine.mp4
#
# Set your keys in THIS PowerShell window first (they last only for the session):
#     $env:HF_TOKEN     = "hf_..."
#     $env:LLM_API_KEY  = "sk-..."
#     $env:LLM_BASE_URL = "https://api.deepseek.com/v1"
#     $env:LLM_MODEL    = "deepseek-chat"
#
# If "python" isn't found, try "py" instead (edit $PY below).

param([string]$video = "task2.mp4")

$PY = "python"                 # change to "py" if needed
$ErrorActionPreference = "Continue"
$results = [ordered]@{}
$base = [System.IO.Path]::GetFileNameWithoutExtension($video)

function Time-Stage($label, [scriptblock]$block) {
    Write-Host "`n=== $label ===" -ForegroundColor Cyan
    $t = Get-Date
    & $block
    $ok = $?
    $sec = [math]::Round(((Get-Date) - $t).TotalSeconds, 1)
    $script:results[$label] = $sec
    $tag = if ($ok) { "OK" } else { "FAILED" }
    Write-Host ("--- {0}: {1}s ({2}) ---" -f $label, $sec, $tag) -ForegroundColor Yellow
}

# quick GPU check up front
Write-Host "GPU check:" -ForegroundColor Green
& $PY -c "import torch; print('CUDA available:', torch.cuda.is_available()); print('Device:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU')"

# ---- Task 2: re-dubbing chain ----
Time-Stage "1 split"        { & $PY split.py $video }
Time-Stage "2 transcribe"   { & $PY transcribe.py "${base}_audio.mp3" }
Time-Stage "3 diarize"      { & $PY diarize_test.py $video --transcript "${base}_audio.json" }
Time-Stage "4 reclassify"   { & $PY reclassify.py }
Time-Stage "5 rewrite"      { & $PY rewrite_narration.py }
Time-Stage "6 tts"          { & $PY tts_narration.py }
Time-Stage "7 reassemble"   { & $PY reassemble.py $video }

# ---- Task 3: thumbnail ----
Time-Stage "8 face-frame"   { & $PY extract_face_frame.py $video }
Time-Stage "9 title"        { & $PY generate_title.py }
Time-Stage "10 thumbnail"   { & $PY compose_thumbnail_pro.py }

# ---- summary ----
Write-Host "`n===== TIMING SUMMARY =====" -ForegroundColor Green
$total = 0.0
foreach ($k in $results.Keys) {
    "{0,-14} {1,8}s" -f $k, $results[$k]
    $total += $results[$k]
}
"{0,-14} {1,8}s" -f "TOTAL", [math]::Round($total, 1)
Write-Host "`nSource video: $video" -ForegroundColor Green
