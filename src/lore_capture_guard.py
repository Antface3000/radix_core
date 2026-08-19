"""Validate agent lore captures — reject meta / conversational junk."""

from __future__ import annotations

import re

# Phrases typical of model self-talk about tags, not in-world canon.
_META_PHRASES = (
    "wait, no",
    "wait no",
    "or perhaps",
    "something like",
    "the setting says",
    "use a different tag",
    "different tag since",
    "for general facts",
    "character profiles",
    "character profile",
    "since characters aren't",
    "tags?",
    "tag syntax",
    "canon markers",
    "capture tag",
    "filed to lorebook",
    "do not write",
    "no markdown inside",
    "markdown inside the tags",
    "discuss tag",
    "[[character]]",
    "[[remember]]",
    "[[species",
    "[[world]]",
    "[[bible",
)

_BAD_NAME_STARTS = (
    "or ",
    "wait",
    "for ",
    "tags",
    "...",
    "perhaps ",
    "something ",
    "maybe ",
    "i ",
    "we ",
    "you ",
    "the setting",
    "note:",
    "general facts",
)

_MARKER_TALK_RE = re.compile(r"\[\[[A-Za-z:/_\-\s]+\]\]", re.I)
_SENTENCE_CONNECTOR_RE = re.compile(
    r"\b(but|since|because|however|although|unless|whether)\b", re.I)


def is_meta_capture_text(text: str) -> bool:
    """True when text looks like agent instruction/meta, not story canon."""
    t = (text or "").strip()
    if not t:
        return True
    lower = t.lower()
    if any(phrase in lower for phrase in _META_PHRASES):
        return True
    if "?" in t[:160]:
        return True
    if _MARKER_TALK_RE.search(t):
        return True
    if lower.startswith("...") or re.search(r"\.\.\.\s*$", t[:100]):
        return True
    if _SENTENCE_CONNECTOR_RE.search(t[:120]) and len(t.split()) > 6:
        return True
    return False


def is_valid_capture_name(name: str) -> bool:
    n = (name or "").strip()
    if len(n) < 2 or len(n) > 56:
        return False
    if "?" in n or "..." in n:
        return False
    if any(n.lower().startswith(p) for p in _BAD_NAME_STARTS):
        return False
    if len(n.split()) > 8:
        return False
    if is_meta_capture_text(n):
        return False
    if _SENTENCE_CONNECTOR_RE.search(n):
        return False
    # Require at least one letter; not only punctuation.
    if not re.search(r"[A-Za-z]", n):
        return False
    return True


def is_valid_capture_body(body: str) -> bool:
    b = (body or "").strip()
    if len(b) < 12:
        return False
    if is_meta_capture_text(b):
        return False
    # Very long unbroken ramble without closed structure is usually junk capture.
    if len(b) > 2000 and b.count("\n") < 2 and "?" in b:
        return False
    return True


def derive_capture_name(block: str, explicit_name: str | None = None) -> str | None:
    """Return a lore entry name or None if the capture should be rejected."""
    if explicit_name and explicit_name.strip():
        name = explicit_name.strip()[:56]
        return name if is_valid_capture_name(name) else None

    block = (block or "").strip()
    if not block:
        return None

    first = block.splitlines()[0].strip()
    first = re.sub(r"^[#*\-\s]+", "", first)
    if ":" in first and len(first.split(":", 1)[0]) <= 56:
        candidate = first.split(":", 1)[0].strip()
    else:
        # Use first clause / phrase, not the whole sentence.
        candidate = re.split(r"[.!?]\s+", first, maxsplit=1)[0].strip()
        if len(candidate.split()) > 6:
            words = candidate.split()[:4]
            candidate = " ".join(words)

    candidate = (candidate[:56] or "").strip()
    if not is_valid_capture_name(candidate):
        return None
    return candidate
