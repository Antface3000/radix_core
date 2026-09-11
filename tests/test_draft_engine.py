"""Tests for Draft Generate Scenes / Plan Draft helpers."""

import os
import tempfile
import unittest

from src import draft_engine, lore, outline, story_bible


def _paths(tmp: str) -> dict:
    return {
        "root": tmp,
        "outlines": os.path.join(tmp, "outlines.json"),
        "lore": os.path.join(tmp, "lore.json"),
        "bible": os.path.join(tmp, "story_bible.json"),
        "world_state": os.path.join(tmp, "world_state.json"),
    }


class DraftEngineTests(unittest.TestCase):
    def test_parse_scene_lines_strips_bullets_and_dupes(self):
        raw = """
        Scenes:
        1. Ada crosses the lock
        - Ada crosses the lock
        * The pump fails
        ## ignore me
        Scene 3: She seals the hatch
        """
        lines = draft_engine.parse_scene_lines(raw)
        self.assertEqual(lines, [
            "Ada crosses the lock",
            "The pump fails",
            "She seals the hatch",
        ])

    def test_write_chapter_beats_keeps_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            outline.write_chapter(paths["outlines"], "ch1", {
                "summary": "Night watch",
                "beats": ["old"],
            })
            saved = draft_engine.write_chapter_beats(
                paths, "ch1", ["Ada waits", "The hatch groans"])
            self.assertEqual(saved["summary"], "Night watch")
            self.assertEqual(saved["beats"], ["Ada waits", "The hatch groans"])
            loaded = outline.read_chapter(paths["outlines"], "ch1")
            self.assertEqual(loaded["summary"], "Night watch")
            self.assertEqual(loaded["beats"], ["Ada waits", "The hatch groans"])

    def test_read_parking_lot_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            self.assertEqual(draft_engine.read_parking_lot(paths), "")
            path = draft_engine.parking_lot_path(paths)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("x" * 50)
            self.assertEqual(draft_engine.read_parking_lot(paths, max_chars=20).startswith("x"), True)
            self.assertIn("…", draft_engine.read_parking_lot(paths, max_chars=20))

    def test_generate_scenes_prompt_includes_context(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            outline.write_chapter(paths["outlines"], "ch1", {
                "summary": "Break into the pump house",
                "beats": [],
            })
            story_bible.write(paths["bible"], {
                "genreTone": "wet industrial noir",
                "styleNotes": "short clauses",
            })
            lore.write(paths["lore"], {
                "characters": [{
                    "id": "a", "name": "Ada", "entryType": "character",
                    "notes": "scout", "keywords": ["Ada", "pump"],
                    "alwaysInclude": True,
                }],
                "world": [],
            })
            with open(draft_engine.parking_lot_path(paths), "w", encoding="utf-8") as fh:
                fh.write("She already knows the night watch drinks early.")
            system, user = draft_engine.build_generate_scenes_prompts(
                paths, "ch1", extra="Keep it quiet", pov="close third",
                tense="past", perspective="Ada")
            self.assertIn("one beat per line", system.lower())
            self.assertIn("Break into the pump house", user)
            self.assertIn("night watch drinks", user)
            self.assertIn("Ada", user)
            self.assertIn("wet industrial noir", user)
            self.assertIn("Keep it quiet", user)
            self.assertIn("close third", user)

    def test_plan_draft_direction_numbers_all_scenes(self):
        direction = draft_engine.build_plan_draft_direction(
            ["Ada waits", "The hatch groans"], extra="No monologue",
            pov="first", tense="present", perspective="Ada")
        self.assertIn("1. Ada waits", direction)
        self.assertIn("2. The hatch groans", direction)
        self.assertIn("ALL of these scenes", direction)
        self.assertIn("No monologue", direction)
        self.assertIn("first", direction)
        self.assertIn("Ada", direction)


if __name__ == "__main__":
    unittest.main()
