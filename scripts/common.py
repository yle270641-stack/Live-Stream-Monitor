# -*- coding: utf-8 -*-
"""公共工具：路径、配置、外部命令、JSON 提取、日志。仅用标准库。"""
import json
import os
import shutil
import subprocess
import sys
import glob
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "anchors.json"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

SUBDIRS = ["scripts", "config", "recordings", "transcripts", "logs", "logs/commands"]


def ensure_dirs():
    for d in SUBDIRS:
        (ROOT / d).mkdir(parents=True, exist_ok=True)
    return {d: ROOT / d for d in SUBDIRS}


def load_config():
    load_dotenv()
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


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
