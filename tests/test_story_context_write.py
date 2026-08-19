"""Write output sanitization (overlap trim)."""

import unittest

from src.story_context import sanitize_write_output, _strip_story_overlap


class StoryContextWriteTests(unittest.TestCase):
    def test_strip_story_overlap_chars(self):
        story = "She walked into the neon rain."
        draft = "She walked into the neon rain. The alley smelled of ozone."
        self.assertEqual(_strip_story_overlap(story, draft),
                         "The alley smelled of ozone.")

    def test_strip_story_overlap_words(self):
        story = "The door creaked open slowly"
        draft = "The door creaked open slowly and she stepped inside."
        self.assertEqual(_strip_story_overlap(story, draft),
                         "and she stepped inside.")

    def test_sanitize_write_output_strips_fence_and_overlap(self):
        story = "End of scene."
        raw = "```\nEnd of scene. New action here.\n```"
        self.assertEqual(sanitize_write_output(raw, story_tail=story),
                         "New action here.")

    def test_strip_self_repetition(self):
        from src.story_context import _strip_self_repetition
        para = (
            "She ran through the alley, legs shaking, corporate sirens fading "
            "behind her as the pack closed in around the flickering neon."
        )
        repeated = f"{para}\n\n{para}\n\nMore text that should be dropped."
        result = _strip_self_repetition(repeated)
        self.assertNotIn("More text", result)
        self.assertIn("She ran through", result)


if __name__ == "__main__":
    unittest.main()
