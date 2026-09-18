# -*- coding: utf-8 -*-
"""Validate configuration and local runtime prerequisites without contacting platforms."""
import argparse
import json
import os
import shutil
from pathlib import Path

from common import (CONFIG_PATH, ROOT, configure_utf8_stdio, inspect_config,
                    load_dotenv, resolve_tool)


def check_tools(config):
    errors = []
    for key in ("ffmpeg", "ffprobe"):
        resolved = resolve_tool(config, key)
        if not Path(resolved).is_file() and not shutil.which(resolved):
            errors.append(f"未找到 {key}；请安装 FFmpeg 或在 tools.{key} 填写可执行文件路径")
    return errors


def main():
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description="离线检查直播监控配置")
    parser.add_argument("--config", default=str(CONFIG_PATH))
    parser.add_argument("--allow-placeholders", action="store_true")
    parser.add_argument("--skip-tools", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    path = Path(args.config)
    if not path.is_absolute():
        path = (ROOT / path).resolve()
    try:
        config = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        errors, warnings = [f"配置文件不存在：{path}"], []
    except json.JSONDecodeError as exc:
        errors, warnings = [f"JSON 格式错误（第 {exc.lineno} 行，第 {exc.colno} 列）：{exc.msg}"], []
    else:
        load_dotenv()
        webhook = os.getenv("FEISHU_WEBHOOK", "").strip()
        if webhook and isinstance(config, dict):
            config["feishu_webhook"] = webhook
        errors, warnings = inspect_config(config, allow_placeholders=args.allow_placeholders)
        if not args.skip_tools and isinstance(config, dict):
            errors.extend(check_tools(config))

    result = {"ok": not errors, "config": str(path), "errors": errors, "warnings": warnings}
    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("配置检查通过" if result["ok"] else "配置检查失败")
        for item in errors:
            print(f"[错误] {item}")
        for item in warnings:
            print(f"[提示] {item}")
    raise SystemExit(0 if result["ok"] else 2)


if __name__ == "__main__":
    main()
