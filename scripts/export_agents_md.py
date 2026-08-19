"""One-shot export of AGENTS.md from src/personas.py."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import personas
from src.orchestration.task_types import AGENT_TO_TASK_TYPE, TASK_TYPE_TO_AGENT

PROBE = {
    "lore_curator": (
        "Check this draft beat against canon: "
        "[insert 3-sentence scene contradicting a bible fact]."
    ),
    "creature_dev": (
        "Design a predator native to [location from bible]; state 3 trade-offs."
    ),
    "character_dev": (
        "Profile a new NPC: a dock worker who knows too much. Surface + Shadow Log."
    ),
    "world_builder": (
        "Expand the undercity district: who controls it, one faction conflict."
    ),
    "ghostwriter": (
        "(Use Editor Write instead) Continue from: [2 paragraphs of sample prose]."
    ),
    "prose_critic": (
        "Polish this draft: [intentionally flat 150-word passage]. Output passage only."
    ),
    "dialogue_writer": (
        "Write a 12-line argument between A and B about a debt, subtext only."
    ),
    "chat_historian": (
        "Summarize this chat log: [paste 800 words of fake planning chat]."
    ),
    "quest_architect": (
        "Design a 5-step heist quest tied to [faction from bible]."
    ),
    "pessimistic_critic": (
        "Critique this passage: [trope-heavy 100 words]. Bullets only."
    ),
    "optimistic_critic": "Elevate this rough dialogue: [generic lines].",
    "horny_critic": (
        "Read this scene for chemistry: [neutral interaction]. What is missing?"
    ),
    "slang_smith": (
        "Coin 5 slang terms for [faction/class]; rewrite one sample line."
    ),
    "system_planner": "Test via Team job — verify JSON-only planner output.",
    "system_liaison": (
        "Test via Team job — verify clarifying questions before planner."
    ),
}


def main() -> None:
    lines: list[str] = []
    lines.append("# Agent roster catalog")
    lines.append("")
    lines.append(
        "Offline reference for every persona prompt, runtime wrappers, "
        "and efficacy review."
    )
    lines.append(
        "Source of truth: `src/personas.py`. "
        "Task dispatch: `src/orchestration/task_types.py`."
    )
    lines.append("")
    lines.append("## Roster summary")
    lines.append("")
    lines.append(
        "| Key | Display name | Tier | Model | Task type | Selectable | "
        "Capture | Temp |"
    )
    lines.append(
        "|-----|--------------|------|-------|-----------|------------|"
        "---------|------|"
    )
    for p in personas.PERSONAS:
        key = p["key"]
        tt = AGENT_TO_TASK_TYPE.get(key, "—")
        sel = "yes" if personas.is_selectable(p) else "no"
        cap = p.get("capture_kind") or "none"
        temp = p.get("temperature", "default")
        lines.append(
            f"| `{key}` | {p['display_name']} | {p['tier']} | "
            f"{p['model_key']} | {tt} | {sel} | {cap} | {temp} |"
        )

    lines.append("")
    lines.append(
        "Legacy aliases (not in manifest): `manager` → `system_planner`, "
        "`user_liaison` → `system_liaison`."
    )
    lines.append("")
    lines.append("## Runtime wrappers")
    lines.append("")
    lines.append("| Surface | What the model sees |")
    lines.append("|---------|---------------------|")
    lines.append(
        "| **Editor Write** | `ghostwriter.system_prompt` + "
        "`build_write_prompt()` user rules + story context |"
    )
    lines.append(
        "| **Editor Write critics** | `critic.system_prompt` + "
        "`_critic_review_prompt()` user block |"
    )
    lines.append(
        "| **Editor Chat** | `editor.chat_persona.system_prompt` + "
        "`build_chat_system()` project context |"
    )
    lines.append(
        "| **Team Specialist** | `persona.system_prompt` + SETTING block + "
        "user message + persona memory |"
    )
    lines.append(
        "| **Team job dispatch** | `persona.system_prompt` + SETTING + "
        "scoped instruction + `_STEP_NO_CAPTURE` |"
    )
    lines.append("")
    lines.append("### `_ANTI_REPEAT` (Team/Specialist user messages)")
    lines.append("```")
    lines.append(
        "Do not repeat or paraphrase facts already present in SETTING above. "
        "Add only new, task-specific information."
    )
    lines.append("```")
    lines.append("")
    lines.append("### `_STEP_NO_CAPTURE` (orchestration dispatch)")
    lines.append("```")
    lines.append(
        "Do not use [[REMEMBER]], [[BIBLE:*]], [[CHARACTER]], or other canon "
        "markers in this step. Focus on your assignment only."
    )
    lines.append("```")
    lines.append("")
    lines.append("### `_REMEMBER_NOTE` (appended to world-building personas)")
    lines.append("```")
    lines.append(personas._REMEMBER_NOTE.strip())
    lines.append("```")
    lines.append("")
    lines.append("## HITL policy")
    lines.append("")
    lines.append(
        "- **Team job** (one-shot and save-plan): Liaison preamble always runs "
        "before planner when `ask_user` is wired."
    )
    lines.append(
        "- **Ambiguity gate**: warnings always toast; blocking Liaison Q&A on "
        "team jobs when prompt is ambiguous; Specialist tab toasts only."
    )
    lines.append(
        "- **Specialist tab**: direct agent access — no Liaison preamble."
    )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## Persona prompts (verbatim)")
    lines.append("")

    for p in personas.PERSONAS:
        key = p["key"]
        lines.append(f"### `{key}` — {p['display_name']}")
        lines.append("")
        lines.append(f"- **Tier:** {p['tier']}")
        lines.append(f"- **Model:** `{p['model_key']}`")
        lines.append(f"- **Task type:** `{AGENT_TO_TASK_TYPE.get(key, '—')}`")
        lines.append(
            f"- **Selectable:** {'yes' if personas.is_selectable(p) else 'no'}"
        )
        lines.append(f"- **Capture:** `{p.get('capture_kind') or 'none'}`")
        lines.append(f"- **Temperature:** {p.get('temperature', 'default')}")
        lines.append("")
        lines.append("**System prompt:**")
        lines.append("```")
        lines.append(p["system_prompt"].strip())
        lines.append("```")
        lines.append("")
        probe = PROBE.get(key, "")
        if probe:
            lines.append(f"**Probe prompt:** {probe}")
            lines.append("")
        if personas.is_selectable(p):
            lines.append(
                "**Efficacy checklist** "
                "(score 1–5: role clarity, format compliance, canon respect, "
                "no meta, length)"
            )
            lines.append("")
            lines.append("- [ ] Role clarity")
            lines.append("- [ ] Output format compliance")
            lines.append("- [ ] Canon respect")
            lines.append("- [ ] No meta-commentary")
            lines.append("- [ ] Appropriate length")
            lines.append("")
            lines.append("**Review notes:**")
            lines.append("")
            lines.append("_Fill in after manual testing._")
            lines.append("")
        lines.append("---")
        lines.append("")

    lines.append("## Task type → agent map")
    lines.append("")
    for tt, key in sorted(TASK_TYPE_TO_AGENT.items()):
        lines.append(f"- `{tt}` → `{key}`")
    lines.append("")
    lines.append("## Probe prompts (quick reference)")
    lines.append("")
    lines.append("| Agent | Test instruction |")
    lines.append("|-------|------------------|")
    for p in personas.PERSONAS:
        probe = PROBE.get(p["key"], "")
        if probe:
            lines.append(f"| {p['display_name']} | {probe} |")
    lines.append("")
    lines.append("## Manual review workflow")
    lines.append("")
    lines.append(
        "1. Open Team → Specialist with Inject setting ON and a project with "
        "minimal Story Bible + one lore entry."
    )
    lines.append(
        "2. Run each probe prompt above; for Prose Writer use Editor → Write."
    )
    lines.append(
        "3. For system planner/liaison, run Team job with a vague then a clear goal."
    )
    lines.append(
        "4. Fill **Review notes** under each agent, then apply targeted prompt "
        "fixes in `src/personas.py`."
    )

    root = ROOT
    out = root / "AGENTS.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {out} ({len(lines)} lines)")


if __name__ == "__main__":
    main()
