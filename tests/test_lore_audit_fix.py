"""Tests for lore audit auto-fix."""

import os
import tempfile
import unittest

from src import lore, lore_audit


class LoreAuditFixTests(unittest.TestCase):
    def test_apply_type_mismatch_fix(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "lore.json")
            eid = "p1"
            lore.write(path, {
                "characters": [],
                "world": [{
                    "id": eid,
                    "name": "Dragon Peak",
                    "entryType": "character",
                    "territory": "northern range",
                    "climate": "cold",
                }],
            })
            paths = {"lore": path, "chapters": tmp}
            issues = lore_audit.audit_lore(paths, orphan_scan=False)
            fixable = [i for i in issues if i.code == "type_mismatch"]
            self.assertTrue(fixable)
            report = lore_audit.apply_fixes(paths, fixable)
            self.assertGreaterEqual(report.applied, 1)
            book = lore.read(path)
            entry = book["characters"][0] if book["characters"] else book["world"][0]
            self.assertEqual(entry["entryType"], "place")

    def test_type_mismatch_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "lore.json")
            lore.write(path, {
                "characters": [],
                "world": [{
                    "id": "p1",
                    "name": "Dragon Peak",
                    "entryType": "character",
                    "territory": "northern range",
                    "climate": "cold",
                }],
            })
            paths = {"lore": path, "chapters": tmp}
            issues = lore_audit.audit_lore(paths, orphan_scan=False)
            codes = [i.code for i in issues]
            self.assertIn("type_mismatch", codes)


if __name__ == "__main__":
    unittest.main()
