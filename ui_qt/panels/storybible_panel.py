"""Qt Story Bible panel (Bible + Lore + World State + Outline)."""

from __future__ import annotations

import threading

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QTabWidget,
    QVBoxLayout,
    QFormLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QLabel,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QComboBox,
    QWidget,
    QCheckBox,
    QMenu,
    QInputDialog,
    QDialog,
    QMessageBox,
    QScrollArea,
    QSizePolicy,
)

from src import story_bible, lore, world_state, outline, export as export_mod
from src import lore_types, lore_migrate, lore_wizard
from src import worldcontext
from src.story_bible_gen import MODE_LABELS
from src.logutil import get_logger
from ui_qt.ambiguity_gate import run_ambiguity_gate
from ui_qt.panels.base import BasePanel
from ui_qt.theme import get_open_file_names, get_save_file_name
from ui_qt.widgets.field_generate_dialog import FieldGenerateDialog
from ui_qt.widgets.activity_indicator import ActivityStatus
from ui_qt.widgets.flow_layout import FlowLayout
from ui_qt.widgets.lore_entry_form import LoreEntryForm
from ui_qt.widgets.lore_audit_dialog import run_lore_audit_dialog
from ui_qt.widgets.lore_wizard_dialog import LoreWizardDialog
from ui_qt.widgets.manuscript_fill_dialog import run_manuscript_fill
from ui_qt.workers import FieldGenerateWorker

log = get_logger("storybible")

_BIBLE_FIELDS = [
    ("premise", "Premise", True),
    ("logline", "Logline", False),
    ("genreTone", "Genre & Tone", False),
    ("themes", "Themes", False),
    ("worldRules", "World rules", True),
    ("styleNotes", "Style notes", True),
    ("pointOfView", "Point of view", False),
    ("tense", "Tense", False),
    ("synopsis", "Synopsis", True),
]

_WORLD_FIELDS = [
    ("currentLocation", "Current location", False),
    ("currentDate", "Current date", False),
    ("scene", "Scene notes", True),
]

_WORLD_LIST_FIELDS = [
    ("timeline", "Timeline (one event per line)", True),
    ("factions", "Factions (one per line)", True),
    ("ongoingEvents", "Ongoing events (one per line)", True),
    ("facts", "Facts & truths (one per line)", True),
]


def _bible_value_to_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(str(v) for v in value if v is not None)
    return str(value)



class StoryBiblePanel(BasePanel):
    title = "Story Bible"

    ask_user_signal = Signal(str, object)

    def __init__(self, app, parent=None):
        super().__init__(app, parent)
        self._bible_widgets: dict[str, QLineEdit | QPlainTextEdit] = {}
        self._world_widgets: dict[str, QLineEdit | QPlainTextEdit] = {}
        self._field_registry: list[tuple] = []
        self._dirty = False
        self._gen_worker: FieldGenerateWorker | None = None
        self._gen_widget = None
        self._gen_start_text = ""
        self._gen_accum = ""
        self._lore_loaded_id: str | None = None
        self._pending_lore_id: str | None = None
        self._lore_filter = "all"

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        self._build_bible_tab()
        self._build_lore_tab()
        self._build_world_tab()
        self._build_outline_tab()

        self.gen_bar = QWidget()
        gen_row = QHBoxLayout(self.gen_bar)
        gen_row.setContentsMargins(0, 4, 0, 4)
        self.gen_status = ActivityStatus("")
        gen_row.addWidget(self.gen_status, 1)
        self.gen_stop_btn = QPushButton("Stop")
        self.gen_stop_btn.setProperty("danger", True)
        self.gen_stop_btn.setToolTip("Stop the current AI generation")
        self.gen_stop_btn.clicked.connect(self._stop_generate)
        self.gen_stop_btn.hide()
        gen_row.addWidget(self.gen_stop_btn)
        layout.addWidget(self.gen_bar)
        self.gen_bar.hide()

        save_row = QHBoxLayout()
        export_btn = QPushButton("Export canon...")
        export_btn.setToolTip("Export Story Bible, lore, and world state as Markdown")
        export_btn.clicked.connect(self._export_canon)
        save_row.addWidget(export_btn)
        save_row.addStretch()
        save_btn = QPushButton("Save All")
        save_btn.clicked.connect(self.save_all)
        save_row.addWidget(save_btn)
        layout.addLayout(save_row)

        self.ask_user_signal.connect(self._show_ask_dialog)

    def _paths(self):
        return self.app.engine.paths

    def _wire_generate_menu(self, widget, field_label: str, bible_key: str | None = None):
        widget.setContextMenuPolicy(Qt.CustomContextMenu)
        widget.customContextMenuRequested.connect(
            lambda pos, w=widget, lbl=field_label, key=bible_key:
            self._field_context_menu(w, pos, lbl, key))
        self._field_registry.append((widget, field_label, bible_key))

    def _field_context_menu(self, widget, pos, field_label, bible_key):
        menu = QMenu(self)
        gen_menu = menu.addMenu("Generate with AI")
        for mode in MODE_LABELS:
            act = gen_menu.addAction(f"{mode}…")
            act.triggered.connect(
                lambda _=False, m=mode, lbl=field_label, key=bible_key, w=widget:
                self._start_generate(w, lbl, m, key))
        menu.addSeparator()
        stop_act = menu.addAction("Stop generation")
        stop_act.setEnabled(self._gen_worker is not None and self._gen_worker.isRunning())
        stop_act.triggered.connect(self._stop_generate)
        menu.exec(widget.mapToGlobal(pos))

    def _field_text(self, widget) -> str:
        if isinstance(widget, QPlainTextEdit):
            return widget.toPlainText()
        return widget.text()

    def _set_field_text(self, widget, text: str, append: bool = False):
        if append and self._field_text(widget).strip():
            text = self._field_text(widget).rstrip() + "\n\n" + text
        if isinstance(widget, QPlainTextEdit):
            widget.setPlainText(text)
        else:
            widget.setText(text)
        self._dirty = True

    def _start_generate(self, widget, field_label, mode, bible_key):
        if self._gen_worker and self._gen_worker.isRunning():
            self.app.show_toast("Another field is still generating.", error=True)
            return
        dlg = FieldGenerateDialog(self, field_label, mode)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        prompt = dlg.user_prompt()
        if not prompt:
            self.app.show_toast("Enter a prompt for generation.", error=True)
            return
        mode = dlg.selected_mode()
        proceed, enriched = run_ambiguity_gate(self, self.app, prompt)
        if not proceed:
            return
        prompt = enriched

        self.flush_if_dirty()
        self.app.engine.clear_cancel()
        existing = self._field_text(widget)
        self._gen_widget = widget
        self._gen_start_text = existing
        self._gen_accum = ""
        exclude = [bible_key] if bible_key else None

        self._gen_worker = FieldGenerateWorker(
            self.app, field_label, prompt, mode, existing,
            exclude_bible_keys=exclude,
            ask_user_fn=self._ask_user_blocking if mode == "Orchestrated" else None,
        )
        self._gen_worker.delta.connect(
            lambda d, w=widget: self._on_gen_delta(w, d))
        self._gen_worker.finished_ok.connect(self._on_gen_done)
        widget.setEnabled(False)
        self._set_gen_busy(True, f"Generating {field_label}… ({mode})")
        self.app.show_toast(f"Generating {field_label}…")
        self._gen_worker.start()

    def _set_gen_busy(self, busy: bool, status: str = ""):
        self.gen_bar.setVisible(busy)
        self.gen_stop_btn.setVisible(busy)
        self.gen_stop_btn.setEnabled(busy)
        self.gen_status.set_status(status, active=busy)

    def _on_gen_delta(self, widget, delta: str):
        self._gen_accum += delta
        if not self._gen_start_text.strip():
            self._set_field_text(widget, self._gen_accum)
        else:
            self._set_field_text(widget, self._gen_start_text.rstrip() + "\n\n" + self._gen_accum)

    def _on_gen_done(self, cancelled: bool, full_text: str):
        widget = self._gen_widget
        self._set_gen_busy(False)
        if widget:
            widget.setEnabled(True)
            if full_text.strip():
                if not self._gen_start_text.strip():
                    self._set_field_text(widget, full_text.strip())
                else:
                    self._set_field_text(
                        widget, self._gen_start_text.rstrip() + "\n\n" + full_text.strip())
                if self.app.settings.get("context.auto_capture", True):
                    paths = self._paths()
                    if paths and worldcontext.has_capture_markers(full_text):
                        summary = worldcontext.capture_from_agent(
                            paths, full_text,
                            bible_mode=self.app.settings.get(
                                "context.capture_bible_mode", "empty"))
                        msg = worldcontext.format_capture_summary(summary)
                        if msg:
                            self.app.show_toast(msg)
                            self.reload()
        self._gen_widget = None
        self._gen_worker = None
        self.app.show_toast("Generation cancelled." if cancelled else "Generation complete.")

    def _stop_generate(self):
        if self._gen_worker and self._gen_worker.isRunning():
            self.gen_status.set_status("Stopping…", active=True)
            self.gen_stop_btn.setEnabled(False)
        self.app.engine.request_cancel()

    def _ask_user_blocking(self, prompt: str) -> str:
        holder = {"value": ""}
        event = threading.Event()

        def done(text):
            holder["value"] = text or ""
            event.set()

        self.ask_user_signal.emit(prompt, done)
        event.wait()
        return holder["value"]

    def _show_ask_dialog(self, prompt: str, callback):
        text, ok = QInputDialog.getText(self, "The team needs your input", prompt)
        callback(text if ok else "")

    def _build_bible_tab(self):
        tab = QWidget()
        v = QVBoxLayout(tab)
        bible_tools = QHBoxLayout()
        canon_wiz = QPushButton("Canon wizard")
        canon_wiz.setToolTip(
            "Interview the model to fill premise, tone, rules, style, and synopsis")
        canon_wiz.clicked.connect(self._canon_wizard)
        bible_tools.addWidget(canon_wiz)
        fill_ch = QPushButton("Fill from chapters…")
        fill_ch.setToolTip(
            "Audit chapter text and fill definite Story Bible, world, outline, "
            "chapter meta, and lore fields")
        fill_ch.clicked.connect(self._fill_from_chapters)
        bible_tools.addWidget(fill_ch)
        bible_tools.addStretch()
        v.addLayout(bible_tools)
        form = QFormLayout()
        for key, label, multiline in _BIBLE_FIELDS:
            if multiline:
                field = QPlainTextEdit()
                field.setMinimumHeight(72)
                field.setMaximumHeight(220)
                field.setSizePolicy(
                    QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            else:
                field = QLineEdit()
            field.textChanged.connect(lambda _=None: setattr(self, "_dirty", True))
            self._bible_widgets[key] = field
            self._wire_generate_menu(field, label, bible_key=key)
            form.addRow(label, field)
        v.addLayout(form)
        v.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(tab)
        self.tabs.addTab(scroll, "Bible")

    def _build_lore_tab(self):
        tab = QWidget()
        v = QVBoxLayout(tab)
        tools = QWidget()
        row = FlowLayout(tools, hspacing=6, vspacing=4)
        self.lore_filter = QComboBox()
        for key, label in lore_types.FILTER_OPTIONS:
            self.lore_filter.addItem(label, key)
        self.lore_filter.currentIndexChanged.connect(self._on_lore_filter_changed)
        row.addWidget(QLabel("Show:"))
        row.addWidget(self.lore_filter)
        add_btn = QPushButton("Add entry")
        add_btn.clicked.connect(self._add_lore)
        row.addWidget(add_btn)
        wizard_btn = QPushButton("Wizard…")
        wizard_btn.setToolTip("Interview the model and create a new lore entry")
        wizard_btn.clicked.connect(self._lore_wizard_new)
        row.addWidget(wizard_btn)
        fill_btn = QPushButton("Fill with wizard")
        fill_btn.setProperty("secondary", True)
        fill_btn.setToolTip("Interview the model to fill the current card")
        fill_btn.clicked.connect(self._lore_wizard_fill)
        row.addWidget(fill_btn)
        from_ch = QPushButton("Fill from chapters…")
        from_ch.setProperty("secondary", True)
        from_ch.setToolTip(
            "Audit chapter text and propose lore cards plus bible/world fields")
        from_ch.clicked.connect(self._fill_from_chapters)
        row.addWidget(from_ch)
        upgrade_btn = QPushButton("Upgrade legacy…")
        upgrade_btn.setProperty("secondary", True)
        upgrade_btn.setToolTip("Re-infer entry types and persist normalized lore")
        upgrade_btn.clicked.connect(self._upgrade_legacy_lore)
        row.addWidget(upgrade_btn)
        reaudit_btn = QPushButton("Re-audit…")
        reaudit_btn.setProperty("secondary", True)
        reaudit_btn.setToolTip("Check lore entries make sense; offer automatic fixes")
        reaudit_btn.clicked.connect(self._reaudit_lore)
        row.addWidget(reaudit_btn)
        import_btn = QPushButton("Import CSV…")
        import_btn.setProperty("secondary", True)
        import_btn.setToolTip(
            "Import a Sudowrite character CSV (Name, Role, Pronouns, Groups, "
            "Other Names, Personality, Physical Description, Dialogue Style).")
        import_btn.clicked.connect(self._import_lore_csv)
        row.addWidget(import_btn)
        v.addWidget(tools)

        sel_row = QHBoxLayout()
        sel_all = QPushButton("Select all")
        sel_all.setProperty("secondary", True)
        sel_all.clicked.connect(self._lore_select_all)
        sel_row.addWidget(sel_all)
        sel_none = QPushButton("Clear selection")
        sel_none.setProperty("secondary", True)
        sel_none.clicked.connect(self._lore_select_none)
        sel_row.addWidget(sel_none)
        sel_row.addStretch()
        self.lore_sel_label = QLabel("")
        self.lore_sel_label.setProperty("muted", True)
        sel_row.addWidget(self.lore_sel_label)
        v.addLayout(sel_row)

        self.lore_list = QListWidget()
        self.lore_list.currentRowChanged.connect(self._load_lore_entry)
        self.lore_list.itemChanged.connect(self._on_lore_item_changed)
        v.addWidget(self.lore_list, 1)

        self.lore_form = LoreEntryForm()
        self.lore_form.changed.connect(lambda: setattr(self, "_dirty", True))
        self.lore_form.typeChanged.connect(self._on_lore_type_changed)
        self.lore_form.wire_generate_menu(
            lambda w, lbl: self._wire_generate_menu(w, lbl))
        v.addWidget(self.lore_form, 2)
        self.portrait_btn = QPushButton("Generate portrait from this entry")
        self.portrait_btn.setToolTip("Requires the Image pack. Saves to portraits/ and fills portrait path.")
        self.portrait_btn.clicked.connect(self._generate_portrait)
        v.addWidget(self.portrait_btn)

        del_btn = QPushButton("Delete selected")
        del_btn.setProperty("danger", True)
        del_btn.setToolTip("Delete checked entries (check boxes in the list)")
        del_btn.clicked.connect(self._delete_lore)
        v.addWidget(del_btn)
        self.tabs.addTab(tab, "Lorebook")

    def _on_lore_filter_changed(self):
        self._save_lore_entry()
        self._lore_filter = self.lore_filter.currentData() or "all"
        self._reload_lore_list()

    def _build_world_tab(self):
        tab = QWidget()
        v = QVBoxLayout(tab)
        world_tools = QHBoxLayout()
        world_wiz = QPushButton("World wizard")
        world_wiz.setToolTip(
            "Interview the model to fill location, date, factions, events, and facts")
        world_wiz.clicked.connect(self._world_wizard)
        world_tools.addWidget(world_wiz)
        fill_ch = QPushButton("Fill from chapters…")
        fill_ch.setToolTip(
            "Audit chapter text and fill definite world, bible, outline, and lore fields")
        fill_ch.clicked.connect(self._fill_from_chapters)
        world_tools.addWidget(fill_ch)
        world_tools.addStretch()
        v.addLayout(world_tools)
        form = QFormLayout()
        for key, label, multiline in _WORLD_FIELDS:
            field = QPlainTextEdit() if multiline else QLineEdit()
            if multiline:
                field.setMinimumHeight(56)
                field.setMaximumHeight(160)
            field.textChanged.connect(lambda _=None: setattr(self, "_dirty", True))
            self._world_widgets[key] = field
            self._wire_generate_menu(field, label)
            form.addRow(label, field)
        for key, label, multiline in _WORLD_LIST_FIELDS:
            field = QPlainTextEdit()
            field.setMinimumHeight(56)
            field.setMaximumHeight(140)
            field.setPlaceholderText("One item per line")
            field.textChanged.connect(lambda _=None: setattr(self, "_dirty", True))
            self._world_widgets[key] = field
            self._wire_generate_menu(field, label)
            form.addRow(label, field)
        v.addLayout(form)
        v.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(tab)
        self.tabs.addTab(scroll, "World State")

    def _build_outline_tab(self):
        tab = QWidget()
        v = QVBoxLayout(tab)
        v.addWidget(QLabel("Global outline"))
        self.outline_global = QPlainTextEdit()
        self.outline_global.setMaximumHeight(80)
        self.outline_global.setPlaceholderText("Overall story summary...")
        self._wire_generate_menu(self.outline_global, "Global outline summary")
        v.addWidget(self.outline_global)
        v.addWidget(QLabel("Global beats (one per line)"))
        self.outline_beats = QPlainTextEdit()
        self._wire_generate_menu(self.outline_beats, "Global outline beats")
        v.addWidget(self.outline_beats)
        v.addWidget(QLabel("Current chapter outline"))
        self.outline_chapter = QComboBox()
        v.addWidget(self.outline_chapter)
        self.outline_ch_summary = QPlainTextEdit()
        self.outline_ch_summary.setMaximumHeight(60)
        self._wire_generate_menu(self.outline_ch_summary, "Chapter outline summary")
        v.addWidget(QLabel("Chapter summary"))
        v.addWidget(self.outline_ch_summary)
        self.outline_ch_beats = QPlainTextEdit()
        self._wire_generate_menu(self.outline_ch_beats, "Chapter outline beats")
        v.addWidget(QLabel("Chapter beats (one per line)"))
        v.addWidget(self.outline_ch_beats)
        self.outline_chapter.currentIndexChanged.connect(self._load_chapter_outline)
        self.tabs.addTab(tab, "Outline")

    def on_show(self):
        from src.plugins import is_enabled
        if hasattr(self, "portrait_btn"):
            self.portrait_btn.setVisible(is_enabled(self.app.settings, "image"))
        QTimer.singleShot(0, self._deferred_reload)

    def _deferred_reload(self):
        pending = getattr(self, "_pending_lore_id", None)
        self.reload(select_id=pending)

    def _generate_portrait(self):
        from src.plugins import is_enabled
        if not is_enabled(self.app.settings, "image"):
            self.app.show_toast("Enable the Image pack in Add Ons.", error=True)
            return
        entry = self.lore_form.to_entry_dict()
        prompt = " ".join(filter(None, [
            entry.get("name"), entry.get("appearance"), entry.get("notes")]))
        if not prompt.strip():
            self.app.show_toast("Add a name or appearance first.", error=True)
            return
        try:
            self.app.comfy.render(prompt)
            self.app.show_toast("Portrait job sent to ComfyUI.")
        except Exception as exc:
            self.app.show_toast(str(exc), error=True)

    def on_project_change(self):
        self.reload()

    def reload(self, *, select_id: str | None = None):
        paths = self._paths()
        if not paths:
            return
        jump = select_id or getattr(self, "_pending_lore_id", None)
        try:
            data = story_bible.read(paths["bible"])
            for key, widget in self._bible_widgets.items():
                val = _bible_value_to_text(data.get(key, ""))
                if isinstance(widget, QPlainTextEdit):
                    widget.setPlainText(val)
                else:
                    widget.setText(val)
            ws = world_state.read(paths["world_state"])
            for key, widget in self._world_widgets.items():
                val = ws.get(key, "")
                if key in ("timeline", "factions", "ongoingEvents", "facts"):
                    lines = val if isinstance(val, list) else []
                    text = "\n".join(str(x) for x in lines if x)
                else:
                    text = _bible_value_to_text(val)
                if isinstance(widget, QPlainTextEdit):
                    widget.setPlainText(text)
                else:
                    widget.setText(text)
            if jump:
                self.tabs.setCurrentIndex(1)
                self._show_all_lore_types()
            self._reload_lore_list()
            self._reload_outline()
            self._dirty = False
            if jump:
                self._focus_lore_row(jump)
            log.debug("Story Bible reloaded")
        except Exception as exc:
            log.exception("Story Bible reload failed")
            self.app.show_toast(f"Could not load Story Bible: {exc}", error=True)

    def _reload_outline(self):
        paths = self._paths()
        if not paths:
            return
        from src import chapters as ch_mod
        ol = outline.read_all(paths["outlines"])
        g = ol.get("global") or {}
        self.outline_global.setPlainText(g.get("summary") or "")
        self.outline_beats.setPlainText("\n".join(g.get("beats") or []))
        self.outline_chapter.blockSignals(True)
        self.outline_chapter.clear()
        ch_items = ch_mod.list_chapters(paths["chapters"])
        for ch in ch_items:
            self.outline_chapter.addItem(ch["name"], ch["id"])
        self.outline_chapter.blockSignals(False)
        if ch_items:
            self._load_chapter_outline(0)

    def _load_chapter_outline(self, index: int):
        paths = self._paths()
        if not paths or index < 0:
            return
        cid = self.outline_chapter.itemData(index)
        if not cid:
            return
        co = outline.read_chapter(paths["outlines"], cid)
        self.outline_ch_summary.setPlainText(co.get("summary") or "")
        self.outline_ch_beats.setPlainText("\n".join(co.get("beats") or []))

    def _reaudit_lore(self):
        self._save_lore_entry()
        run_lore_audit_dialog(self, self.app)
        self.reload()

    def _import_lore_csv(self):
        paths = self._paths()
        if not paths:
            return
        selected, _f = get_open_file_names(
            self, "Import character CSV", "",
            "CSV files (*.csv);;All files (*.*)")
        if not selected:
            return
        from src import lore_import
        added = updated = 0
        for path in selected:
            report = lore_import.import_character_csv(
                paths["lore"], path, mode="upsert")
            added += report["added"]
            updated += report["updated"]
        self.reload()
        parts = []
        if added:
            parts.append(f"{added} added")
        if updated:
            parts.append(f"{updated} updated")
        self.app.show_toast(
            "Imported character CSV: " + (", ".join(parts) or "nothing to import") + ".")

    def _lore_select_all(self):
        for i in range(self.lore_list.count()):
            item = self.lore_list.item(i)
            item.setCheckState(Qt.CheckState.Checked)
        self._update_lore_sel_label()

    def _lore_select_none(self):
        for i in range(self.lore_list.count()):
            item = self.lore_list.item(i)
            item.setCheckState(Qt.CheckState.Unchecked)
        self._update_lore_sel_label()

    def _on_lore_item_changed(self, item: QListWidgetItem):
        if item:
            self._update_lore_sel_label()

    def _update_lore_sel_label(self):
        n = sum(
            1 for i in range(self.lore_list.count())
            if self.lore_list.item(i).checkState() == Qt.CheckState.Checked)
        self.lore_sel_label.setText(
            f"{n} selected" if n else "Check entries to delete multiple")

    def _checked_lore_ids(self) -> list[str]:
        ids = []
        for i in range(self.lore_list.count()):
            item = self.lore_list.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                eid = item.data(Qt.ItemDataRole.UserRole)
                if eid:
                    ids.append(eid)
        return ids

    def _reload_lore_list(self, *, persist: bool = True):
        paths = self._paths()
        if not paths:
            return
        if persist:
            self._save_lore_entry()
        checked_before = set(self._checked_lore_ids())
        filt = self.lore_filter.currentData() or "all"
        self._lore_entries = lore.entries_by_type(paths["lore"], filt)
        self.lore_list.blockSignals(True)
        self.lore_list.clear()
        for entry in self._lore_entries:
            item = QListWidgetItem(lore_types.entry_display_name(entry))
            eid = entry.get("id")
            item.setData(Qt.ItemDataRole.UserRole, eid)
            item.setFlags(
                item.flags()
                | Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEnabled
                | Qt.ItemFlag.ItemIsSelectable)
            if eid in checked_before:
                item.setCheckState(Qt.CheckState.Checked)
            else:
                item.setCheckState(Qt.CheckState.Unchecked)
            self.lore_list.addItem(item)
        self.lore_list.blockSignals(False)
        self._update_lore_sel_label()
        if self._lore_entries:
            pick = 0
            if self._lore_loaded_id:
                for i, e in enumerate(self._lore_entries):
                    if e.get("id") == self._lore_loaded_id:
                        pick = i
                        break
            self.lore_list.setCurrentRow(pick)
        else:
            self._lore_loaded_id = None
            self.lore_form.load_entry({})

    def _save_lore_entry(self):
        paths = self._paths()
        if not paths or not self._lore_loaded_id:
            return
        base = next((e for e in getattr(self, "_lore_entries", [])
                     if e.get("id") == self._lore_loaded_id), None)
        if not base:
            base = {"id": self._lore_loaded_id}
        entry = self.lore_form.to_entry_dict(base)
        saved = lore.save_entry(paths["lore"], entry)
        updated = False
        for i, e in enumerate(getattr(self, "_lore_entries", [])):
            if e.get("id") == saved.get("id"):
                self._lore_entries[i] = saved
                updated = True
                break
        if not updated:
            self._lore_entries = list(getattr(self, "_lore_entries", [])) + [saved]
        return saved

    def _on_lore_type_changed(self):
        """Keep notes/shared fields, persist the new type, refresh the list label."""
        saved = self._save_lore_entry()
        if not saved:
            return
        et = saved.get("entryType")
        filt = self.lore_filter.currentData() if hasattr(self, "lore_filter") else "all"
        if filt not in (None, "all") and filt != et:
            self._show_all_lore_types()
            self._reload_lore_list(persist=False)
            self._focus_lore_row(saved.get("id") or "")
            return
        eid = saved.get("id")
        for i in range(self.lore_list.count()):
            item = self.lore_list.item(i)
            if item and item.data(Qt.ItemDataRole.UserRole) == eid:
                item.setText(lore_types.entry_display_name(saved))
                break
        self._dirty = True

    def _load_lore_entry(self, row: int):
        if row < 0 or row >= len(getattr(self, "_lore_entries", [])):
            return
        entry = self._lore_entries[row]
        new_id = entry.get("id")
        if self._lore_loaded_id and self._lore_loaded_id != new_id:
            self._save_lore_entry()
        self._lore_loaded_id = new_id
        self.lore_form.load_entry(entry)

    def _add_lore(self):
        paths = self._paths()
        if not paths:
            return
        filt = self.lore_filter.currentData() or "all"
        entry_type = filt if filt != "all" else "character"
        created = lore.add(paths["lore"], {
            "name": "New entry",
            "entryType": entry_type,
        })
        self._lore_loaded_id = created.get("id")
        self._dirty = True
        self._reload_lore_list()

    def _llm_ready(self) -> bool:
        from src.plugins import is_enabled
        if not self._paths():
            self.app.show_toast("Open a project first.", error=True)
            return False
        if not is_enabled(self.app.settings, "llm"):
            self.app.show_toast("Enable the Local LLM pack in Add Ons.", error=True)
            return False
        return True

    def _run_wizard(self, kind: str, existing=None, *, pick_type: bool = False,
                    title: str = "") -> dict | None:
        if not self._llm_ready():
            return None
        self.flush_if_dirty()
        dlg = LoreWizardDialog(
            self, self.app, kind=kind, existing=existing or {},
            pick_type=pick_type, title=title)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return None
        return {
            "kind": dlg.selected_kind(),
            "fields": dlg.result_fields(),
            "replace": dlg.replace_mode(),
        }

    def _lore_wizard_new(self):
        filt = self.lore_filter.currentData() or "all"
        kind = filt if filt != "all" else "character"
        result = self._run_wizard(kind, pick_type=True, title="Lore wizard")
        if not result:
            return
        fields = dict(result["fields"])
        fields["entryType"] = result["kind"]
        if not lore_wizard.fill_has_content(fields):
            self.app.show_toast("Wizard produced an empty card. Try again.", error=True)
            return
        if not (fields.get("name") or "").strip():
            fields["name"] = "New entry"
        created = lore.add(self._paths()["lore"], fields)
        eid = created.get("id") or ""
        self._lore_loaded_id = eid
        self._dirty = True
        self.tabs.setCurrentIndex(1)
        self._show_all_lore_types()
        self._reload_lore_list(persist=False)
        self._focus_lore_row(eid)
        self.app.show_toast(f"Created {created.get('name') or 'entry'} from wizard.")

    def _lore_wizard_fill(self):
        if not self._lore_loaded_id:
            self.app.show_toast("Select a lore entry first.", error=True)
            return
        self._save_lore_entry()
        base = next((e for e in getattr(self, "_lore_entries", [])
                     if e.get("id") == self._lore_loaded_id), {})
        kind = base.get("entryType") or "character"
        result = self._run_wizard(kind, existing=base, title="Fill lore entry")
        if not result or not lore_wizard.fill_has_content(result.get("fields")):
            if result:
                self.app.show_toast("Wizard produced no new fields.", error=True)
            return
        merged = {**base, **result["fields"], "id": self._lore_loaded_id,
                  "entryType": kind}
        saved = lore.save_entry(self._paths()["lore"], merged)
        self._lore_loaded_id = saved.get("id")
        self._dirty = True
        self._reload_lore_list(persist=False)
        self._focus_lore_row(saved.get("id") or "")
        self.app.show_toast("Lore entry filled from wizard.")

    def _apply_widget_fields(self, widgets: dict, fields: dict, list_keys=()):
        for key, value in fields.items():
            widget = widgets.get(key)
            if widget is None:
                continue
            if key in list_keys:
                if isinstance(value, list):
                    text = "\n".join(str(v).strip() for v in value if str(v).strip())
                else:
                    text = str(value or "")
            elif isinstance(value, list):
                text = ", ".join(str(v) for v in value if v)
            else:
                text = str(value or "")
            self._set_field_text(widget, text, append=False)

    def _fill_from_chapters(self):
        run_manuscript_fill(self, self.app)

    def _canon_wizard(self):
        existing = {}
        for key in ("premise", "genreTone", "worldRules", "styleNotes", "synopsis"):
            widget = self._bible_widgets.get(key)
            if widget is not None:
                existing[key] = self._field_text(widget)
        result = self._run_wizard("canon", existing=existing, title="Canon wizard")
        if not result:
            return
        self._apply_widget_fields(self._bible_widgets, result["fields"])
        self.save_all()
        self.app.show_toast("Story Bible filled from wizard.")

    def _world_wizard(self):
        existing = {}
        list_keys = ("factions", "ongoingEvents", "facts")
        for key in ("currentLocation", "currentDate") + list_keys:
            widget = self._world_widgets.get(key)
            if widget is None:
                continue
            text = self._field_text(widget)
            if key in list_keys:
                existing[key] = [ln.strip() for ln in text.splitlines() if ln.strip()]
            else:
                existing[key] = text
        result = self._run_wizard("world", existing=existing, title="World wizard")
        if not result:
            return
        self._apply_widget_fields(
            self._world_widgets, result["fields"], list_keys=list_keys)
        self.save_all()
        self.app.show_toast("World State filled from wizard.")

    def _delete_lore(self):
        paths = self._paths()
        if not paths:
            return
        ids = self._checked_lore_ids()
        if not ids:
            row = self.lore_list.currentRow()
            if row < 0:
                self.app.show_toast("Check entries to delete, or select one in the list.", error=True)
                return
            entry = self._lore_entries[row]
            ids = [entry.get("id")]
        names = [
            next((e.get("name") for e in self._lore_entries if e.get("id") == i), i)
            for i in ids]
        label = names[0] if len(ids) == 1 else f"{len(ids)} entries"
        ans = QMessageBox.question(
            self, "Delete lore entries",
            f"Delete {label}?\n" + ("\n".join(f"• {n}" for n in names[:12]))
            + (f"\n… and {len(names) - 12} more" if len(names) > 12 else ""),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        for eid in ids:
            if eid:
                lore.remove(paths["lore"], eid)
        if self._lore_loaded_id in ids:
            self._lore_loaded_id = None
        self._dirty = True
        self._reload_lore_list()
        self.app.show_toast(f"Deleted {len(ids)} lore entr{'y' if len(ids) == 1 else 'ies'}.")

    def _export_canon(self):
        paths = self._paths()
        if not paths:
            return
        self.save_all()
        path, _ = get_save_file_name(
            self, "Export Story Bible", "", "Markdown (*.md);;Text (*.txt)")
        if not path:
            return
        fmt = "md" if path.lower().endswith(".md") else "md"
        content = export_mod.export_bible_bundle(
            paths, self.app.engine.project_id, fmt)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        self.app.show_toast(f"Exported canon to {path}")

    def save_all(self):
        paths = self._paths()
        if not paths:
            return
        bible = story_bible.read(paths["bible"])
        for key, widget in self._bible_widgets.items():
            bible[key] = (widget.toPlainText() if isinstance(widget, QPlainTextEdit)
                          else widget.text())
        story_bible.write(paths["bible"], bible)

        self._save_lore_entry()

        ws = world_state.read(paths["world_state"])
        for key, widget in self._world_widgets.items():
            if isinstance(widget, QPlainTextEdit):
                val = widget.toPlainText()
            else:
                val = widget.text()
            if key in ("timeline", "factions", "ongoingEvents", "facts"):
                ws[key] = [ln.strip() for ln in val.splitlines() if ln.strip()]
            else:
                ws[key] = val
        world_state.write(paths["world_state"], ws)

        ol = outline.read_all(paths["outlines"])
        ol["global"] = {
            "summary": self.outline_global.toPlainText().strip(),
            "beats": [b.strip() for b in self.outline_beats.toPlainText().splitlines()
                      if b.strip()],
        }
        idx = self.outline_chapter.currentIndex()
        if idx >= 0:
            cid = self.outline_chapter.itemData(idx)
            if cid:
                ol.setdefault("chapters", {})[cid] = {
                    "summary": self.outline_ch_summary.toPlainText().strip(),
                    "beats": [b.strip() for b in self.outline_ch_beats.toPlainText().splitlines()
                              if b.strip()],
                }
        outline.write_all(paths["outlines"], ol)

        self._dirty = False
        self.app.show_toast("Story Bible saved.")

    def flush_if_dirty(self):
        if self._dirty:
            self.save_all()

    def show_world_state_tab(self):
        self.tabs.setCurrentIndex(2)

    def _show_all_lore_types(self):
        if not hasattr(self, "lore_filter"):
            return
        if self.lore_filter.currentData() in (None, "all"):
            return
        idx = self.lore_filter.findData("all")
        if idx >= 0:
            self.lore_filter.blockSignals(True)
            self.lore_filter.setCurrentIndex(idx)
            self.lore_filter.blockSignals(False)

    def _focus_lore_row(self, entry_id: str) -> bool:
        if not entry_id:
            return False
        for i in range(self.lore_list.count()):
            item = self.lore_list.item(i)
            if item and item.data(Qt.ItemDataRole.UserRole) == entry_id:
                if self.lore_list.currentRow() != i:
                    self.lore_list.setCurrentRow(i)
                else:
                    self._load_lore_entry(i)
                self.lore_list.scrollToItem(item)
                self._pending_lore_id = None
                return True
        return False

    def select_lore_entry(self, entry_id: str) -> bool:
        """Snap Lorebook list + form to this entry (Focus / continuity jump)."""
        if not entry_id:
            return False
        self._pending_lore_id = entry_id
        self.tabs.setCurrentIndex(1)
        self._show_all_lore_types()
        self._reload_lore_list(persist=True)
        if self._focus_lore_row(entry_id):
            return True
        self._pending_lore_id = None
        return False

    def select_lore_entry_by_name(self, name: str) -> bool:
        paths = self._paths()
        if not paths or not name:
            return False
        needle = lore._norm_name(name)
        for entry in lore.all_entries(paths["lore"]):
            if lore._norm_name(entry.get("name")) == needle:
                return self.select_lore_entry(entry.get("id") or "")
            for alias in entry.get("aliases") or []:
                if lore._norm_name(alias) == needle:
                    return self.select_lore_entry(entry.get("id") or "")
        return False

    def add_lore_from_audit(self, name: str, *, issue=None) -> bool:
        """Create a Lorebook card prefilled from an unmapped-name audit hit."""
        paths = self._paths()
        name = (name or "").strip()
        if not paths or not name:
            return False
        if self.select_lore_entry_by_name(name):
            return True
        from src import lore_audit
        self._save_lore_entry()
        draft = lore_audit.draft_unmapped_entry(paths, name, issue=issue)
        created = lore.add(paths["lore"], draft)
        eid = created.get("id") or ""
        self._pending_lore_id = eid
        self._lore_loaded_id = eid
        self.tabs.setCurrentIndex(1)
        self._show_all_lore_types()
        self._reload_lore_list(persist=False)
        if not self._focus_lore_row(eid):
            return False
        self._dirty = True
        editor = getattr(self.app, "editor", None)
        if editor is not None and hasattr(editor, "_refresh_continuity"):
            editor._refresh_continuity()
        self.app.show_toast(f"Started lore for {name}. Review the notes and save.")
        return True

    def _upgrade_legacy_lore(self):
        paths = self._paths()
        if not paths:
            return
        report = lore_migrate.migrate_lore(paths, dry_run=True)
        if report.changed == 0:
            self.app.show_toast("No legacy entries need upgrading.")
            return
        preview = "\n".join(report.details[:15])
        if len(report.details) > 15:
            preview += f"\n… and {len(report.details) - 15} more"
        ans = QMessageBox.question(
            self, "Upgrade legacy entries",
            f"{report.changed} of {report.total} entries would be updated.\n\n{preview}\n\nApply?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if ans == QMessageBox.StandardButton.Yes:
            lore_migrate.migrate_lore(paths, dry_run=False)
            self.reload()
            self.app.show_toast(f"Upgraded {report.changed} lore entries.")
