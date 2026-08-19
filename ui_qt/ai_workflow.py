"""Shared labels for Editor vs Team surfaces."""

EDITOR_AI_SUBTITLE = (
    "Manuscript modes — Write continues prose; Chat discusses the project. "
    "Specialists and team jobs live in the Team panel."
)

TEAM_SUBTITLE = (
    "Team — run one specialist or a team job (planner → specialists). "
    "Use the editor to draft prose into the manuscript."
)

EDITOR_MODE_TIPS = {
    "Write": (
        "Continue prose from the manuscript (Prose Writer + optional Line Editor). "
        "Use Instructions for scene-specific direction."
    ),
    "Chat": (
        "Discuss plot, characters, and canon without inserting prose."
    ),
    "Query / blurb": (
        "Named marketing job: query letter, synopsis, or cover blurb. "
        "Never mixed into manuscript Write."
    ),
}

TEAM_TAB_TIPS = {
    "Specialist": "Message one enabled specialist with project setting context.",
    "Team job": (
        "One-shot or saved project plan — Liaison clarifies, then planner assigns "
        "specialists. Check Save as project plan to write plan.json; otherwise runs "
        "immediately. Task list appears after generate."
    ),
}

# Legacy aliases
AGENTS_SUBTITLE = TEAM_SUBTITLE
AGENTS_MODE_LABELS = ["Specialist", "Team job"]
AGENTS_MODE_TIPS = TEAM_TAB_TIPS
