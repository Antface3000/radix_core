"""Update check and apply helpers for Radix Core.

Supports git installs (fetch + compare origin/main:VERSION) and zip installs
(GitHub Releases API, optional RADIX_GITHUB_TOKEN for private repos).
"""

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import Optional

import config

try:
    import requests
except ImportError:
    requests = None


@dataclass
class UpdateResult:
    available: bool
    local_version: str
    remote_version: str
    summary: str
    method: str  # "git" | "release" | "none"
    releases_url: str = config.RELEASES_URL
    error: str = ""


def parse_version(text):
    """Return (major, minor, patch) tuple; non-numeric parts become 0."""
    text = (text or "").strip().lstrip("v")
    parts = re.findall(r"\d+", text)
    while len(parts) < 3:
        parts.append("0")
    return tuple(int(p) for p in parts[:3])


def version_gt(a, b):
    return parse_version(a) > parse_version(b)


def local_version():
    return config.APP_VERSION


def is_git_install():
    return os.path.isdir(os.path.join(config.BASE_DIR, ".git"))


def _run_git(args, timeout=8):
    try:
        proc = subprocess.run(
            ["git"] + args,
            cwd=config.BASE_DIR,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        if proc.returncode != 0:
            return None
        return proc.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return None


def _check_git(timeout=8):
    if not is_git_install():
        return None
    _run_git(["fetch", "origin", "main"], timeout=timeout)
    remote = _run_git(["show", "origin/main:VERSION"], timeout=timeout)
    if not remote:
        return None
    local = local_version()
    return UpdateResult(
        available=version_gt(remote, local),
        local_version=local,
        remote_version=remote,
        summary=f"Remote main is at v{remote}.",
        method="git",
    )


def _github_headers():
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("RADIX_GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _check_release(timeout=8):
    if requests is None:
        return UpdateResult(
            available=False,
            local_version=local_version(),
            remote_version="",
            summary="",
            method="release",
            error="requests not installed",
        )
    url = f"https://api.github.com/repos/{config.REPO_SLUG}/releases/latest"
    try:
        resp = requests.get(url, headers=_github_headers(), timeout=timeout)
    except requests.RequestException as exc:
        return UpdateResult(
            available=False,
            local_version=local_version(),
            remote_version="",
            summary="",
            method="release",
            error=str(exc),
        )
    if resp.status_code in (401, 403, 404):
        return UpdateResult(
            available=False,
            local_version=local_version(),
            remote_version="",
            summary="",
            method="release",
            error=f"HTTP {resp.status_code} (private repo may need RADIX_GITHUB_TOKEN)",
        )
    resp.raise_for_status()
    data = resp.json()
    tag = (data.get("tag_name") or "").lstrip("v")
    body = (data.get("body") or "").strip()
    summary = body.splitlines()[0][:200] if body else f"Release v{tag}."
    local = local_version()
    return UpdateResult(
        available=bool(tag) and version_gt(tag, local),
        local_version=local,
        remote_version=tag,
        summary=summary,
        method="release",
    )


def check_for_update(timeout=8, prefer_git=True):
    """Return UpdateResult or None if check could not run at all."""
    if prefer_git and is_git_install():
        result = _check_git(timeout=timeout)
        if result is not None:
            return result
    return _check_release(timeout=timeout)


def apply_update(parent_dir=None):
    """Launch update.bat detached. Returns (ok, message)."""
    root = parent_dir or config.BASE_DIR
    bat = os.path.join(root, "update.bat")
    if not os.path.isfile(bat):
        return False, f"update.bat not found in {root}"
    try:
        if sys.platform == "win32":
            subprocess.Popen(
                ["cmd", "/c", "start", "", bat],
                cwd=root,
                close_fds=True,
            )
        else:
            subprocess.Popen([bat], cwd=root, close_fds=True)
    except OSError as exc:
        return False, str(exc)
    return True, "Updater started. Close Radix Core, then follow the update window."


def read_version_json():
    try:
        with open(config.VERSION_JSON_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}
