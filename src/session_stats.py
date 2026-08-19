"""Session / daily word-count targets."""

from __future__ import annotations

from datetime import date

from src import projects


def _stats_path(paths) -> str:
    return paths.get("session_stats") or __import__("os").path.join(
        paths["root"], "session_stats.json")


def load(paths) -> dict:
    return projects.read_json_safe(_stats_path(paths), {
        "sessionStartWords": 0,
        "sessionWords": 0,
        "day": "",
        "dayWords": 0,
    })


def save(paths, data: dict) -> None:
    projects.write_json(_stats_path(paths), data)


def on_word_count(paths, current_words: int) -> dict:
    """Update session and daily totals from the current chapter word count.

    Session words are the delta from the count when the session started
    (first call today / after project open). Daily words accumulate across
    chapters loosely: we store the last seen count per day as a running max
    of (dayWords + positive delta).
    """
    data = load(paths)
    today = date.today().isoformat()
    if data.get("day") != today:
        data["day"] = today
        data["dayWords"] = 0
        data["sessionStartWords"] = current_words
        data["lastWords"] = current_words
    last = int(data.get("lastWords") or data.get("sessionStartWords") or 0)
    delta = current_words - last
    if delta > 0:
        data["dayWords"] = int(data.get("dayWords") or 0) + delta
    data["lastWords"] = current_words
    start = int(data.get("sessionStartWords") or current_words)
    data["sessionWords"] = max(0, current_words - start)
    save(paths, data)
    return data
