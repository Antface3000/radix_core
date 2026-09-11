"""Tests for Story Bible wizard parse, fallbacks, and merge."""

import unittest

from src import lore_types, lore_wizard


class LoreWizardTests(unittest.TestCase):
    def test_known_keys_follow_field_specs(self):
        for kind, _label, _bucket in lore_types.ENTRY_TYPES:
            keys = lore_wizard.known_keys(kind)
            self.assertIn("name", keys)
            self.assertNotIn("portraitPath", keys)
            for field, _lbl, _multi in lore_types.fields_for_entry_type(kind):
                if field != "portraitPath":
                    self.assertIn(field, keys)

    def test_canon_and_world_keys(self):
        self.assertEqual(lore_wizard.known_keys("canon"), lore_wizard.CANON_KEYS)
        self.assertEqual(lore_wizard.known_keys("world"), lore_wizard.WORLD_KEYS)

    def test_persona_mapping(self):
        self.assertEqual(lore_wizard.persona_for_kind("character")["key"], "character_dev")
        self.assertEqual(lore_wizard.persona_for_kind("creature")["key"], "creature_dev")
        self.assertEqual(lore_wizard.persona_for_kind("place")["key"], "world_builder")
        self.assertEqual(lore_wizard.persona_for_kind("thing")["key"], "world_builder")
        self.assertEqual(lore_wizard.persona_for_kind("faction")["key"], "world_builder")
        self.assertEqual(lore_wizard.persona_for_kind("event")["key"], "quest_architect")
        self.assertEqual(lore_wizard.persona_for_kind("concept")["key"], "lore_curator")
        self.assertEqual(lore_wizard.persona_for_kind("canon")["key"], "lore_curator")
        self.assertEqual(lore_wizard.persona_for_kind("world")["key"], "world_builder")

    def test_fallback_questions_for_every_kind(self):
        for kind in lore_wizard.WIZARD_KINDS:
            qs = lore_wizard.fallback_questions(kind)
            self.assertGreaterEqual(len(qs), 3, kind)
            for q in qs:
                self.assertTrue(q["id"])
                self.assertTrue(q["prompt"])
                self.assertIsInstance(q["chips"], list)
                self.assertIn(q["multi"], (True, False))

    def test_parse_questions_object_and_array(self):
        obj = lore_wizard.parse_questions(
            '{"questions":[{"id":"role","prompt":"Role?","chips":["hero"],"multi":false}]}',
            "character")
        self.assertEqual(obj[0]["id"], "role")
        self.assertEqual(obj[0]["chips"], ["hero"])
        arr = lore_wizard.parse_questions(
            '["What is the hook?", {"prompt":"Tone?","options":["grim","dry"],"multi":true}]',
            "canon")
        self.assertEqual(arr[0]["prompt"], "What is the hook?")
        self.assertTrue(arr[1]["multi"])
        self.assertEqual(arr[1]["chips"], ["grim", "dry"])

    def test_parse_questions_garbage_uses_fallback(self):
        qs = lore_wizard.parse_questions("not json at all", "place")
        self.assertEqual(qs, lore_wizard.fallback_questions("place"))

    def test_parse_fill_known_keys_only(self):
        raw = """```json
        {"name":"Ada","role":"scout","notes":"marsh born","secret":"drop me","keywords":"Ada, scout"}
        ```"""
        filled = lore_wizard.parse_fill(raw, "character")
        self.assertEqual(filled["name"], "Ada")
        self.assertEqual(filled["role"], "scout")
        self.assertEqual(filled["keywords"], ["Ada", "scout"])
        self.assertNotIn("secret", filled)

    def test_parse_fill_drops_unknown_canon_keys(self):
        filled = lore_wizard.parse_fill(
            '{"premise":"A city sinks.","logline":"nope","pointOfView":"x"}',
            "canon")
        self.assertEqual(filled, {"premise": "A city sinks."})

    def test_merge_without_clobber(self):
        existing = {"name": "Ada", "role": "scout", "notes": ""}
        generated = {"name": "Ada Voss", "role": "captain", "notes": "from the marsh"}
        merged = lore_wizard.merge_without_clobber(existing, generated, replace=False)
        self.assertEqual(merged["name"], "Ada")
        self.assertEqual(merged["role"], "scout")
        self.assertEqual(merged["notes"], "from the marsh")
        replaced = lore_wizard.merge_without_clobber(existing, generated, replace=True)
        self.assertEqual(replaced["name"], "Ada Voss")
        self.assertEqual(replaced["role"], "captain")

    def test_merge_ignores_empty_generated(self):
        existing = {"notes": "keep"}
        merged = lore_wizard.merge_without_clobber(
            existing, {"notes": "  ", "role": ""}, replace=True)
        self.assertEqual(merged["notes"], "keep")

    def test_chip_phrases_fill_and_clear_answer_text(self):
        self.assertEqual(lore_wizard.insert_chip_phrase("", "protagonist"), "protagonist")
        self.assertEqual(
            lore_wizard.insert_chip_phrase("reluctant", "protagonist"),
            "reluctant, protagonist")
        self.assertEqual(
            lore_wizard.insert_chip_phrase("protagonist", "protagonist"),
            "protagonist")
        self.assertEqual(
            lore_wizard.remove_chip_phrase("reluctant, protagonist", "protagonist"),
            "reluctant")
        self.assertEqual(lore_wizard.remove_chip_phrase("protagonist", "protagonist"), "")
        self.assertEqual(
            lore_wizard.remove_chip_phrase("a weathered scout", "weathered"),
            "a weathered scout")

    def test_format_answers_skips_chips_already_in_text(self):
        block = lore_wizard.format_answers({
            "role": {"prompt": "Role?", "chips": ["protagonist"], "text": "protagonist"},
        })
        self.assertEqual(block.count("protagonist"), 1)

    def test_format_answers_and_prompts(self):
        answers = {
            "role": {"prompt": "Role?", "chips": ["protagonist"], "text": "reluctant"},
            "skip": {"prompt": "Empty", "chips": [], "text": ""},
        }
        block = lore_wizard.format_answers(answers)
        self.assertIn("Role?", block)
        self.assertIn("protagonist", block)
        self.assertNotIn("Empty", block)
        system, user = lore_wizard.build_questions_prompt(
            "character", seed="Ada", existing={"name": "Ada"}, setting="=== SETTING ===")
        self.assertIn("STRICT JSON", system)
        self.assertIn("Ada", user)
        self.assertIn("SETTING", user)
        system2, user2 = lore_wizard.build_fill_prompt(
            "character", seed="Ada", answers=answers, existing={"name": "Ada"})
        self.assertIn("name", user2)
        self.assertIn("INTERVIEW ANSWERS", user2)
        self.assertIn("Character Profiler", system2)
        self.assertIn("STRICT JSON", system2)
        self.assertNotIn("PERSISTENCE:", system2)
        self.assertNotIn("Shadow Log", system2)

    def test_parse_fill_wrapped_and_aliased_keys(self):
        wrapped = lore_wizard.parse_fill(
            '{"entry":{"name":"Ada","description":"rain-cut coat","Role":"scout"}}',
            "character")
        self.assertEqual(wrapped["name"], "Ada")
        self.assertEqual(wrapped["appearance"], "rain-cut coat")
        self.assertEqual(wrapped["role"], "scout")

    def test_parse_fill_repairs_trailing_comma(self):
        filled = lore_wizard.parse_fill(
            '{"name":"Ada","role":"scout",}', "character")
        self.assertEqual(filled["name"], "Ada")

    def test_complete_fill_uses_interview_when_json_empty(self):
        answers = {
            "role": {"prompt": "Role?", "chips": ["protagonist"], "text": "reluctant"},
            "looks": {"prompt": "Look?", "chips": [], "text": "weathered"},
        }
        filled = lore_wizard.complete_fill(
            "Sure, I can help with that.", "character",
            seed="Ada Voss — marsh scout", answers=answers)
        self.assertEqual(filled["name"], "Ada Voss")
        self.assertIn("reluctant", filled["role"])
        self.assertEqual(filled["appearance"], "weathered")
        self.assertTrue(lore_wizard.fill_has_content(filled))
        self.assertFalse(lore_wizard.fill_has_content({"name": "New entry"}))

    def test_complete_fill_json_wins_over_interview(self):
        filled = lore_wizard.complete_fill(
            '{"name":"Ada","role":"captain"}', "character",
            seed="Other", answers={"role": {"text": "scout", "chips": []}})
        self.assertEqual(filled["name"], "Ada")
        self.assertEqual(filled["role"], "captain")

    def test_complete_fill_reads_character_marker(self):
        raw = (
            "[[CHARACTER:Ada Voss]]\n"
            "role: scout\n"
            "appearance: rain-cut coat\n"
            "[[/CHARACTER]]"
        )
        filled = lore_wizard.complete_fill(raw, "character")
        self.assertEqual(filled["name"], "Ada Voss")
        self.assertEqual(filled["role"], "scout")
        self.assertIn("rain-cut", filled["appearance"])


if __name__ == "__main__":
    unittest.main()
