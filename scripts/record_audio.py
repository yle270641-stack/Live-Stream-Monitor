# -*- coding: utf-8 -*-
"""通用直播录音：输入流地址，用 ffmpeg 只录音频（丢弃画面），输出 16k 单声道 mp3。
用法：
  python record_audio.py --url "<流地址>" --out "../recordings/x.mp3" [--seconds 120] [--referer URL]
说明：
  --seconds 0 或缺省 = 一直录到流结束（主播下播/断流后 ffmpeg 自行退出）。
"""
import argparse
import json
import re
import sys
import threading
import time
import subprocess
from collections import deque
from pathlib import Path

from common import load_config, resolve_tool, run, log, UA, ROOT


def probe_duration(ffprobe, path):
    rc, out, err = run([ffprobe, "-v", "error", "-show_entries",
                        "format=duration", "-of",
                        "default=noprint_wrappers=1:nokey=1", str(path)])
    try:
        return round(float(out.strip()), 2)
    except Exception:
        return None


def main():
    # 统一 UTF-8 输出：watcher 以 UTF-8 解码子进程输出，默认 GBK 会让中文路径和 ffmpeg 报错乱码
    import io as _io
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = _io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
    if hasattr(sys.stderr, "buffer"):
        sys.stderr = _io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--seconds", type=int, default=0, help="0=录到流结束")
    ap.add_argument("--referer", default="")
    ap.add_argument("--stop-file", default="", help="存在时立即结束当前录音")
    args = ap.parse_args()

    cfg = load_config()
    rc_cfg = cfg.get("record", {})
    ffmpeg = resolve_tool(cfg, "ffmpeg")
    ffprobe = resolve_tool(cfg, "ffprobe")

    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = (ROOT / out_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        ffmpeg, "-y",
        "-rw_timeout", str(rc_cfg.get("rw_timeout_us", 20000000)),
        "-reconnect", "1", "-reconnect_streamed", "1",
        "-reconnect_delay_max", str(rc_cfg.get("reconnect_max", 5)),
        "-user_agent", UA,
    ]
    if args.referer:
        cmd += ["-headers", f"Referer: {args.referer}\r\n"]
    cmd += ["-i", args.url, "-vn"]
    if args.seconds and args.seconds > 0:
        cmd += ["-t", str(args.seconds)]
    cmd += [
        "-ac", str(rc_cfg.get("channels", 1)),
        "-ar", str(rc_cfg.get("sample_rate", 16000)),
        "-acodec", "libmp3lame",
        "-b:a", rc_cfg.get("bitrate", "64k"),
        str(out_path),
    ]

    log(f"开始录音 -> {out_path.name}（限时 {args.seconds or '直到结束'}s）")
    # 限时模式给足余量；录到结束模式不设 timeout，由断流自然退出
    timeout = args.seconds + 60 if args.seconds else None
    stop_file = Path(args.stop_file) if args.stop_file else None
    if stop_file and stop_file.exists():
        stop_file.unlink(missing_ok=True)
    if stop_file:
        Path(str(stop_file) + ".done").unlink(missing_ok=True)
    # stdout 丢弃（ffmpeg 日志全在 stderr）；stderr 必须由后台线程持续读空，
    # 否则 Windows 管道缓冲区（约4KB）被 ffmpeg 的进度日志写满后 ffmpeg 会阻塞、
    # 停止写入音频文件，表现为文件一直 0 字节、误判卡住（subprocess 管道死锁）。
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", errors="replace")
    err_lines = deque(maxlen=200)  # 保留最后 200 行 ffmpeg 日志用于诊断
    # ffmpeg 内部处理进度（秒）及该时间戳"数值真正增长"的最近墙钟时间。mp3 分块落盘
    # （约每 30-35 秒写一批）会让文件大小出现正常平台期，故必须结合 time= 是否推进判断真卡；
    # 注意要比较 time 数值是否变大，而不是有没有新日志行（断流重试时可能反复输出相同 time）。
    progress = {"fftime": -1.0, "advance_wall": 0.0}
    _PROG_RE = re.compile(r"time=(\d+):(\d{2}):(\d{2}(?:\.\d+)?)")

    def _drain_stderr():
        try:
            for line in proc.stderr:
                line = line.rstrip("\r\n")
                err_lines.append(line)
                m = _PROG_RE.search(line)  # 进度行形如 ... time=00:01:23.45 ...
                if m:
                    hh, mm, ss = m.groups()
                    cur = int(hh) * 3600 + int(mm) * 60 + float(ss)
                    if cur > progress["fftime"] + 1e-6:  # 只有转码时间真正往前走才算活着
                        progress["fftime"] = cur
                        progress["advance_wall"] = time.time()
        except (ValueError, OSError):
            pass

    drainer = threading.Thread(target=_drain_stderr, daemon=True)
    drainer.start()
    started = time.time()
    last_growth_time = started
    last_size = 0
    STALL_GRACE_SECONDS = 60   # 启动后前 60 秒不检查（ffmpeg 连接/缓冲期）
    STALL_TIMEOUT_SECONDS = 45  # 文件大小与 ffmpeg 内部时间双双停滞超过该秒数才判定卡住
    while True:
        if proc.poll() is not None:
            break
        if stop_file and stop_file.exists():
            log("收到即时总结请求，结束当前录音片段")
            Path(str(stop_file) + ".done").touch()
            stop_file.unlink(missing_ok=True)
            proc.terminate()
            break
        if timeout and time.time() - started > timeout:
            proc.terminate()
            break
        # 卡住检测：主播下播/断流时 ffmpeg 会挂起。需同时满足"文件不增长"且"ffmpeg 内部
        # time= 也停滞"才算真卡，避免在 mp3 分块落盘的正常平台期误杀正在录音的进程。
        elapsed = time.time() - started
        if elapsed > STALL_GRACE_SECONDS:
            now = time.time()
            current_size = out_path.stat().st_size if out_path.exists() else 0
            if current_size > last_size:
                last_size = current_size
                last_growth_time = now
            file_stalled = now - last_growth_time > STALL_TIMEOUT_SECONDS
            fftime_stalled = (progress["fftime"] < 0 or
                              now - progress["advance_wall"] > STALL_TIMEOUT_SECONDS)
            if file_stalled and fftime_stalled:
                log(f"录音卡住：{STALL_TIMEOUT_SECONDS}秒内文件与转码进度均无增长"
                    f"（当前 {current_size} 字节，ffmpeg时间 {progress['fftime']:.0f}s），结束录音")
                proc.terminate()
                break
        time.sleep(0.5)
    # 等待进程退出并让 drain 线程读完残余日志（不再用 communicate，stderr 已由线程接管）
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass
    drainer.join(timeout=5)
    rc = proc.returncode

    exists = out_path.exists()
    size = out_path.stat().st_size if exists else 0
    duration = probe_duration(ffprobe, out_path) if exists else None
    # ffmpeg 因断流/卡住终止等原因提前退出时，只要已录部分有有效音频数据就算成功，避免丢弃
    has_valid_audio = exists and size >= 1024 and (duration or 0) > 0
    result = {
        "ok": has_valid_audio,
        "partial": has_valid_audio and rc != 0,
        "out": str(out_path),
        "bytes": size,
        "duration_s": duration,
        "ffmpeg_rc": rc,
        "tail": list(err_lines)[-3:],
    }
    if not result["ok"] and exists:
        try:
            out_path.unlink()
        except OSError:
            pass
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result["ok"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
