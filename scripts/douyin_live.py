# -*- coding: utf-8 -*-
"""Douyin live detection and signed-FLV capture via a local Playwright profile.

It deliberately uses the browser's real player request rather than handling
cookies itself. The player-generated URL is short-lived and is only returned
to the caller for immediate recording.
"""
import argparse
import json
import re
import sys
from contextlib import contextmanager
from pathlib import Path

from common import ROOT, get_anchor, load_config, out_json


LIVE_RE = re.compile(r"https?://live\.douyin\.com/(\d+)")
LOCK_PATH = ROOT / "logs" / "douyin_browser.lock"


@contextmanager
def browser_lock(timeout=90):
    """Serialize access to the shared persistent browser profile."""
    import time
    import msvcrt
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    handle = open(LOCK_PATH, "a+b")
    handle.seek(0)
    handle.write(b"0")
    handle.flush()
    deadline = time.time() + timeout
    acquired = False
    while time.time() < deadline:
        try:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            acquired = True
            break
        except OSError:
            time.sleep(0.5)
    if not acquired:
        handle.close()
        raise RuntimeError("抖音浏览器正在被另一个任务使用，请稍后重试")
    try:
        yield
    finally:
        try:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            handle.close()


def launch_kwargs():
    kwargs = {"headless": True, "viewport": {"width": 1440, "height": 960}, "locale": "zh-CN"}
    edge = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
    chrome = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    browser = edge if edge.exists() else chrome if chrome.exists() else None
    if browser:
        kwargs["executable_path"] = str(browser)
    return kwargs


def browser_context(playwright):
    profile = ROOT / "browser_profile" / "douyin"
    if not profile.exists():
        raise RuntimeError("未找到抖音登录态。请先双击 登录抖音.bat 扫码登录。")
    return playwright.chromium.launch_persistent_context(
        str(profile), **launch_kwargs())


def find_live_url(page, anchor):
    page.goto("https://www.douyin.com/user/" + anchor["sec_uid"],
              wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(5000)
    links = page.locator("a").evaluate_all("els => els.map(x => x.href).filter(Boolean)")
    for href in links:
        m = LIVE_RE.search(href)
        if m:
            return "https://live.douyin.com/" + m.group(1)
    return ""


def status(anchor):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError("未安装 Playwright。请先双击 安装依赖.bat")
    with browser_lock(), sync_playwright() as p:
        context = None
        try:
            context = browser_context(p)
            page = context.pages[0] if context.pages else context.new_page()
            live_url = find_live_url(page, anchor)
            return {"id": anchor["id"], "name": anchor["name"],
                    "is_live": bool(live_url), "live_url": live_url}
        finally:
            if context is not None:
                try:
                    context.close()
                except Exception:
                    pass


def stream(anchor):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError("未安装 Playwright。请先双击 安装依赖.bat")
    with browser_lock(), sync_playwright() as p:
        context = None
        try:
            context = browser_context(p)
            page = context.pages[0] if context.pages else context.new_page()
            live_url = find_live_url(page, anchor)
            if not live_url:
                return {"id": anchor["id"], "is_live": False, "chosen": None}
            urls = []
            def on_request(request):
                url = request.url
                if "douyincdn.com" in url and ".flv" in url.lower():
                    urls.append(url)
            page.on("request", on_request)
            page.goto(live_url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(12000)
            chosen = next(iter(dict.fromkeys(urls)), None)
            if not chosen:
                # A reload triggers a fresh player request on pages that delayed loading.
                page.reload(wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(12000)
                chosen = next(iter(dict.fromkeys(urls)), None)
            return {"id": anchor["id"], "is_live": True, "live_url": live_url,
                    "chosen": {"url": chosen} if chosen else None}
        finally:
            if context is not None:
                try:
                    context.close()
                except Exception:
                    pass


def main():
    import io as _io
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = _io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="backslashreplace", line_buffering=True)
    if hasattr(sys.stderr, "buffer"):
        sys.stderr = _io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="backslashreplace", line_buffering=True)
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["status", "stream"])
    ap.add_argument("--anchor", required=True)
    args = ap.parse_args()
    anchor = get_anchor(load_config(), args.anchor)
    if anchor.get("platform") != "douyin":
        raise SystemExit("该主播不是抖音主播")
    try:
        result = status(anchor) if args.cmd == "status" else stream(anchor)
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        raise SystemExit(2)
    out_json(result)


if __name__ == "__main__":
    main()
