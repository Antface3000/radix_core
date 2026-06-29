"""Dead-simple JSON-backed memory for the test bench.

Stores a list of turns per persona key in data/memory.json:

    {
      "lore_curator": [
        {"user": "...", "response": "...", "ts": 1700000000.0},
        ...
      ]
    }

This is intentionally dumb. The Chat Historian persona is the intended place to
later summarize these into compact "Memory Blobs"; for now we just keep recent
raw turns and inject a few back as context.
"""

import json
import os
import time


class Memory:
    def __init__(self, path):
        self.path = path
        self.data = self._load()

    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data if isinstance(data, dict) else {}
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def _save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)

    def append(self, persona_key, user, response):
        self.data.setdefault(persona_key, []).append(
            {"user": user, "response": response, "ts": time.time()}
        )
        self._save()

    def recent(self, persona_key, n=4):
        """Return the last n turns for a persona (oldest -> newest)."""
        if n <= 0:
            return []
        return self.data.get(persona_key, [])[-n:]

    def clear(self, persona_key=None):
        """Clear one persona's memory, or everything if persona_key is None."""
        if persona_key is None:
            self.data = {}
        else:
            self.data.pop(persona_key, None)
        self._save()
