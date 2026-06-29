"""AI generation helpers for Story Bible field widgets.

Supports single-tier (T1/T2/T3) streaming and full orchestration with synthesis
capture for populating bible / outline / lore / world-state fields.
"""

from src import worldcontext

TIER_MODES = {
    "T1 (Architect)": "architect",
    "T2 (Operator)": "operator",
    "T3 (Flavor)": "flavor",
}

MODE_LABELS = tuple(TIER_MODES.keys()) + ("Orchestrated",)

_SYSTEM = (
    "You are helping the author fill in a Story Bible field for their creative "
    "writing project. Use the SETTING block as ground truth.\n"
    "Output ONLY the content for the requested field — no preamble, labels, "
    "markdown headers, or meta commentary."
)


def _build_user_prompt(field_label, user_prompt, existing_text, extra_context):
    parts = [f"FIELD: {field_label}"]
    if user_prompt.strip():
        parts.append(f"AUTHOR REQUEST:\n{user_prompt.strip()}")
    if existing_text.strip():
        parts.append(f"CURRENT CONTENT (revise or extend as appropriate):\n"
                     f"{existing_text.strip()}")
    if extra_context and extra_context.strip():
        parts.append(f"CONTEXT:\n{extra_context.strip()}")
    parts.append("Write the field content now.")
    return "\n\n".join(parts)


def _system_prompt(paths):
    setting = worldcontext.assemble(paths)
    if setting.strip():
        return f"{_SYSTEM}\n\n{setting}"
    return _SYSTEM


def stream_field(engine, paths, field_label, user_prompt, mode, existing_text="",
                 extra_context="", temperature=0.7, max_tokens=None):
    """Yield text deltas for T1/T2/T3 modes. Raises on unknown mode."""
    model_key = TIER_MODES.get(mode)
    if not model_key:
        raise ValueError(f"Not a tier mode: {mode!r}")
    user = _build_user_prompt(field_label, user_prompt, existing_text, extra_context)
    system = _system_prompt(paths)
    yield from engine.stream_prompt(
        model_key, system, user,
        temperature=temperature, max_tokens=max_tokens, show_think=False)


def orchestrate_field(engine, task, ask_user=None, show_think=False):
    """Run orchestration and yield (event_kind, payload) tuples.

    After completion, callers can read the synthesis text via last_orchestrated_text().
    """
    holder = {"text": "", "collect": False}

    for ev in engine.orchestrate(task, show_think=show_think, ask_user=ask_user):
        kind = ev[0]
        if kind == "synthesis":
            holder["collect"] = True
            holder["text"] = ""
            yield ("synthesis_start", ev[1])
        elif kind == "delta" and holder["collect"]:
            holder["text"] += ev[2]
            yield ("delta", ev[2])
        elif kind == "done":
            holder["collect"] = False
            yield ("done", holder["text"])
        else:
            yield (kind, ev[1:] if len(ev) > 1 else None)

    if holder["collect"]:
        yield ("done", holder["text"])


def build_orchestrated_task(paths, field_label, user_prompt, existing_text="",
                            extra_context=""):
    """Compose a manager task string for orchestrated field generation."""
    user = _build_user_prompt(field_label, user_prompt, existing_text, extra_context)
    setting = worldcontext.assemble(paths)
    task = (
        f"Fill in the Story Bible field '{field_label}' for the author's project.\n\n"
        f"{user}\n\n"
        "Coordinate the team to produce accurate, setting-consistent field content. "
        "The final synthesis should be ONLY the field text — no chat or labels."
    )
    if setting.strip():
        task = f"{setting}\n\n{task}"
    return task
