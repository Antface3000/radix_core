"""Download Piper (offline TTS) into assets/piper/.

Usage:
    python scripts/setup_piper.py

Fetches the Windows Piper binary and the en_US-amy-medium voice so the app's
offline voice fallback works without any server. Re-running is safe: existing
files are left in place.
"""

import io
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

import config

PIPER_WIN_ZIP = ("https://github.com/rhasspy/piper/releases/download/"
                 "2023.11.14-2/piper_windows_amd64.zip")
VOICE_REPO = "rhasspy/piper-voices"
VOICE_FILES = [
    "en/en_US/amy/medium/en_US-amy-medium.onnx",
    "en/en_US/amy/medium/en_US-amy-medium.onnx.json",
]

PIPER_DIR = os.path.dirname(config.PIPER_EXE)        # assets/piper
ASSETS_DIR = os.path.dirname(PIPER_DIR)              # assets


def _download_binary():
    if os.path.isfile(config.PIPER_EXE):
        print(f"[piper] binary already present: {config.PIPER_EXE}")
        return True
    print(f"[piper] downloading Windows binary from {PIPER_WIN_ZIP} ...")
    try:
        r = requests.get(PIPER_WIN_ZIP, timeout=180)
        r.raise_for_status()
    except requests.RequestException as exc:
        print(f"[piper] ERROR downloading binary: {exc}")
        return False
    # The zip contains a top-level "piper/" folder, so extracting into assets/
    # yields assets/piper/piper.exe alongside its DLLs and espeak-ng-data.
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        zf.extractall(ASSETS_DIR)
    if os.path.isfile(config.PIPER_EXE):
        print(f"[piper] binary ready: {config.PIPER_EXE}")
        return True
    print("[piper] ERROR: piper.exe not found after extraction.")
    return False


def _download_voice():
    if os.path.isfile(config.PIPER_VOICE) and os.path.isfile(config.PIPER_VOICE + ".json"):
        print(f"[piper] voice already present: {config.PIPER_VOICE}")
        return True
    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        print("[piper] huggingface_hub not installed - cannot fetch the voice.")
        return False
    os.makedirs(PIPER_DIR, exist_ok=True)
    print(f"[piper] downloading voice en_US-amy-medium from {VOICE_REPO} ...")
    ok = True
    for rel in VOICE_FILES:
        try:
            src = hf_hub_download(repo_id=VOICE_REPO, filename=rel)
        except Exception as exc:
            print(f"[piper] ERROR downloading {rel}: {exc}")
            ok = False
            continue
        dest = os.path.join(PIPER_DIR, os.path.basename(rel))
        if os.path.abspath(src) != os.path.abspath(dest):
            import shutil
            shutil.copyfile(src, dest)
        print(f"[piper] voice file ready: {dest}")
    return ok


def main():
    os.makedirs(PIPER_DIR, exist_ok=True)
    bin_ok = _download_binary()
    voice_ok = _download_voice()
    print("-" * 60)
    if bin_ok and voice_ok:
        print("[piper] setup complete - offline voice is ready.")
        return 0
    print("[piper] setup incomplete - see messages above. AllTalk can still be "
          "used as the primary voice.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
