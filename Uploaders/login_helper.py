"""
One-time login helper.

Opens a Chrome window using an account's PERSISTENT profile, on YouTube Studio
or TikTok, so you can log in by hand. After you log in, the cookies are saved
in that profile and the uploaders reuse them — you won't need to log in again.

Usage:
    python login_helper.py youtube               # first enabled account
    python login_helper.py tiktok
    python login_helper.py youtube account_2     # a specific account id

Log in in the window, then press Enter in this terminal to close it.
"""

import sys
from uploader_common import BaseUploader, load_accounts_config, get_enabled_accounts

URLS = {
    "youtube": "https://studio.youtube.com",
    "tiktok": "https://www.tiktok.com/login",
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in URLS:
        print("Usage: python login_helper.py <youtube|tiktok> [account_id]")
        return
    platform = sys.argv[1]
    config = load_accounts_config()
    accounts = get_enabled_accounts(config)
    if len(sys.argv) > 2:
        accounts = [a for a in accounts if a.get("id") == sys.argv[2]]
    if not accounts:
        print("No matching account in accounts_config.json")
        return
    acc = accounts[0]

    up = BaseUploader(account=acc, config=config, auto_start=True)
    up.driver.get(URLS[platform])
    print(f"\nA Chrome window opened at {platform}. Log in to the account, then")
    input("come back here and press Enter to save the session and close...")
    up.close()
    print("Login saved to the profile. The uploader will reuse it.")


if __name__ == "__main__":
    main()
