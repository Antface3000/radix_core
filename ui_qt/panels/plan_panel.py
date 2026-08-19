"""Backward-compatible alias — plan lives in Team panel."""

from ui_qt.panels.team_panel import TeamPanel

PlanPanel = TeamPanel

__all__ = ["PlanPanel", "TeamPanel"]
