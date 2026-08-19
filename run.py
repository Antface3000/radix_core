"""Launcher for the Radix Core test bench.

Run from anywhere:  python run.py

On the first run this bootstraps a local virtual environment in ``.venv`` and
installs everything from ``requirements.txt``, then relaunches itself inside
that environment. Later runs skip pip when ``.venv/.deps-installed`` matches
the current requirements file (content hash).
"""

import hashlib
import os
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
VENV_DIR = PROJECT_DIR / ".venv"
REQUIREMENTS = PROJECT_DIR / "requirements.txt"
DEPS_STAMP = VENV_DIR / ".deps-installed"

# Core imports used to detect a usable venv without running pip every launch.
# llama_cpp is optional until the Local LLM pack is installed.
_IMPORT_PROBE = (
    "import importlib.util as u\n"
    "mods = ('PySide6', 'PIL', 'requests', 'websocket')\n"
    "raise SystemExit(0 if all(u.find_spec(m) for m in mods) else 1)\n"
)


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


def _requirements_fingerprint() -> str:
    if not REQUIREMENTS.exists():
        return ""
    return hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()


def _read_stamp() -> str:
    try:
        return DEPS_STAMP.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _write_stamp() -> None:
    fp = _requirements_fingerprint()
    if fp:
        DEPS_STAMP.parent.mkdir(parents=True, exist_ok=True)
        DEPS_STAMP.write_text(fp, encoding="utf-8")


def _dependencies_stale() -> bool:
    """True when requirements.txt changed since last successful install."""
    fp = _requirements_fingerprint()
    if not fp:
        return False
    return _read_stamp() != fp


def _imports_ok(python: Path) -> bool:
    try:
        result = subprocess.run(
            [str(python), "-c", _IMPORT_PROBE],
            capture_output=True,
            timeout=45,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _pip_install(python: Path) -> None:
    print("[setup] Installing dependencies (first run can take a few minutes) ...",
          flush=True)
    script = PROJECT_DIR / "scripts" / "bootstrap_deps.py"
    try:
        subprocess.check_call([str(python), str(script), str(python)])
    except subprocess.CalledProcessError:
        sys.exit(
            "[setup] Studio packages failed to install. See INSTALL.txt."
        )
    _write_stamp()
    print("[setup] Dependencies OK.", flush=True)


def _ensure_deps_current(python: Path) -> None:
    """Install only when imports fail or requirements.txt changed."""
    if not REQUIREMENTS.exists():
        return
    if _imports_ok(python) and not _dependencies_stale():
        if not DEPS_STAMP.exists():
            _write_stamp()
        return
    _pip_install(python)


def _ensure_venv() -> None:
    """Create the venv + install deps if needed, then re-exec inside it.

    If we're already running inside ``.venv`` this only verifies the stamp.
    """
    if _in_project_venv():
        _ensure_deps_current(Path(sys.executable))
        return

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

    _ensure_deps_current(venv_py)

    env = {**os.environ, "RADIX_BOOTSTRAPPED": "1"}
    result = subprocess.run(
        [str(venv_py), str(PROJECT_DIR / "run.py"), *sys.argv[1:]], env=env
    )
    sys.exit(result.returncode)


def main():
    sys.path.insert(0, str(PROJECT_DIR))
    from src.logutil import setup_logging
    setup_logging(verbose=("--verbose" in sys.argv or "-v" in sys.argv))
    from ui_qt.app import main as qt_main  # noqa: E402

    sys.exit(qt_main())


if __name__ == "__main__":
    _ensure_venv()
    if "--bootstrap-only" in sys.argv:
        if _in_project_venv():
            _ensure_deps_current(Path(sys.executable))
        print("[setup] Environment ready.")
        sys.exit(0)
    main()
