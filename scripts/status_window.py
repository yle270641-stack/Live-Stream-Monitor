# -*- coding: utf-8 -*-
"""Small always-on-top local status window for the live watcher."""
import json
import tkinter as tk
import ctypes
import time
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "logs" / "state.json"
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateMutexW.restype = wintypes.HANDLE
_kernel32.GetLastError.restype = ctypes.c_ulong
MUTEX = _kernel32.CreateMutexW(None, False, "Global\\FinanceLiveStatusWindow")
if _kernel32.GetLastError() == 183:
    raise SystemExit(0)

def read_state():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {"date": "", "anchors": {}}

def read_anchor_names():
    try:
        cfg = json.loads((ROOT / "config" / "anchors.json").read_text(encoding="utf-8"))
        return {a["id"]: a.get("name", a["id"]) for a in cfg.get("anchors", [])}
    except Exception:
        return {}

ANCHOR_NAMES = read_anchor_names()
STATUS_CN = {
    "checking": "检测中", "recording": "录音中", "recorded": "已录待转写",
    "queued": "排队中", "transcribing": "转写中", "summarizing": "摘要中",
    "pushing": "推送中", "done": "完成", "failed": "失败",
    "not_live": "未开播", "outside_window": "监控窗口外", "starting": "启动中",
    "summary_sent": "已补发摘要",
}

HEARTBEAT = ROOT / "logs" / "watcher_heartbeat.json"
DAILY_STATE = ROOT / "logs" / "daily_summary_state.json"
RETRY_STATE = ROOT / "logs" / "pending_retry.json"

DAILY_STATUS_CN = {
    "pending": "待生成", "generating": "生成中", "generated": "已生成待发送",
    "sent": "已发送", "no_content": "无内容", "retrying": "失败待重试",
}

def read_daily_state():
    try:
        return json.loads(DAILY_STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}

def pending_audio_rows():
    """Return valid recordings waiting for (or backing off from) processing."""
    rows = []
    try:
        retry = json.loads(RETRY_STATE.read_text(encoding="utf-8")) if RETRY_STATE.exists() else {}
        for p in (ROOT / "recordings").glob("*.mp3"):
            if p.stat().st_size < 1024:
                continue
            # 成功推送后 watcher 会清理录音；兼容清理关闭时留下的已完成文件，
            # 不把它们误报成“待补处理”。
            completed = False
            for anchor_dir in (ROOT / "transcripts").iterdir() if (ROOT / "transcripts").exists() else []:
                out_dir = anchor_dir / p.stem
                if ((out_dir / (p.stem + ".summary.txt")).exists()
                        and (out_dir / (p.stem + ".pushed")).exists()):
                    completed = True
                    break
            if completed:
                continue
            item = retry.get(p.name, {})
            if item.get("next_retry", 0) > time.time():
                state = f"重试倒计时 {int(item['next_retry'] - time.time())}秒"
            else:
                state = "待处理"
            rows.append(f"{p.name}（{state}）")
    except Exception:
        return []
    return sorted(rows)

def watcher_health():
    try:
        item = json.loads(HEARTBEAT.read_text(encoding="utf-8"))
        stamp = datetime.fromisoformat(item["updated_at"])
        age = (datetime.now() - stamp).total_seconds()
        if item.get("status") == "stopped":
            return False, "已停止"
        if age > 120:
            return False, f"心跳已中断 {int(age)} 秒"
        return True, "运行中"
    except Exception:
        return False, "尚未启动或无心跳"

def refresh():
    state = read_state(); running, health_text = watcher_health()
    daily = read_daily_state()
    header.config(text=("● 监控运行中" if running else "○ 监控异常/未运行"),
                  fg=("#16803c" if running else "#c62828"))
    lines = [f"检查时间：{datetime.now():%Y-%m-%d %H:%M:%S}", f"进程心跳：{health_text}", ""]
    today = datetime.now().strftime("%Y-%m-%d")
    daily_rows = daily.get("days", {}).get(today, {})
    if daily_rows:
        summary = "；".join(
            f"{ANCHOR_NAMES.get(aid, aid)}：{DAILY_STATUS_CN.get(item.get('status'), item.get('status', '待生成'))}"
            for aid, item in daily_rows.items())
        lines.extend([f"今晚复盘（21:00）：{summary}",
                      f"最近每日复盘：{daily.get('last_run', '尚未运行')}", ""])
    else:
        lines.extend(["今晚复盘（21:00）：待生成", "最近每日复盘：尚未运行", ""])
    pending = pending_audio_rows()
    if pending:
        lines.extend([f"待补处理录音：{len(pending)} 个", *pending[:4], ""])
    for aid, item in state.get("anchors", {}).items():
        name = ANCHOR_NAMES.get(aid, aid)
        status_cn = STATUS_CN.get(item.get("status", "starting"), item.get("status", "starting"))
        line = f"{name}：{status_cn}｜已推送 {item.get('segments', 0)} 段"
        ts = item.get("transcript_status")
        if ts and ts != "done":
            line += f"｜当前：{STATUS_CN.get(ts, ts)}"
        if item.get("last_summary"):
            line += f"\n  最近摘要：{Path(item['last_summary']).name}"
        if item.get("last_error"): line += f"\n  错误：{item['last_error'][:120]}"
        lines.extend([line, ""])
    body.config(text="\n".join(lines))
    root.after(2000, refresh)

root = tk.Tk(); root.title("直播监控状态"); root.geometry("520x360"); root.minsize(420, 260)
root.attributes("-topmost", True)
header = tk.Label(root, text="检查中...", font=("Microsoft YaHei UI", 18, "bold"), anchor="w")
header.pack(fill="x", padx=16, pady=(14, 4))
body = tk.Label(root, text="", justify="left", anchor="nw", font=("Microsoft YaHei UI", 10), wraplength=480)
body.pack(fill="both", expand=True, padx=16, pady=8)
refresh(); root.mainloop()
