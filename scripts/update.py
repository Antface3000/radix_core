"""Apply Radix Core updates: git pull or release zip overlay."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
PRESERVE_DIRS = {"data", "models", ".venv", "assets/piper", "assets\\piper"}


def _preserve_rel(path: Path) -> bool:
    rel = path.as_posix()
    for p in PRESERVE_DIRS:
        pnorm = p.replace("\\", "/")
        if rel == pnorm or rel.startswith(pnorm + "/"):
            return True
    return False


def git_update():
    if not (PROJECT_DIR / ".git").is_dir():
        return False, "Not a git install."
    for cmd in (
        ["git", "fetch", "origin", "main"],
        ["git", "pull", "origin", "main"],
    ):
        proc = subprocess.run(cmd, cwd=PROJECT_DIR, capture_output=True, text=True)
        if proc.returncode != 0:
            return False, proc.stderr or proc.stdout or f"git failed: {cmd}"
    return pip_install()


def pip_install():
    venv_py = PROJECT_DIR / ".venv" / "Scripts" / "python.exe"
    if os.name != "nt":
        venv_py = PROJECT_DIR / ".venv" / "bin" / "python"
    if not venv_py.is_file():
        return True, "Git update done (no .venv yet — run Start Radix Core.bat)."
    req = PROJECT_DIR / "requirements.txt"
    if not req.is_file():
        return True, "Git update done."
    proc = subprocess.run(
        [str(venv_py), "-m", "pip", "install", "-r", str(req)],
        cwd=PROJECT_DIR,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return False, proc.stderr or proc.stdout
    return True, "Git update and dependencies installed."


def _github_headers():
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("RADIX_GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _download_release_zip(dest: Path):
    try:
        import requests
    except ImportError:
        return None, "requests not installed"
    slug = "Antface3000/radix_core"
    url = f"https://api.github.com/repos/{slug}/releases/latest"
    resp = requests.get(url, headers=_github_headers(), timeout=60)
    if resp.status_code != 200:
        return None, f"GitHub API HTTP {resp.status_code}"
    data = resp.json()
    assets = data.get("assets") or []
    zip_asset = None
    for a in assets:
        if a.get("name", "").endswith(".zip"):
            zip_asset = a
            break
    if not zip_asset:
        return None, "No zip asset on latest release."
    dl = requests.get(
        zip_asset["browser_download_url"],
        headers=_github_headers(),
        timeout=300,
        stream=True,
    )
    if dl.status_code != 200:
        return None, f"Download HTTP {dl.status_code}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with open(dest, "wb") as fh:
        for chunk in dl.iter_content(65536):
            fh.write(chunk)
    return dest, data.get("tag_name", "")


def zip_overlay():
    with tempfile.TemporaryDirectory() as tmp:
        zip_path = Path(tmp) / "release.zip"
        result, tag_or_err = _download_release_zip(zip_path)
        if result is None:
            return False, tag_or_err
        extract = Path(tmp) / "extract"
        extract.mkdir()
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(extract)
        # git archive produces flat tree; release zip may have one top folder
        roots = list(extract.iterdir())
        src_root = roots[0] if len(roots) == 1 and roots[0].is_dir() else extract
        copied = 0
        for root, dirs, files in os.walk(src_root):
            rel_root = Path(root).relative_to(src_root)
            if _preserve_rel(rel_root):
                dirs.clear()
                continue
            for d in list(dirs):
                rel = (rel_root / d).as_posix()
                if _preserve_rel(Path(rel)):
                    dirs.remove(d)
            dest_dir = PROJECT_DIR / rel_root
            dest_dir.mkdir(parents=True, exist_ok=True)
            for fname in files:
                rel_file = rel_root / fname
                if _preserve_rel(rel_file):
                    continue
                shutil.copy2(Path(root) / fname, dest_dir / fname)
                copied += 1
        ok, msg = pip_install()
        if not ok:
            return False, msg
        return True, f"Installed {copied} files from {tag_or_err}. {msg}"


def open_releases_page():
    url = "https://github.com/Antface3000/radix_core/releases/latest"
    if sys.platform == "win32":
        os.startfile(url)  # noqa: S606
    else:
        subprocess.run(["xdg-open", url], check=False)


def main():
    parser = argparse.ArgumentParser(description="Update Radix Core")
    parser.add_argument("--zip", action="store_true", help="Zip overlay from GitHub release")
    args = parser.parse_args()
    os.chdir(PROJECT_DIR)
    if args.zip or not (PROJECT_DIR / ".git").is_dir():
        ok, msg = zip_overlay()
        if not ok:
            print(f"Zip update failed: {msg}")
            print("Download the latest release manually:")
            print("  https://github.com/Antface3000/radix_core/releases/latest")
            if os.environ.get("RADIX_GITHUB_TOKEN"):
                print("(Token was set but download still failed.)")
            else:
                print("For a private repo, set RADIX_GITHUB_TOKEN and retry.")
            open_releases_page()
            return 1
    else:
        ok, msg = git_update()
        if not ok:
            print(f"Git update failed: {msg}")
            return 1
    print(msg)
    print("\nClose Radix Core if it is open, then double-click Start Radix Core.bat.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
