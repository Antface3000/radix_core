"""Tests for rule-based lore audit."""

import os
import tempfile
import unittest

from src import lore, lore_audit


class LoreAuditTests(unittest.TestCase):
    def test_duplicate_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "lore.json")
            lore.write(path, {
                "characters": [
                    {"id": "a", "name": "Alice", "entryType": "character"},
                    {"id": "b", "name": "alice", "entryType": "character"},
                ],
                "world": [],
            })
            paths = {"lore": path, "chapters": tmp}
            issues = lore_audit.audit_lore(paths, orphan_scan=False)
            codes = [i.code for i in issues]
            self.assertIn("duplicate_name", codes)

    def test_thin_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "lore.json")
            lore.write(path, {
                "characters": [{"id": "a", "name": "Bob", "entryType": "character"}],
                "world": [],
            })
            paths = {"lore": path, "chapters": tmp}
            issues = lore_audit.audit_lore(paths, orphan_scan=False)
            self.assertTrue(any(i.code == "thin_entry" for i in issues))


if __name__ == "__main__":
    unittest.main()
