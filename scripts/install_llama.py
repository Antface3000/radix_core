"""Install only the llama-cpp-python wheel (CPU or CUDA)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bootstrap_deps import install_llama

if __name__ == "__main__":
    raise SystemExit(0 if install_llama() else 1)
