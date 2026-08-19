"""Tests for export and ambiguity modules."""

import os
import tempfile
import unittest

from src import chapters, lore, story_bible, world_state, export as export_mod
from src.ambiguity import evaluate, is_vague_prompt
from src.settings import Settings
from src.worldcontext import has_capture_markers, _paragraph_after_open


class ExportAmbiguityTests(unittest.TestCase):
    def test_compile_manuscript(self):
        tmp = tempfile.mkdtemp()
        ch_dir = os.path.join(tmp, "chapters")
        c1 = chapters.create(ch_dir, "One")
        chapters.write(ch_dir, c1["id"], "Hello")
        paths = {"chapters": ch_dir}
        text = export_mod.compile_manuscript(paths, "md")
        self.assertIn("# One", text)
        self.assertIn("Hello", text)

    def test_vague_prompt(self):
        self.assertTrue(is_vague_prompt("help"))
        self.assertFalse(is_vague_prompt(
            "Write a tense confrontation between Mara and the gatekeeper at dawn "
            "while the city bells ring"))

    def test_ambiguity_empty_canon(self):
        tmp = tempfile.mkdtemp()
        paths = {
            "bible": os.path.join(tmp, "story_bible.json"),
            "lore": os.path.join(tmp, "lore.json"),
            "world_state": os.path.join(tmp, "world_state.json"),
            "outlines": os.path.join(tmp, "outlines.json"),
            "chapters": os.path.join(tmp, "chapters"),
        }
        story_bible.write(paths["bible"], {})
        lore.write(paths["lore"], {"characters": [], "world": []})
        world_state.write(paths["world_state"], {})
        with open(paths["outlines"], "w", encoding="utf-8") as f:
            f.write('{"chapters":{}}')
        s = Settings()
        result = evaluate(paths, "expand the scene", s)
        self.assertTrue(result.blocked)

    def test_capture_markers(self):
        self.assertTrue(has_capture_markers("Some text [[REMEMBER]] fact here"))
        chunk = _paragraph_after_open(
            "[[REMEMBER]] line one\nline two\n\nafter", "REMEMBER")
        self.assertIn("line two", chunk)


if __name__ == "__main__":
    unittest.main()
