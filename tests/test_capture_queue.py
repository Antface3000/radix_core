"""Tests for the staged canon capture queue (stage → approve / discard)."""

import json
import os
import tempfile
import unittest

from src import lore, story_bible, world_state, worldcontext
from src.capture_queue import CaptureQueue, describe_item


def _paths(tmp):
    return {
        "lore": os.path.join(tmp, "lore.json"),
        "bible": os.path.join(tmp, "story_bible.json"),
        "world_state": os.path.join(tmp, "world_state.json"),
        "capture_queue": os.path.join(tmp, "capture_queue.json"),
    }


_AGENT_TEXT = (
    "The city rests on stilts.\n"
    "[[REMEMBER]] Port Vell: a stilt-city above the tide flats. [[/REMEMBER]]\n"
    "[[BIBLE:premise]] A smuggler inherits a sentient ship. [[/BIBLE]]\n"
    "[[WORLDSTATE:currentLocation]] Port Vell docks [[/WORLDSTATE]]\n"
)


class CaptureQueueTests(unittest.TestCase):
    def test_stage_then_approve_all_writes_canon(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            queue = CaptureQueue(paths)
            summary = worldcontext.capture_from_agent(
                paths, _AGENT_TEXT, source="Tester", stage=queue.stage)

            self.assertTrue(summary.get("staged"))
            self.assertEqual(len(summary["lore"]), 1)
            self.assertIn("premise", summary["bible"])
            self.assertIn("currentLocation", summary["world_state"])

            # Nothing written yet.
            self.assertEqual(lore.read(paths["lore"])["world"], [])
            self.assertFalse(story_bible.read(paths["bible"]).get("premise"))
            self.assertFalse(
                world_state.read(paths["world_state"]).get("currentLocation"))
            self.assertEqual(queue.count(), 3)

            applied = queue.approve_all()
            self.assertEqual(applied, 3)
            self.assertEqual(queue.count(), 0)

            book = lore.read(paths["lore"])
            names = [e["name"] for e in book["world"] + book["characters"]]
            self.assertIn("Port Vell", names)
            self.assertIn("sentient ship",
                          story_bible.read(paths["bible"])["premise"])
            self.assertEqual(
                world_state.read(paths["world_state"])["currentLocation"],
                "Port Vell docks")

    def test_stage_then_discard_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            queue = CaptureQueue(paths)
            worldcontext.capture_from_agent(
                paths, _AGENT_TEXT, source="Tester", stage=queue.stage)
            items = queue.load()
            self.assertEqual(len(items), 3)

            for item in items:
                self.assertTrue(queue.discard(item["id"]))
            self.assertEqual(queue.count(), 0)

            self.assertEqual(lore.read(paths["lore"])["world"], [])
            self.assertFalse(story_bible.read(paths["bible"]).get("premise"))
            self.assertFalse(
                world_state.read(paths["world_state"]).get("currentLocation"))

    def test_approve_single_item_removes_only_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            queue = CaptureQueue(paths)
            worldcontext.capture_from_agent(
                paths, _AGENT_TEXT, source="Tester", stage=queue.stage)
            items = queue.load()
            lore_item = next(i for i in items if i["kind"] == "lore")

            applied = queue.approve(lore_item["id"])
            self.assertIsNotNone(applied)
            self.assertEqual(queue.count(), 2)
            book = lore.read(paths["lore"])
            self.assertEqual(len(book["world"] + book["characters"]), 1)

    def test_direct_capture_unchanged_without_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            summary = worldcontext.capture_from_agent(
                paths, _AGENT_TEXT, source="Tester")
            self.assertFalse(summary.get("staged"))
            self.assertIn("premise", story_bible.read(paths["bible"]))
            self.assertFalse(os.path.exists(paths["capture_queue"]))

    def test_describe_item_and_persistence(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            queue = CaptureQueue(paths)
            queue.stage("bible", {"field": "premise", "body": "x"}, "merge", "Bob")
            with open(paths["capture_queue"], encoding="utf-8") as fh:
                raw = json.load(fh)
            self.assertEqual(len(raw), 1)
            label = describe_item(raw[0])
            self.assertIn("premise", label)
            self.assertIn("Bob", label)

    def test_format_summary_staged_prefix(self):
        summary = {"lore": [{"name": "X"}], "bible": {}, "world_state": {},
                   "staged": True}
        text = worldcontext.format_capture_summary(summary)
        self.assertTrue(text.startswith("Canon staged for review:"))


if __name__ == "__main__":
    unittest.main()
