"""Install studio Python deps, then llama-cpp-python from a prebuilt wheel.

Never fails the whole app install if the LLM wheel is missing — writing studio
still launches. Used by install.bat and run.py.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIREMENTS = ROOT / "requirements.txt"
WHEEL_BASE = "https://abetlen.github.io/llama-cpp-python/whl"


def _pip(python: str, *args: str) -> bool:
    cmd = [python, "-m", "pip", *args]
    try:
        subprocess.check_call(cmd)
        return True
    except subprocess.CalledProcessError:
        return False


def detect_cuda_tag() -> str | None:
    """Return cu124 / cu121 / cu118 or None if no NVIDIA driver."""
    try:
        out = subprocess.check_output(
            ["nvidia-smi"], text=True, timeout=8, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    match = re.search(r"CUDA Version:\s*(\d+)\.(\d+)", out)
    if not match:
        return "cu124"
    major, minor = int(match.group(1)), int(match.group(2))
    if major > 12 or (major == 12 and minor >= 4):
        return "cu124"
    if major == 12:
        return "cu121"
    if major == 11:
        return "cu118"
    return "cu124"


def llama_installed(python: str | None = None) -> bool:
    py = python or sys.executable
    try:
        r = subprocess.run(
            [py, "-c", "import llama_cpp"],
            capture_output=True, timeout=20)
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def install_studio(python: str | None = None) -> bool:
    py = python or sys.executable
    print("[setup] Installing studio packages (PySide6, etc.) …", flush=True)
    if not _pip(py, "install", "--upgrade", "pip"):
        return False
    return _pip(py, "install", "-r", str(REQUIREMENTS))


def install_llama(python: str | None = None, *, prefer_gpu: bool = True) -> bool:
    """Install a prebuilt llama-cpp-python wheel. Returns True if importable."""
    py = python or sys.executable
    if llama_installed(py):
        print("[setup] llama-cpp-python already installed.", flush=True)
        return True
    tags = []
    if prefer_gpu:
        tag = detect_cuda_tag()
        if tag:
            tags.append(tag)
            if tag == "cu124":
                tags.append("cu121")
    tags.append("cpu")
    for tag in tags:
        url = f"{WHEEL_BASE}/{tag}"
        print(f"[setup] Trying llama-cpp-python wheel ({tag}) …", flush=True)
        ok = _pip(
            py, "install", "--upgrade", "llama-cpp-python",
            "--extra-index-url", url,
        )
        if ok and llama_installed(py):
            print(f"[setup] llama-cpp-python ready ({tag}).", flush=True)
            return True
    print(
        "[setup] Could not install llama-cpp-python. The writing studio still "
        "works. Enable the Local LLM pack later and use Add Ons → Install "
        "inference engine.",
        flush=True,
    )
    return False


def bootstrap(python: str | None = None) -> int:
    py = python or sys.executable
    os.chdir(ROOT)
    if not install_studio(py):
        print("[setup] Studio packages failed. See INSTALL.txt.", flush=True)
        return 1
    install_llama(py)
    return 0


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else sys.executable
    raise SystemExit(bootstrap(target))
