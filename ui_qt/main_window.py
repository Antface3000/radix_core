"""Radix Core v1 — PySide6 MainWindow."""

from __future__ import annotations

import config
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QMainWindow,
    QProgressBar,
    QStatusBar,
    QLabel,
    QMessageBox,
    QToolBar,
    QWidget,
)


class _ClickLabel(QLabel):
    clicked = Signal()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

from src.plugins import is_enabled, panel_allowed, PACK_LABELS
from src.logutil import get_logger
from src.settings import Settings
from src.engine import AgentEngine
from src.writing_engine import WritingEngine
from src.comfyui import ComfyClient
from src.tts import TTSClient

from ui_qt.theme import load_stylesheet
from ui_qt.widgets.editor import EditorWidget
from ui_qt.widgets.feature_lightbox import FeatureLightbox
from ui_qt.panels.storybible_panel import StoryBiblePanel
from ui_qt.panels.team_panel import TeamPanel
from ui_qt.panels.projects_panel import ProjectsPanel
from ui_qt.panels.settings_panel import SettingsPanel
from ui_qt.panels.help_panel import HelpPanel
from ui_qt.panels.addons_panel import AddOnsPanel
from ui_qt.panels.imagegen_panel import ImageGenPanel
from ui_qt.panels.voice_panel import VoicePanel
from ui_qt.panels.focus_panel import FocusPanel
from ui_qt.widgets.spellcheck import (
    SpellCheckWatcher,
    install_spellcheck_subtree,
    set_spellcheck_enabled,
)

log = get_logger("ui")


class MainWindow(QMainWindow):
    DEFAULT_PANEL = "Story Bible"

    request_flush = Signal()
    request_capture = Signal()

    def __init__(self):
        super().__init__()
        projects.ensure_initialized()
        self.settings = Settings()
        self.engine = AgentEngine(settings=self.settings)
        self.request_flush.connect(
            self.flush_project_context, Qt.ConnectionType.QueuedConnection)
        self.request_capture.connect(
            self._schedule_capture_refresh, Qt.ConnectionType.QueuedConnection)
        self.engine.flush_callback = self.request_flush.emit
        self.engine.capture_callback = self.request_capture.emit
        self._capture_refresh_timer = QTimer(self)
        self._capture_refresh_timer.setSingleShot(True)
        self._capture_refresh_timer.timeout.connect(self.refresh_canon_panels)
        self.writing = WritingEngine(self.engine)
        self.comfy = ComfyClient(self.settings, self.engine)
        self.tts = TTSClient(self.settings)
        self.editor: EditorWidget | None = None
        self._panels: dict[str, object] = {}
        self._lightboxes: dict[str, FeatureLightbox] = {}
        self._feature_actions: dict[str, QAction] = {}
        self._panel_holder = QWidget()
        self._panel_holder.hide()
        self._shutting_down = False
        self._lightboxes_restored = False
        self._startup_done = False
        self._service_worker = None
        self._update_check_worker = None
        self._service_health: dict = {}

        self.setWindowTitle(f"{config.APP_TITLE} v{config.APP_VERSION}")
        self.resize(1280, 820)
        self.setStyleSheet(load_stylesheet())

        self._build_editor()
        self._build_toolbar()
        self._build_statusbar()
        self._register_features()
        self._migrate_pinned_panels()
        set_spellcheck_enabled(self.settings.get("editor.spellcheck", True))
        self._spell_watcher = SpellCheckWatcher(self, self)
        install_spellcheck_subtree(self._panel_holder)
        self.refresh_header()
        self.update_capture_chip()
        self.apply_plugin_chrome()

        self._heartbeat = QTimer(self)
        self._heartbeat.timeout.connect(self._tick_services)

        log.info("Main window ready (project=%s)", self.engine.project_id)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._startup_done:
            self._startup_done = True
            QTimer.singleShot(0, self._run_startup_sequence)

    def _run_startup_sequence(self):
        from ui_qt.startup_flow import run_startup_flow
        run_startup_flow(self)
        if not self._lightboxes_restored:
            self._lightboxes_restored = True
            self._restore_lightboxes()
        interval = int(self.settings.get(
            "services.heartbeat_interval_s", config.HEARTBEAT_INTERVAL_S))
        self._heartbeat.start(max(5000, interval * 1000))

    def _sync_feature_action(self, name: str):
        act = self._feature_actions.get(name)
        lb = self._lightboxes.get(name)
        if not act:
            return
        act.blockSignals(True)
        act.setChecked(lb is not None and lb.isVisible())
        act.blockSignals(False)

    def _build_editor(self):
        self.editor = EditorWidget(self)
        self.setCentralWidget(self.editor)
        self.editor.word_count_changed.connect(self._update_word_count)

    def _build_toolbar(self):
        tb = QToolBar("Features")
        tb.setMovable(False)
        tb.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.addToolBar(Qt.LeftToolBarArea, tb)
        self._feature_toolbar = tb

    def _build_statusbar(self):
        sb = QStatusBar()
        self.setStatusBar(sb)
        self._project_lbl = _ClickLabel("")
        self._project_lbl.setToolTip("Click to open Projects panel")
        self._project_lbl.setProperty("chip", True)
        self._project_lbl.clicked.connect(lambda: self.show_feature("Projects"))
        self._canon_lbl = _ClickLabel("")
        self._canon_lbl.setToolTip(
            "Agents proposed canon updates — click to review and approve.")
        self._canon_lbl.setProperty("chip", True)
        self._canon_lbl.setProperty("accent", True)
        self._canon_lbl.clicked.connect(self.open_capture_review)
        self._canon_lbl.hide()
        self._mock_lbl = _ClickLabel("MOCK MODE")
        self._mock_lbl.setProperty("chip", True)
        self._mock_lbl.setProperty("warn", True)
        self._mock_lbl.clicked.connect(lambda: self.show_feature("Add Ons"))
        self._mock_lbl.hide()
        self._world_lbl = _ClickLabel("")
        self._world_lbl.setToolTip("Click to open Story Bible → World State")
        self._world_lbl.setProperty("chip", True)
        self._world_lbl.clicked.connect(self._open_world_state)
        self._goal_bar = QProgressBar()
        self._goal_bar.setTextVisible(False)
        self._goal_bar.setFixedWidth(90)
        self._goal_bar.setFixedHeight(10)
        self._goal_bar.hide()
        self._word_lbl = QLabel("0 words")
        self._word_lbl.setProperty("chip", True)
        self._session_lbl = QLabel("")
        self._session_lbl.setProperty("chip", True)
        self._pack_dots = {}
        for key in ("llm", "image", "audio"):
            dot = QLabel("●")
            dot.setToolTip(f"{PACK_LABELS[key]} pack")
            dot.hide()
            self._pack_dots[key] = dot
        sb.addWidget(self._project_lbl, 1)
        sb.addPermanentWidget(self._mock_lbl)
        for dot in self._pack_dots.values():
            sb.addPermanentWidget(dot)
        sb.addPermanentWidget(self._canon_lbl)
        sb.addPermanentWidget(self._world_lbl)
        sb.addPermanentWidget(self._goal_bar)
        sb.addPermanentWidget(self._session_lbl)
        sb.addPermanentWidget(self._word_lbl)
        self._update_mock_pill()

    def _register_features(self):
        features = [
            ("Story Bible", StoryBiblePanel),
            ("Team", TeamPanel),
            ("Projects", ProjectsPanel),
            ("Image Gen", ImageGenPanel),
            ("Voice", VoicePanel),
            ("Focus", FocusPanel),
            ("Add Ons", AddOnsPanel),
            ("Help", HelpPanel),
            ("Settings", SettingsPanel),
        ]
        self._features = features
        self._feature_map = dict(features)
        for name, _cls in features:
            act = QAction(name, self)
            act.setCheckable(True)
            act.triggered.connect(lambda _checked=False, n=name: self.show_feature(n))
            self._feature_toolbar.addAction(act)
            self._feature_actions[name] = act

    def _ensure_panel(self, name: str):
        if name in self._panels:
            return self._panels[name]
        cls = self._feature_map.get(name)
        if cls is None:
            log.warning("Unknown feature panel: %s", name)
            return None
        try:
            panel = cls(self) if isinstance(cls, type) else cls(self)
            panel.setParent(self._panel_holder)
            self._panels[name] = panel
            install_spellcheck_subtree(panel)
            log.debug("Created panel: %s", name)
            return panel
        except Exception:
            log.exception("Failed to create panel: %s", name)
            raise

    def _geometry_key(self, name: str) -> str:
        if name == "Add Ons":
            legacy = self.settings.get("ui.lightbox_geometry.setup")
            current = self.settings.get(self._geometry_key_for(name))
            if legacy and not current:
                self.settings.set(self._geometry_key_for(name), legacy, save=True)
        return self._geometry_key_for(name)

    @staticmethod
    def _geometry_key_for(name: str) -> str:
        safe = name.replace(" ", "_").lower()
        return f"ui.lightbox_geometry.{safe}"

    def _migrate_pinned_panels(self):
        pinned = list(self.settings.get("ui.pinned_panels") or [])
        changed = False
        out: list[str] = []
        for name in pinned:
            if name in ("Setup", "Music"):
                if "Add Ons" not in out:
                    out.append("Add Ons")
                changed = True
            elif name == "Agents":
                if "Team" not in out:
                    out.append("Team")
                changed = True
            elif name == "Plan":
                if "Team" not in out:
                    out.append("Team")
                changed = True
            elif name not in out:
                out.append(name)
        if changed:
            self.settings.set("ui.pinned_panels", out, save=True)

    def _save_lightbox_geometry(self, name: str, geo: dict):
        self.settings.set(self._geometry_key(name), geo, save=True)

    def _open_lightbox(self, name: str, *, focus: bool = False) -> FeatureLightbox | None:
        panel = self._ensure_panel(name)
        if panel is None:
            return None

        lb = self._lightboxes.get(name)
        if lb is None:
            lb = FeatureLightbox(name, self)
            lb.closed.connect(self._on_lightbox_closed)
            lb.stay_open_changed.connect(self._on_stay_open_changed)
            lb.geometry_saved.connect(self._save_lightbox_geometry)
            geo = self.settings.get(self._geometry_key(name))
            lb.restore_geometry(geo)
            self._lightboxes[name] = lb

        lb.set_content(panel)
        install_spellcheck_subtree(panel)
        pinned = self.settings.get("ui.pinned_panels") or []
        lb.stay_open.setChecked(name in pinned)
        lb.show()
        lb.raise_()
        if focus:
            lb.activateWindow()

        self._sync_feature_action(name)

        if hasattr(panel, "on_show"):
            try:
                panel.on_show()
            except Exception as exc:
                log.exception("Panel on_show failed: %s", name)
                self.show_toast(f"Could not open {name}: {exc}", error=True)
        return lb

    def open_team(self, initial_message: str = "", mode: str = "single", tab: int | None = None):
        """Open Team lightbox; optionally pre-fill message and tab from editor."""
        self.show_feature("Team")
        panel = self._panels.get("Team")
        if panel and hasattr(panel, "prepare_from_editor"):
            panel.prepare_from_editor(initial_message, mode, tab=tab)

    def open_agents(self, initial_message: str = "", mode: str = "single"):
        """Legacy alias for open_team."""
        self.open_team(initial_message, mode)

    def show_feature(self, name: str):
        """Open or toggle a feature lightbox."""
        team_tab = None
        if name == "Plan":
            team_tab = TeamPanel.TAB_PLAN
            name = "Team"
        elif name == "Agents":
            name = "Team"
        if name not in self._feature_map:
            return
        if not panel_allowed(self.settings, name):
            self.show_toast(
                f"{name} needs an Add Ons pack enabled first.", error=True)
            self.show_feature("Add Ons")
            return

        lb = self._lightboxes.get(name)
        if lb and lb.isVisible():
            if lb.stay_open.isChecked():
                lb.raise_()
                lb.activateWindow()
                if team_tab is not None:
                    panel = self._panels.get(name)
                    if panel and hasattr(panel, "show_plan_tab"):
                        panel.show_plan_tab()
                return
            self._close_lightbox(name)
            return

        single_mode = self.settings.get("ui.lightbox_single_mode", "replace")
        if single_mode == "replace":
            for other, other_lb in list(self._lightboxes.items()):
                if other != name and other_lb.isVisible():
                    if not other_lb.stay_open.isChecked():
                        self._close_lightbox(other)

        self._open_lightbox(name, focus=True)
        if team_tab is not None:
            panel = self._panels.get(name)
            if panel and hasattr(panel, "show_plan_tab"):
                panel.show_plan_tab()

    def _close_lightbox(self, name: str):
        lb = self._lightboxes.get(name)
        if lb and lb.isVisible():
            lb.close()

    def _on_lightbox_closed(self, name: str):
        if self._shutting_down:
            return
        panel = self._panels.get(name)
        if panel:
            panel.setParent(self._panel_holder)
        lb = self._lightboxes.pop(name, None)
        if lb:
            lb.deleteLater()
        self._sync_feature_action(name)
        log.debug("Lightbox closed: %s", name)

    def _on_stay_open_changed(self, name: str, pinned: bool):
        pinned_list = list(self.settings.get("ui.pinned_panels") or [])
        if pinned and name not in pinned_list:
            pinned_list.append(name)
        elif not pinned and name in pinned_list:
            pinned_list.remove(name)
        self.settings.set("ui.pinned_panels", pinned_list, save=True)

    def _restore_lightboxes(self):
        """Restore only panels the user pinned with Stay open."""
        pinned = self.settings.get("ui.pinned_panels") or []
        for name in pinned:
            if name in self._feature_map and panel_allowed(self.settings, name):
                self._open_lightbox(name)

    def _open_world_state(self):
        self.show_feature("Story Bible")
        panel = self._panels.get("Story Bible")
        if panel and hasattr(panel, "show_world_state_tab"):
            panel.show_world_state_tab()

    def open_lore_entry(self, entry_id: str):
        """Open Story Bible lore tab and select an entry (audit jump-to)."""
        self.show_feature("Story Bible")
        panel = self._panels.get("Story Bible")
        if panel and hasattr(panel, "select_lore_entry"):
            panel.select_lore_entry(entry_id)

    def switch_project(self, project_id: str):
        try:
            self.engine.set_project(project_id)
        except Exception as exc:
            log.exception("Project switch failed: %s", project_id)
            self.show_toast(f"Could not switch project: {exc}", error=True)
            return
        self.refresh_header()
        self.refresh_worldbar()
        self.update_capture_chip()
        if self.editor:
            self.editor.on_project_change()
        for panel in self._panels.values():
            if hasattr(panel, "on_project_change"):
                try:
                    panel.on_project_change()
                except Exception:
                    log.exception("on_project_change failed on %s", type(panel).__name__)
        proj = self.engine.active_project()
        name = proj["name"] if proj else project_id
        self.show_toast(f"Switched to {name}")
        log.info("Active project: %s (%s)", name, project_id)

    def flush_project_context(self):
        panel = self._panels.get("Story Bible")
        if panel and hasattr(panel, "flush_if_dirty"):
            try:
                panel.flush_if_dirty()
            except Exception:
                log.exception("Story Bible flush failed")
        if self.editor:
            try:
                self.editor.flush()
            except Exception:
                log.exception("Editor autosave flush failed")

    def _schedule_capture_refresh(self):
        """Coalesce capture UI refreshes (safe from worker threads via signal)."""
        if not self._capture_refresh_timer.isActive():
            self._capture_refresh_timer.start(300)

    def refresh_canon_panels(self):
        panel = self._panels.get("Story Bible")
        if panel and hasattr(panel, "reload"):
            try:
                panel.reload()
            except Exception as exc:
                log.exception("Canon panel reload failed")
                self.show_toast(f"Could not refresh canon data: {exc}", error=True)
        self.refresh_worldbar()
        self.update_capture_chip()

    def update_capture_chip(self):
        """Show/hide the 'Pending canon' status chip."""
        try:
            from src.capture_queue import CaptureQueue
            count = CaptureQueue(self.engine.paths).count() if self.engine.paths else 0
        except Exception:
            log.exception("Capture chip refresh failed")
            count = 0
        if count:
            self._canon_lbl.setText(f"Pending canon ({count})")
            self._canon_lbl.show()
        else:
            self._canon_lbl.hide()

    def open_capture_review(self):
        from ui_qt.widgets.capture_review_dialog import CaptureReviewDialog
        dlg = CaptureReviewDialog(self, self)
        dlg.exec()
        self.update_capture_chip()

    def refresh_header(self):
        proj = self.engine.active_project()
        name = proj["name"] if proj else "(none)"
        self._project_lbl.setText(f"Project: {name}")

    def refresh_worldbar(self):
        paths = self.engine.paths
        if not paths:
            self._world_lbl.setText("")
            return
        try:
            ws = world_state.read(paths["world_state"])
            parts = [ws.get("currentDate", ""), ws.get("currentLocation", "")]
            self._world_lbl.setText("  |  ".join(p for p in parts if p))
        except Exception:
            log.exception("World bar refresh failed")

    def _update_word_count(self, words: int, chars: int):
        try:
            goal = int(self.settings.get("editor.word_goal", 0) or 0)
        except (TypeError, ValueError):
            goal = 0
        if goal > 0:
            self._word_lbl.setText(f"{words:,} / {goal:,} words")
            self._word_lbl.setToolTip("Word-goal progress for this chapter")
            self._goal_bar.setMaximum(goal)
            self._goal_bar.setValue(min(words, goal))
            self._goal_bar.show()
        else:
            self._word_lbl.setText(f"{words:,} words  ·  {chars:,} chars")
            self._word_lbl.setToolTip("")
            self._goal_bar.hide()
        paths = self.engine.paths
        if paths:
            try:
                from src import session_stats
                stats = session_stats.on_word_count(paths, words)
                self._session_lbl.setText(
                    f"session {stats.get('sessionWords', 0):,}  ·  today {stats.get('dayWords', 0):,}")
            except Exception:
                self._session_lbl.setText("")
        else:
            self._session_lbl.setText("")

    def _update_mock_pill(self):
        if not is_enabled(self.settings, "llm"):
            self._mock_lbl.hide()
            return
        try:
            from src.llm_runner import mock_mode_reason
            reason = mock_mode_reason(self.settings)
        except Exception:
            reason = None
        if reason:
            self._mock_lbl.setToolTip(
                f"Generation is mocked: {reason}. Click to open Add Ons.")
            self._mock_lbl.show()
        else:
            self._mock_lbl.hide()

    def apply_plugin_chrome(self):
        """Hide AI feature buttons and heartbeat until packs are enabled."""
        for name, act in self._feature_actions.items():
            allowed = panel_allowed(self.settings, name)
            act.setVisible(allowed)
            if not allowed:
                lb = self._lightboxes.get(name)
                if lb and lb.isVisible():
                    self._close_lightbox(name)
        self._update_mock_pill()
        self._paint_pack_dots()
        if self.editor and hasattr(self.editor, "apply_plugin_chrome"):
            self.editor.apply_plugin_chrome()

    def _paint_pack_dots(self):
        health = self._service_health or {}
        mapping = {
            "llm": None,
            "image": health.get("comfyui"),
            "audio": health.get("alltalk") or health.get("piper"),
        }
        for pack, status in mapping.items():
            dot = self._pack_dots.get(pack)
            if not dot:
                continue
            if not is_enabled(self.settings, pack):
                dot.hide()
                continue
            dot.show()
            ok = True
            if pack == "llm":
                from src.llm_runner import mock_mode_reason
                ok = not mock_mode_reason(self.settings)
            elif isinstance(status, dict):
                ok = bool(status.get("ok"))
            color = "#7CB87C" if ok else "#C45C5C"
            dot.setStyleSheet(f"color: {color};")
            dot.setToolTip(f"{PACK_LABELS[pack]}: {'ready' if ok else 'not ready'}")

    def show_toast(self, message: str, error: bool = False):
        self.statusBar().showMessage(message, 5000)
        if error:
            log.warning("User toast (error): %s", message)
            QMessageBox.warning(self, config.APP_TITLE, message)
        else:
            log.info("User toast: %s", message)

    def _tick_services(self):
        self._update_mock_pill()
        if self._service_worker and self._service_worker.isRunning():
            return
        from ui_qt.workers import ServiceCheckWorker
        self._service_worker = ServiceCheckWorker(self.settings)
        self._service_worker.result.connect(self._on_service_health)
        self._service_worker.finished.connect(
            lambda: setattr(self, "_service_worker", None))
        self._service_worker.start()

    def _on_service_health(self, health: dict):
        self._service_health = health or {}
        self._paint_pack_dots()

    def _close_all_lightboxes(self):
        """Close every feature lightbox (app shutdown or full reset)."""
        for lb in self._lightboxes.values():
            lb.blockSignals(True)
        for name in list(self._lightboxes.keys()):
            lb = self._lightboxes.get(name)
            if lb is None:
                continue
            panel = self._panels.get(name)
            if panel:
                panel.setParent(self._panel_holder)
            lb.hide()
            lb.deleteLater()
            act = self._feature_actions.get(name)
            if act:
                act.setChecked(False)
        self._lightboxes.clear()

    def closeEvent(self, event):
        log.info("Shutting down")
        self._shutting_down = True
        self.flush_project_context()
        if self.editor and self.engine.paths and getattr(self.editor, "_chapter_id", None):
            from src import snapshots
            snapshots.take_snapshot(
                self.engine.paths, self.editor._chapter_id,
                self.editor.editor.toPlainText(), reason="close")
        pinned = [
            name for name, lb in self._lightboxes.items()
            if lb.isVisible() and lb.stay_open.isChecked()
        ]
        self.settings.set("ui.pinned_panels", pinned, save=True)
        for name, lb in list(self._lightboxes.items()):
            self._save_lightbox_geometry(name, lb.geometry_dict())
        self._close_all_lightboxes()
        super().closeEvent(event)
