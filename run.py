"""Launcher for the Radix Core test bench.

Run from anywhere:  python run.py

On the first run this bootstraps a local virtual environment in ``.venv`` and
installs everything from ``requirements.txt``, then relaunches itself inside
that environment. Every later run sees the venv already exists and starts the
app immediately. You never have to create or activate a venv by hand.
"""

import os
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
VENV_DIR = PROJECT_DIR / ".venv"
REQUIREMENTS = PROJECT_DIR / "requirements.txt"
DEPS_STAMP = VENV_DIR / ".deps-installed"


def _venv_python() -> Path:
    """Path to the interpreter inside the project's venv."""
    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def _in_project_venv() -> bool:
    """True when the current interpreter is the one inside ``.venv``."""
    try:
        return os.path.normcase(Path(sys.prefix).resolve()) == os.path.normcase(
            VENV_DIR.resolve()
        )
    except OSError:
        return False


def _dependencies_stale() -> bool:
    """Whether deps need (re)installing: never installed, or requirements changed."""
    if not DEPS_STAMP.exists():
        return True
    if REQUIREMENTS.exists():
        return DEPS_STAMP.stat().st_mtime < REQUIREMENTS.stat().st_mtime
    return False


def _ensure_venv() -> None:
    """Create the venv + install deps if needed, then re-exec inside it.

    If we're already running inside ``.venv`` this is a no-op, so day-to-day
    launches pay no setup cost.
    """
    if _in_project_venv():
        return

    # Guard against an impossible relaunch loop (e.g. a broken venv).
    if os.environ.get("RADIX_BOOTSTRAPPED") == "1":
        return

    venv_py = _venv_python()

    if not venv_py.exists():
        print("[setup] Creating virtual environment in .venv ...", flush=True)
        try:
            subprocess.check_call([sys.executable, "-m", "venv", str(VENV_DIR)])
        except subprocess.CalledProcessError:
            sys.exit(
                "[setup] Failed to create the virtual environment. "
                "Make sure Python 3.10+ is installed and on PATH."
            )

    if _dependencies_stale() and REQUIREMENTS.exists():
        print(
            "[setup] Installing dependencies (first run can take a few minutes) ...",
            flush=True,
        )
        try:
            subprocess.check_call([str(venv_py), "-m", "pip", "install", "--upgrade", "pip"])
            subprocess.check_call(
                [str(venv_py), "-m", "pip", "install", "-r", str(REQUIREMENTS)]
            )
        except subprocess.CalledProcessError:
            sys.exit(
                "[setup] A dependency failed to install (often llama-cpp-python "
                "needing a prebuilt wheel). See INSTALL.txt, 'GPU acceleration'."
            )
        DEPS_STAMP.write_text("ok", encoding="utf-8")

    # Hand off to the venv interpreter and exit with its return code.
    env = {**os.environ, "RADIX_BOOTSTRAPPED": "1"}
    result = subprocess.run(
        [str(venv_py), str(PROJECT_DIR / "run.py"), *sys.argv[1:]], env=env
    )
    sys.exit(result.returncode)


def main():
    sys.path.insert(0, str(PROJECT_DIR))
    from gui.main import RadixApp  # noqa: E402  (imported after venv bootstrap)

    app = RadixApp()
    app.mainloop()


if __name__ == "__main__":
    _ensure_venv()
    # Used by the launcher .bat to build the venv without opening the GUI, so it
    # can then run the pre-launch service script with the venv's Python.
    if "--bootstrap-only" in sys.argv:
        print("[setup] Environment ready.")
        sys.exit(0)
    main()
