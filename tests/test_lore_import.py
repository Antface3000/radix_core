"""Sudowrite-style character CSV import."""

import os
import tempfile
import unittest

from src import lore, lore_import, lore_types


SAMPLE = '''Name,Role,Pronouns,Groups,Other Names,Personality,Physical Description,Dialogue Style
Laura Reeves,protagonist,she/her,,"Dr. Reeves, ""The Ruin Chaser""","A brilliant mind trapped in self-doubt.","Mid-forties with prematurely graying hair.","Speaks in clipped, authoritative sentences."
'''


class LoreImportTests(unittest.TestCase):
    def test_parse_sudowrite_headers(self):
        rows = lore_import.parse_character_csv(SAMPLE)
        self.assertEqual(len(rows), 1)
        e = rows[0]
        self.assertEqual(e["name"], "Laura Reeves")
        self.assertEqual(e["role"], "protagonist")
        self.assertEqual(e["pronouns"], "she/her")
        self.assertIn("Dr. Reeves", e["aliases"])
        self.assertTrue(any("Ruin Chaser" in a for a in e["aliases"]))
        self.assertFalse(any(a.startswith("The Ruin Chaser\"") for a in e["aliases"]))
        self.assertIn("self-doubt", e["personality"])
        self.assertIn("graying", e["appearance"])
        self.assertIn("clipped", e["voiceStyle"])

    def test_character_fields_include_personality(self):
        keys = [k for k, _, _ in lore_types.fields_for_entry_type("character")]
        self.assertIn("personality", keys)
        self.assertIn("groups", keys)

    def test_upsert_into_lore(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "lore.json")
            lore.write(path, {
                "characters": [{
                    "id": "a",
                    "name": "Laura Reeves",
                    "entryType": "character",
                    "role": "Main Protagonist",
                }],
                "world": [],
            })
            report = lore_import.import_character_csv(path, SAMPLE, mode="upsert")
            self.assertEqual(report["updated"], 1)
            book = lore.read(path)
            e = book["characters"][0]
            self.assertEqual(e["pronouns"], "she/her")
            self.assertIn("self-doubt", e["personality"])
            self.assertTrue(e["appearance"])
            self.assertTrue(e["voiceStyle"])


if __name__ == "__main__":
    unittest.main()
