"""Maintainer release helper: bump VERSION, tag, and create GitHub release."""

import argparse
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
VERSION_FILE = PROJECT_DIR / "VERSION"
VERSION_JSON = PROJECT_DIR / "version.json"
CHANGELOG = PROJECT_DIR / "CHANGELOG.txt"


def parse_version(text):
    text = text.strip().lstrip("v")
    parts = re.findall(r"\d+", text)
    while len(parts) < 3:
        parts.append("0")
    return tuple(int(p) for p in parts[:3])


def format_version(t):
    return f"{t[0]}.{t[1]}.{t[2]}"


def bump(current, kind):
    major, minor, patch = parse_version(current)
    if kind == "major":
        return format_version((major + 1, 0, 0))
    if kind == "minor":
        return format_version((major, minor + 1, 0))
    return format_version((major, minor, patch + 1))


def read_version():
    return VERSION_FILE.read_text(encoding="utf-8").strip()


def write_version(ver):
    VERSION_FILE.write_text(ver + "\n", encoding="utf-8")
    try:
        data = json.loads(VERSION_JSON.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {"repo": "Antface3000/radix_core"}
    data["version"] = ver
    data["released"] = date.today().isoformat()
    VERSION_JSON.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def move_changelog(ver):
    text = CHANGELOG.read_text(encoding="utf-8")
    today = date.today().isoformat()
    header = f"[{ver}] - {today}"
    if header in text:
        return
    unreleased = re.search(
        r"\[UNRELEASED\]\s*\n=+\s*\n(.*?)(?=\n\[|\Z)",
        text,
        re.DOTALL,
    )
    block = unreleased.group(1).strip() if unreleased else ""
    new_section = f"\n{header}\n{'=' * len(header)}\n\n{block}\n" if block else f"\n{header}\n{'=' * len(header)}\n\n"
    text = re.sub(
        r"(\[UNRELEASED\]\s*\n=+\s*\n)",
        r"\1\n",
        text,
        count=1,
    )
    text = text.replace(
        "[UNRELEASED]\n============\n\n",
        f"[UNRELEASED]\n============\n{new_section}",
        1,
    )
    CHANGELOG.write_text(text, encoding="utf-8")


def build_zip(ver):
    out = PROJECT_DIR / f"radix_core-{ver}.zip"
    if out.exists():
        out.unlink()
    subprocess.check_call(
        ["git", "archive", "--format=zip", "-o", str(out), "HEAD"],
        cwd=PROJECT_DIR,
    )
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("bump", nargs="?", choices=("patch", "minor", "major"))
    parser.add_argument("--set", dest="set_ver", metavar="X.Y.Z")
    parser.add_argument("--no-tag", action="store_true")
    parser.add_argument("--no-release", action="store_true")
    args = parser.parse_args()

    current = read_version()
    if args.set_ver:
        new_ver = args.set_ver.lstrip("v")
    elif args.bump:
        new_ver = bump(current, args.bump)
    else:
        parser.error("Provide patch|minor|major or --set X.Y.Z")

    print(f"Bumping {current} -> {new_ver}")
    write_version(new_ver)
    move_changelog(new_ver)

    subprocess.check_call(["git", "add", "VERSION", "version.json", "CHANGELOG.txt"], cwd=PROJECT_DIR)
    print(f"\nSuggested commit:\n  git commit -m \"Release v{new_ver}\"")
    print(f"  git tag -a v{new_ver} -m \"Radix Core v{new_ver}\"")

    if args.no_tag:
        return 0

    tag = f"v{new_ver}"
    subprocess.check_call(["git", "tag", "-a", tag, "-m", f"Radix Core {tag}"], cwd=PROJECT_DIR)
    print(f"Created tag {tag}")

    if args.no_release:
        return 0

    zip_path = build_zip(new_ver)
    notes = CHANGELOG.read_text(encoding="utf-8")
    match = re.search(rf"\[{re.escape(new_ver)}\].*?(?=\n\[|\Z)", notes, re.DOTALL)
    notes_body = match.group(0) if match else f"Radix Core {tag}"
    notes_file = PROJECT_DIR / f".release-notes-{new_ver}.txt"
    notes_file.write_text(notes_body, encoding="utf-8")
    try:
        subprocess.check_call(
            ["gh", "release", "create", tag,
             str(zip_path),
             "--title", f"Radix Core {tag}",
             "--notes-file", str(notes_file)],
            cwd=PROJECT_DIR,
        )
        print(f"GitHub release {tag} created with {zip_path.name}")
    finally:
        notes_file.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
