"""Pre-flight ambiguity checks before agent/generate dispatch."""

from __future__ import annotations

from dataclasses import dataclass, field

from src import worldcontext

CANON_MIN_CHARS = 200
VAGUE_MIN_WORDS = 12

_GENERIC_VERBS = frozenset({
    "help", "write", "expand", "continue", "something", "anything", "more",
    "improve", "fix", "generate", "create", "develop", "brainstorm",
})


@dataclass
class AmbiguityResult:
    blocked: bool = False
    block_reason: str | None = None
    warnings: list[str] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)


def is_vague_prompt(prompt: str) -> bool:
    text = (prompt or "").strip()
    if not text:
        return True
    words = text.split()
    if len(words) < VAGUE_MIN_WORDS:
        lower = {w.lower().strip(".,!?") for w in words}
        if lower <= _GENERIC_VERBS or lower & _GENERIC_VERBS:
            return True
    return False


def _canon_thin(paths) -> tuple[bool, str]:
    if not paths:
        return True, "No project loaded."
    summary = worldcontext.summarize_injection(paths)
    if summary.get("empty"):
        return True, "No setting configured yet (Story Bible is empty)."
    if summary.get("chars", 0) < CANON_MIN_CHARS:
        return True, (
            f"Setting context is very thin ({summary['chars']} chars). "
            "Fill Story Bible or Lorebook for better results."
        )
    return False, ""


def evaluate(paths, prompt: str, settings) -> AmbiguityResult:
    """Pure evaluation — UI layer handles dialogs."""
    result = AmbiguityResult()
    if not settings.get("orchestration.ambiguity_check", True):
        return result

    thin, reason = _canon_thin(paths)
    if thin:
        result.blocked = True
        result.block_reason = reason

    if is_vague_prompt(prompt):
        if settings.get("orchestration.hitl", False):
            result.questions = _clarifying_questions(prompt)
        else:
            result.warnings.append(
                "Prompt is short or vague — add subject and intent for sharper output."
            )
    return result


def _clarifying_questions(prompt: str) -> list[str]:
    base = (prompt or "").strip() or "your request"
    return [
        f"What specific outcome do you want from: \"{base[:80]}\"?",
        "Which characters, locations, or plot threads should this focus on?",
        "Any tone, length, or constraints I should follow?",
    ]
