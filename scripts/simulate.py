# -*- coding: utf-8 -*-
"""Run a safe local end-to-end simulation without touching live streams.

The simulation uses a fixture transcript and is fully offline by default.
It never uploads audio or sends a Feishu message. Passing --use-llm explicitly
allows the configured summary endpoint to process the synthetic fixture.
"""
import argparse
import json
import os
from datetime import datetime
from common import ROOT, configure_utf8_stdio, load_dotenv
from summarize import summarize_text


FIXTURE = """[00:01] 主播：今天大盘高开后震荡，指数没有形成明确突破，整体仓位建议控制在三成以内。
[00:38] 主播：板块方面，继续观察券商和人工智能，新能源暂时不追高。
[01:12] 主播：个股提到中信证券，只有放量突破前高才考虑关注；这不是买卖建议。
[01:46] 主播：如果成交量继续萎缩，短线要防范冲高回落，投资者注意控制风险。
"""


def main():
    configure_utf8_stdio()
    ap = argparse.ArgumentParser()
    ap.add_argument("--keep-transcript", action="store_true")
    ap.add_argument("--use-llm", action="store_true",
                    help="允许把内置虚构逐字稿发送到已配置的 LLM 接口")
    args = ap.parse_args()
    load_dotenv()
    if not args.use_llm:
        os.environ.pop("LLM_API_KEY", None)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    transcript = ROOT / "transcripts" / f"simulation_{stamp}.txt"
    summary = ROOT / "logs" / f"simulation_{stamp}_summary.txt"
    transcript.parent.mkdir(parents=True, exist_ok=True)
    summary.parent.mkdir(parents=True, exist_ok=True)
    transcript.write_text(FIXTURE, encoding="utf-8")
    result = summarize_text(FIXTURE)
    summary.write_text(result, encoding="utf-8")
    if not args.keep_transcript:
        transcript.unlink(missing_ok=True)
    print(json.dumps({"ok": True, "mode": "llm" if args.use_llm else "offline",
                      "summary_path": str(summary),
                      "transcript_kept": args.keep_transcript}, ensure_ascii=False, indent=2))
    print("\n" + result)


if __name__ == "__main__":
    main()
