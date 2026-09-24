"""
TikTok uploader (Selenium, drives the TikTok web upload page).

Same structure as the Douyin script: persistent Chrome login profile per
account, per-video .txt metadata ({"title","tags"}), optional scheduling.

First-time login:  run  login.bat  (or: python login_helper.py tiktok),
log into TikTok in the window that opens, then close it. Cookies persist in the
account's Chrome profile.

IMPORTANT: TikTok's upload page changes often and uses a contenteditable caption
box (not a normal <textarea>). It also has aggressive bot detection — keep the
window visible, don't run headless, and don't post too fast. Selectors are
best-effort with fallbacks; adjust the SEL dict if a step isn't found.
"""

import time
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from uploader_common import BaseUploader, run_all

# current upload page (redirects into TikTok Studio)
UPLOAD_URL = "https://www.tiktok.com/tiktokstudio/upload"
UPLOAD_URL_FALLBACK = "https://www.tiktok.com/upload"

SEL = {
    "file_input": "input[type='file']",
    # caption is a Draft.js contenteditable, not a textarea
    "caption": "div[contenteditable='true'], div.public-DraftEditor-content",
    "post_button": "button[data-e2e='post_video_button']",
}


class TikTokUploader(BaseUploader):
    PLATFORM = "TikTok"

    def _logged_in(self):
        url = self.driver.current_url.lower()
        return "login" not in url and "tiktok.com" in url

    def upload_one(self, video_path, meta):
        d = self.driver
        d.get(UPLOAD_URL)
        time.sleep(6)
        if "upload" not in d.current_url.lower():
            d.get(UPLOAD_URL_FALLBACK)
            time.sleep(6)
        if not self._logged_in():
            print("  NOT LOGGED IN. Run login.bat for this account first.")
            return False

        # some TikTok versions put the upload form in an iframe
        in_iframe = False
        try:
            iframe = d.find_elements(By.CSS_SELECTOR, "iframe")
            for fr in iframe:
                try:
                    d.switch_to.frame(fr)
                    if d.find_elements(By.CSS_SELECTOR, SEL["file_input"]):
                        in_iframe = True
                        break
                    d.switch_to.default_content()
                except Exception:
                    d.switch_to.default_content()
        except Exception:
            d.switch_to.default_content()

        # send the file
        try:
            self.send_file(video_path, SEL["file_input"], wait=25)
            print("  video file submitted; uploading...")
        except Exception as e:
            print(f"  file input not found: {e}")
            if in_iframe:
                d.switch_to.default_content()
            return False

        # wait for TikTok to process the upload and reveal the caption box
        time.sleep(15)

        # caption = title + #tags
        caption = (meta["title"] + " " +
                   " ".join(f"#{t}" for t in meta.get("tags", []))).strip()
        try:
            box = WebDriverWait(d, 30).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, SEL["caption"])))
            box.click(); time.sleep(0.5)
            # clear any auto-filled filename, then type
            box.send_keys(Keys.CONTROL, "a"); box.send_keys(Keys.DELETE)
            box.send_keys(caption)
            print(f"  caption set: {caption}")
        except Exception as e:
            print(f"  caption box not found: {e}")

        # wait for the upload to finish so Post enables
        time.sleep(10)

        # post
        posted = self.click_css(SEL["post_button"], "Post") or \
            self.click_text(["post"], "Post")
        if in_iframe:
            d.switch_to.default_content()
        if not posted:
            print("  couldn't find the Post button (upload may still be processing)")
            return False
        time.sleep(8)
        return True


if __name__ == "__main__":
    run_all(TikTokUploader)
