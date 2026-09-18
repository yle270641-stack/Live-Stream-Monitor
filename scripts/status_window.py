# -*- coding: utf-8 -*-
"""Local status window for the live watcher."""
import ctypes
import json
import tkinter as tk
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "logs" / "state.json"
HEARTBEAT = ROOT / "logs" / "watcher_heartbeat.json"
DAILY_STATE = ROOT / "logs" / "daily_summary_state.json"

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.CreateMutexW.restype = wintypes.HANDLE
kernel32.GetLastError.restype = ctypes.c_ulong
mutex = kernel32.CreateMutexW(None, False, "Global\\FinanceLiveStatusWindow")
if kernel32.GetLastError() == 183:
    raise SystemExit(0)


def read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def anchor_names():
    return {a["id"]: a.get("name", a["id"])
            for a in read_json(ROOT / "config" / "anchors.json", {}).get("anchors", [])}


def watcher_health():
    item = read_json(HEARTBEAT, {})
    try:
        age = (datetime.now() - datetime.fromisoformat(item["updated_at"])).total_seconds()
    except Exception:
        return False, "尚未启动或无心跳"
    if item.get("status") == "stopped":
        return False, "已停止"
    if age > 120:
        return False, f"心跳已中断 {int(age)} 秒"
    return True, "运行中"


def refresh():
    names = anchor_names()
    state = read_json(STATE, {"anchors": {}})
    daily = read_json(DAILY_STATE, {})
    running, health = watcher_health()
    header.config(text=("● 监控运行中" if running else "● 监控异常/未运行"),
                  fg=("#16803c" if running else "#c62828"))
    lines = [f"检查时间：{datetime.now():%Y-%m-%d %H:%M:%S}", f"进程心跳：{health}", ""]
    today = datetime.now().strftime("%Y-%m-%d")
    daily_rows = daily.get("days", {}).get(today, {})
    if daily_rows:
        summary = "；".join(f"{names.get(aid, aid)}：{item.get('status', '待生成')}"
                            for aid, item in daily_rows.items() if not names or aid in names)
        lines.extend([f"今晚复盘（21:00）：{summary or '暂无当前主播记录'}",
                      f"最近日复盘：{daily.get('last_run', '尚未运行')}", ""])
    else:
        lines.extend(["今晚复盘（21:00）：待生成", "最近日复盘：尚未运行", ""])
    current = state.get("anchors", {})
    if not names:
        lines.extend(["当前没有配置主播。请在工具栏中添加 UID。", ""])
    else:
        for aid, item in current.items():
            if aid not in names:
                continue
            line = f"{names[aid]}：{item.get('status', '启动中')}｜已推送 {item.get('segments', 0)} 段"
            if item.get("last_summary"):
                line += f"\n  最近摘要：{Path(item['last_summary']).name}"
            if item.get("last_error"):
                line += f"\n  错误：{item['last_error'][:120]}"
            lines.extend([line, ""])
    body.config(state="normal")
    body.delete("1.0", "end")
    body.insert("1.0", "\n".join(lines))
    body.config(state="disabled")
    root.after(2000, refresh)


root = tk.Tk()
root.title("直播监控状态")
root.geometry("720x520")
root.minsize(520, 320)
root.attributes("-topmost", True)
header = tk.Label(root, text="检查中...", font=("Microsoft YaHei UI", 18, "bold"), anchor="w")
header.pack(fill="x", padx=16, pady=(14, 4))
frame = tk.Frame(root)
frame.pack(fill="both", expand=True, padx=16, pady=8)
scrollbar = tk.Scrollbar(frame)
scrollbar.pack(side="right", fill="y")
body = tk.Text(frame, wrap="word", font=("Microsoft YaHei UI", 10),
               state="disabled", yscrollcommand=scrollbar.set, relief="flat", borderwidth=0)
body.pack(side="left", fill="both", expand=True)
scrollbar.config(command=body.yview)
refresh()
root.mainloop()
