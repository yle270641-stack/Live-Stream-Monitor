# -*- coding: utf-8 -*-
"""飞书自定义群机器人推送。
用法:
  python feishu_push.py --title "标题" --body "正文"
  python feishu_push.py --title "标题" --body-file notes.txt
未配置 webhook 时不报错，把待发消息落盘到 logs/pending_push_*.txt（避免静默丢失）。
"""
import argparse
import json
import urllib.request
from datetime import datetime
from pathlib import Path

from common import load_config, ROOT, ensure_dirs, log


def post_text(webhook, text):
    body = json.dumps({"msg_type": "text", "content": {"text": text}}).encode("utf-8")
    req = urllib.request.Request(
        webhook, data=body, headers={"Content-Type": "application/json; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", default="")
    ap.add_argument("--body", default="")
    ap.add_argument("--body-file", default="")
    ap.add_argument("--webhook", default="")
    args = ap.parse_args()

    cfg = load_config()
    dirs = ensure_dirs()

    if args.body_file:
        p = Path(args.body_file)
        body = (p if p.is_absolute() else ROOT / p).read_text(encoding="utf-8")
    else:
        body = args.body
    text = (args.title + "\n\n" if args.title else "") + body

    webhook = args.webhook or cfg.get("feishu_webhook", "")
    if not webhook:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        f = dirs["logs"] / f"pending_push_{ts}.txt"
        f.write_text(text, encoding="utf-8")
        print(json.dumps({"ok": None, "reason": "no_webhook_configured", "saved": str(f)},
                         ensure_ascii=False, indent=2))
        # A saved pending message is not a successful delivery.  Returning 0
        # made watcher/process_pending mark the audio as sent and delete it.
        raise SystemExit(3)

    try:
        resp = post_text(webhook, text)
    except Exception as e:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        f = dirs["logs"] / f"failed_push_{ts}.txt"
        f.write_text(text, encoding="utf-8")
        print(json.dumps({"ok": False, "reason": "post_error: " + str(e), "saved": str(f)},
                         ensure_ascii=False, indent=2))
        raise SystemExit(2)

    code = resp.get("code", resp.get("StatusCode"))
    ok = (code == 0)
    print(json.dumps({"ok": ok, "resp": resp}, ensure_ascii=False, indent=2))
    if not ok:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
