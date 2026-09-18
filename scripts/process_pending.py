# -*- coding: utf-8 -*-
"""Process valid recordings that have no transcript/summary yet."""
import json
import argparse
import subprocess
import sys
import time
from datetime import datetime
from common import ROOT, cleanup_source_files, extract_json, load_config

LOCK_PATH = ROOT / "logs" / "process_pending.lock"
_LOCK_HANDLE = None
RETRY_STATE = ROOT / "logs" / "pending_retry.json"

def load_retry_state():
    try:
        data = json.loads(RETRY_STATE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}

def save_retry_state(data):
    RETRY_STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = RETRY_STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(RETRY_STATE)


def acquire_lock():
    global _LOCK_HANDLE
    if sys.platform != "win32":
        return True
    import msvcrt
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    handle = open(LOCK_PATH, "a+b")
    handle.seek(0)
    handle.write(b"1")
    handle.flush()
    try:
        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        handle.close()
        return False
    _LOCK_HANDLE = handle
    return True


def release_lock():
    global _LOCK_HANDLE
    if _LOCK_HANDLE is None:
        return
    import msvcrt
    try:
        _LOCK_HANDLE.seek(0)
        msvcrt.locking(_LOCK_HANDLE.fileno(), msvcrt.LK_UNLCK, 1)
    except OSError:
        pass
    _LOCK_HANDLE.close()
    _LOCK_HANDLE = None

def call(args):
    p = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1500)
    if p.returncode: raise RuntimeError((p.stderr or p.stdout)[-1500:])
    data = extract_json(p.stdout)
    if not data: raise RuntimeError("子命令没有返回有效 JSON")
    return data


def update_state(anchor_id, **changes):
    """Best-effort status update without breaking the pending queue."""
    path = ROOT / "logs" / "state.json"
    try:
        state = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"date": "", "anchors": {}}
        item = state.setdefault("anchors", {}).setdefault(anchor_id, {})
        item.update(changes)
        item["updated_at"] = datetime.now().isoformat(timespec="seconds")
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
    except Exception as exc:
        print(f"状态写入失败：{exc}", file=sys.stderr, flush=True)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-age", type=int, default=0,
                    help="只处理最后修改时间超过指定秒数的录音，避免抢正在录音的文件")
    args = ap.parse_args()
    if not acquire_lock():
        print(json.dumps({"ok": False, "reason": "pending_processor_already_running"}, ensure_ascii=False))
        return
    cfg = load_config(); by_prefix = {a["id"]: a for a in cfg.get("anchors", [])}
    retries = load_retry_state()
    done = 0
    failed = 0
    try:
        for audio in sorted((ROOT / "recordings").glob("*.mp3"), key=lambda p: p.stat().st_mtime):
            if audio.stat().st_size < 1024: continue
            if args.min_age > 0 and time.time() - audio.stat().st_mtime < args.min_age:
                continue
            aid = next((x for x in by_prefix if audio.name.startswith(x + "_")), None)
            if not aid: continue
            out_dir = ROOT / "transcripts" / aid / audio.stem
            summary = out_dir / (audio.stem + ".summary.txt")
            pushed_marker = out_dir / (audio.stem + ".pushed")
            retry = retries.get(audio.name, {})
            if retry.get("next_retry", 0) > time.time():
                continue
            # 已有摘要且已推送成功的跳过；摘要存在但推送失败的只重推不重转写
            if summary.exists() and pushed_marker.exists():
                continue
            print(f"处理 {audio.name} ...", flush=True)
            try:
                transcript = out_dir / (audio.stem + ".txt")
                if not summary.exists():
                    call([sys.executable, str(ROOT / "scripts/transcribe.py"), "--audio", str(audio), "--output-dir", str(out_dir)])
                    call([sys.executable, str(ROOT / "scripts/summarize.py"), "--transcript", str(transcript)])
                summary_path = out_dir / (audio.stem + ".summary.txt")
                text = summary_path.read_text(encoding="utf-8")
                body = f"主播：{by_prefix[aid]['name']}\n平台：{by_prefix[aid]['platform']}\n音频：{audio.name}\n\n{text}"
                call([sys.executable, str(ROOT / "scripts/feishu_push.py"), "--title", f"{by_prefix[aid]['name']}｜补发摘要", "--body", body])
                pushed_marker.touch()
                retries.pop(audio.name, None)
                save_retry_state(retries)
                cleanup_source_files(audio, transcript)
                done += 1
                state_path = ROOT / "logs" / "state.json"
                try:
                    current = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
                    previous = current.get("anchors", {}).get(aid, {})
                    segments = int(previous.get("segments", 0)) + 1
                except Exception:
                    segments = 1
                update_state(aid, status="summary_sent", transcript_status="done",
                             segments=segments, last_job=audio.stem,
                             last_summary=str(summary_path), pending_audio="",
                             pending_processed_at=datetime.now().isoformat(timespec="seconds"), last_error="")
            except Exception as exc:
                failed += 1
                attempt = int(retry.get("attempts", 0)) + 1
                # Exponential backoff (5m, 10m, 20m ... max 6h) prevents a
                # temporary Portdan/LLM outage from hammering the endpoint.
                delay = min(21600, 300 * (2 ** min(attempt - 1, 6)))
                retries[audio.name] = {"attempts": attempt,
                                       "next_retry": time.time() + delay,
                                       "last_error": str(exc)}
                save_retry_state(retries)
                update_state(aid, pending_error=str(exc))
                print(f"跳过 {audio.name}：{exc}", file=sys.stderr, flush=True)
        print(json.dumps({"ok": failed == 0, "processed": done, "failed": failed}, ensure_ascii=False))
    finally:
        release_lock()

if __name__ == "__main__": main()
