# -*- coding: utf-8 -*-
"""公共工具：路径、配置、外部命令、JSON 提取、日志。仅用标准库。"""
import json
import os
import re
import shutil
import subprocess
import sys
import glob
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "anchors.json"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

SUBDIRS = ["scripts", "config", "recordings", "transcripts", "logs", "logs/commands"]
SUPPORTED_PLATFORMS = {"bilibili", "douyin"}
ANCHOR_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


def ensure_dirs():
    for d in SUBDIRS:
        (ROOT / d).mkdir(parents=True, exist_ok=True)
    return {d: ROOT / d for d in SUBDIRS}


def configure_utf8_stdio():
    """Use deterministic UTF-8 output for Windows pipes, logs, and terminals."""
    import io
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True
        )
    if hasattr(sys.stderr, "buffer"):
        sys.stderr = io.TextIOWrapper(
            sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True
        )


def load_config():
    load_dotenv()
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            "缺少 config/anchors.json；请复制 config/anchors.example.json 后填写配置。"
        )
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        config = json.load(f)
    if not isinstance(config, dict):
        raise ValueError("配置无效：配置根节点必须是 JSON 对象")
    if not isinstance(config.get("anchors"), list):
        raise ValueError("config/anchors.json 中的 anchors 必须是列表。")
    webhook = os.getenv("FEISHU_WEBHOOK", "").strip()
    if webhook:
        config["feishu_webhook"] = webhook
    errors, _ = inspect_config(config)
    if errors:
        raise ValueError("配置无效：\n- " + "\n- ".join(errors))
    return config


def inspect_config(config, allow_placeholders=False):
    """Return configuration errors and warnings without exposing secret values."""
    errors, warnings = [], []
    if not isinstance(config, dict):
        return ["配置根节点必须是 JSON 对象"], warnings

    anchors = config.get("anchors")
    if not isinstance(anchors, list) or not anchors:
        return ["anchors 必须是非空列表"], warnings

    seen = set()
    for index, anchor in enumerate(anchors, 1):
        label = f"anchors[{index}]"
        if not isinstance(anchor, dict):
            errors.append(f"{label} 必须是对象")
            continue
        anchor_id = str(anchor.get("id", "")).strip()
        if not ANCHOR_ID_RE.fullmatch(anchor_id):
            errors.append(f"{label}.id 只能包含英文字母、数字、下划线和连字符")
        elif anchor_id in seen:
            errors.append(f"主播 id 重复：{anchor_id}")
        seen.add(anchor_id)
        if not str(anchor.get("name", "")).strip():
            errors.append(f"{label}.name 不能为空")

        platform = anchor.get("platform")
        if platform not in SUPPORTED_PLATFORMS:
            errors.append(f"{label}.platform 必须是 bilibili 或 douyin")
        required = (("mid", "room_id") if platform == "bilibili"
                    else ("sec_uid",) if platform == "douyin" else ())
        for field in required:
            value = str(anchor.get(field, "")).strip()
            if not value:
                errors.append(f"{label}.{field} 不能为空")
            elif not allow_placeholders and value.startswith("替换为"):
                errors.append(f"{label}.{field} 仍是示例占位符")
        if platform == "bilibili":
            for field in ("mid", "room_id"):
                value = str(anchor.get(field, "")).strip()
                if value and not value.startswith("替换为") and not value.isdigit():
                    errors.append(f"{label}.{field} 必须是数字")

        windows = anchor.get("poll_windows")
        if not isinstance(windows, list) or not windows:
            errors.append(f"{label}.poll_windows 必须是非空列表")
        else:
            for window_index, window in enumerate(windows, 1):
                valid = (isinstance(window, list) and len(window) == 2
                         and all(isinstance(x, str) and TIME_RE.fullmatch(x) for x in window))
                if not valid:
                    errors.append(
                        f"{label}.poll_windows[{window_index}] 必须是 [\"HH:MM\", \"HH:MM\"]"
                    )

    webhook = str(config.get("feishu_webhook", "")).strip()
    if webhook:
        parsed = urlparse(webhook)
        if parsed.scheme != "https" or not parsed.netloc:
            errors.append("feishu_webhook 必须是有效的 HTTPS URL")
    else:
        warnings.append("未配置 FEISHU_WEBHOOK；摘要会保存在本地但不会推送")

    retention = config.get("retention_days", 7)
    if not isinstance(retention, int) or isinstance(retention, bool) or retention < 1:
        errors.append("retention_days 必须是大于等于 1 的整数")
    return errors, warnings


def time_in_windows(current, windows):
    """Return whether HH:MM is inside normal or cross-midnight time windows."""
    current_minutes = _time_minutes(current)
    for start, end in windows:
        start_minutes, end_minutes = _time_minutes(start), _time_minutes(end)
        if start_minutes <= end_minutes:
            if start_minutes <= current_minutes <= end_minutes:
                return True
        elif current_minutes >= start_minutes or current_minutes <= end_minutes:
            return True
    return False


def _time_minutes(value):
    if not isinstance(value, str) or not TIME_RE.fullmatch(value):
        raise ValueError(f"非法时间：{value!r}，应为 HH:MM")
    hour, minute = value.split(":")
    return int(hour) * 60 + int(minute)


def load_dotenv():
    """Load local KEY=VALUE settings for child tools such as lark-cli."""
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for raw in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if value[:1] in {"'", '"'} and value[-1:] == value[:1]:
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


def get_anchor(cfg, anchor_id):
    for a in cfg["anchors"]:
        if a["id"] == anchor_id:
            return a
    raise SystemExit(f"[common] 未找到主播 id={anchor_id}")


def resolve_tool(cfg, key):
    """config 绝对路径 -> PATH -> 目录搜索，逐级兜底，返回可执行路径。"""
    tools = cfg.get("tools", {})
    p = tools.get(key)
    if p and Path(p).exists():
        return p
    name = {"ffmpeg": "ffmpeg", "ffprobe": "ffprobe", "lark_cli": "lark-cli"}.get(key, key)
    w = shutil.which(name)
    if w:
        return w
    if key == "ffmpeg":
        hits = sorted(glob.glob(str(Path.home() / "AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg*/**/ffmpeg.exe"), recursive=True))
        if hits:
            return hits[-1]
    return name  # 留给调用方报错


def log(msg):
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    # Windows consoles may use GBK while subprocess errors contain Unicode.
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    try:
        line = line.encode(encoding, errors="replace").decode(encoding, errors="replace")
    except LookupError:
        line = line.encode("utf-8", errors="replace").decode("utf-8", errors="replace")
    print(line, flush=True)


def run(cmd, cwd=None, timeout=None):
    """运行外部命令，返回 (rc, stdout, stderr)，统一 UTF-8。"""
    p = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout,
    )
    return p.returncode, p.stdout or "", p.stderr or ""


def extract_json(text):
    """从可能夹杂日志行的输出里截取最外层 JSON 对象。"""
    if not text:
        return None
    s = text.find("{")
    e = text.rfind("}")
    if s == -1 or e == -1 or e <= s:
        return None
    frag = text[s:e + 1]
    try:
        return json.loads(frag)
    except Exception:
        # 退化为括号配平，取第一个完整对象
        depth = 0
        for i, ch in enumerate(frag):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(frag[:i + 1])
                    except Exception:
                        return None
    return None


def out_json(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def cleanup_source_files(audio, transcript):
    """推送成功后删除原始录音和逐字稿，只保留摘要。受 CLEANUP_AFTER_PUSH 控制（默认开启）。
    删除失败只记日志、不抛异常，不影响主流程。返回已删除的路径列表。"""
    if os.getenv("CLEANUP_AFTER_PUSH", "true").lower() not in ("true", "1", "yes", "on"):
        return []
    removed = []
    for f in (audio, transcript):
        try:
            p = Path(f) if f else None
            if p and p.exists():
                p.unlink()
                removed.append(str(p))
        except Exception as exc:
            log(f"清理原始文件失败（不影响摘要）：{f} - {exc}")
    if removed:
        log(f"已清理原始文件（摘要已推送）：{', '.join(removed)}")
    return removed
