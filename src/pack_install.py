"""Pack readiness: models, Piper, ComfyUI/AllTalk folders."""

from __future__ import annotations

import os
import shutil

import config
from src.plugins import is_enabled
from src.services import check_piper


def _exists(path: str) -> bool:
    return bool(path) and os.path.isfile(path)


def _isdir(path: str) -> bool:
    return bool(path) and os.path.isdir(path)


def llama_ok() -> bool:
    try:
        import llama_cpp  # noqa: F401
        return True
    except Exception:
        return False


def model_rows() -> list[dict]:
    rows = []
    for key, spec in (config.MODEL_REGISTRY or {}).items():
        path = spec.get("path") or ""
        present = _exists(path)
        rows.append({
            "key": key,
            "name": key,
            "path": path,
            "filename": os.path.basename(path),
            "present": present,
            "bytes": os.path.getsize(path) if present else 0,
        })
    return rows


def models_ready() -> bool:
    rows = model_rows()
    return bool(rows) and all(r["present"] for r in rows)


def guess_comfy_dirs() -> list[str]:
    home = os.path.expanduser("~")
    candidates = [
        os.path.join(home, "Documents", "ComfyUI"),
        os.path.join(home, "ComfyUI"),
        os.path.join(home, "ComfyUI_windows_portable"),
        r"C:\ComfyUI",
        r"C:\ComfyUI_windows_portable",
        r"C:\AI\ComfyUI",
    ]
    found = []
    for folder in candidates:
        if not _isdir(folder):
            continue
        if os.path.isfile(os.path.join(folder, "main.py")) or _find_comfy_script(folder):
            found.append(folder)
    return found


def _find_comfy_script(folder: str) -> str | None:
    for name in ("run_nvidia_gpu.bat", "run_cpu.bat", "run.bat", "main.py"):
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            return path
    return None


def guess_alltalk_dirs() -> list[str]:
    candidates = [
        r"C:\AllTalkV2\alltalk_tts",
        r"C:\alltalk_tts",
        os.path.join(os.path.expanduser("~"), "AllTalkV2", "alltalk_tts"),
    ]
    return [p for p in candidates if _isdir(p)]


def piper_ready(settings) -> bool:
    exe = settings.get("services.piper_exe", config.PIPER_EXE)
    voice = settings.get("services.piper_voice", config.PIPER_VOICE)
    return bool(check_piper(exe, voice).get("ok"))


def summarize(settings) -> dict:
    rows = model_rows()
    present = sum(1 for r in rows if r["present"])
    comfy = (settings.get("services.comfyui_dir") or "").strip()
    if not comfy:
        guessed = guess_comfy_dirs()
        comfy = guessed[0] if guessed else ""
    alltalk = (settings.get("services.alltalk_dir") or "").strip()
    if not alltalk:
        guessed_at = guess_alltalk_dirs()
        alltalk = guessed_at[0] if guessed_at else ""
    return {
        "llm": {
            "enabled": is_enabled(settings, "llm"),
            "llama": llama_ok(),
            "models_present": present,
            "models_total": len(rows),
            "models": rows,
            "ready": llama_ok() and present > 0,
        },
        "image": {
            "enabled": is_enabled(settings, "image"),
            "folder": comfy,
            "folder_ok": _isdir(comfy),
            "guesses": guess_comfy_dirs(),
            "ready": _isdir(comfy),
        },
        "audio": {
            "enabled": is_enabled(settings, "audio"),
            "piper": piper_ready(settings),
            "alltalk_folder": alltalk,
            "alltalk_ok": _isdir(alltalk),
            "guesses": guess_alltalk_dirs(),
            "ready": piper_ready(settings) or _isdir(alltalk),
        },
        "which_comfy": shutil.which("nvidia-smi") is not None,
    }
