"""Tests for lore capture validation."""

import unittest

from src import lore_capture_guard as guard


class LoreCaptureGuardTests(unittest.TestCase):
    def test_rejects_meta_question_name(self):
        self.assertFalse(guard.is_valid_capture_name(
            "or something similar? Wait, no. The setting says"))
        self.assertIsNone(guard.derive_capture_name(
            "or something similar? Wait, no. The setting says tags?"))

    def test_rejects_marker_discussion(self):
        body = "for general facts, [[CHARACTER]] for character profiles (but"
        self.assertFalse(guard.is_valid_capture_body(body))

    def test_accepts_real_character_note(self):
        body = "Fei Vaughna is a courier who smuggles memory crystals through the undercity."
        name = guard.derive_capture_name(body, "Fei Vaughna")
        self.assertEqual(name, "Fei Vaughna")
        self.assertTrue(guard.is_valid_capture_body(body))


if __name__ == "__main__":
    unittest.main()
