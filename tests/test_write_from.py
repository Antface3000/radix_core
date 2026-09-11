"""Smoke tests for Write continue-from context prefix rules."""

from __future__ import annotations

import unittest


def write_context_prefix(text, selection, write_from, cursor_pos):
    """Mirror EditorWidget._write_context_prefix without Qt."""
    if selection:
        idx = text.find(selection)
        if idx >= 0:
            return text[:idx + len(selection)], "selection"
    if write_from == "end":
        return text, "end"
    pos = max(0, min(cursor_pos, len(text)))
    return text[:pos], "cursor"


class WriteFromTests(unittest.TestCase):
    def test_cursor_uses_prefix(self):
        text = "AAA BBB CCC"
        before, mode = write_context_prefix(text, "", "cursor", 3)
        self.assertEqual(before, "AAA")
        self.assertEqual(mode, "cursor")

    def test_end_uses_full_chapter(self):
        text = "AAA BBB CCC"
        before, mode = write_context_prefix(text, "", "end", 3)
        self.assertEqual(before, text)
        self.assertEqual(mode, "end")

    def test_selection_overrides_end(self):
        text = "AAA BBB CCC"
        before, mode = write_context_prefix(text, "BBB", "end", 0)
        self.assertEqual(before, "AAA BBB")
        self.assertEqual(mode, "selection")


if __name__ == "__main__":
    unittest.main()
