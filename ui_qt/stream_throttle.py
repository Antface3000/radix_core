"""Coalesce rapid stream deltas before updating Qt widgets."""

from __future__ import annotations

from PySide6.QtCore import QObject, QTimer


class StreamThrottler(QObject):
    """Buffer text chunks and flush to the UI at a fixed interval."""

    def __init__(self, flush_fn, interval_ms: int = 80, parent=None):
        super().__init__(parent)
        self._flush_fn = flush_fn
        self._interval_ms = interval_ms
        self._buffer: list[str] = []
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._flush)

    def append(self, text: str) -> None:
        if not text:
            return
        self._buffer.append(text)
        if not self._timer.isActive():
            self._timer.start(self._interval_ms)

    def flush_now(self) -> None:
        self._timer.stop()
        self._flush()

    def _flush(self) -> None:
        if not self._buffer:
            return
        chunk = "".join(self._buffer)
        self._buffer.clear()
        self._flush_fn(chunk)
