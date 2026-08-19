"""Tests for Plan.md ↔ plan.json round-trip."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.orchestration.plan_state import PlanStateStore, empty_plan, new_task_id
from src import projects


class PlanSyncTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        projects.DATA_DIR = os.path.join(self._tmpdir, "data")
        projects.PROJECTS_DIR = os.path.join(projects.DATA_DIR, "projects")
        projects.PROJECTS_INDEX_PATH = os.path.join(projects.DATA_DIR, "projects.json")
        projects.ensure_initialized()
        self.project_id = "default"
        self.store = PlanStateStore(self.project_id)

    def test_json_to_md_to_json(self):
        tid = new_task_id()
        self.store.load()
        self.store.upsert_task({
            "id": tid,
            "title": "Establish hero profile",
            "type": "lore_check",
            "status": "pending",
            "priority": 10,
            "assignee": None,
            "dependsOn": [],
            "instruction": "Develop psychological profile.",
            "resultRef": None,
        })
        md = self.store.export_markdown()
        self.assertIn(tid, md)
        self.assertIn("Establish hero profile", md)

        reloaded = PlanStateStore(self.project_id)
        reloaded.load()
        summary = reloaded.import_markdown(md)
        self.assertEqual(summary["tasks_updated"], 1)
        task = reloaded.task_by_id(tid)
        self.assertIsNotNone(task)
        assert task is not None
        self.assertEqual(task["title"], "Establish hero profile")
        self.assertEqual(task["instruction"], "Develop psychological profile.")

    def test_empty_plan_seed(self):
        plan = empty_plan("Test")
        self.assertEqual(plan["version"], 1)
        self.assertEqual(plan["tasks"], [])


if __name__ == "__main__":
    unittest.main()
