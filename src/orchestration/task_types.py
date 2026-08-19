"""Task type constants and specialist dispatch map (one job per agent)."""

from __future__ import annotations

TASK_TYPES = frozenset({
    "prose_write",
    "line_edit",
    "canon_check",
    "setting_design",
    "character_profile",
    "species_design",
    "plot_design",
    "dialogue_write",
    "session_summarize",
    "dialect_write",
    "critique_cliche",
    "critique_spark",
    "critique_tension",
    "hitl",
})

# Legacy plan.json types → current task types
LEGACY_TYPE_MAP = {
    "world_build": "setting_design",
    "lore_check": "canon_check",
    "character": "character_profile",
    "write_dialogue": "dialogue_write",
    "general": "plot_design",
    "plan": "plot_design",
    "synthesis": "plot_design",
}

TASK_TYPE_TO_AGENT: dict[str, str] = {
    "prose_write": "ghostwriter",
    "line_edit": "prose_critic",
    "canon_check": "lore_curator",
    "setting_design": "world_builder",
    "character_profile": "character_dev",
    "species_design": "creature_dev",
    "plot_design": "quest_architect",
    "dialogue_write": "dialogue_writer",
    "session_summarize": "chat_historian",
    "dialect_write": "slang_smith",
    "critique_cliche": "pessimistic_critic",
    "critique_spark": "optimistic_critic",
    "critique_tension": "horny_critic",
    "hitl": "system_liaison",
}

AGENT_TO_TASK_TYPE: dict[str, str] = {
    v: k for k, v in TASK_TYPE_TO_AGENT.items()
}


def normalize_task_type(raw: str | None) -> str:
    t = (raw or "").strip().lower()
    if t in TASK_TYPES:
        return t
    if t in LEGACY_TYPE_MAP:
        return LEGACY_TYPE_MAP[t]
    return t


def task_type_for_agent(agent_key: str) -> str | None:
    return AGENT_TO_TASK_TYPE.get(agent_key)
