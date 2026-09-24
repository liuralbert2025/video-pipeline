YouTube Shorts + TikTok auto-uploaders (Selenium)
=================================================

NOTE ON THE YOUTUBE UPLOADER
  upload_youtube_api.py (official YouTube Data API v3) is the one to use.
  upload_youtube.py drives YouTube Studio through Selenium and is kept for
  reference only — Google blocks sign-in from automated browsers, so it can't
  authenticate reliably. The API version needs a one-time OAuth consent and
  then runs headless forever. See SETUP_YOUTUBE_API.txt.
  The TikTok uploader is still Selenium-based (TikTok's Content Posting API
  requires an approved developer app).
Ported from the Douyin uploader, same idea: a persistent Chrome login profile
per account, per-video metadata from a same-name .txt file, optional scheduling.
These drive the real YouTube Studio / TikTok upload pages in a logged-in
browser (no API keys, no app approval needed).

FILES
  uploader_common.py   shared base: config, Chrome profile, scheduling, metadata
  upload_youtube.py     YouTube Shorts upload flow
  upload_tiktok.py      TikTok upload flow
  login_helper.py       one-time login helper (saves cookies into the profile)
  accounts_config.json  accounts + settings
  requirements.txt      selenium
  login_youtube.bat / login_tiktok.bat / run_youtube.bat / run_tiktok.bat

SETUP (once)
  1. Install Google Chrome (normal desktop Chrome).
  2. pip install -r requirements.txt
     (Selenium 4.6+ auto-manages ChromeDriver — nothing else to download.)
  3. Edit accounts_config.json: set video_save_dir to the folder with your
     .mp4 files, and enable the account(s) you want.

LOG IN (once per account, per site)
  Run:  login_youtube.bat      (and/or)  login_tiktok.bat
  A Chrome window opens. Log into your channel/account by hand, then press Enter
  in the terminal. The cookies are saved in that account's Chrome profile and
  reused on every run — you won't log in again unless the session expires.

VIDEO FOLDER LAYOUT
  In video_save_dir, put your videos as .mp4. Optionally, next to each video:
    myclip.mp4
    myclip.txt   ->  {"title": "天家父子", "tags": ["大明王朝", "历史"]}
    myclip.jpg   ->  optional custom thumbnail (YouTube; needs a verified channel)
  If there's no .txt, the filename is used as the title and no tags are added.

RUN
  YouTube:  run_youtube.bat        (or: python upload_youtube.py)
  TikTok:   run_tiktok.bat         (or: python upload_tiktok.py)
  One account only:  python upload_youtube.py account_2

  With use_schedule=false (default) it uploads the videos back to back — good for
  testing. Set use_schedule=true in accounts_config.json to spread them across
  the 06-09 / 11-14 / 17-23 windows.

HONEST NOTES / TROUBLESHOOTING
  - YouTube Studio and TikTok change their pages often. The click targets live
    in the SEL dict at the top of each upload_*.py. If a run stops at a step
    ("couldn't find X"), open that file and update that one selector — everything
    else keeps working.
  - Keep the window visible; do NOT run headless. Both sites detect automation,
    and TikTok especially may show a captcha — if it does, solve it by hand in
    the window and the script continues.
  - Upload/encode waits are fixed sleeps (YouTube ~8s+, TikTok ~15s). If your
    videos are large or the machine is slow, increase the time.sleep() values.
  - YouTube marks a video as a Short automatically when it's vertical 9:16,
    <= 60s, and has #Shorts (this is added to the description automatically).
  - Post modestly at first. Rapid automated posting risks temporary limits on
    a new account.
