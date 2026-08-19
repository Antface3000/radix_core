"""Backward-compatible alias — use TeamPanel."""

from ui_qt.panels.team_panel import TeamPanel

AgentsPanel = TeamPanel

__all__ = ["AgentsPanel", "TeamPanel"]
