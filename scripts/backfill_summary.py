# -*- coding: utf-8 -*-
"""补跑所有"有逐字稿但缺摘要"的段落。

单段失败不会中断整体：内部 summarize_text 已带 6 次长退避重试，
本脚本再做最多 3 轮扫描，直到全部补齐或确认无法恢复。

用法：
    .venv\\Scripts\\python.exe scripts\\backfill_summary.py
"""
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import ROOT, configure_utf8_stdio
from summarize import load_dotenv, summarize_text

TRANSCRIPTS = ROOT / "transcripts"
SKIP_DIRS = {"daily", "gpu_test", "test_asr", "simulation_asr"}
MAX_ROUNDS = 3


def find_missing():
    missing = []
    for anchor in sorted(TRANSCRIPTS.iterdir()):
        if not anchor.is_dir() or anchor.name in SKIP_DIRS or anchor.name.startswith("simulation"):
            continue
        for part in sorted(anchor.iterdir()):
            if not part.is_dir():
                continue
            txts = [f for f in part.glob("*.txt") if not f.name.endswith(".summary.txt")]
            sums = list(part.glob("*.summary.txt"))
            if txts and not sums:
                missing.append((part, txts[0]))
    return missing


def main():
    configure_utf8_stdio()
    load_dotenv()
    for round_no in range(1, MAX_ROUNDS + 1):
        missing = find_missing()
        if not missing:
            print("[backfill] 全部段落摘要齐全，无需补跑。")
            return 0
        print(f"[backfill] 第 {round_no} 轮：发现 {len(missing)} 段缺摘要")
        failed = []
        for idx, (part, txt) in enumerate(missing, 1):
            tag = part.name
            print(f"\n[backfill] ({idx}/{len(missing)}) 处理 {tag}（逐字稿 {txt.stat().st_size} 字节）", flush=True)
            try:
                t0 = time.time()
                result = summarize_text(txt.read_text(encoding="utf-8"))
                out = txt.with_suffix(".summary.txt")
                out.write_text(result, encoding="utf-8")
                print(f"[backfill] 完成 {tag}，摘要 {len(result)} 字，耗时 {time.time()-t0:.0f}s -> {out.name}", flush=True)
            except Exception as exc:
                print(f"[backfill] 失败 {tag}：{type(exc).__name__}: {str(exc)[:200]}", flush=True)
                failed.append(tag)
        if not failed:
            print("\n[backfill] 本轮全部成功。")
            return 0
        print(f"\n[backfill] 本轮仍失败 {len(failed)} 段：{failed}")
        if round_no < MAX_ROUNDS:
            print("[backfill] 60s 后开始下一轮…")
            time.sleep(60)
    left = [p.name for p, _ in find_missing()]
    print(f"\n[backfill] 经 {MAX_ROUNDS} 轮仍未完成：{left}")
    print("[backfill] 这些段落可能需要开启代理（v2rayN）后重跑本脚本。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
