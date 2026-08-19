"""Tests for tier-aware dispatch ordering (minimize model reloads)."""

import unittest

from src.orchestration.registry import (
    AgentCapability,
    AgentRegistry,
    order_tasks_for_dispatch,
)


def _cap(key, model_key, handles):
    return AgentCapability(
        key=key, display_name=key, handles=handles, tools=[],
        model_key=model_key, system_prompt="")


def _registry():
    reg = AgentRegistry()
    reg.register(_cap("world_builder", "architect", ["setting_design"]))
    reg.register(_cap("quest_architect", "operator", ["plot_design"]))
    reg.register(_cap("slang_smith", "flavor", ["dialect_write"]))
    return reg


def _task(tid, ttype, assignee=None, priority=10, depends=None):
    return {
        "id": tid,
        "type": ttype,
        "assignee": assignee,
        "priority": priority,
        "dependsOn": depends or [],
        "status": "pending",
    }


class TierOrderingTests(unittest.TestCase):
    def test_groups_same_tier_together(self):
        reg = _registry()
        tasks = [
            _task("t1", "setting_design", "world_builder"),
            _task("t2", "plot_design", "quest_architect"),
            _task("t3", "setting_design", "world_builder"),
            _task("t4", "dialect_write", "slang_smith"),
            _task("t5", "plot_design", "quest_architect"),
        ]
        ordered = order_tasks_for_dispatch(tasks, reg)
        ids = [t["id"] for t in ordered]
        self.assertEqual(ids, ["t1", "t3", "t2", "t5", "t4"])

    def test_priority_beats_tier(self):
        reg = _registry()
        tasks = [
            _task("arch", "setting_design", "world_builder", priority=20),
            _task("flav", "dialect_write", "slang_smith", priority=1),
        ]
        ordered = order_tasks_for_dispatch(tasks, reg)
        self.assertEqual([t["id"] for t in ordered], ["flav", "arch"])

    def test_dependents_stay_after_dependencies(self):
        reg = _registry()
        tasks = [
            # Architect task depends on a flavor task; tier sort alone would
            # put it first.
            _task("arch", "setting_design", "world_builder",
                  depends=["flav"]),
            _task("op", "plot_design", "quest_architect"),
            _task("flav", "dialect_write", "slang_smith"),
        ]
        ordered = order_tasks_for_dispatch(tasks, reg)
        ids = [t["id"] for t in ordered]
        self.assertLess(ids.index("flav"), ids.index("arch"))

    def test_stable_for_unknown_assignee(self):
        reg = _registry()
        tasks = [
            _task("known", "setting_design", "world_builder"),
            _task("unknown", "mystery_type", "nobody"),
        ]
        ordered = order_tasks_for_dispatch(tasks, reg)
        self.assertEqual(len(ordered), 2)
        self.assertEqual(ordered[0]["id"], "known")


if __name__ == "__main__":
    unittest.main()
