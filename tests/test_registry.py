"""Registry dispatch tests — one specialist per task type."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.orchestration.registry import AgentRegistry
from src.orchestration.task_types import TASK_TYPE_TO_AGENT, normalize_task_type
from src.settings import Settings


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.registry = AgentRegistry()
        self.registry.populate_from_settings(Settings(), "default")

    def test_each_task_type_maps_to_agent(self):
        for task_type, key in TASK_TYPE_TO_AGENT.items():
            cap = self.registry.best_for(task_type)
            self.assertIsNotNone(cap, f"missing specialist for {task_type}")
            assert cap is not None
            self.assertEqual(cap.key, key)

    def test_legacy_type_migration(self):
        self.assertEqual(normalize_task_type("world_build"), "setting_design")
        self.assertEqual(normalize_task_type("lore_check"), "canon_check")

    def test_no_fallback_for_unknown(self):
        self.assertIsNone(self.registry.best_for("nonexistent_type_xyz"))

    def test_hidden_personas_excluded_from_selectable(self):
        s = Settings()
        keys = {p["key"] for p in s.selectable_personas("default")}
        for hidden in ("system_planner", "system_liaison", "manager", "user_liaison"):
            self.assertNotIn(hidden, keys, f"{hidden} should not be selectable")


if __name__ == "__main__":
    unittest.main()
