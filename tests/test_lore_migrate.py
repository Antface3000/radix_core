"""Tests for lore migration heuristics."""

import os
import tempfile
import unittest

from src import lore, lore_migrate


class LoreMigrateTests(unittest.TestCase):
    def test_infer_creature_from_species(self):
        entry = {"type": "world", "name": "Dragon", "species": "wyrm", "powers": "fire"}
        self.assertEqual(lore_migrate.infer_entry_type(entry), "creature")

    def test_migrate_moves_creature_to_characters_bucket(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "lore.json")
            raw = {
                "characters": [],
                "world": [{
                    "id": "x1",
                    "name": "Ash Wyrm",
                    "type": "world",
                    "species": "dragon",
                    "powers": "fire breath",
                }],
            }
            lore.write(path, raw)
            paths = {"lore": path}
            report = lore_migrate.migrate_lore(paths, dry_run=True)
            self.assertGreaterEqual(report.changed, 1)
            lore_migrate.migrate_lore(paths, dry_run=False)
            book = lore.read(path)
            self.assertEqual(len(book["world"]), 0)
            self.assertEqual(len(book["characters"]), 1)
            self.assertEqual(book["characters"][0]["entryType"], "creature")

    def test_save_entry_keeps_notes_when_moving_person_to_place(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "lore.json")
            created = lore.add(path, {
                "name": "Tito",
                "entryType": "character",
                "notes": "Dock worker who knows too much.",
                "keywords": ["Tito"],
            })
            saved = lore.save_entry(path, {
                **created,
                "entryType": "place",
                "type": "world",
            })
            book = lore.read(path)
            self.assertEqual(len(book["characters"]), 0)
            self.assertEqual(len(book["world"]), 1)
            row = book["world"][0]
            self.assertEqual(row["id"], created["id"])
            self.assertEqual(row["entryType"], "place")
            self.assertEqual(row["notes"], "Dock worker who knows too much.")
            self.assertIn("Tito", row.get("keywords") or [])
            self.assertEqual(saved["notes"], row["notes"])


if __name__ == "__main__":
    unittest.main()
