"""
YouTube Shorts uploader (Selenium, drives YouTube Studio).

Same structure as the Douyin script: persistent Chrome login profile per
account, per-video .txt metadata ({"title","tags"}), optional scheduling.

A video is treated as a Short automatically when it is vertical 9:16, <= 60s,
and tagged #Shorts — so this appends #Shorts to the description.

First-time login:  run  login.bat  (or: python login_helper.py youtube),
log into your channel in the window that opens, then close it. The cookies are
saved in the account's Chrome profile and reused here.

IMPORTANT: YouTube Studio's DOM uses custom <ytcp-*> elements and changes
periodically. The selectors below are best-effort with text fallbacks; if a
step can't be found, adjust the CSS in the SEL dict at the top.
"""

import time
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from uploader_common import BaseUploader, run_all

STUDIO_URL = "https://studio.youtube.com"

# --- selectors (adjust here if YouTube Studio changes) ---
SEL = {
    "file_input": "input[type='file']",
    "title_box": "#title-textarea #textbox, ytcp-social-suggestions-textbox[label='Add a title that describes your video (type @ to mention a channel)'] #textbox",
    "desc_box": "#description-textarea #textbox",
    "not_for_kids": "tp-yt-paper-radio-button[name='VIDEO_MADE_FOR_KIDS_NOT_MFK']",
    "next_button": "#next-button",
    "public_radio": "tp-yt-paper-radio-button[name='PUBLIC']",
    "done_button": "#done-button",
    "thumb_input": "#file-loader",   # custom thumbnail (needs verified channel)
}


class YouTubeUploader(BaseUploader):
    PLATFORM = "YouTube Shorts"

    def _logged_in(self):
        url = self.driver.current_url.lower()
        return "studio.youtube.com" in url and "accounts.google" not in url

    def upload_one(self, video_path, meta):
        d = self.driver
        d.get(STUDIO_URL)
        time.sleep(5)
        if not self._logged_in():
            print("  NOT LOGGED IN. Run login.bat for this account first.")
            return False

        # open the upload dialog
        if not (self.click_css("#create-icon", "Create") or
                self.click_css("ytcp-button#create-icon", "Create")):
            print("  couldn't find the Create button")
            return False
        time.sleep(1)
        self.click_css("#text-item-0", "Upload videos") or \
            self.click_text(["upload videos", "upload video"], "Upload videos")
        time.sleep(2)

        # send the file
        try:
            self.send_file(video_path, SEL["file_input"])
            print("  video file submitted; encoding/uploading...")
        except Exception as e:
            print(f"  file input not found: {e}")
            return False
        time.sleep(8)

        # title (Studio prefills the filename; replace it)
        title = meta["title"]
        try:
            box = WebDriverWait(d, 30).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, SEL["title_box"])))
            box.click(); time.sleep(0.3)
            box.send_keys(Keys.CONTROL, "a"); box.send_keys(Keys.DELETE)
            box.send_keys(title)
            print(f"  title set: {title}")
        except Exception as e:
            print(f"  title box not found: {e}")

        # description = title + #tags + #Shorts
        tagtext = " ".join(f"#{t}" for t in meta.get("tags", []))
        desc = f"{title} {tagtext} #Shorts".strip()
        try:
            dbox = d.find_element(By.CSS_SELECTOR, SEL["desc_box"])
            dbox.click(); time.sleep(0.3)
            dbox.send_keys(desc)
            print("  description set")
        except Exception:
            print("  (description box not found; skipping — #Shorts helps ranking)")

        # optional custom thumbnail: same-name .jpg/.png (needs verified channel)
        import os
        for ext in (".jpg", ".png"):
            thumb = os.path.splitext(video_path)[0] + ext
            if os.path.exists(thumb):
                try:
                    d.find_element(By.CSS_SELECTOR, SEL["thumb_input"]).send_keys(thumb)
                    print(f"  thumbnail set: {os.path.basename(thumb)}")
                except Exception:
                    print("  (thumbnail upload not available; skipping)")
                break

        # "not made for kids" (required)
        self.click_css(SEL["not_for_kids"], "Not made for kids") or \
            self.click_text(["no, it's not made for kids", "not made for kids"], "Not for kids")
        time.sleep(1)

        # Next x3: Details -> Video elements -> Checks -> Visibility
        for step in range(3):
            if not (self.click_css(SEL["next_button"], f"Next ({step+1})") or
                    self.click_text(["next"], f"Next ({step+1})")):
                print(f"  couldn't find Next button on step {step+1}")
            time.sleep(2)

        # visibility = Public
        self.click_css(SEL["public_radio"], "Public") or \
            self.click_text(["public"], "Public")
        time.sleep(1)

        # publish
        if not (self.click_css(SEL["done_button"], "Publish") or
                self.click_text(["publish", "done"], "Publish")):
            print("  couldn't find Publish button")
            return False
        time.sleep(6)
        return True


if __name__ == "__main__":
    run_all(YouTubeUploader)
