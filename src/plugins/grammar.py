"""Optional grammar plugin loader (Phase E).

Drop a module named `radix_grammar.py` on `plugins.extra_paths` with:

    def check(text: str) -> list[dict]
        # each dict: {"offset": int, "length": int, "message": str, "replacements": [str]}
"""

from __future__ import annotations

import importlib.util
import os

from src.plugins import extra_paths


def load_checker(settings):
    """Return a check(text) callable or None."""
    for root in extra_paths(settings):
        path = os.path.join(root, "radix_grammar.py")
        if not os.path.isfile(path):
            continue
        spec = importlib.util.spec_from_file_location("radix_grammar", path)
        if spec is None or spec.loader is None:
            continue
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        fn = getattr(mod, "check", None)
        if callable(fn):
            return fn
    return None
