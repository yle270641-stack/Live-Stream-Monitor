# -*- coding: utf-8 -*-
"""Local audio transcription with faster-whisper. No audio is uploaded."""
import argparse
import json
import os
import sys
import site
from pathlib import Path

from common import ROOT, log, ensure_dirs, load_dotenv


def fail(reason, **extra):
    result = {"ok": False, "reason": reason}
    result.update(extra)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(2)


def format_ts(seconds):
    total = max(0, int(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def transcribe(audio, out_dir):
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        fail("faster_whisper_not_installed", hint="运行 安装依赖.bat")
    model_name = os.getenv("WHISPER_MODEL", "small")
    device = os.getenv("WHISPER_DEVICE", "cpu")
    compute_type = os.getenv("WHISPER_COMPUTE_TYPE", "int8" if device == "cpu" else "float16")
    language = os.getenv("WHISPER_LANGUAGE", "zh") or None
    if device == "cuda":
        # NVIDIA pip packages install runtime DLLs outside PATH on Windows.
        for root in site.getsitepackages() + [site.getusersitepackages()]:
            base = Path(root) / "nvidia"
            for name in ("cublas", "cudnn"):
                dll_dir = base / name / "bin"
                if dll_dir.exists():
                    os.add_dll_directory(str(dll_dir))
                    os.environ["PATH"] = str(dll_dir) + os.pathsep + os.environ.get("PATH", "")
    log(f"加载本地语音模型 {model_name} ({device}/{compute_type})，首次运行会下载模型")
    try:
        model = WhisperModel(model_name, device=device, compute_type=compute_type)
        segments, info = model.transcribe(str(audio), language=language, vad_filter=True,
                                          beam_size=5, condition_on_previous_text=False,
                                          no_speech_threshold=0.6)
        lines = []
        for segment in segments:
            text = segment.text.strip()
            if text:
                lines.append(f"[{format_ts(segment.start)}] {text}")
    except Exception as exc:
        hint = ""
        if device == "cuda":
            hint = "CUDA 模式需要 NVIDIA CUDA 运行库（cuBLAS/cuDNN）；请运行 安装CUDA依赖.bat"
        fail("local_transcription_failed", error=str(exc), model=model_name, hint=hint)
    if not lines:
        fail("empty_transcript", audio=str(audio), model=model_name)
    out_dir.mkdir(parents=True, exist_ok=True)
    transcript = out_dir / (audio.stem + ".txt")
    transcript.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return transcript, info


def main():
    import io as _io
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = _io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True)
    if hasattr(sys.stderr, "buffer"):
        sys.stderr = _io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace", line_buffering=True)
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio", required=True)
    ap.add_argument("--output-dir", default="")
    args = ap.parse_args()
    load_dotenv()
    dirs = ensure_dirs()
    audio = Path(args.audio)
    if not audio.is_absolute():
        audio = (ROOT / audio).resolve()
    if not audio.exists():
        fail("audio_not_found", audio=str(audio))
    out_dir = Path(args.output_dir) if args.output_dir else dirs["transcripts"]
    if not out_dir.is_absolute():
        out_dir = (ROOT / out_dir).resolve()
    transcript, info = transcribe(audio, out_dir)
    text = transcript.read_text(encoding="utf-8")
    print(json.dumps({"ok": True, "audio": str(audio), "transcript_path": str(transcript),
                      "chars": len(text), "language": getattr(info, "language", "zh"),
                      "duration_s": getattr(info, "duration", None),
                      "backend": "faster-whisper"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
