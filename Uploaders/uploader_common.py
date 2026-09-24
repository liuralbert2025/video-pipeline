"""
Shared infrastructure for the Selenium uploaders (YouTube Shorts, TikTok).

Ported from the supervisor's Douyin uploader, keeping the same ideas:
  - multi-account config (accounts_config.json)
  - a PERSISTENT Chrome profile per account, so you log in once and stay logged
    in (cookies live in the profile folder)
  - per-video metadata read from a same-name .txt file: {"title","tags"}
  - optional publish scheduling across time windows

Selenium 4.6+ auto-manages ChromeDriver, so there is no manual driver download
here — it just needs Google Chrome installed.

Platform specifics (which buttons to click) live in the subclasses in
upload_youtube.py and upload_tiktok.py.
"""

import os
import sys
import glob
import json
import time
from datetime import datetime, timedelta

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ACCOUNTS_CONFIG_FILE = os.path.join(BASE_DIR, "accounts_config.json")

# publish windows (local time), same idea as the Douyin script
PUBLISH_TIME_WINDOWS = [(6, 9), (11, 14), (17, 23)]


# --------------------------- config + scheduling ---------------------------

def load_accounts_config():
    if not os.path.exists(ACCOUNTS_CONFIG_FILE):
        return None
    try:
        with open(ACCOUNTS_CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"config load failed: {e}")
        return None


def get_enabled_accounts(config):
    if not config:
        return []
    return [a for a in config.get("accounts", []) if a.get("enabled", True)]


def video_save_dir(config):
    d = (config or {}).get("shared_settings", {}).get("video_save_dir", "videos")
    return d if os.path.isabs(d) else os.path.join(BASE_DIR, d)


def build_publish_schedule(video_count, now=None):
    """Even publish times across today's remaining windows (ported)."""
    if video_count <= 0:
        return []
    now = now or datetime.now()

    def windows_for(day, start_from=None):
        out = []
        for sh, eh in PUBLISH_TIME_WINDOWS:
            start = day.replace(hour=sh, minute=0, second=0, microsecond=0)
            end = day.replace(hour=eh, minute=0, second=0, microsecond=0)
            if start_from and end <= start_from:
                continue
            if start_from and start < start_from < end:
                start = start_from
            out.append((start, end))
        return out

    windows = windows_for(now, now) or windows_for(now + timedelta(days=1))
    if video_count == 1:
        return [windows[0][0]]
    total = sum((e - s).total_seconds() for s, e in windows)
    step = total / (video_count - 1)
    schedule = []
    for i in range(video_count):
        off = step * i
        for s, e in windows:
            span = (e - s).total_seconds()
            if off <= span:
                schedule.append(s + timedelta(seconds=off))
                break
            off -= span
    return schedule


def wait_until(publish_time):
    secs = (publish_time - datetime.now()).total_seconds()
    if secs > 0:
        print(f"\nWaiting until {publish_time:%Y-%m-%d %H:%M:%S} (~{int(secs)}s)...")
        time.sleep(secs)


# ------------------------------ base uploader ------------------------------

class BaseUploader:
    PLATFORM = "base"          # overridden by subclasses

    def __init__(self, account, config=None, auto_start=True):
        self.account = account
        self.config = config or {}
        self.account_id = account.get("id", "default")
        self.account_name = account.get("name", self.account_id)
        self.video_dir = video_save_dir(self.config)
        self.video_files = []
        self.driver = None
        # each account gets its own persistent Chrome profile (holds the login)
        profile = account.get("profile_dir", f"chrome_profile_{self.account_id}")
        self.user_data_dir = profile if os.path.isabs(profile) else os.path.join(BASE_DIR, profile)
        self.chrome_binary = account.get("chrome_binary_path")  # optional
        if auto_start:
            self.setup_driver()

    # ---- browser ----
    def setup_driver(self):
        print("\n" + "=" * 60)
        print(f"{self.PLATFORM} uploader  [{self.account_name}]")
        print("=" * 60)

        if not os.path.exists(self.user_data_dir):
            os.makedirs(self.user_data_dir)
            print(f"Created new Chrome profile: {os.path.basename(self.user_data_dir)}")
            print("  (first run: you'll need to log in once; it persists after)")
        else:
            print(f"Using Chrome profile: {os.path.basename(self.user_data_dir)}")

        opts = Options()
        if self.chrome_binary and os.path.exists(self.chrome_binary):
            opts.binary_location = self.chrome_binary
        opts.add_argument(f"--user-data-dir={self.user_data_dir}")
        opts.add_argument("--profile-directory=Default")
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_experimental_option("excludeSwitches", ["enable-automation"])
        opts.add_experimental_option("useAutomationExtension", False)
        opts.add_argument("--start-maximized")

        # Selenium 4.6+ finds/updates ChromeDriver automatically.
        self.driver = webdriver.Chrome(options=opts)
        self.driver.execute_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})")
        print("Chrome started.")

    def close(self):
        if self.driver:
            self.driver.quit()
            print(f"[{self.account_name}] browser closed.")

    # ---- generic helpers ----
    def click_css(self, css, desc, wait=10):
        try:
            el = WebDriverWait(self.driver, wait).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, css)))
            self.driver.execute_script(
                "arguments[0].scrollIntoView({block:'center'});", el)
            time.sleep(0.4)
            self.driver.execute_script("arguments[0].click();", el)
            print(f"  clicked: {desc}")
            return True
        except Exception:
            return False

    def click_text(self, texts, desc, wait=8):
        """Click the first clickable element whose visible text matches any of
        `texts` (case-insensitive). Robust to UI language/label changes."""
        if isinstance(texts, str):
            texts = [texts]
        conds = " or ".join(
            [f"contains(translate(normalize-space(.),"
             f"'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),"
             f"'{t.lower()}')" for t in texts])
        xpath = f"//*[self::button or self::div or self::span or self::a or self::tp-yt-paper-radio-button][{conds}]"
        try:
            el = WebDriverWait(self.driver, wait).until(
                EC.element_to_be_clickable((By.XPATH, xpath)))
            self.driver.execute_script(
                "arguments[0].scrollIntoView({block:'center'});", el)
            time.sleep(0.4)
            self.driver.execute_script("arguments[0].click();", el)
            print(f"  clicked (text): {desc}")
            return True
        except Exception:
            return False

    def send_file(self, path, css="input[type='file']", wait=20):
        """Send a file path to a (possibly hidden) file input."""
        el = WebDriverWait(self.driver, wait).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, css)))
        el.send_keys(path)
        return True

    # ---- metadata + scanning ----
    def load_metadata(self, video_path):
        txt = os.path.splitext(video_path)[0] + ".txt"
        default = {"title": os.path.splitext(os.path.basename(video_path))[0], "tags": []}
        if os.path.exists(txt):
            try:
                with open(txt, "r", encoding="utf-8") as f:
                    meta = json.load(f)
                return {"title": meta.get("title", default["title"]),
                        "tags": meta.get("tags", [])}
            except Exception as e:
                print(f"  metadata read failed ({e}); using defaults")
        return default

    def scan_videos(self):
        if not os.path.exists(self.video_dir):
            print(f"video dir not found: {self.video_dir}")
            return False
        self.video_files = sorted(glob.glob(os.path.join(self.video_dir, "*.mp4")))
        max_up = self.account.get("max_uploads_per_day")
        if max_up and len(self.video_files) > max_up:
            print(f"limiting to first {max_up} of {len(self.video_files)} videos")
            self.video_files = self.video_files[:max_up]
        print(f"{len(self.video_files)} video(s) to upload from {self.video_dir}")
        return bool(self.video_files)

    # ---- to be implemented by each platform ----
    def upload_one(self, video_path, meta):
        raise NotImplementedError

    # ---- driver of the whole run ----
    def run(self):
        try:
            if not self.scan_videos():
                return 0
            use_schedule = self.config.get("shared_settings", {}).get("use_schedule", False)
            schedule = build_publish_schedule(len(self.video_files)) if use_schedule else None
            if schedule:
                print("\nPublish schedule:")
                for i, t in enumerate(schedule, 1):
                    print(f"  {i}. {t:%Y-%m-%d %H:%M:%S}")

            ok = 0
            for i, vp in enumerate(self.video_files, 1):
                if schedule:
                    wait_until(schedule[i - 1])
                print(f"\n{'='*60}\n[{self.account_name}] {i}/{len(self.video_files)}: "
                      f"{os.path.basename(vp)}\n{'='*60}")
                meta = self.load_metadata(vp)
                try:
                    if self.upload_one(vp, meta):
                        ok += 1
                        print(f"  -> uploaded OK")
                    else:
                        print(f"  -> upload FAILED")
                except Exception as e:
                    print(f"  -> upload error: {e}")
            print(f"\n[{self.account_name}] done: {ok}/{len(self.video_files)}")
            return ok
        finally:
            self.close()


def run_all(uploader_cls):
    """Run the given uploader class for every enabled account."""
    config = load_accounts_config()
    accounts = get_enabled_accounts(config)
    if not accounts:
        print("No enabled accounts in accounts_config.json")
        return
    # allow: python upload_x.py <account_id>
    if len(sys.argv) > 1:
        accounts = [a for a in accounts if a.get("id") == sys.argv[1]]
        if not accounts:
            print(f"account not found: {sys.argv[1]}")
            return
    for i, acc in enumerate(accounts, 1):
        print(f"\n{'#'*60}\n# account {i}/{len(accounts)}: {acc.get('name')}\n{'#'*60}")
        try:
            uploader_cls(account=acc, config=config).run()
        except Exception as e:
            print(f"account {acc.get('name')} failed: {e}")
        if i < len(accounts):
            time.sleep(5)
