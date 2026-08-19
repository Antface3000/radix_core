"""Tests for Manager-driven plan generation."""

import os
import sys
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.orchestration.plan_builder import _parse_plan_json, _default_plan
from src.orchestration.registry import AgentRegistry


class PlanBuilderTests(unittest.TestCase):
    def test_parse_plan_json(self):
        text = """
        Here is the plan:
        {
          "title": "Act 2 outline",
          "tasks": [
            {
              "title": "Build set piece",
              "type": "world_build",
              "assignee": "world_builder",
              "instruction": "Design the vault layout.",
              "priority": 10
            },
            {
              "title": "Canon check",
              "type": "lore_check",
              "assignee": "lore_curator",
              "instruction": "Verify vault against lore."
            }
          ]
        }
        """
        parsed = _parse_plan_json(text, 10)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed["title"], "Act 2 outline")
        self.assertEqual(len(parsed["tasks"]), 2)
        self.assertEqual(parsed["tasks"][0]["assignee"], "world_builder")

    def test_default_plan(self):
        registry = AgentRegistry()
        registry.register_persona({
            "key": "world_builder",
            "display_name": "Setting Designer",
            "model_key": "architect",
            "system_prompt": "Build.",
            "capture_kind": "world",
            "tier": "Tier 1 - Architects",
        })
        registry.register_persona({
            "key": "lore_curator",
            "display_name": "Canon Checker",
            "model_key": "architect",
            "system_prompt": "Check.",
            "capture_kind": "lore",
            "tier": "Tier 1 - Architects",
        })
        plan = _default_plan("Expand the heist", registry)
        self.assertEqual(len(plan["tasks"]), 2)
        self.assertEqual(plan["tasks"][0]["type"], "setting_design")


if __name__ == "__main__":
    unittest.main()
