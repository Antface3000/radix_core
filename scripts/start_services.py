"""Pre-launch service orchestration for Radix Core.

Run by "Start Radix Core.bat" before the app window opens (and usable on its
own from an activated venv):

    python scripts/start_services.py

It:
  - starts AllTalk from its install folder (auto-start, in its own console),
  - probes ComfyUI and reports whether it's running (never auto-starts it),
  - reports whether Piper (offline voice) is ready.

Everything here is best-effort and non-fatal: whatever the outcome, it exits 0
so the app still launches. Service health is also re-checked live in-app.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from src import service_launch, services
from src.settings import Settings

# Sensible default if the AllTalk folder was never configured.
DEFAULT_ALLTALK_DIR = r"C:\AllTalkV2\alltalk_tts"


def _line(char="-", n=60):
    print(char * n)


def _ensure_alltalk_dir(settings):
    """Make sure alltalk_dir points at a real folder; fall back to the default."""
    current = (settings.get("services.alltalk_dir", config.ALLTALK_DIR) or "").strip()
    if current and os.path.isdir(current):
        return current
    if os.path.isdir(DEFAULT_ALLTALK_DIR):
        settings.set("services.alltalk_dir", DEFAULT_ALLTALK_DIR)
        print(f"[setup] AllTalk folder set to {DEFAULT_ALLTALK_DIR}")
        return DEFAULT_ALLTALK_DIR
    return current


def _start_alltalk(settings):
    url = settings.get("services.alltalk_url", config.ALLTALK_URL)
    if services.check_alltalk(url)["ok"]:
        print("[AllTalk] already running - skipping startup.")
        return True
    folder = _ensure_alltalk_dir(settings)
    if not folder:
        print("[AllTalk] no install folder set - skipping (set it in Setup).")
        return False
    print("[AllTalk] Starting (this can take a minute while it loads)...")
    res = service_launch.launch_alltalk(settings)
    status = "OK" if res.get("ok") else "DOWN"
    print(f"[AllTalk] {status}: {res.get('detail', '')}")
    return bool(res.get("ok"))


def _probe_comfyui(settings):
    url = settings.get("services.comfyui_url", config.COMFYUI_URL)
    res = services.check_comfyui(url)
    if res.get("ok"):
        print(f"[ComfyUI] running at {url} ({res.get('detail', '')}).")
        return True
    print(f"[ComfyUI] not running at {url} - start it to enable image generation.")
    return False


def _report_piper(settings):
    exe = settings.get("services.piper_exe", config.PIPER_EXE)
    voice = settings.get("services.piper_voice", config.PIPER_VOICE)
    res = services.check_piper(exe, voice)
    if res.get("ok"):
        print("[Piper] installed (offline voice ready).")
        return True
    print(f"[Piper] not ready: {res.get('detail', '')} "
          f"(drop piper.exe + a .onnx voice into {os.path.dirname(exe)}).")
    return False


def main():
    settings = Settings()
    _line("=")
    print(" Radix Core - starting services")
    _line("=")

    alltalk_ok = _start_alltalk(settings)
    comfy_ok = _probe_comfyui(settings)
    piper_ok = _report_piper(settings)

    _line()
    print("Summary:  AllTalk={}  ComfyUI={}  Piper={}".format(
        "up" if alltalk_ok else "down",
        "up" if comfy_ok else "down",
        "ready" if piper_ok else "missing"))
    print("Opening Radix Core...")
    _line()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # never block the app launch
        print(f"[start_services] non-fatal error: {exc}")
        sys.exit(0)
