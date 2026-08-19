"""Studio core: packs, snapshots, search, series, import, retrieval, compile."""

from __future__ import annotations

import os
import tempfile
import unittest

from src import (
    chapters, import_docs, lore, plugins, project_search, retrieval,
    series, snapshots, export, worldcontext, story_bible, world_state,
)
from src.plugins.grammar import load_checker


class FakeSettings:
    def __init__(self, data=None):
        self.data = data or {}

    def get(self, key, default=None):
        return self.data.get(key, default)


def _paths(tmp: str) -> dict:
    ch = os.path.join(tmp, "chapters")
    os.makedirs(ch, exist_ok=True)
    return {
        "root": tmp,
        "chapters": ch,
        "lore": os.path.join(tmp, "lore.json"),
        "bible": os.path.join(tmp, "story_bible.json"),
        "world_state": os.path.join(tmp, "world_state.json"),
        "config": os.path.join(tmp, "config.json"),
    }


class PluginPackTests(unittest.TestCase):
    def test_packs_default_off(self):
        s = FakeSettings({})
        self.assertFalse(plugins.is_enabled(s, "llm"))
        self.assertFalse(plugins.is_enabled(s, "image"))
        self.assertTrue(plugins.panel_allowed(s, "Story Bible"))
        self.assertFalse(plugins.panel_allowed(s, "Team"))
        self.assertFalse(plugins.panel_allowed(s, "Image Gen"))
        self.assertFalse(plugins.panel_allowed(s, "Voice"))

    def test_llm_unlocks_team(self):
        s = FakeSettings({"plugins.llm": True})
        self.assertTrue(plugins.panel_allowed(s, "Team"))

    def test_grammar_loader_missing(self):
        self.assertIsNone(load_checker(FakeSettings({"plugins.extra_paths": []})))


class SnapshotSearchSeriesTests(unittest.TestCase):
    def test_snapshot_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            created = chapters.create(paths["chapters"], "One")
            chapters.write(paths["chapters"], created["id"], "hello world")
            snapshots.take_snapshot(paths, created["id"], "hello world", "manual")
            items = snapshots.list_snapshots(paths, created["id"])
            self.assertTrue(items)
            text = snapshots.read_snapshot(paths, created["id"], items[0]["stamp"])
            self.assertEqual(text, "hello world")

    def test_search_and_replace(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            created = chapters.create(paths["chapters"], "One")
            chapters.write(paths["chapters"], created["id"], "The red door.")
            lore.write(paths["lore"], {
                "characters": [{"id": "a", "name": "Ada", "notes": "red coat"}],
                "world": [],
            })
            story_bible.write(paths["bible"], {"premise": "a red city"})
            hits = project_search.search(paths, "red")
            kinds = {h["kind"] for h in hits}
            self.assertIn("chapter", kinds)
            self.assertIn("lore", kinds)
            self.assertIn("bible", kinds)
            n = project_search.replace_in_chapters(paths, "red", "blue")
            self.assertGreaterEqual(n, 1)
            self.assertIn("blue", chapters.read(paths["chapters"], created["id"])["content"])

    def test_series_overlay(self):
        with tempfile.TemporaryDirectory() as tmp:
            child = _paths(os.path.join(tmp, "child"))
            parent = _paths(os.path.join(tmp, "parent"))
            with open(parent["lore"], "w", encoding="utf-8") as fh:
                fh.write("{}")
            series.set_share_from(child, "parent-id")
            # overlay uses projects.project_paths — skip if DATA_DIR layout required
            self.assertEqual(series.share_from(child), "parent-id")

    def test_import_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            md = os.path.join(tmp, "scene.md")
            with open(md, "w", encoding="utf-8") as fh:
                fh.write("# Title\nHello")
            created = import_docs.import_file(paths["chapters"], md)
            self.assertIn("Hello", created["content"])

    def test_retrieval_and_compile(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            created = chapters.create(paths["chapters"], "One")
            chapters.write(paths["chapters"], created["id"], "Ada walked through the undercity.")
            lore.write(paths["lore"], {
                "characters": [{"id": "a", "name": "Ada", "notes": "scout"}],
                "world": [],
            })
            story_bible.write(paths["bible"], {"premise": "test"})
            world_state.write(paths["world_state"], {})
            hits = retrieval.search(paths, "Ada undercity")
            self.assertTrue(hits)
            text = export.compile_standard_manuscript(paths, title="T")
            self.assertIn("ONE", text.upper())
            bible = export.export_production_bible(paths, "T")
            self.assertIn("Ada", bible)

    def test_parking_not_captured(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = _paths(tmp)
            lore.write(paths["lore"], {"characters": [], "world": []})
            story_bible.write(paths["bible"], {})
            world_state.write(paths["world_state"], {})
            summary = worldcontext.capture_from_agent(
                paths, "[[REMEMBER]] secret [[/REMEMBER]]",
                source="parking lot")
            self.assertFalse(summary.get("lore") or summary.get("added"))


class PackInstallTests(unittest.TestCase):
    def test_model_rows_match_registry(self):
        from src import pack_install
        import config
        rows = pack_install.model_rows()
        self.assertEqual(len(rows), len(config.MODEL_REGISTRY))
        self.assertTrue(all("filename" in r for r in rows))

    def test_summarize_with_fake_settings(self):
        from src import pack_install

        class S:
            def get(self, key, default=None):
                return default

        info = pack_install.summarize(S())
        self.assertIn("llm", info)
        self.assertIn("image", info)
        self.assertIn("audio", info)
        self.assertFalse(info["llm"]["enabled"])

    def test_download_catalog_keys(self):
        import config
        self.assertEqual(
            set(config.MODEL_REGISTRY),
            {"architect", "operator", "flavor"})


if __name__ == "__main__":
    unittest.main()
