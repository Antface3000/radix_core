"""Human-in-the-loop pause and resume."""

from __future__ import annotations

import json
import os
import threading
from typing import Any, Callable

from src import projects


class HitlController:
    """Serialize paused sessions and block until UI provides input."""

    def __init__(self, project_id: str):
        self.project_id = project_id
        self._lock = threading.Lock()
        self._paused_path = projects.project_paths(project_id)["paused_session"]

    def save_paused(self, session: dict[str, Any]) -> None:
        os.makedirs(os.path.dirname(self._paused_path) or ".", exist_ok=True)
        with open(self._paused_path, "w", encoding="utf-8") as fh:
            json.dump(session, fh, indent=2, ensure_ascii=False)

    def load_paused(self) -> dict[str, Any] | None:
        if not os.path.exists(self._paused_path):
            return None
        try:
            with open(self._paused_path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, json.JSONDecodeError):
            return None

    def clear_paused(self) -> None:
        if os.path.exists(self._paused_path):
            os.remove(self._paused_path)

    def request_input(
        self,
        reason: str,
        context: dict[str, Any],
        ask_user: Callable[[str], str] | None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> str | None:
        """Block until user responds or cancel is requested."""
        self.save_paused({"reason": reason, "context": context})
        if not callable(ask_user):
            return None
        answer = ask_user(reason)
        if callable(cancel_check) and cancel_check():
            self.clear_paused()
            return None
        self.clear_paused()
        return answer

    def has_pending(self) -> bool:
        return self.load_paused() is not None
