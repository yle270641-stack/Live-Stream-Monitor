# -*- coding: utf-8 -*-
"""Open a persistent Douyin browser profile for QR-code login.

The profile remains local under browser_profile/douyin. This program never
prints, exports, or sends cookies anywhere.
"""
import sys
from pathlib import Path

from common import ROOT, ensure_dirs


def launch_kwargs(profile):
    kwargs = {"headless": False, "viewport": {"width": 1440, "height": 960}, "locale": "zh-CN"}
    edge = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
    chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    browser = edge if edge.exists() else chrome if chrome.exists() else None
    if browser:
        kwargs["executable_path"] = str(browser)
    return kwargs


def main():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("未安装 Playwright。请先双击 安装依赖.bat", file=sys.stderr)
        raise SystemExit(2)

    ensure_dirs()
    profile = ROOT / "browser_profile" / "douyin"
    profile.mkdir(parents=True, exist_ok=True)
    print("已打开抖音登录窗口。请用抖音 App 扫码登录；确认头像出现后关闭此窗口即可。")
    with sync_playwright() as p:
        try:
            context = p.chromium.launch_persistent_context(
                str(profile), **launch_kwargs(profile)
            )
        except Exception as e:
            print("浏览器组件未安装。请先双击 安装依赖.bat。\n" + str(e), file=sys.stderr)
            raise SystemExit(2)
        page = context.pages[0] if context.pages else context.new_page()
        page.goto("https://live.douyin.com/", wait_until="domcontentloaded", timeout=60000)
        print("登录完成后可直接关闭浏览器窗口；登录态会保留在本机。")
        try:
            page.wait_for_event("close", timeout=0)
        finally:
            context.close()


if __name__ == "__main__":
    main()
