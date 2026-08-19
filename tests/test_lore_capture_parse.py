"""Tests for structured lore capture parsing."""

import os
import tempfile
import unittest

from src import lore, lore_capture_parse, worldcontext


class LoreCaptureParseTests(unittest.TestCase):
    def test_field_lines_character(self):
        block = (
            "role: courier\n"
            "appearance: Tall, scarred hands\n"
            "goals: Pay off her debt\n"
            "A smuggler who runs memory crystals through the undercity."
        )
        parsed = lore_capture_parse.parse_capture_block(
            block, "character", "Fei Vaughna")
        self.assertEqual(parsed["role"], "courier")
        self.assertIn("Tall", parsed["appearance"])
        self.assertIn("debt", parsed["goals"])
        self.assertIn("smuggler", parsed["notes"])

    def test_pipe_syntax(self):
        block = "creatureType: apex predator | origin: deep marsh | powers: venom spit"
        parsed = lore_capture_parse.parse_capture_block(
            block, "creature", "Glass Eel")
        self.assertEqual(parsed["creatureType"], "apex predator")
        self.assertEqual(parsed["origin"], "deep marsh")
        self.assertEqual(parsed["powers"], "venom spit")

    def test_prose_only_falls_back_to_notes(self):
        block = "The undercity markets never close; neon rain slicks every alley."
        parsed = lore_capture_parse.parse_capture_block(block, "concept", "Undercity")
        self.assertEqual(parsed["notes"], block)

    def test_capture_from_agent_structured(self):
        with tempfile.TemporaryDirectory() as tmp:
            lore_path = os.path.join(tmp, "lore.json")
            lore.write(lore_path, {"characters": [], "world": []})
            paths = {"lore": lore_path, "bible": os.path.join(tmp, "b.json"),
                     "world_state": os.path.join(tmp, "w.json")}
            raw = (
                "[[CHARACTER:Fei Vaughna]]\n"
                "role: courier\n"
                "appearance: Lean, quick-eyed\n"
                "goals: Escape the syndicate\n"
                "[[/CHARACTER]]"
            )
            summary = worldcontext.capture_from_agent(
                paths, raw, default_kind="world", source="test")
            self.assertEqual(len(summary["lore"]), 1)
            entry = summary["lore"][0]
            self.assertEqual(entry["name"], "Fei Vaughna")
            self.assertEqual(entry["role"], "courier")
            self.assertIn("quick-eyed", entry["appearance"])
            self.assertIn("syndicate", entry["goals"])


if __name__ == "__main__":
    unittest.main()
