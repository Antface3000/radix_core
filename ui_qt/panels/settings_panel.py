"""Qt Settings control center — tabbed panels aligned with USER_GUIDE."""

from __future__ import annotations

import copy
import config
from PySide6.QtWidgets import (
    QVBoxLayout, QFormLayout, QComboBox, QSpinBox, QCheckBox, QPushButton,
    QLabel, QGroupBox, QTabWidget, QWidget, QLineEdit, QPlainTextEdit,
    QScrollArea, QHBoxLayout, QMessageBox, QListWidget, QListWidgetItem,
)
from PySide6.QtCore import Qt

from src.settings import DEFAULT_GLOBAL
from src.logutil import get_logger
from ui_qt.panels.base import BasePanel

log = get_logger("settings")


def _scroll_tab(inner: QWidget) -> QWidget:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setWidget(inner)
    return scroll


def _tip(*lines: str) -> str:
    """Join tooltip lines; blank lines become paragraph breaks."""
    return "\n".join(lines)


_TEMP_TTIP = _tip(
    "Sampling temperature. The spinbox shows ×100 (divide by 100).",
    "Lower = more focused. Higher = more varied.",
    "Examples: 55 → 0.55 · 70 → 0.70 · 100 → 1.00",
)


def _temp_spin(value: float) -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(0, 200)
    spin.setValue(int(round(float(value) * 100)))
    return spin


def _persona_combo(settings, current_key: str) -> QComboBox:
    """Dropdown of known personas (display name, stores key)."""
    combo = QComboBox()
    for p in settings.selectable_personas():
        combo.addItem(p["display_name"], p["key"])
    idx = combo.findData(current_key)
    if idx >= 0:
        combo.setCurrentIndex(idx)
    elif current_key:
        combo.addItem(f"{current_key} (unknown)", current_key)
        combo.setCurrentIndex(combo.count() - 1)
    combo.setToolTip(_tip(
        "Choose which agent persona runs this action.",
        "Keys are saved internally; names come from the Team specialist roster.",
    ))
    return combo


def _persona_checklist(settings, selected_keys: list[str]) -> QListWidget:
    """Checklist for choosing one or more persona keys."""
    selected = set(selected_keys or [])
    box = QListWidget()
    box.setMaximumHeight(100)
    for p in settings.selectable_personas():
        item = QListWidgetItem(p["display_name"])
        item.setData(Qt.ItemDataRole.UserRole, p["key"])
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        state = (Qt.CheckState.Checked if p["key"] in selected
                 else Qt.CheckState.Unchecked)
        item.setCheckState(state)
        box.addItem(item)
    for key in selected:
        if not any(box.item(i).data(Qt.ItemDataRole.UserRole) == key
                   for i in range(box.count())):
            item = QListWidgetItem(f"{key} (unknown)")
            item.setData(Qt.ItemDataRole.UserRole, key)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            box.addItem(item)
    return box


class SettingsPanel(BasePanel):
    title = "Settings"

    def __init__(self, app, parent=None):
        super().__init__(app, parent)
        self._widgets: dict[str, object] = {}
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)

        self.tabs.addTab(_scroll_tab(self._build_general()), "General")
        self.tabs.addTab(_scroll_tab(self._build_generation()), "Generation")
        self.tabs.addTab(_scroll_tab(self._build_context()), "Context")
        self.tabs.addTab(_scroll_tab(self._build_orchestration()), "Orchestration")
        self.tabs.addTab(_scroll_tab(self._build_editor()), "Editor")
        self.tabs.addTab(_scroll_tab(self._build_agents()), "Team")
        self.tabs.addTab(_scroll_tab(self._build_services()), "Services")
        self.tabs.addTab(_scroll_tab(self._build_image()), "Image")
        self.tabs.addTab(_scroll_tab(self._build_appearance()), "Appearance")

        row = QHBoxLayout()
        save_btn = QPushButton("Save settings")
        save_btn.clicked.connect(self._save)
        row.addWidget(save_btn)
        reset_btn = QPushButton("Reset current tab to defaults")
        reset_btn.setProperty("secondary", True)
        reset_btn.clicked.connect(self._reset_tab)
        row.addWidget(reset_btn)
        row.addStretch()
        layout.addLayout(row)

        self._load_all()

    def _s(self):
        return self.app.settings

    def _bind(self, key: str, widget):
        self._widgets[key] = widget

    def _build_general(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        s = self._s()
        show_w = QCheckBox("Show welcome dialog on launch")
        show_w.setChecked(s.get("ui.show_welcome", True))
        show_w.setToolTip("Short intro when the app opens")
        self._bind("ui.show_welcome", show_w)
        f.addRow(show_w)
        show_s = QCheckBox("Show project launcher on launch")
        show_s.setChecked(s.get("ui.show_startup", True))
        show_s.setToolTip("Pick or create a project before the editor opens")
        self._bind("ui.show_startup", show_s)
        f.addRow(show_s)
        upd = QCheckBox("Check for updates on launch (background)")
        upd.setChecked(s.get("updates.check_on_startup", True))
        upd.setToolTip("Non-blocking check; notifies if a newer version exists")
        self._bind("updates.check_on_startup", upd)
        f.addRow(upd)
        audit_open = QCheckBox("Run lore audit when opening Focus panel")
        audit_open.setChecked(s.get("lore.audit_on_project_open", False))
        audit_open.setToolTip("Only when you open Focus → Canon Audit tab")
        self._bind("lore.audit_on_project_open", audit_open)
        f.addRow(audit_open)
        orphan = QCheckBox("Include manuscript orphan scan in lore audit")
        orphan.setChecked(s.get("lore.audit_orphan_scan", True))
        orphan.setToolTip("When you run Re-audit manually or from Focus")
        f.addRow(orphan)
        return w

    def _build_generation(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        s = self._s()
        temp = _temp_spin(s.get("generation.temperature", 0.7))
        temp.setToolTip(_tip(
            _TEMP_TTIP,
            "",
            "Default for agent chat and orchestration.",
            "Per-persona overrides: Agents tab.",
        ))
        self._bind("generation.temperature", temp)
        temp_lbl = QLabel("Temperature")
        temp_lbl.setToolTip(temp.toolTip())
        f.addRow(temp_lbl, temp)
        rp = QSpinBox()
        rp.setRange(100, 200)
        rp.setValue(int(round(float(s.get("generation.repeat_penalty", 1.15)) * 100)))
        rp.setToolTip(_tip(
            "Repeat penalty. Spinbox shows ×100 (divide by 100).",
            "Penalizes re-using the same words and phrases.",
            "100 = off · 115 = mild (default) · 130 = strong",
            "",
            "Raise if Write output loops or echoes itself.",
        ))
        self._bind("generation.repeat_penalty", rp)
        rp_lbl = QLabel("Repeat penalty")
        rp_lbl.setToolTip(rp.toolTip())
        f.addRow(rp_lbl, rp)
        mt = QSpinBox()
        mt.setRange(256, 8192)
        mt.setValue(int(s.get("generation.max_tokens", config.DEFAULT_MAX_TOKENS)))
        self._bind("generation.max_tokens", mt)
        f.addRow("Max tokens", mt)
        stream = QCheckBox("Stream model output")
        stream.setChecked(s.get("generation.streaming", True))
        self._bind("generation.streaming", stream)
        f.addRow(stream)
        return w

    def _build_context(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        s = self._s()
        inject = QCheckBox("Inject setting into agent runs")
        inject.setChecked(s.get("context.inject", True))
        self._bind("context.inject", inject)
        f.addRow(inject)
        cap = QComboBox()
        cap.addItem("Fill empty only", "empty")
        cap.addItem("Append with note", "append")
        cap.addItem("Merge into one entry", "merge")
        mode = s.get("context.capture_bible_mode", "empty")
        if mode == "replace":
            mode = "merge"
        idx = max(0, cap.findData(mode))
        cap.setCurrentIndex(idx)
        self._bind("context.capture_bible_mode", cap)
        f.addRow("Bible capture mode", cap)
        auto = QCheckBox("Auto-capture canon markers")
        auto.setChecked(s.get("context.auto_capture", True))
        self._bind("context.auto_capture", auto)
        f.addRow(auto)
        review = QCheckBox("Review captured canon before writing")
        review.setToolTip(
            "When on, agent captures go to a pending queue (status bar chip) "
            "for approval instead of writing straight into the Lorebook, "
            "Story Bible, and World State.")
        review.setChecked(s.get("context.capture_review", True))
        self._bind("context.capture_review", review)
        f.addRow(review)
        inj_max = QSpinBox()
        inj_max.setRange(500, 20000)
        inj_max.setValue(int(s.get("context.inject_max_chars", config.CONTEXT_INJECT_MAX_CHARS)))
        self._bind("context.inject_max_chars", inj_max)
        f.addRow("SETTING inject max chars", inj_max)
        mem = QSpinBox()
        mem.setRange(0, 50)
        mem.setValue(int(s.get("context.memory_recent_turns", config.MEMORY_RECENT_TURNS)))
        self._bind("context.memory_recent_turns", mem)
        f.addRow("Memory recent turns", mem)
        return w

    def _build_orchestration(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        s = self._s()
        steps = QSpinBox()
        steps.setRange(1, 20)
        steps.setValue(int(s.get("orchestration.max_steps", config.ORCHESTRATION_MAX_STEPS)))
        self._bind("orchestration.max_steps", steps)
        f.addRow("Max orchestration steps", steps)
        hitl = QCheckBox("Human-in-the-loop (Liaison)")
        hitl.setChecked(s.get("orchestration.hitl", False))
        self._bind("orchestration.hitl", hitl)
        f.addRow(hitl)
        syn = QCheckBox("Optional team summary (planner merge pass)")
        syn.setToolTip(
            "When enabled, the system planner summarizes team output after a run. "
            "Specialist prose is not rewritten unless you enable this.")
        syn.setChecked(s.get("orchestration.synthesis", config.ORCHESTRATION_SYNTHESIS))
        self._bind("orchestration.synthesis", syn)
        f.addRow(syn)
        amb = QCheckBox("Ambiguity pre-flight check")
        amb.setChecked(s.get("orchestration.ambiguity_check", True))
        self._bind("orchestration.ambiguity_check", amb)
        f.addRow(amb)
        mgr = QLineEdit(s.get("orchestration.manager_key", config.ORCHESTRATION_MANAGER_KEY))
        mgr.setToolTip("Hidden system planner persona key (architect model).")
        self._bind("orchestration.manager_key", mgr)
        f.addRow("System planner key", mgr)
        lia = QLineEdit(s.get("orchestration.liaison_key", config.ORCHESTRATION_LIAISON_KEY))
        lia.setToolTip("Hidden liaison persona key for HITL clarifications.")
        self._bind("orchestration.liaison_key", lia)
        f.addRow("System liaison key", lia)
        return w

    def _build_editor(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        s = self._s()

        scan = QGroupBox("Lore autoscan")
        sf = QFormLayout(scan)
        autoscan = QCheckBox("Enable lore autoscan in editor")
        autoscan.setChecked(s.get("editor.lore_autoscan", True))
        self._bind("editor.lore_autoscan", autoscan)
        sf.addRow(autoscan)
        interval = QSpinBox()
        interval.setRange(1000, 60000)
        interval.setSingleStep(500)
        interval.setValue(int(s.get("editor.lore_scan_interval_ms", 3000)))
        self._bind("editor.lore_scan_interval_ms", interval)
        sf.addRow("Scan interval (ms)", interval)
        cards = QSpinBox()
        cards.setRange(1, 20)
        cards.setValue(int(s.get("editor.lore_max_cards", 5)))
        self._bind("editor.lore_max_cards", cards)
        sf.addRow("Max active lore cards", cards)
        match = QComboBox()
        match.addItem("Substring", "substring")
        match.addItem("Word boundary", "word_boundary")
        match.addItem("Regex keywords (/pat/)", "regex")
        idx = max(0, match.findData(s.get("editor.lore_match_mode", "substring")))
        match.setCurrentIndex(idx)
        self._bind("editor.lore_match_mode", match)
        sf.addRow("Lore match mode", match)
        v.addWidget(scan)

        qol = QGroupBox("Comfort (off by default — not on the editor toolbar)")
        qf = QFormLayout(qol)
        tw = QCheckBox("Typewriter scrolling (keep cursor centered)")
        tw.setChecked(bool(s.get("editor.typewriter", False)))
        self._bind("editor.typewriter", tw)
        qf.addRow(tw)
        foc = QCheckBox("Focus mode (hide AI dock)")
        foc.setChecked(bool(s.get("editor.focus_mode", False)))
        self._bind("editor.focus_mode", foc)
        qf.addRow(foc)
        ac = QCheckBox("Autocorrect as you type")
        ac.setChecked(bool(s.get("editor.autocorrect", False)))
        self._bind("editor.autocorrect", ac)
        qf.addRow(ac)
        notes = QCheckBox("Include fix-later notes in Write/Chat")
        notes.setChecked(bool(s.get("editor.include_notes_in_ai", False)))
        self._bind("editor.include_notes_in_ai", notes)
        qf.addRow(notes)
        v.addWidget(qol)

        find_g = QGroupBox("Find defaults")
        ff = QFormLayout(find_g)
        f_case = QCheckBox("Match case")
        f_case.setChecked(s.get("editor.find_case_sensitive", False))
        self._bind("editor.find_case_sensitive", f_case)
        ff.addRow(f_case)
        f_whole = QCheckBox("Whole words")
        f_whole.setChecked(s.get("editor.find_whole_words", False))
        self._bind("editor.find_whole_words", f_whole)
        ff.addRow(f_whole)
        f_re = QCheckBox("Regular expression")
        f_re.setChecked(s.get("editor.find_regex", False))
        self._bind("editor.find_regex", f_re)
        ff.addRow(f_re)
        v.addWidget(find_g)

        pipe = QGroupBox("Editor AI (Write / Chat)")
        pf = QFormLayout(pipe)
        wp = _persona_combo(s, s.get("editor.write_persona", "ghostwriter"))
        self._bind("editor.write_persona", wp)
        pf.addRow("Prose Writer", wp)
        wc = _persona_checklist(s, s.get("editor.write_critics") or [])
        wc.setToolTip(_tip(
            "Optional post-draft reviewers.",
            "Line Editor (prose_critic) — polish rhythm",
            "Canon Checker (lore_curator) — fix canon only",
            "Check none to skip review passes.",
        ))
        self._bind("editor.write_critics", wc)
        wc_lbl = QLabel("Write critics")
        wc_lbl.setToolTip(wc.toolTip())
        pf.addRow(wc_lbl, wc)
        wmt = QSpinBox()
        wmt.setRange(256, 8192)
        wmt.setValue(int(s.get("editor.write_max_tokens", 2400)))
        self._bind("editor.write_max_tokens", wmt)
        pf.addRow("Write max tokens", wmt)
        wt = _temp_spin(s.get("editor.write_temperature", 0.58))
        wt.setToolTip(_tip(
            _TEMP_TTIP,
            "",
            "Editor → Write only.",
            "Try 50–65 if output feels repetitive.",
        ))
        self._bind("editor.write_temperature", wt)
        wt_lbl = QLabel("Write temperature")
        wt_lbl.setToolTip(wt.toolTip())
        pf.addRow(wt_lbl, wt)
        cp = _persona_combo(s, s.get("editor.chat_persona", "quest_architect"))
        self._bind("editor.chat_persona", cp)
        pf.addRow("Chat persona", cp)
        cmt = QSpinBox()
        cmt.setRange(256, 8192)
        cmt.setValue(int(s.get("editor.chat_max_tokens", 1200)))
        self._bind("editor.chat_max_tokens", cmt)
        pf.addRow("Chat max tokens", cmt)
        sg_my = QPlainTextEdit()
        sg_my.setMaximumHeight(60)
        sg_my.setPlainText(s.get("editor.style_guide_my") or "")
        self._bind("editor.style_guide_my", sg_my)
        pf.addRow("My style guide", sg_my)
        sg_alt = QPlainTextEdit()
        sg_alt.setMaximumHeight(60)
        sg_alt.setPlainText(s.get("editor.style_guide_alt") or "")
        self._bind("editor.style_guide_alt", sg_alt)
        pf.addRow("Alt style guide", sg_alt)
        v.addWidget(pipe)

        team_g = QGroupBox("Team defaults")
        tf = QFormLayout(team_g)
        dp = _persona_combo(s, s.get("team.default_specialist", "world_builder"))
        self._bind("team.default_specialist", dp)
        tf.addRow("Default specialist", dp)
        bp = _persona_combo(s, s.get("team.ideas_persona", "quest_architect"))
        self._bind("team.ideas_persona", bp)
        tf.addRow("Ideas / plot specialist", bp)
        bmt = QSpinBox()
        bmt.setRange(256, 8192)
        bmt.setValue(int(s.get("team.ideas_max_tokens", 2200)))
        self._bind("team.ideas_max_tokens", bmt)
        tf.addRow("Team ideas max tokens", bmt)
        v.addWidget(team_g)
        v.addStretch()
        return w

    def _build_agents(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.addWidget(QLabel(
            "Per-persona overrides. Scope: Global applies to all projects; "
            "Project overrides global for the active project only."))
        row = QHBoxLayout()
        self.agent_scope = QComboBox()
        self.agent_scope.addItems(["Global default", "Current project"])
        self.agent_scope.currentIndexChanged.connect(self._load_agent_fields)
        row.addWidget(QLabel("Scope:"))
        row.addWidget(self.agent_scope)
        row.addStretch()
        v.addLayout(row)

        self.agent_pick = QComboBox()
        for p in self._s().personas():
            self.agent_pick.addItem(p["display_name"], p["key"])
        self.agent_pick.currentIndexChanged.connect(self._load_agent_fields)
        v.addWidget(self.agent_pick)

        af = QFormLayout()
        self.agent_model = QLineEdit()
        self._bind("_agent.model_key", self.agent_model)
        af.addRow("Model key", self.agent_model)
        self.agent_temp = _temp_spin(0.7)
        self.agent_temp.setToolTip(_tip(
            _TEMP_TTIP,
            "",
            "Override for the selected persona only.",
            "Uses Generation default if this persona has none set.",
        ))
        self._bind("_agent.temperature", self.agent_temp)
        at_lbl = QLabel("Temperature")
        at_lbl.setToolTip(self.agent_temp.toolTip())
        af.addRow(at_lbl, self.agent_temp)
        self.agent_tokens = QSpinBox()
        self.agent_tokens.setRange(256, 8192)
        self._bind("_agent.max_tokens", self.agent_tokens)
        af.addRow("Max tokens", self.agent_tokens)
        self.agent_enabled = QCheckBox("Enabled")
        self._bind("_agent.enabled", self.agent_enabled)
        af.addRow(self.agent_enabled)
        self.agent_prompt = QPlainTextEdit()
        self.agent_prompt.setMaximumHeight(120)
        self._bind("_agent.system_prompt", self.agent_prompt)
        af.addRow("System prompt override", self.agent_prompt)
        v.addLayout(af)

        btn_row = QHBoxLayout()
        save_ag = QPushButton("Save agent override")
        save_ag.clicked.connect(self._save_agent_override)
        btn_row.addWidget(save_ag)
        reset_ag = QPushButton("Reset this agent (project scope)")
        reset_ag.setProperty("secondary", True)
        reset_ag.clicked.connect(self._reset_agent_override)
        btn_row.addWidget(reset_ag)
        v.addLayout(btn_row)
        v.addStretch()
        self._load_agent_fields()
        return w

    def _build_services(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        s = self._s()
        for key, label in (
            ("services.comfyui_url", "ComfyUI URL"),
            ("services.alltalk_url", "AllTalk URL"),
            ("services.comfyui_dir", "ComfyUI install folder"),
            ("services.alltalk_dir", "AllTalk install folder"),
            ("services.piper_exe", "Piper executable"),
            ("services.piper_voice", "Piper voice model"),
            ("services.styles_csv", "Styles CSV path"),
        ):
            le = QLineEdit(str(s.get(key) or ""))
            self._bind(key, le)
            f.addRow(label, le)
        tts = QComboBox()
        tts.addItems(["alltalk", "piper", "none"])
        tts.setCurrentText(s.get("services.tts_engine", config.TTS_ENGINE))
        self._bind("services.tts_engine", tts)
        f.addRow("TTS engine", tts)
        voice = QLineEdit(s.get("services.tts_voice") or "")
        self._bind("services.tts_voice", voice)
        f.addRow("TTS voice", voice)
        hb = QSpinBox()
        hb.setRange(5, 300)
        hb.setValue(int(s.get("services.heartbeat_interval_s", config.HEARTBEAT_INTERVAL_S)))
        self._bind("services.heartbeat_interval_s", hb)
        f.addRow("Heartbeat interval (s)", hb)
        return w

    def _build_image(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        s = self._s()
        wf = QLineEdit(s.get("image.workflow") or "")
        self._bind("image.workflow", wf)
        f.addRow("Workflow file", wf)
        iw = QSpinBox()
        iw.setRange(256, 2048)
        iw.setValue(int(s.get("image.width", config.IMAGE_WIDTH)))
        self._bind("image.width", iw)
        f.addRow("Width", iw)
        ih = QSpinBox()
        ih.setRange(256, 2048)
        ih.setValue(int(s.get("image.height", config.IMAGE_HEIGHT)))
        self._bind("image.height", ih)
        f.addRow("Height", ih)
        sp = QLineEdit(s.get("image.style_prefix") or "")
        self._bind("image.style_prefix", sp)
        f.addRow("Style prefix", sp)
        seed = QComboBox()
        seed.addItems(["random", "fixed", "increment"])
        seed.setCurrentText(s.get("image.seed_behavior", config.IMAGE_SEED_BEHAVIOR))
        self._bind("image.seed_behavior", seed)
        f.addRow("Seed behavior", seed)
        return w

    def _build_appearance(self) -> QWidget:
        w = QWidget()
        f = QFormLayout(w)
        s = self._s()
        spell = QCheckBox("Spellcheck (all text fields)")
        spell.setChecked(s.get("editor.spellcheck", True))
        self._bind("editor.spellcheck", spell)
        f.addRow(spell)
        scroll = QCheckBox("Auto-scroll to end (streaming panels)")
        scroll.setChecked(s.get("ui.panel_auto_scroll", True))
        self._bind("ui.panel_auto_scroll", scroll)
        f.addRow(scroll)
        pfs = QSpinBox()
        pfs.setRange(9, 18)
        pfs.setValue(int(s.get("ui.panel_font_size", config.PANEL_FONT_SIZE)))
        self._bind("ui.panel_font_size", pfs)
        f.addRow("Panel font size", pfs)
        lbw = QSpinBox()
        lbw.setRange(320, 900)
        lbw.setValue(int(s.get("ui.lightbox_default_width", config.LIGHTBOX_DEFAULT_WIDTH)))
        self._bind("ui.lightbox_default_width", lbw)
        f.addRow("Lightbox default width", lbw)
        lbh = QSpinBox()
        lbh.setRange(400, 1200)
        lbh.setValue(int(s.get("ui.lightbox_default_height", config.LIGHTBOX_DEFAULT_HEIGHT)))
        self._bind("ui.lightbox_default_height", lbh)
        f.addRow("Lightbox default height", lbh)
        mode = QComboBox()
        mode.addItem("Replace non-pinned panels", "replace")
        mode.addItem("Stack panels", "stack")
        idx = max(0, mode.findData(s.get("ui.lightbox_single_mode", "replace")))
        mode.setCurrentIndex(idx)
        self._bind("ui.lightbox_single_mode", mode)
        f.addRow("Lightbox open mode", mode)
        ff = QLineEdit(s.get("editor.font_family") or config.EDITOR_FONT_FAMILY)
        self._bind("editor.font_family", ff)
        f.addRow("Editor font family", ff)
        lh = QSpinBox()
        lh.setRange(100, 250)
        lh.setValue(int(float(s.get("editor.line_height", config.EDITOR_LINE_HEIGHT)) * 100))
        self._bind("editor.line_height", lh)
        f.addRow("Editor line height (×100)", lh)
        wg = QSpinBox()
        wg.setRange(0, 100000)
        wg.setValue(int(s.get("editor.word_goal", config.EDITOR_WORD_GOAL)))
        self._bind("editor.word_goal", wg)
        f.addRow("Word goal", wg)
        return w

    def _load_all(self):
        pass

    def _load_agent_fields(self):
        key = self.agent_pick.currentData()
        if not key:
            return
        scope = "global" if self.agent_scope.currentIndex() == 0 else "project"
        pid = self.app.engine.project_id if scope == "project" else None
        persona = self._s().persona(pid or self.app.engine.project_id, key)
        if not persona:
            return
        self.agent_model.setText(str(persona.get("model_key") or ""))
        temp = persona.get("temperature")
        self.agent_temp.setValue(int(float(temp) * 100) if temp is not None else 70)
        mt = persona.get("max_tokens")
        self.agent_tokens.setValue(int(mt) if mt is not None else config.DEFAULT_MAX_TOKENS)
        self.agent_enabled.setChecked(persona.get("enabled", True))
        self.agent_prompt.setPlainText(persona.get("system_prompt") or "")

    def _save_agent_override(self):
        key = self.agent_pick.currentData()
        if not key:
            self.app.show_toast("No agent selected.", error=True)
            return
        scope = "global" if self.agent_scope.currentIndex() == 0 else "project"
        pid = self.app.engine.project_id if scope == "project" else None
        if scope == "project" and not pid:
            self.app.show_toast("No project loaded.", error=True)
            return
        s = self._s()
        s.set_agent_field(scope, key, "model_key", self.agent_model.text().strip() or None, pid)
        s.set_agent_field(scope, key, "temperature", self.agent_temp.value() / 100.0, pid)
        s.set_agent_field(scope, key, "max_tokens", self.agent_tokens.value(), pid)
        s.set_agent_field(scope, key, "enabled", self.agent_enabled.isChecked(), pid)
        prompt = self.agent_prompt.toPlainText()
        s.set_agent_field(scope, key, "system_prompt", prompt if prompt.strip() else None, pid)
        self.app.show_toast(f"Saved {scope} override for {key}.")

    def _reset_agent_override(self):
        key = self.agent_pick.currentData()
        pid = self.app.engine.project_id
        if not pid:
            return
        self._s().reset_agent(pid, key)
        self._load_agent_fields()
        self.app.show_toast(f"Reset project override for {key}.")

    def _reset_tab(self):
        idx = self.tabs.currentIndex()
        name = self.tabs.tabText(idx)
        mapping = {
            "General": ("ui", "lore", "updates"),
            "Generation": ("generation",),
            "Context": ("context",),
            "Orchestration": ("orchestration",),
            "Editor": ("editor",),
            "Services": ("services",),
            "Image": ("image",),
            "Appearance": ("ui", "editor"),
        }
        keys = mapping.get(name, ())
        if not keys:
            QMessageBox.information(self, "Reset", "Agents tab resets per-agent only.")
            return
        for top in keys:
            self._s().global_data[top] = copy.deepcopy(DEFAULT_GLOBAL.get(top, {}))
        self._s().save_global()
        self.app.show_toast(f"Reset {name} tab to defaults. Reopen Settings to refresh.")
        QMessageBox.information(
            self, "Reset", f"{name} defaults restored. Close and reopen Settings to see values.")

    def _save(self):
        s = self._s()
        for key, widget in self._widgets.items():
            if key.startswith("_agent"):
                continue
            val = self._read_widget(widget)
            if key == "generation.temperature":
                val = val / 100.0
            elif key == "generation.repeat_penalty":
                val = val / 100.0
            elif key == "editor.write_temperature":
                val = val / 100.0
            elif key == "editor.line_height":
                val = val / 100.0
            elif key == "editor.write_critics" and not isinstance(val, list):
                val = [x.strip() for x in str(val).split(",") if x.strip()]
            s.set(key, val, save=False)
        s.save_global()

        from ui_qt.widgets.auto_scroll import set_auto_scroll
        set_auto_scroll(self.app, s.get("ui.panel_auto_scroll", True))

        self.app.engine.context_auto_capture = s.get("context.auto_capture", True)
        if self.app.editor:
            try:
                self.app.editor.apply_settings()
            except RuntimeError as exc:
                log.warning("Editor apply_settings after save: %s", exc)
        hb = int(s.get("services.heartbeat_interval_s", config.HEARTBEAT_INTERVAL_S))
        if hasattr(self.app, "_heartbeat"):
            self.app._heartbeat.setInterval(max(5000, hb * 1000))
        self.app.show_toast("Settings saved.")

    def _read_widget(self, widget):
        if isinstance(widget, QCheckBox):
            return widget.isChecked()
        if isinstance(widget, QSpinBox):
            return widget.value()
        if isinstance(widget, QComboBox):
            data = widget.currentData()
            return data if data is not None else widget.currentText()
        if isinstance(widget, QListWidget):
            keys = []
            for i in range(widget.count()):
                item = widget.item(i)
                if item.checkState() == Qt.CheckState.Checked:
                    keys.append(item.data(Qt.ItemDataRole.UserRole))
            return keys
        if isinstance(widget, QPlainTextEdit):
            return widget.toPlainText()
        if isinstance(widget, QLineEdit):
            return widget.text()
        return None
