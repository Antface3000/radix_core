"""Pure geometry helpers (no Qt). Used to keep pop-outs on screen."""

from __future__ import annotations

MARGIN = 24
MIN_W = 280
MIN_H = 200


def clamp_geometry(
    x: int, y: int, w: int, h: int,
    avail_x: int, avail_y: int, avail_w: int, avail_h: int,
    *,
    min_w: int = MIN_W,
    min_h: int = MIN_H,
    margin: int = MARGIN,
) -> tuple[int, int, int, int]:
    """Return x, y, w, h fully inside the available rectangle when possible."""
    max_w = max(min_w, avail_w - margin * 2)
    max_h = max(min_h, avail_h - margin * 2)
    max_w = min(max_w, avail_w)
    max_h = max(min(max_h, avail_h), 1)
    min_w = min(min_w, max_w)
    min_h = min(min_h, max_h)
    w = max(min_w, min(int(w), max_w))
    h = max(min_h, min(int(h), max_h))
    x = max(avail_x, min(int(x), avail_x + avail_w - w))
    y = max(avail_y, min(int(y), avail_y + avail_h - h))
    return x, y, w, h
