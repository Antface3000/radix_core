"""Download Hermes-3-Llama-3.1-8B Q4_K_M for the Architect role."""

from __future__ import annotations

import os
import sys

from huggingface_hub import hf_hub_download

REPO = "bartowski/Hermes-3-Llama-3.1-8B-GGUF"
FILENAME = "Hermes-3-Llama-3.1-8B-Q4_K_M.gguf"


def main() -> int:
    dest_dir = os.path.dirname(os.path.abspath(__file__))
    print(f"Downloading {FILENAME}")
    print(f"From: {REPO}")
    print(f"To:   {dest_dir}")
    path = hf_hub_download(
        repo_id=REPO,
        filename=FILENAME,
        local_dir=dest_dir,
        local_dir_use_symlinks=False,
    )
    size_gb = os.path.getsize(path) / (1024**3)
    print(f"Done: {path}")
    print(f"Size: {size_gb:.2f} GB")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        raise SystemExit(130) from None
