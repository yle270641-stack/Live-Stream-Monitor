# -*- coding: utf-8 -*-
"""Generate and deliver one independent daily review per streamer.

This module deliberately owns its state and file discovery so a failure in the
21:00 job cannot stop recording or the normal segment-summary pipeline.
"""
import argparse
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

from common import ROOT, ensure_dirs, load_config, load_dotenv, log
from summarize import api_summary

STATE_PATH = ROOT / "logs" / "daily_summary_state.json"
OUTPUT_ROOT = ROOT / "transcripts" / "daily"
DATE_RE = re.compile(r"(?<!\d)(20\d{2}[01]\d[0-3]\d)(?!\d)")

DAILY_SYSTEM = """你是财经直播的日终复盘编辑。只依据输入的主播摘要，不补充外部事实，不给买卖建议。
请输出一篇简短、可快速阅读的中文复盘，严格只包含以下三个部分，每部分使用指定标题：
一、当前市场形势：概括当天主播对大盘、情绪、资金和仓位的判断；没有明确内容就写“当天摘要未明确说明”。
二、未来展望：概括主播对后续行情、催化和风险的判断；没有明确内容就写“当天摘要未明确说明”。
三、核心方向：列出主播当天反复提及的板块、主题或个股及其逻辑，最多五项；没有明确内容就写“当天摘要未明确说明”。
每个部分写一段连贯文字，不要添加第四部分、免责声明、开场白或 markdown 代码块。全文控制在800字以内。"""

# Retry a failed delivery twice immediately (three attempts total) before
# leaving the job in retrying state for the scheduler's next pass.
SEND_RETRIES = 2
SEND_RETRY_DELAYS = (2, 5)


def _today():
    return datetime.now().strftime("%Y-%m-%d")


def _date_in_file(path, day):
    wanted = day.replace("-", "")
    match = DATE_RE.search(path.name)
    if match:
        return match.group(1) == wanted
    # Files created by older versions may not contain a date in the leaf name.
    try:
        return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d") == day
    except OSError:
        return False


def collect_summaries(anchor_id, day, root=None):
    """Return deterministic, date-filtered summary files for one anchor only."""
    root = root or ROOT
    folder = Path(root) / "transcripts" / anchor_id
    if not folder.exists():
        return []
    files = [p for p in folder.rglob("*.summary.txt") if p.is_file() and _date_in_file(p, day)]
    return sorted(files, key=lambda p: (p.stat().st_mtime, str(p).lower()))


def _read_material(files, limit=30000):
    chunks, used = [], 0
    for path in files:
        try:
            text = path.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        if not text:
            continue
        remaining = limit - used
        if remaining <= 0:
            break
        text = text[:remaining]
        chunks.append(f"【{path.stem}】\n{text}")
        used += len(text)
    return "\n\n".join(chunks)


def _load_state():
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STATE_PATH)


def _entry(state, day, aid):
    days = state.setdefault("days", {})
    record = days.setdefault(day, {})
    return record.setdefault(aid, {"status": "pending", "attempts": 0})


def _fallback_review(name, day, files):
    return (f"{name}｜{day} 每日复盘\n\n一、当前市场形势\n"
            "当天摘要已收集，但模型暂不可用，请稍后重试。\n\n"
            "二、未来展望\n当天摘要未明确说明。\n\n"
            "三、核心方向\n当天摘要未明确说明。\n\n"
            f"信息来源：当天 {len(files)} 份小结。")


def build_prompt(name, day, material):
    return (f"主播：{name}\n日期：{day}\n\n以下仅是该主播当天的阶段摘要，不能与其他主播内容混用：\n"
            + material)


def generate_review(name, day, files, simulate=False):
    material = _read_material(files)
    if not material:
        return ""
    if simulate:
        return _fallback_review(name, day, files)
    if not os.getenv("LLM_API_KEY", "").strip():
        raise RuntimeError("未配置 LLM_API_KEY，日终复盘不会发送占位内容")
    # api_summary accepts the normal segment prompt only, so temporarily pass
    # the daily prompt through its optional system_prompt argument.
    result = api_summary(build_prompt(name, day, material), max_retries=3,
                         system_prompt=DAILY_SYSTEM)
    return f"{name}｜{day} 每日复盘\n\n{result.strip()}\n\n信息来源：当天 {len(files)} 份小结。"


def _deliver(cfg, title, body, push_callback=None, retries=SEND_RETRIES):
    """Deliver one message, retrying transient failures immediately."""
    attempts = retries + 1
    last_error = None
    for attempt in range(1, attempts + 1):
        try:
            if push_callback:
                push_callback(title, body)
                return
            from feishu_push import post_text
            webhook = cfg.get("feishu_webhook", "")
            if not webhook:
                raise RuntimeError("未配置飞书 webhook")
            response = post_text(webhook, body)
            result_code = response.get("code") if "code" in response else response.get("StatusCode")
            if result_code != 0:
                raise RuntimeError("飞书返回失败：" + json.dumps(response, ensure_ascii=False))
            return
        except Exception as exc:
            last_error = exc
            if attempt < attempts:
                delay = SEND_RETRY_DELAYS[min(attempt - 1, len(SEND_RETRY_DELAYS) - 1)]
                log(f"{title}: 发送失败，第 {attempt} 次失败，{delay} 秒后重试 - {exc}")
                time.sleep(delay)
    raise RuntimeError(f"发送失败（已尝试 {attempts} 次）：{last_error}") from last_error


def run_daily(cfg=None, day=None, dry_run=False, no_push=False, simulate=False,
              push_callback=None, now=None, retry_after=300):
    """Process all anchors. Returns per-anchor result; safe to call repeatedly."""
    load_dotenv()
    # A dry run must be fully offline: never call the configured model or
    # webhook unless the caller explicitly opts into normal execution.
    simulate = simulate or dry_run
    ensure_dirs()
    cfg = cfg or load_config()
    day = day or _today()
    state = _load_state()
    persist_state = not dry_run
    results = {}
    for anchor in cfg.get("anchors", []):
        aid, name = anchor["id"], anchor.get("name", anchor["id"])
        rec = _entry(state, day, aid)
        files = collect_summaries(aid, day)
        results[aid] = {"name": name, "files": len(files), "status": rec.get("status", "pending")}
        if not files:
            rec.update(status="no_content", checked_at=datetime.now().isoformat(timespec="seconds"), files=0)
            results[aid]["status"] = "no_content"
            continue
        if rec.get("status") == "sent" and rec.get("date") == day:
            results[aid]["status"] = "sent"
            continue
        if rec.get("status") == "retrying" and rec.get("next_retry", 0) > time.time():
            results[aid]["status"] = "retrying"
            continue
        try:
            rec.update(status="generating", files=len(files), attempts=int(rec.get("attempts", 0)) + 1)
            if persist_state:
                _save_state(state)
            review = generate_review(name, day, files, simulate=simulate)
            if not review:
                rec.update(status="no_content")
                continue
            out_root = OUTPUT_ROOT if persist_state else (ROOT / "logs" / "daily_dry_run")
            out = out_root / aid / f"{day}.daily.txt"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(review, encoding="utf-8")
            if dry_run or no_push:
                rec.update(status="generated", output=str(out), generated_at=datetime.now().isoformat(timespec="seconds"))
                results[aid].update(status="generated", output=str(out))
                continue
            _deliver(cfg, f"{name}｜{day} 每日复盘", review, push_callback=push_callback)
            rec.update(status="sent", date=day, output=str(out), sent_at=datetime.now().isoformat(timespec="seconds"), last_error="")
            results[aid].update(status="sent", output=str(out))
        except Exception as exc:
            rec.update(status="retrying", next_retry=time.time() + retry_after, last_error=str(exc))
            results[aid].update(status="retrying", error=str(exc))
            log(f"{name}: 每日复盘失败，将重试 - {exc}")
        finally:
            if persist_state:
                _save_state(state)
    state["last_run"] = datetime.now().isoformat(timespec="seconds")
    if persist_state:
        _save_state(state)
    return results


def scheduler(cfg, stop, push_callback=None, interval=30):
    """Run at/after 21:00 and catch up automatically when started late."""
    while not stop.is_set():
        try:
            now = datetime.now()
            if now.hour >= 21:
                run_daily(cfg, day=now.strftime("%Y-%m-%d"), push_callback=push_callback, now=now)
        except Exception as exc:
            log(f"每日21点复盘调度异常，稍后重试 - {exc}")
        stop.wait(interval)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="")
    ap.add_argument("--dry-run", action="store_true", help="生成文件但不调用模型/飞书")
    ap.add_argument("--simulate", action="store_true", help="使用本地假模型，配合 dry-run 做离线测试")
    ap.add_argument("--no-push", action="store_true")
    args = ap.parse_args()
    result = run_daily(day=args.date or _today(), dry_run=args.dry_run, no_push=args.no_push,
                       simulate=args.simulate)
    print(json.dumps({"ok": True, "date": args.date or _today(), "anchors": result},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
