"""Cooperative cancellation token for streaming inference."""

from __future__ import annotations

import threading


class CancelToken:
    def __init__(self):
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    def clear(self) -> None:
        self._event.clear()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def check(self) -> None:
        if self.is_cancelled:
            from src.engine import RunCancelled
            raise RunCancelled()
