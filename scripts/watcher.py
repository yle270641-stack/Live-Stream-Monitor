# -*- coding: utf-8 -*-
"""Multi-anchor live watcher with 30-minute segment summaries and heartbeats."""
import argparse
import json
import os
import queue
import subprocess
import sys
import threading
import time
import ctypes
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

from common import ROOT, load_config, ensure_dirs, log, extract_json, cleanup_source_files
from daily_summary import scheduler as daily_summary_scheduler

STATE_PATH = ROOT / "logs" / "state.json"
HEARTBEAT_PATH = ROOT / "logs" / "watcher_heartbeat.json"
INSTANCE_LOCK_PATH = ROOT / "logs" / "watcher.lock"
INSTANCE_MUTEX_NAME = "Global\\FinanceLiveWatcher_直播监控"
_INSTANCE_FILE_HANDLE = None

# 录音线把已录好的音频放入此队列，转写线在后台消费（转写→摘要→推送）。
# 这样录音永远不中断，转写与录音并行。
TRANSCRIPT_QUEUE = queue.Queue()

# 每日旧文件清理的日期标记，避免重复清理
_last_cleanup_date = ""

# 失败段的持久化重试队列（键 = mp3 文件名，与 process_pending.py 共用同一文件）。
# 失败信息落盘后，即使 watcher 重启或某段成功，也不会丢失其他仍在退避中的失败段。
RETRY_STATE = ROOT / "logs" / "pending_retry.json"
# 保护重试队列文件读改写：transcript_worker 线程与 Timer 回调线程可能同时操作
LOCK_FOR_RETRY = threading.RLock()


def load_retry_state():
    try:
        data = json.loads(RETRY_STATE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_retry_state(data):
    try:
        RETRY_STATE.parent.mkdir(parents=True, exist_ok=True)
        tmp = RETRY_STATE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(RETRY_STATE)
    except Exception as exc:
        log(f"重试状态写入失败（不影响本次处理）：{exc}")


def pop_retry(audio_name):
    """从持久化重试队列移除某段（成功、已入队重试时调用），返回是否移除成功。"""
    with LOCK_FOR_RETRY:
        data = load_retry_state()
        if audio_name not in data:
            return False
        data.pop(audio_name, None)
        save_retry_state(data)
        return True


def wait_for_transcripts(stop, timeout=300):
    """Wait for queued and currently-processing jobs, not just queue emptiness."""
    deadline = time.time() + timeout
    while TRANSCRIPT_QUEUE.unfinished_tasks and time.time() < deadline:
        time.sleep(2)
    if TRANSCRIPT_QUEUE.unfinished_tasks:
        log(f"转写队列等待超时，仍有 {TRANSCRIPT_QUEUE.unfinished_tasks} 个任务未完成")


def acquire_instance_lock():
    """Acquire both a named mutex and an OS file lock for robust single-instance behavior."""
    global _INSTANCE_FILE_HANDLE
    if sys.platform != "win32":
        return None
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CreateMutexW.argtypes = (wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR)
    kernel32.GetLastError.restype = wintypes.DWORD
    handle = kernel32.CreateMutexW(None, False, INSTANCE_MUTEX_NAME)
    if not handle:
        raise RuntimeError("无法创建 watcher 单实例锁")
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        kernel32.CloseHandle(handle)
        raise RuntimeError("已有一个 watcher 正在运行，请勿重复启动")
    # The file lock also covers launchers/processes that end up in different
    # Windows sessions where a Global mutex may not be shared as expected.
    import msvcrt
    INSTANCE_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    fh = open(INSTANCE_LOCK_PATH, "a+b")
    fh.seek(0)
    fh.write(b"1")
    fh.flush()
    try:
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        fh.close()
        kernel32.CloseHandle(handle)
        raise RuntimeError("已有一个 watcher 正在运行，请勿重复启动")
    _INSTANCE_FILE_HANDLE = fh
    return handle


def release_instance_lock(handle):
    global _INSTANCE_FILE_HANDLE
    if _INSTANCE_FILE_HANDLE is not None:
        import msvcrt
        try:
            _INSTANCE_FILE_HANDLE.seek(0)
            msvcrt.locking(_INSTANCE_FILE_HANDLE.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        _INSTANCE_FILE_HANDLE.close()
        _INSTANCE_FILE_HANDLE = None
    if handle:
        ctypes.windll.kernel32.CloseHandle(handle)


def load_state():
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"date": "", "anchors": {}}


def today_state():
    state = load_state()
    today = datetime.now().strftime("%Y-%m-%d")
    return state if state.get("date") == today else {"date": today, "anchors": {}}


def _atomic_replace(src, dst, attempts=12):
    """Windows 上把临时文件替换成正式文件。

    目标文件可能正被状态浮窗（每 2 秒读一次 state.json）、杀毒软件或 Windows
    搜索索引短暂打开，此时 os.replace 会抛 PermissionError（WinError 5 拒绝访问 /
    WinError 32 占用）。读取方的占用窗口通常只有几毫秒，短暂重试即可成功；只有连续
    失败到最后一次才把异常向上抛，避免偶发占用被误判成"监控循环未预期异常"。
    """
    for i in range(attempts):
        try:
            src.replace(dst)
            return
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(0.03 * (i + 1))


def save_state(state, lock):
    with lock:
        # 原子写：先写临时文件再替换，避免写入瞬间进程被杀导致 state.json 损坏
        tmp = STATE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        _atomic_replace(tmp, STATE_PATH)


def write_heartbeat(state, lock, status="running"):
    """Write an atomic liveness marker for the status UI and diagnostics."""
    payload = {
        "status": status,
        "pid": os.getpid(),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    tmp = HEARTBEAT_PATH.with_suffix(".tmp")
    with lock:
        HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        _atomic_replace(tmp, HEARTBEAT_PATH)


def update_anchor(state, lock, anchor_id, **changes):
    with lock:
        item = state["anchors"].setdefault(anchor_id, {})
        item.update(changes)
        item["updated_at"] = datetime.now().isoformat(timespec="seconds")
        save_state(state, lock)


def call_json(args, timeout=600):
    try:
        p = subprocess.run(args, cwd=str(ROOT), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"子命令超时（{timeout}秒）：{' '.join(str(a) for a in args[-2:])}") from exc
    if p.returncode:
        raise RuntimeError((p.stderr or p.stdout)[-1200:])
    data = extract_json(p.stdout)
    if data is None:
        raise RuntimeError("子命令没有返回有效 JSON: " + (p.stdout or p.stderr)[-1200:])
    return data


def _requeue_due_pending(cfg, state, lock):
    """持久化重试队列兜底：把 next_retry 已到点、音频仍存在的失败段补入转写队列。

    失败段信息已落盘（logs/pending_retry.json），watcher 重启后也能恢复重试；
    入队即从队列文件移除，避免与重试定时器重复补队。"""
    try:
        with LOCK_FOR_RETRY:
            now = time.time()
            data = load_retry_state()
            due = [(name, meta) for name, meta in data.items()
                   if isinstance(meta, dict) and 0 < meta.get("next_retry", 0) <= now]
            if not due:
                return
            # 一次只补一个到点段，避免瞬时把整批失败段灌进队列挤掉正常录音
            name, meta = due[0]
            audio = ROOT / "recordings" / name
            if not audio.exists():
                data.pop(name, None)
                save_retry_state(data)
                return
            attempts = int(meta.get("attempts", 0))
            data.pop(name, None)
            save_retry_state(data)
        aid = next((x for x in (a["id"] for a in cfg.get("anchors", []))
                    if name.startswith(x + "_")), None)
        anchor = next((a for a in cfg.get("anchors", []) if a["id"] == aid), None)
        if anchor is None:
            return
        m = audio.stem.rsplit("part", 1)
        segment_no = int(m[1]) if len(m) == 2 and m[1].isdigit() else 0
        TRANSCRIPT_QUEUE.put({"anchor": anchor, "audio": audio,
                              "segment_no": segment_no, "instant": False,
                              "transcript_attempts": attempts})
        log(f"兜底补入队列: {audio.name}")
    except Exception as exc:
        log(f"兜底补队异常: {exc}")


def push_feishu(title, body):
    # 加 subprocess 级超时做纵深防御：即使推送进程自身卡住，也不会永久堵死转写队列
    subprocess.run([sys.executable, str(ROOT / "scripts/feishu_push.py"),
                    "--title", title, "--body", body], cwd=str(ROOT), check=True,
                   timeout=60)


def in_window(anchor):
    now = datetime.now().strftime("%H:%M")
    return any(start <= now <= end for start, end in anchor.get("poll_windows", []))


def get_stream(anchor):
    if anchor["platform"] == "bilibili":
        status = call_json([sys.executable, str(ROOT / "scripts/bili_live.py"), "status", "--anchor", anchor["id"]])
        if not status.get("is_live"):
            return None
        stream = call_json([sys.executable, str(ROOT / "scripts/bili_live.py"), "playurl", "--anchor", anchor["id"]]).get("chosen")
        if not stream:
            raise RuntimeError("直播中但没有可用流地址")
        return stream["url"], status["live_url"]
    if anchor["platform"] == "douyin":
        result = call_json([sys.executable, str(ROOT / "scripts/douyin_live.py"), "stream", "--anchor", anchor["id"]])
        if not result.get("is_live"):
            return None
        chosen = result.get("chosen") or {}
        if not chosen.get("url"):
            raise RuntimeError("抖音直播中但未捕获到 FLV 流地址；请重新登录后重试")
        return chosen["url"], result["live_url"]
    raise RuntimeError(f"不支持的平台：{anchor.get('platform')}")


def record_segment(anchor, seconds, segment_no, stage=None):
    """只录音；录完后把音频丢入后台转写队列，立即返回以便继续录下一段。"""
    def set_stage(value):
        if stage:
            stage(value)

    job_id = f"{anchor['id']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_part{segment_no:03d}"
    set_stage("checking")
    stream = get_stream(anchor)
    if stream is None:
        return None
    url, referer = stream
    audio = ROOT / "recordings" / f"{job_id}.mp3"
    command_dir = ROOT / "logs" / "commands"
    command_dir.mkdir(parents=True, exist_ok=True)
    stop_file = command_dir / f"{anchor['id']}.now"
    # 清理上一次 F9 即时摘要残留的 .done 标记，否则本段会被误判为即时摘要
    Path(str(stop_file) + ".done").unlink(missing_ok=True)
    set_stage("recording")
    # 推送录音中进度通知，写清开始时间和预计出摘要时间，避免用户干等；加超时避免阻塞录音
    try:
        from datetime import timedelta
        _start = datetime.now()
        _eta = _start + timedelta(seconds=seconds + 180)  # 录音时长 + 转写摘要约3分钟缓冲
        _title = f"{anchor['name']}｜录音中 第{segment_no}段"
        _body = (f"开始：{_start.strftime('%H:%M')}\n"
                 f"预计：{_eta.strftime('%H:%M')} 出摘要\n"
                 f"（录音{seconds // 60}分钟 + 转写摘要约3分钟）\n"
                 f"平台：{anchor['platform']}")
        subprocess.run([sys.executable, str(ROOT / "scripts/feishu_push.py"),
                        "--title", _title, "--body", _body],
                       cwd=str(ROOT), timeout=15, capture_output=True)
    except Exception:
        pass
    # 必须 capture_output：record_audio 失败时把 ffmpeg 具体报错带出来，
    # 否则只能看到"非零退出"，无法诊断是流过期、断流还是 ffmpeg 报错
    rec = subprocess.run([sys.executable, str(ROOT / "scripts/record_audio.py"), "--url", url,
                          "--out", str(audio), "--seconds", str(seconds), "--referer", referer,
                          "--stop-file", str(stop_file)],
                         capture_output=True, text=True, encoding="utf-8", errors="replace",
                         timeout=max(120, seconds + 120))
    if rec.returncode:
        raise RuntimeError(f"录音失败（exit {rec.returncode}）："
                           f"{(rec.stderr or rec.stdout)[-1200:]}")
    if not audio.exists() or audio.stat().st_size < 1024:
        raise RuntimeError(f"录音文件无效或为空：{audio.name}")
    instant = Path(str(stop_file) + ".done").exists()
    # 录音结束后清理 .now 和 .done 两个标记，避免残留影响下一段；
    # .now 只在录音期间有意义，无论本次是 F9 触发还是正常超时结束都应清掉
    Path(str(stop_file) + ".done").unlink(missing_ok=True)
    stop_file.unlink(missing_ok=True)
    TRANSCRIPT_QUEUE.put({
        "anchor": anchor,
        "audio": str(audio),
        "segment_no": segment_no,
        "instant": instant,
    })
    return {"job_id": job_id, "audio": str(audio), "instant": instant}


def transcript_worker(cfg, state, lock, stop):
    """后台线程：从队列取已录好的音频，依次转写→摘要→推送飞书。与录音并行。"""
    while not stop.is_set():
        task = None
        try:
            try:
                task = TRANSCRIPT_QUEUE.get(timeout=2)
            except queue.Empty:
                # 队列空闲时顺带处理到点的 pending 重试（定时器之外的兜底）
                _requeue_due_pending(cfg, state, lock)
                continue
            anchor = task["anchor"]
            audio = Path(task["audio"])
            segment_no = task["segment_no"]
            instant = task.get("instant", False)
            aid = anchor["id"]
            try:
                update_anchor(state, lock, aid, transcript_status="transcribing")
                transcript_dir = ROOT / "transcripts" / aid / audio.stem
                call_json([sys.executable, str(ROOT / "scripts/transcribe.py"),
                           "--audio", str(audio), "--output-dir", str(transcript_dir)],
                          timeout=900)
                # Do not trust a child process' console-encoded path on Windows; derive it locally.
                transcript_path = transcript_dir / (audio.stem + ".txt")
                if not transcript_path.exists():
                    raise RuntimeError("转写完成但找不到逐字稿文件")
                update_anchor(state, lock, aid, transcript_status="summarizing")
                # summarize.py 内部有 6 次重试（每次最长 120s + 退避），外层超时须盖住其预算
                call_json([sys.executable, str(ROOT / "scripts/summarize.py"),
                           "--transcript", str(transcript_path)], timeout=1200)
                summary_path = transcript_path.with_suffix(".summary.txt")
                if not summary_path.exists():
                    raise RuntimeError("摘要生成完成但找不到摘要文件")
                text = summary_path.read_text(encoding="utf-8")
                body = f"主播：{anchor['name']}\n平台：{anchor['platform']}\n音频：{audio.name}\n\n{text}"
                update_anchor(state, lock, aid, transcript_status="pushing")
                title = f"{anchor['name']}｜即时摘要" if instant else f"{anchor['name']}｜直播第 {segment_no} 段摘要"
                push_feishu(title, body)
                # Keep a durable marker when cleanup is disabled, otherwise the
                # pending processor would treat an already-pushed recording as new.
                (transcript_dir / (audio.stem + ".pushed")).touch()
                cleanup_source_files(audio, transcript_path)
                with lock:
                    previous = state["anchors"].get(aid, {})
                    segments = int(previous.get("segments", 0)) + 1
                # 成功只移除本段的重试记录；不清零 pending_retry_at/transcript_attempts，
                # 否则同一主播其他仍在退避中的失败段会失去重试状态（历史上因此被永久搁置）
                pop_retry(audio.name)
                update_anchor(state, lock, aid, transcript_status="done",
                              segments=segments, last_summary=str(summary_path),
                              last_job=audio.stem, last_error="")
                log(f"{anchor['name']}: 第 {segment_no} 段摘要已推送")
            except Exception as exc:
                attempt = int(task.get("transcript_attempts", 0)) + 1
                delay = min(21600, 300 * (2 ** min(attempt - 1, 6)))
                update_anchor(state, lock, aid, transcript_status="failed",
                              last_audio=str(audio), pending_audio=str(audio),
                              transcript_attempts=attempt,
                              pending_retry_at=time.time() + delay,
                              last_error=f"转写/摘要失败: {exc}")
                log(f"{anchor['name']}: 第 {segment_no} 段转写/摘要失败 - {exc}")
                try:
                    push_feishu(f"{anchor['name']}｜转写/摘要失败",
                                 f"第 {segment_no} 段处理失败：{exc}\n音频：{audio.name}")
                except Exception:
                    pass
                # 失败信息落盘：watcher 重启后由 _requeue_due_pending 兜底补队，
                # 同一主播其他段成功也不会覆盖本段的重试状态
                with LOCK_FOR_RETRY:
                    retries = load_retry_state()
                    retries[audio.name] = {"attempts": attempt,
                                           "next_retry": time.time() + delay,
                                           "last_error": str(exc)}
                    save_retry_state(retries)
                # Retry in this worker so state writes remain serialized in
                # one process. The standalone process_pending utility remains
                # available for recordings left behind by a stopped watcher.
                retry_task = dict(task)
                retry_task["transcript_attempts"] = attempt
                def _retry_later():
                    if not stop.is_set() and audio.exists():
                        # 定时器补队时从持久化队列移除本段，兜底扫描便不会重复补队
                        pop_retry(audio.name)
                        TRANSCRIPT_QUEUE.put(retry_task)
                timer = threading.Timer(delay, _retry_later)
                timer.daemon = True
                timer.start()
            finally:
                TRANSCRIPT_QUEUE.task_done()
        except Exception as exc:
            # 最外层兜底：队列/状态写入等任何未预期异常都不能让唯一的转写线程死亡，
            # 否则所有主播的摘要都会永久停摆
            log(f"转写线程发生未预期异常，5秒后自动恢复 - {exc}")
            if task is not None:
                try:
                    TRANSCRIPT_QUEUE.task_done()
                except Exception:
                    pass
            stop.wait(5)


def anchor_worker(anchor, args, state, lock, stop, active):
    aid = anchor["id"]
    while not stop.is_set():
        was_recording = False
        recording_started = False
        try:
            refresh_day(state, lock)
            if in_window(anchor):
                with lock:
                    previous = state["anchors"].get(aid, {})
                    retry_at = previous.get("retry_at", 0)
                    if retry_at and time.time() < retry_at:
                        stop.wait(min(60, retry_at - time.time()))
                        continue
                    part = int(previous.get("recorded_segments", 0)) + 1
                try:
                    with lock:
                        active[aid] = True
                    def stage(value):
                        nonlocal recording_started
                        if value == "recording":
                            recording_started = True
                        update_anchor(state, lock, aid, status=value, segment=part)
                    result = record_segment(anchor, args.max_seconds if args.max_seconds > 0 else args.segment_seconds, part, stage)
                    if result is None:
                        update_anchor(state, lock, aid, status="not_live", last_error="", retry_at=0, attempts=0)
                    else:
                        was_recording = True
                        update_anchor(state, lock, aid, status="recorded", segment=part,
                                      recorded_segments=part,
                                      last_audio=result["audio"], transcript_status="queued")
                        log(f"{anchor['name']}: 第 {part} 段已录制，已加入转写队列")
                except Exception as exc:
                    update_anchor(state, lock, aid, status="failed", segment=part,
                                  attempts=int(previous.get("attempts", 0)) + 1,
                                  retry_at=time.time() + 300,
                                  last_error=str(exc))
                    log(f"{anchor['name']}: 处理失败 - {exc}")
                    # 已推送过"录音中"却没能录完时，补一条中断通知，避免用户对着预告干等
                    if recording_started:
                        try:
                            push_feishu(f"{anchor['name']}｜本段录音中断",
                                        f"第 {part} 段已开始录音但未能完成（主播可能中途下播或网络中断），本段不出摘要，将在约5分钟后自动重试。\n原因：{exc}")
                        except Exception:
                            pass
                finally:
                    with lock:
                        active.pop(aid, None)
            else:
                # Do not carry a stale recording/browser error into the next poll window.
                update_anchor(state, lock, aid, status="outside_window", last_error="", retry_at=0)
            if args.once:
                break
            # 主播在播时立即录下一段，不等待；
            # 失败时按 retry_at 退避（循环开头的检查会等待到 retry_at）；
            # 未开播/窗口外时按 interval 轮询
            with lock:
                cur = state["anchors"].get(aid, {})
                cur_retry = cur.get("retry_at", 0)
            if not was_recording and not (cur_retry and cur_retry > time.time()):
                stop.wait(max(30, args.interval))
        except Exception as exc:
            # 最外层兜底：refresh_day/状态写入/锁等待等 try 外的代码一旦抛异常，
            # 绝不能让该主播的监控线程静默死亡（否则会永久停止监控且无告警）
            log(f"{anchor['name']}: 监控循环发生未预期异常，30秒后自动恢复 - {exc}")
            try:
                update_anchor(state, lock, aid, status="failed",
                              last_error=f"循环异常已自动恢复: {exc}")
            except Exception:
                pass
            try:
                with lock:
                    active.pop(aid, None)
            except Exception:
                pass
            stop.wait(30)


def heartbeat_worker(cfg, args, state, lock, stop):
    last_push = 0.0
    while not stop.is_set():
      try:
        refresh_day(state, lock)
        write_heartbeat(state, lock)
        # 每天清理一次旧文件（录音/转写/日志，保留 7 天）
        global _last_cleanup_date
        today_str = datetime.now().strftime("%Y-%m-%d")
        if _last_cleanup_date != today_str:
            try:
                cleanup_old_files(cfg)
                _last_cleanup_date = today_str
                log("已执行每日旧文件清理")
            except Exception as exc:
                log(f"每日清理失败 - {exc}")
        now = time.time()
        if now - last_push >= max(60, args.health_interval) or last_push == 0:
            with lock:
                rows = []
                failed = 0
                for anchor in cfg.get("anchors", []):
                    item = state["anchors"].get(anchor["id"], {})
                    row = f"- {anchor['name']}：{item.get('status', 'starting')}，已录 {item.get('recorded_segments', 0)} 段 / 已推 {item.get('segments', 0)} 段"
                    if item.get("last_error"):
                        failed += 1
                        row += f"，错误：{item['last_error']}"
                    rows.append(row)
            try:
                title = "直播监控｜部分异常" if failed else "直播监控｜运行正常"
                push_feishu(title, ("直播监控状态\n" if failed else "直播监控运行正常\n") +
                            "检查时间：" + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "\n\n" + "\n".join(rows))
                log("运行状态已推送到飞书")
                last_push = now
            except Exception as exc:
                log(f"运行状态推送失败 - {exc}")
        stop.wait(min(60, max(15, args.health_interval)))
      except Exception as exc:
        # 兜底：心跳线程绝不能因写状态/清理异常而死亡，否则状态窗口会误报监控中断
        log(f"心跳线程发生未预期异常，10秒后自动恢复 - {exc}")
        stop.wait(10)


def hotkey_worker(active, lock, stop):
    """Register global F9 and signal only anchors currently recording."""
    user32 = ctypes.windll.user32
    hotkey_id = 1
    if not user32.RegisterHotKey(None, hotkey_id, 0, 0x78):  # VK_F9
        log("F9 快捷键注册失败，可能已被其他程序占用")
        return
    WM_HOTKEY = 0x0312
    WM_QUIT = 0x0012
    msg = wintypes.MSG()
    try:
        while not stop.is_set():
            result = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if result <= 0:
                break
            if msg.message == WM_HOTKEY and msg.wParam == hotkey_id:
                with lock:
                    current = list(active)
                if current:
                    for aid in current:
                        command = ROOT / "logs" / "commands" / f"{aid}.now"
                        command.parent.mkdir(parents=True, exist_ok=True)
                        command.touch()
                    log("F9：已请求当前直播立即生成摘要")
                else:
                    log("F9：当前没有正在录音的主播")
    finally:
        user32.UnregisterHotKey(None, hotkey_id)


def refresh_day(state, lock):
    today = datetime.now().strftime("%Y-%m-%d")
    with lock:
        if state.get("date") != today:
            state.clear()
            state.update({"date": today, "anchors": {}})
            save_state(state, lock)


def cleanup_old_files(cfg):
    days = int(cfg.get("retention_days", 7))
    cutoff = time.time() - days * 86400
    for folder in (ROOT / "recordings", ROOT / "transcripts", ROOT / "logs"):
        if not folder.exists():
            continue
        for path in folder.rglob("*"):
            # 小体积 mp3 视为失败残片，但必须文件年龄超过5分钟才删，
            # 避免误删刚启动录音、文件还在增长的正常录音
            age = time.time() - path.stat().st_mtime if path.is_file() else 0
            invalid_recording = (folder.name == "recordings" and path.suffix.lower() == ".mp3"
                                 and path.is_file() and path.stat().st_size < 1024 and age > 300)
            if path.is_file() and path.name != "state.json" and (invalid_recording or path.stat().st_mtime < cutoff):
                try:
                    path.unlink()
                except OSError as exc:
                    log(f"清理失败 {path.name}: {exc}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--daemon", action="store_true")
    ap.add_argument("--interval", type=int, default=900)
    ap.add_argument("--segment-seconds", type=int, default=900)
    ap.add_argument("--max-seconds", type=int, default=0)
    ap.add_argument("--health-interval", type=int, default=1800)
    args = ap.parse_args()
    # 用 TextIOWrapper 重新包装设置 UTF-8，避免 sys.stdout.reconfigure 在 Windows 上触发进程重启
    import io as _io
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = _io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
    if hasattr(sys.stderr, "buffer"):
        sys.stderr = _io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)
    cfg = load_config(); ensure_dirs()
    try:
        instance_lock = acquire_instance_lock()
    except RuntimeError as exc:
        log(str(exc))
        return
    cleanup_old_files(cfg)
    state, lock, stop, active = today_state(), threading.RLock(), threading.Event(), {}
    save_state(state, lock)
    write_heartbeat(state, lock)
    workers = [threading.Thread(target=anchor_worker, args=(a, args, state, lock, stop, active), daemon=True)
               for a in cfg.get("anchors", [])]
    for worker in workers:
        worker.start()
    if args.daemon:
        threading.Thread(target=heartbeat_worker, args=(cfg, args, state, lock, stop), daemon=True).start()
    threading.Thread(target=hotkey_worker, args=(active, lock, stop), daemon=True).start()
    threading.Thread(target=transcript_worker, args=(cfg, state, lock, stop), daemon=True).start()
    # Daily 21:00 review runs independently; exceptions are contained inside
    # the scheduler so recording and normal segment summaries remain healthy.
    if not args.once:
        threading.Thread(target=daily_summary_scheduler, args=(cfg, stop),
                         kwargs={"interval": 30}, daemon=True,
                         name="daily-summary-scheduler").start()
    if args.once:
        for worker in workers: worker.join()
        # queue.empty() 只表示没有等待中的项目，不能表示当前项目已处理完。
        wait_for_transcripts(stop, timeout=300)
        write_heartbeat(state, lock, "stopped")
        if instance_lock:
            release_instance_lock(instance_lock)
        return
    try:
        while True: time.sleep(1)
    except KeyboardInterrupt:
        stop.set()
    finally:
        # 等待转写队列完成（最多 5 分钟），避免退出时丢失已录好的音频
        wait_for_transcripts(stop, timeout=300)
        try:
            write_heartbeat(state, lock, "stopped")
        except Exception:
            pass
        try:
            if instance_lock:
                release_instance_lock(instance_lock)
        finally:
            pass


if __name__ == "__main__":
    main()
