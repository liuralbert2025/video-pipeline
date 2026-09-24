"""
YouTube Shorts uploader using the OFFICIAL YouTube Data API v3.

No browser, no Selenium, no Chrome profiles — so none of the automated-sign-in
blocking, profile locks, or selector breakage. You authorize once in a normal
browser window and the token is saved and auto-refreshed after that.

Reads the same folder layout as the Selenium version:
    videos/test.mp4        the video
    videos/test.txt        {"title": "...", "tags": ["a","b"]}   (optional)
    videos/test.jpg        custom thumbnail (optional; needs a verified channel)

Usage:
    python upload_youtube_api.py                 # uploads everything in videos/
    python upload_youtube_api.py --privacy public
    python upload_youtube_api.py --file videos/test.mp4

Setup (one time — see SETUP_YOUTUBE_API.txt):
    pip install google-api-python-client google-auth-oauthlib google-auth-httplib2
    put client_secret.json next to this script, then run it once and approve
    the consent screen in the browser that opens.
"""

import argparse
import glob
import json
import os
import sys

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
CLIENT_SECRET = "client_secret.json"
TOKEN_FILE = "youtube_token.json"

# A video becomes a Short when it's vertical 9:16, <= 60s, and tagged #Shorts.
SHORTS_TAG = "#Shorts"
CATEGORY_ID = "24"          # 24 = Entertainment
DEFAULT_PRIVACY = "private"  # private | unlisted | public


def get_service():
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError:
        sys.exit("Missing packages. Run:\n"
                 "  pip install google-api-python-client google-auth-oauthlib "
                 "google-auth-httplib2")

    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("Refreshing saved token ...")
            creds.refresh(Request())
        else:
            if not os.path.exists(CLIENT_SECRET):
                sys.exit(f"{CLIENT_SECRET} not found.\n"
                         "Download it from Google Cloud Console (OAuth client ID,\n"
                         "type 'Desktop app') and put it next to this script.\n"
                         "See SETUP_YOUTUBE_API.txt for the full walkthrough.")
            print("Opening a browser for one-time authorization ...")
            flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
        print(f"Authorization saved to {TOKEN_FILE} (reused from now on).")

    from googleapiclient.discovery import build
    return build("youtube", "v3", credentials=creds)


def load_metadata(video_path):
    """Read <video>.txt = {"title","tags"}; fall back to the filename."""
    txt = os.path.splitext(video_path)[0] + ".txt"
    default = {"title": os.path.splitext(os.path.basename(video_path))[0],
               "tags": []}
    if os.path.exists(txt):
        try:
            with open(txt, "r", encoding="utf-8") as f:
                meta = json.load(f)
            return {"title": meta.get("title", default["title"]),
                    "tags": meta.get("tags", [])}
        except Exception as e:
            print(f"  couldn't read {os.path.basename(txt)} ({e}); using defaults")
    return default


def upload(youtube, video_path, privacy):
    from googleapiclient.http import MediaFileUpload

    meta = load_metadata(video_path)
    title = meta["title"][:100]                       # YouTube caps titles at 100
    tagline = " ".join(f"#{t}" for t in meta.get("tags", []))
    description = f"{meta['title']} {tagline} {SHORTS_TAG}".strip()

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": meta.get("tags", []),
            "categoryId": CATEGORY_ID,
        },
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
        },
    }

    print(f"  title   : {title}")
    print(f"  privacy : {privacy}")
    media = MediaFileUpload(video_path, chunksize=1024 * 1024 * 4, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body,
                                      media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"  uploading... {int(status.progress() * 100)}%", end="\r")
    print("  uploading... 100%   ")

    video_id = response["id"]
    print(f"  DONE -> https://youtu.be/{video_id}")

    # optional custom thumbnail (requires a verified channel)
    for ext in (".jpg", ".png"):
        thumb = os.path.splitext(video_path)[0] + ext
        if os.path.exists(thumb):
            try:
                youtube.thumbnails().set(videoId=video_id,
                                         media_body=MediaFileUpload(thumb)).execute()
                print(f"  thumbnail set: {os.path.basename(thumb)}")
            except Exception as e:
                print(f"  thumbnail skipped ({str(e)[:120]})")
            break
    return video_id


def main():
    ap = argparse.ArgumentParser(description="Upload to YouTube via the Data API.")
    ap.add_argument("--dir", default="videos", help="folder of .mp4 files")
    ap.add_argument("--file", default=None, help="upload just this one file")
    ap.add_argument("--privacy", default=DEFAULT_PRIVACY,
                    choices=["private", "unlisted", "public"])
    args = ap.parse_args()

    if args.file:
        videos = [args.file]
    else:
        videos = sorted(glob.glob(os.path.join(args.dir, "*.mp4")))
    videos = [v for v in videos if os.path.exists(v)]
    if not videos:
        sys.exit(f"No .mp4 files found in '{args.dir}'.")

    youtube = get_service()
    print(f"\n{len(videos)} video(s) to upload\n")

    ok = 0
    for i, v in enumerate(videos, 1):
        print(f"[{i}/{len(videos)}] {os.path.basename(v)}")
        try:
            upload(youtube, v, args.privacy)
            ok += 1
        except Exception as e:
            print(f"  FAILED: {str(e)[:300]}")
        print()
    print(f"Uploaded {ok}/{len(videos)}")


if __name__ == "__main__":
    main()
