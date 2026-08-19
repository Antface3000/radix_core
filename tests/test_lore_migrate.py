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


if __name__ == "__main__":
    unittest.main()
