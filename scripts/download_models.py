"""Download the three Radix Core GGUF models into models/.

Usage:
    pip install huggingface_hub
    python scripts/download_models.py

This auto-detects the Q4_K_M file in each repo (filenames vary between GGUF
publishers) and saves it under models/ with the clean name config.py expects.
Each model is ~5GB; total ~15GB. They download once and are cached by HF too.

If a repo/quant isn't found, the script prints the available .gguf files so you
can edit the DOWNLOADS list below.
"""

import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from huggingface_hub import hf_hub_download, list_repo_files
except ImportError:
    sys.exit("huggingface_hub not installed. Run: pip install huggingface_hub")

import config

MODELS_DIR = config.MODELS_DIR


def _target(model_key):
    """The exact local filename config.py expects for a model tier."""
    return os.path.basename(config.MODEL_REGISTRY[model_key]["path"])


# repo_id + desired quant per tier. The local `target` filename is pulled
# straight from config.MODEL_REGISTRY so the two can never drift apart.
DOWNLOADS = [
    {
        "repo_id": "unsloth/DeepSeek-R1-0528-Qwen3-8B-GGUF",
        "quant": "Q4_K_M",
        "target": _target("architect"),
    },
    {
        "repo_id": "Qwen/Qwen3-8B-GGUF",
        "quant": "Q4_K_M",
        "target": _target("operator"),
    },
    {
        "repo_id": "bartowski/L3-8B-Stheno-v3.2-GGUF",
        "quant": "Q4_K_M",
        "target": _target("flavor"),
    },
]


def find_quant_file(repo_id, quant):
    files = [f for f in list_repo_files(repo_id) if f.lower().endswith(".gguf")]
    matches = [f for f in files if quant.lower() in f.lower()]
    return matches, files


def main():
    os.makedirs(MODELS_DIR, exist_ok=True)
    for item in DOWNLOADS:
        target_path = os.path.join(MODELS_DIR, item["target"])
        if os.path.exists(target_path):
            print(f"[skip] {item['target']} already present.")
            continue

        print(f"[lookup] {item['repo_id']} ({item['quant']}) ...")
        try:
            matches, all_files = find_quant_file(item["repo_id"], item["quant"])
        except Exception as exc:
            print(f"  ! could not list repo: {exc}")
            continue

        if not matches:
            print(f"  ! no '{item['quant']}' .gguf found. Available:")
            for f in all_files:
                print(f"      {f}")
            continue

        remote = matches[0]
        print(f"[download] {remote}  ->  models/{item['target']}")
        cached = hf_hub_download(repo_id=item["repo_id"], filename=remote)
        shutil.copyfile(cached, target_path)
        print(f"  done: {target_path}")

    print("\nAll done. Launch the bench with:  python run.py")


if __name__ == "__main__":
    main()
