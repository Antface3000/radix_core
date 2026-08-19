"""Download GGUF models into models/ (Hugging Face).

CLI:
    python scripts/download_models.py
    python scripts/download_models.py --keys architect
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config

MODELS_DIR = config.MODELS_DIR


def _target(model_key: str) -> str:
    return os.path.basename(config.MODEL_REGISTRY[model_key]["path"])


DOWNLOADS = [
    {
        "key": "architect",
        "repo_id": "unsloth/DeepSeek-R1-0528-Qwen3-8B-GGUF",
        "quant": "Q4_K_M",
        "target": _target("architect"),
        "label": "Architect (writing / specialists)",
    },
    {
        "key": "operator",
        "repo_id": "Qwen/Qwen3-8B-GGUF",
        "quant": "Q4_K_M",
        "target": _target("operator"),
        "label": "Operator (Team planner)",
    },
    {
        "key": "flavor",
        "repo_id": "bartowski/L3-8B-Stheno-v3.2-GGUF",
        "quant": "Q4_K_M",
        "target": _target("flavor"),
        "label": "Flavor (critics / dialect)",
    },
]


def find_quant_file(repo_id, quant):
    from huggingface_hub import list_repo_files
    files = [f for f in list_repo_files(repo_id) if f.lower().endswith(".gguf")]
    matches = [f for f in files if quant.lower() in f.lower()]
    return matches, files


def download_one(item: dict, log=print) -> bool:
    os.makedirs(MODELS_DIR, exist_ok=True)
    target_path = os.path.join(MODELS_DIR, item["target"])
    if os.path.exists(target_path):
        log(f"[skip] {item['target']} already present.")
        return True
    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        log("huggingface_hub is missing. Re-run install.bat.")
        return False
    log(f"[lookup] {item['repo_id']} ({item['quant']}) …")
    try:
        matches, all_files = find_quant_file(item["repo_id"], item["quant"])
    except Exception as exc:
        log(f"  ! could not list repo: {exc}")
        return False
    if not matches:
        log(f"  ! no '{item['quant']}' .gguf found. Available:")
        for name in all_files:
            log(f"      {name}")
        return False
    remote = matches[0]
    log(f"[download] {remote}  →  models/{item['target']}")
    try:
        cached = hf_hub_download(repo_id=item["repo_id"], filename=remote)
        shutil.copyfile(cached, target_path)
    except Exception as exc:
        log(f"  ! download failed: {exc}")
        return False
    log(f"  done: {target_path}")
    return True


def download_keys(keys: list[str] | None = None, log=print) -> bool:
    wanted = set(keys) if keys else {d["key"] for d in DOWNLOADS}
    ok = True
    for item in DOWNLOADS:
        if item["key"] not in wanted:
            continue
        if not download_one(item, log=log):
            ok = False
    return ok


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Download Radix GGUF models.")
    parser.add_argument(
        "--keys",
        help="Comma-separated: architect,operator,flavor (default: all)",
    )
    args = parser.parse_args(argv)
    keys = None
    if args.keys:
        keys = [k.strip() for k in args.keys.split(",") if k.strip()]
    return 0 if download_keys(keys) else 1


if __name__ == "__main__":
    raise SystemExit(main())
