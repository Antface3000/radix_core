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

    def test_unmapped_ignores_title_cased_stopwords(self):
        """Regression: never .title() the manuscript (Against/Way/Can false hits)."""
        text = (
            "Against the wall she waited. Way beyond the gate something moved. "
            "Can they see her? Through the smoke them same has gone. "
            "Against the wall she waited. Way beyond. Can they. Through smoke. "
            "Them same has. Against again. Way again. Can again. Through again. "
            "She met Kaelith near the pumps and asked Kaelith about the seals "
            "before Kaelith sealed the hatch. Later she saw Kaelith again."
        )
        suggestions = lore_audit._unmapped_proper_nouns(text, entries=[])
        joined = " ".join(msg for msg, _name in suggestions).lower()
        for noise in ("against", "way", "something", "can", "through", "them",
                      "same", "has"):
            self.assertNotIn(f"'{noise}'", joined)
            self.assertNotIn(f"'{noise.title()}'", joined)
        self.assertTrue(any(name == "Kaelith" for _msg, name in suggestions))

    def test_unmapped_issue_carries_target_name(self):
        from src import chapters as ch_mod
        with tempfile.TemporaryDirectory() as tmp:
            lore_path = os.path.join(tmp, "lore.json")
            lore.write(lore_path, {"characters": [], "world": []})
            ch_dir = os.path.join(tmp, "chapters")
            created = ch_mod.create(ch_dir, "Chapter 1")
            ch_mod.write(
                ch_dir, created["id"],
                "She met Kaelith near the pumps and asked Kaelith about the "
                "seals before Kaelith sealed the hatch.\n")
            issues = lore_audit.audit_lore(
                {"lore": lore_path, "chapters": ch_dir}, orphan_scan=True)
            hits = [i for i in issues if i.code == "unmapped_proper_noun"]
            self.assertTrue(hits)
            self.assertEqual(hits[0].target_name, "Kaelith")
            self.assertIsNone(hits[0].entry_id)

    def test_draft_unmapped_entry_fills_only_definite_fields(self):
        from src import chapters as ch_mod
        with tempfile.TemporaryDirectory() as tmp:
            lore_path = os.path.join(tmp, "lore.json")
            lore.write(lore_path, {"characters": [], "world": []})
            ch_dir = os.path.join(tmp, "chapters")
            created = ch_mod.create(ch_dir, "Chapter 1")
            ch_mod.write(
                ch_dir, created["id"],
                "She met Kaelith near the pumps and asked Kaelith about the "
                "seals before Kaelith sealed the hatch. Kaelith said he would "
                "wait. Kaelith knew his luck was thin.\n")
            paths = {"lore": lore_path, "chapters": ch_dir}
            issue = lore_audit.AuditIssue(
                "info", "unmapped_proper_noun", None,
                "Manuscript mentions 'Kaelith' 4× with no lore entry.",
                target_name="Kaelith",
            )
            draft = lore_audit.draft_unmapped_entry(
                paths, "Kaelith", issue=issue)
            self.assertEqual(draft["name"], "Kaelith")
            self.assertEqual(draft["entryType"], "character")
            self.assertIn("Kaelith", draft["keywords"])
            self.assertIn("pumps", draft["notes"])
            self.assertIn("From the manuscript:", draft["notes"])
            self.assertIn("4×", draft["notes"])
            self.assertEqual(draft.get("pronouns"), "he/him")
            self.assertFalse(draft.get("appearance"))
            self.assertFalse(draft.get("role"))
            self.assertFalse(draft.get("goals"))


if __name__ == "__main__":
    unittest.main()
