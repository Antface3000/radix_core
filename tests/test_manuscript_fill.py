"""Tests for manuscript → canon field extraction."""

import os
import tempfile
import unittest

from src import chapters, lore, manuscript_fill, outline, story_bible, world_state


def _paths(tmp: str) -> dict:
    ch = os.path.join(tmp, "chapters")
    os.makedirs(ch, exist_ok=True)
    return {
        "root": tmp,
        "chapters": ch,
        "lore": os.path.join(tmp, "lore.json"),
        "bible": os.path.join(tmp, "story_bible.json"),
        "world_state": os.path.join(tmp, "world_state.json"),
        "outlines": os.path.join(tmp, "outlines.json"),
    }


class ManuscriptFillTests(unittest.TestCase):
    def test_infer_past_third(self):
        text = (
            "She walked to the lock. He looked at the gauges. They turned "
            "the wheel. She said nothing. He took the lamp. She felt the "
            "heat. He knew the watch. She asked him to wait. He told her "
            "to move. She stood still. He sat down. She heard the pump. "
            "He left the hatch. She made a mark."
        )
        self.assertEqual(manuscript_fill.infer_tense(text), "past")
        self.assertEqual(manuscript_fill.infer_point_of_view(text), "third person")

    def test_infer_present_first(self):
        text = (
            "I walk the lock. I look at the gauges. I turn the wheel. "
            "I take the lamp. I feel the heat. I know the watch. I ask "
            "them to wait. I tell her to move. I stand still. I sit down. "
            "I hear the pump. I leave the hatch. I make a mark. My hands shake."
        )
        self.assertEqual(manuscript_fill.infer_tense(text), "present")
        self.assertEqual(manuscript_fill.infer_point_of_view(text), "first person")

    def test_infer_skips_mixed(self):
        text = "She was there. I am here. You are late."
        self.assertEqual(manuscript_fill.infer_tense(text), "")
        self.assertEqual(manuscript_fill.infer_point_of_view(text), "")

    def test_parse_payload_known_keys_only(self):
        raw = """```json
        {"bible":{"tense":"past","pointOfView":"third person","secret":"nope"},
         "world":{"currentLocation":"the lock","bogus":1},
         "chapter":{"pov":"Ada","location":"pump house"},
         "outline":{"summary":"Night watch","beats":["Ada waits","Hatch fails"]},
         "lore":[{"name":"Ada","entryType":"character","role":"scout","secret":"x"},
                 {"entryType":"place"}]}
        ```"""
        payload = manuscript_fill.parse_payload(raw)
        self.assertEqual(payload["bible"]["tense"], "past")
        self.assertNotIn("secret", payload["bible"])
        self.assertEqual(payload["world"]["currentLocation"], "the lock")
        self.assertNotIn("bogus", payload["world"])
        self.assertEqual(payload["chapter"]["pov"], "Ada")
        self.assertEqual(payload["outline"]["beats"], ["Ada waits", "Hatch fails"])
        self.assertEqual(len(payload["lore"]), 1)
        self.assertEqual(payload["lore"][0]["name"], "Ada")
        self.assertEqual(payload["lore"][0]["role"], "scout")
        self.assertNotIn("secret", payload["lore"][0])

    def test_merge_heuristics_do_not_override_model(self):
        payload = {"bible": {"tense": "present"}, "world": {}, "chapter": {},
                   "outline": {}, "lore": []}
        merged = manuscript_fill.merge_heuristics(
            payload, {"tense": "past", "pointOfView": "third person"})
        self.assertEqual(merged["bible"]["tense"], "present")
        self.assertEqual(merged["bible"]["pointOfView"], "third person")

    def test_apply_payload_fills_blanks_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            created = chapters.create(paths["chapters"], "One")
            chapters.write(paths["chapters"], created["id"], "Ada waited at the lock.")
            story_bible.write(paths["bible"], {"tense": "past", "premise": ""})
            world_state.write(paths["world_state"], {"currentLocation": "old mill"})
            lore.write(paths["lore"], {
                "characters": [{"id": "a", "name": "Ada", "entryType": "character",
                                "role": "scout", "notes": ""}],
                "world": [],
            })
            payload = {
                "bible": {"tense": "present", "premise": "A city sinks."},
                "world": {"currentLocation": "the lock", "currentDate": "third watch"},
                "chapter": {"pov": "Ada", "location": "the lock"},
                "outline": {"summary": "Night watch", "beats": ["Ada waits"]},
                "lore": [{"name": "Ada", "entryType": "character",
                          "role": "captain", "notes": "from the marsh"}],
            }
            counts = manuscript_fill.apply_payload(
                paths, payload, replace=False, chapter_id=created["id"])
            bible = story_bible.read(paths["bible"])
            self.assertEqual(bible["tense"], "past")
            self.assertEqual(bible["premise"], "A city sinks.")
            ws = world_state.read(paths["world_state"])
            self.assertEqual(ws["currentLocation"], "old mill")
            self.assertEqual(ws["currentDate"], "third watch")
            meta = chapters.read(paths["chapters"], created["id"])
            self.assertEqual(meta["pov"], "Ada")
            ol = outline.read_chapter(paths["outlines"], created["id"])
            self.assertEqual(ol["summary"], "Night watch")
            book = lore.read(paths["lore"])
            ada = book["characters"][0]
            self.assertEqual(ada["role"], "scout")
            self.assertEqual(ada["notes"], "from the marsh")
            self.assertGreater(counts["bible"], 0)
            self.assertGreater(counts["lore"], 0)

    def test_collect_manuscript_prefers_current_and_caps(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            a = chapters.create(paths["chapters"], "A")
            b = chapters.create(paths["chapters"], "B")
            chapters.write(paths["chapters"], a["id"], "A" * 200)
            chapters.write(paths["chapters"], b["id"], "B" * 200)
            packed = manuscript_fill.collect_manuscript(
                paths, [a["id"], b["id"]], prefer_id=b["id"],
                per_chapter=80, total=150)
            self.assertTrue(packed["text"].startswith("=== CHAPTER: B ==="))
            self.assertLessEqual(len(packed["text"]), 160)
            self.assertIn(b["id"], packed["used_ids"])


if __name__ == "__main__":
    unittest.main()
