"""Keep pop-out windows on the usable screen (taskbar, DPI, multi-monitor)."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect
from PySide6.QtWidgets import QApplication, QWidget

from src.geom import MARGIN, MIN_H, MIN_W, clamp_geometry

__all__ = [
    "MARGIN", "MIN_W", "MIN_H", "clamp_geometry",
    "available_rect", "max_window_size", "max_content_width", "fit_widget",
]


def available_rect(widget: QWidget | None = None) -> QRect:
    screen = None
    if widget is not None:
        screen = widget.screen()
        if screen is None:
            parent = widget.parentWidget()
            if parent is not None:
                screen = parent.screen()
        if screen is None:
            screen = widget.window().screen()
    app = QApplication.instance()
    if screen is None and app is not None:
        screen = app.primaryScreen()
    if screen is None:
        return QRect(0, 0, 1280, 720)
    return screen.availableGeometry()


def _screen_at(x: int, y: int) -> QRect | None:
    app = QApplication.instance()
    if app is None:
        return None
    pt = QPoint(int(x), int(y))
    for screen in app.screens():
        geo = screen.availableGeometry()
        if geo.contains(pt):
            return geo
    return None


def _intersects_any_screen(x: int, y: int, w: int, h: int) -> bool:
    app = QApplication.instance()
    if app is None:
        return True
    rect = QRect(int(x), int(y), max(1, int(w)), max(1, int(h)))
    for screen in app.screens():
        if screen.availableGeometry().intersects(rect):
            return True
    return False


def max_window_size(widget: QWidget | None = None, *, margin: int = MARGIN) -> tuple[int, int]:
    avail = available_rect(widget)
    return (
        max(MIN_W, avail.width() - margin * 2),
        max(MIN_H, avail.height() - margin * 2),
    )


def max_content_width(widget: QWidget | None, *, fallback: int = 560) -> int:
    """Preferred wrap width so flow rows do not demand a super-wide window."""
    avail = available_rect(widget)
    cap = max(MIN_W, avail.width() - MARGIN * 2)
    if widget is not None and widget.width() >= 80:
        return max(MIN_W, min(cap, widget.width()))
    return max(MIN_W, min(cap, fallback))


def fit_widget(
    widget: QWidget,
    *,
    width: int | None = None,
    height: int | None = None,
    x: int | None = None,
    y: int | None = None,
    center: bool = False,
    margin: int = MARGIN,
) -> None:
    """Resize and move `widget` so it stays on a real, usable screen."""
    if widget is None:
        return
    if widget.isMaximized() or widget.isFullScreen():
        return

    hint = widget.sizeHint()
    w = int(width if width is not None else (widget.width() or hint.width() or 480))
    h = int(height if height is not None else (widget.height() or hint.height() or 360))
    x = widget.x() if x is None else int(x)
    y = widget.y() if y is None else int(y)

    avail = _screen_at(x, y)
    if avail is None or not _intersects_any_screen(x, y, w, h):
        avail = available_rect(widget)
        center = True

    min_w = widget.minimumWidth() or MIN_W
    min_h = widget.minimumHeight() or MIN_H
    max_w = max(MIN_W, avail.width() - margin * 2)
    max_h = max(MIN_H, avail.height() - margin * 2)
    if widget.minimumWidth() > max_w or widget.minimumHeight() > max_h:
        widget.setMinimumSize(min(widget.minimumWidth(), max_w),
                              min(widget.minimumHeight(), max_h))
        min_w = widget.minimumWidth()
        min_h = widget.minimumHeight()

    if center:
        w = max(min(w, max_w), min(min_w, max_w))
        h = max(min(h, max_h), min(min_h, max_h))
        x = avail.x() + max(0, (avail.width() - w) // 2)
        y = avail.y() + max(0, (avail.height() - h) // 3)

    x, y, w, h = clamp_geometry(
        x, y, w, h,
        avail.x(), avail.y(), avail.width(), avail.height(),
        min_w=min_w, min_h=min_h, margin=margin,
    )
    widget.resize(w, h)
    widget.move(x, y)
