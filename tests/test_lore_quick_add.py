"""Tests for lore quick-add line parser."""

import os
import tempfile
import unittest

from src import lore, lore_quick_add, lore_types


class LoreQuickAddTests(unittest.TestCase):
    def test_plain_name_notes(self):
        rows = lore_quick_add.parse_quick_add_lines("Alice: brave scout")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Alice")
        self.assertEqual(rows[0]["entryType"], "character")
        self.assertIn("brave scout", rows[0]["notes"])

    def test_creature_prefix_and_pipes(self):
        rows = lore_quick_add.parse_quick_add_lines(
            "creature: Smaug | type: dragon | notes: hoard guardian")
        self.assertEqual(rows[0]["entryType"], "creature")
        self.assertEqual(rows[0]["creatureType"], "dragon")
        self.assertEqual(rows[0]["notes"], "hoard guardian")

    def test_legacy_world_prefix(self):
        rows = lore_quick_add.parse_quick_add_lines(
            "world: The Undercity: flooded tier")
        self.assertEqual(rows[0]["entryType"], "place")
        self.assertEqual(rows[0]["name"], "The Undercity")

    def test_comments_skipped(self):
        rows = lore_quick_add.parse_quick_add_lines("# comment\n\nBob: notes")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Bob")

    def test_apply_add(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "lore.json")
            lore.write(path, {"characters": [], "world": []})
            summary = lore_quick_add.apply_quick_add(
                path, "place: Mill Town: quiet village\nNPC: Guard",
                default_type="character")
            self.assertEqual(summary["added"], 2)
            book = lore.read(path)
            self.assertEqual(len(book["world"]), 1)
            self.assertEqual(book["world"][0]["entryType"], "place")


if __name__ == "__main__":
    unittest.main()
