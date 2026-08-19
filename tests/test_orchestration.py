"""Orchestration loop tests with mock LLM runner."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import projects
from src.orchestration.registry import AgentRegistry
from src.orchestration.loop import OrchestratorLoop
from src.orchestration.plan_state import new_task_id


class MockRunner:
    def __init__(self):
        self._cancelled = False

    def clear_cancel(self):
        self._cancelled = False

    def request_cancel(self):
        self._cancelled = True

    def is_cancelled(self):
        return self._cancelled

    def stream_persona(self, key, instruction, show_think=False, **kwargs):
        for word in ("Hello", " ", "world"):
            if self._cancelled:
                return
            yield word

    def finalize_persona(self, key, instruction, raw):
        pass


class OrchestrationTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        projects.DATA_DIR = os.path.join(self._tmpdir, "data")
        projects.PROJECTS_DIR = os.path.join(projects.DATA_DIR, "projects")
        projects.PROJECTS_INDEX_PATH = os.path.join(projects.DATA_DIR, "projects.json")
        projects.ensure_initialized()
        self.project_id = "default"
        self.registry = AgentRegistry()
        self.registry.register_persona({
            "key": "world_builder",
            "display_name": "Setting Designer",
            "model_key": "architect",
            "system_prompt": "Build worlds.",
            "capture_kind": "world",
            "tier": "Tier 1 - Architects",
        })
        self.registry.register_persona({
            "key": "quest_architect",
            "display_name": "Plot Designer",
            "model_key": "architect",
            "system_prompt": "Plot.",
            "capture_kind": "quest",
            "tier": "Tier 1 - Architects",
        })
        self.runner = MockRunner()
        self.loop = OrchestratorLoop(
            self.project_id, self.registry, self.runner)

    def test_run_pending_task(self):
        tid = new_task_id()
        self.loop.plan.load()
        self.loop.plan.upsert_task({
            "id": tid,
            "title": "Test task",
            "type": "setting_design",
            "status": "pending",
            "priority": 10,
            "assignee": "world_builder",
            "dependsOn": [],
            "instruction": "Build a city.",
            "resultRef": None,
        })
        events = list(self.loop.run_pending(max_tasks=1))
        kinds = [e[0] for e in events]
        self.assertIn("delta", kinds)
        self.assertIn("done", kinds)
        task = self.loop.plan.task_by_id(tid)
        assert task is not None
        self.assertEqual(task["status"], "done")

    def test_cancel_mid_run(self):
        tid = new_task_id()
        self.loop.plan.load()
        self.loop.plan.upsert_task({
            "id": tid,
            "title": "Cancel me",
            "type": "plot_design",
            "status": "pending",
            "priority": 10,
            "assignee": "quest_architect",
            "dependsOn": [],
            "instruction": "Go.",
            "resultRef": None,
        })

        def run_and_cancel():
            gen = self.loop.dispatch_task(self.loop.plan.task_by_id(tid))
            first = next(gen)
            self.runner.request_cancel()
            rest = list(gen)
            return first, rest

        first, rest = run_and_cancel()
        self.assertEqual(first[0], "task")
        self.assertEqual(rest[0][0], "step")


if __name__ == "__main__":
    unittest.main()
