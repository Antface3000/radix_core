"""Team panel — specialists, one-shot team runs, and project plans in one place."""

from __future__ import annotations

import threading

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtGui import QColor, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src import personas, worldcontext
from src.logutil import get_logger
from src.orchestration.loop import OrchestratorLoop
from src.orchestration.plan_state import PlanStateStore
from src.orchestration.registry import AgentRegistry
from src.tools import build_tools
from ui_qt.ai_workflow import TEAM_SUBTITLE, TEAM_TAB_TIPS
from ui_qt.ambiguity_gate import run_ambiguity_gate
from ui_qt.panels.base import BasePanel
from ui_qt.stream_throttle import StreamThrottler
from ui_qt.workers import AgentWorker, PlanWorker
from ui_qt.widgets.activity_indicator import ActivityStatus
from ui_qt.widgets.auto_scroll import make_auto_scroll_checkbox, scroll_to_end

log = get_logger("team")

_TIER_TAG = {
    personas.TIER_ARCHITECT: "T1",
    personas.TIER_OPERATOR: "T2",
    personas.TIER_FLAVOR: "T3",
}

_STATUS_PREFIX = {
    "pending": "[ ]",
    "in_progress": "[~]",
    "done": "[x]",
    "cancelled": "[-]",
}


class _CaptureDialog(QDialog):
    def __init__(self, parent, initial=""):
        super().__init__(parent)
        self.setWindowTitle("Capture canon from text")
        self.resize(520, 320)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "Paste agent output with [[REMEMBER]], [[BIBLE:field]], etc. markers:"))
        self.text = QPlainTextEdit()
        self.text.setPlainText(initial)
        layout.addWidget(self.text)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class TeamPanel(BasePanel):
    title = "Team"

    ask_user_signal = Signal(str, object)

    TAB_SPECIALIST = 0
    TAB_TEAM_JOB = 1
    # Legacy aliases (main_window / editor handoff)
    TAB_TEAM_RUN = TAB_TEAM_JOB
    TAB_PLAN = TAB_TEAM_JOB

    def __init__(self, app, parent=None):
        super().__init__(app, parent)
        self._busy = False
        self._agent_worker: AgentWorker | None = None
        self._plan_worker: PlanWorker | None = None
        self._current = ""
        self.last_response = ""
        self._loop: OrchestratorLoop | None = None
        self._store: PlanStateStore | None = None
        self._transcript: list[list] = []   # [who, text] sections for run reports
        self._run_goal = ""
        self._report_kind: str | None = None

        layout = QVBoxLayout(self)
        subtitle = QLabel(TEAM_SUBTITLE)
        subtitle.setWordWrap(True)
        subtitle.setProperty("secondary", True)
        layout.addWidget(subtitle)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_specialist_tab(), "Specialist")
        self.tabs.addTab(self._build_team_job_tab(), "Team job")
        self.tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self.tabs)

        split = QSplitter(Qt.Vertical)
        self.chat = QPlainTextEdit()
        self.chat.setReadOnly(True)
        split.addWidget(self.chat)
        self.event_log = QPlainTextEdit()
        self.event_log.setReadOnly(True)
        self.event_log.setMaximumHeight(100)
        self.event_log.setPlaceholderText("Event log…")
        split.addWidget(self.event_log)
        layout.addWidget(split, 1)

        util_row = QHBoxLayout()
        capture_btn = QPushButton("Capture from text…")
        capture_btn.setProperty("secondary", True)
        capture_btn.clicked.connect(self._capture_from_text)
        util_row.addWidget(capture_btn)
        insert_btn = QPushButton("Insert into manuscript")
        insert_btn.setProperty("secondary", True)
        insert_btn.clicked.connect(self._insert_into_manuscript)
        util_row.addWidget(insert_btn)
        preview_btn = QPushButton("Preview setting")
        preview_btn.setProperty("secondary", True)
        preview_btn.clicked.connect(self._preview_setting)
        util_row.addWidget(preview_btn)
        util_row.addStretch()
        layout.addLayout(util_row)

        bottom = QHBoxLayout()
        self.entry = QLineEdit()
        self.entry.returnPressed.connect(self.run)
        bottom.addWidget(self.entry, 1)
        self.run_btn = QPushButton("Run")
        self.run_btn.clicked.connect(self.run)
        bottom.addWidget(self.run_btn)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setProperty("danger", True)
        self.stop_btn.clicked.connect(self.stop)
        self.stop_btn.hide()
        bottom.addWidget(self.stop_btn)
        clear_btn = QPushButton("Clear")
        clear_btn.setProperty("secondary", True)
        clear_btn.clicked.connect(self.chat.clear)
        bottom.addWidget(clear_btn)
        layout.addLayout(bottom)

        self.status = ActivityStatus("Ready.")
        layout.addWidget(self.status)

        self.ask_user_signal.connect(self._show_ask_dialog)
        self._stream_throttle = StreamThrottler(
            self._append_text_chunk, interval_ms=80, parent=self)
        self._status_timer = QTimer(self)
        self._status_timer.setSingleShot(True)
        self._status_timer.timeout.connect(self._flush_status)
        self._pending_status = ""
        self._refresh_personas()
        self._init_loop()
        self._on_tab_changed(self.tabs.currentIndex())

    def _build_specialist_tab(self) -> QWidget:
        w = QWidget()
        row = QHBoxLayout(w)
        row.addWidget(QLabel("Specialist:"))
        self.persona_combo = QComboBox()
        row.addWidget(self.persona_combo, 1)
        self.show_think = QCheckBox("Show thinking")
        row.addWidget(self.show_think)
        row.addWidget(make_auto_scroll_checkbox(self.app, self))
        self.inject_cb = QCheckBox("Inject setting")
        self.inject_cb.setChecked(self.app.engine.context_inject)
        self.inject_cb.toggled.connect(self._toggle_inject)
        row.addWidget(self.inject_cb)
        return w

    def _build_team_job_tab(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        hint = QLabel(TEAM_TAB_TIPS["Team job"])
        hint.setWordWrap(True)
        hint.setProperty("secondary", True)
        v.addWidget(hint)

        self.plan_title = QLabel("No plan loaded.")
        self.plan_title.setWordWrap(True)
        v.addWidget(self.plan_title)

        self.goal = QPlainTextEdit()
        self.goal.setPlaceholderText(
            "Team job goal (or use the message bar below).\n"
            "Example: Outline Act 2 — escalate conflict and verify against canon.")
        self.goal.setMaximumHeight(72)
        v.addWidget(self.goal)

        opt_row = QHBoxLayout()
        self.save_plan_cb = QCheckBox("Save as project plan")
        self.save_plan_cb.setToolTip(
            "When checked, Run generates a saved plan.json task list instead of "
            "a one-shot ephemeral pipeline.")
        opt_row.addWidget(self.save_plan_cb)
        self.save_plan_cb.toggled.connect(
            lambda _checked: self._on_tab_changed(self.tabs.currentIndex()))
        opt_row.addStretch()
        v.addLayout(opt_row)

        gen_row = QHBoxLayout()
        self.generate_btn = QPushButton("Generate plan")
        self.generate_btn.clicked.connect(self._generate_plan)
        gen_row.addWidget(self.generate_btn)
        refresh_btn = QPushButton("Refresh tasks")
        refresh_btn.setProperty("secondary", True)
        refresh_btn.clicked.connect(self._refresh_tasks)
        gen_row.addWidget(refresh_btn)
        gen_row.addStretch()
        v.addLayout(gen_row)

        self.task_list = QListWidget()
        self.task_list.setMaximumHeight(100)
        self.task_list.setToolTip("Right-click a task to run, edit, or reassign it.")
        self.task_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.task_list.customContextMenuRequested.connect(self._show_task_menu)
        v.addWidget(self.task_list)

        self.run_plan_btn = QPushButton("Run pending tasks")
        self.run_plan_btn.clicked.connect(self._execute_plan)
        v.addWidget(self.run_plan_btn)

        advanced = QGroupBox("Advanced: edit Plan.md")
        advanced.setCheckable(True)
        advanced.setChecked(False)
        adv_layout = QVBoxLayout(advanced)
        self.md_editor = QPlainTextEdit()
        self.md_editor.setMaximumHeight(80)
        adv_layout.addWidget(self.md_editor)
        md_row = QHBoxLayout()
        save_md_btn = QPushButton("Save Plan.md")
        save_md_btn.clicked.connect(self._save_md)
        md_row.addWidget(save_md_btn)
        rebuild_btn = QPushButton("Rebuild from JSON")
        rebuild_btn.setProperty("secondary", True)
        rebuild_btn.clicked.connect(self._rebuild_md)
        md_row.addWidget(rebuild_btn)
        adv_layout.addLayout(md_row)
        v.addWidget(advanced)
        return w

    def _build_team_run_tab(self):
        """Deprecated — merged into _build_team_job_tab."""
        return self._build_team_job_tab()

    def _build_plan_tab(self):
        """Deprecated — merged into _build_team_job_tab."""
        return self._build_team_job_tab()

    def _on_tab_changed(self, index: int):
        tips = {
            self.TAB_SPECIALIST: TEAM_TAB_TIPS["Specialist"],
            self.TAB_TEAM_JOB: TEAM_TAB_TIPS["Team job"],
        }
        self.entry.setPlaceholderText(tips.get(index, "Message…"))
        self.persona_combo.setEnabled(index == self.TAB_SPECIALIST)
        if index == self.TAB_TEAM_JOB:
            self._refresh_tasks()
            pending = self._pending_task_count()
            if pending:
                self.run_btn.setText(f"Run pending ({pending})")
            elif self.save_plan_cb.isChecked():
                self.run_btn.setText("Generate & save plan")
            else:
                self.run_btn.setText("Run team job")
        else:
            self.run_btn.setText("Run")

    def _plan_has_pending(self) -> bool:
        return self._pending_task_count() > 0

    def prepare_from_editor(self, message: str, mode: str = "single", tab: int | None = None):
        tab_map = {
            "single": self.TAB_SPECIALIST,
            "orchestrate": self.TAB_TEAM_JOB,
            "plan": self.TAB_TEAM_JOB,
            "team": self.TAB_TEAM_JOB,
        }
        idx = tab if tab is not None else tab_map.get(mode, self.TAB_SPECIALIST)
        self.tabs.setCurrentIndex(idx)
        if message:
            if idx == self.TAB_TEAM_JOB:
                self.goal.setPlainText(message)
            else:
                self.entry.setText(message)

    def show_plan_tab(self):
        self.tabs.setCurrentIndex(self.TAB_TEAM_JOB)

    def _init_loop(self):
        registry = AgentRegistry()
        registry.populate_from_settings(self.app.settings, self.app.engine.project_id)
        self._loop = OrchestratorLoop(
            self.app.engine.project_id,
            registry,
            self.app.engine,
            self.app.settings,
            ask_user=self._ask_user_blocking,
        )
        if self.app.engine.paths:
            match_mode = self.app.settings.get("editor.lore_match_mode", "substring")
            tools = build_tools(self.app.engine.paths, match_mode=match_mode)
            for name, fn in tools.items():
                self._loop.gatekeeper.register(name, fn)

    def _store_for_project(self) -> PlanStateStore:
        pid = self.app.engine.project_id
        if self._store is None or self._store.project_id != pid:
            self._store = PlanStateStore(pid)
            self._store.load()
        return self._store

    def _pending_task_count(self) -> int:
        try:
            store = self._store_for_project()
            store.load()
            return sum(
                1 for t in (store.data.get("tasks") or [])
                if t.get("status") == "pending")
        except Exception:
            return 0

    def _refresh_personas(self):
        self.persona_combo.clear()
        self._persona_map = {}
        for tier, plist in self.app.engine.get_personas_grouped().items():
            tag = _TIER_TAG.get(tier, "")
            for p in plist:
                label = f"[{tag}] {p['display_name']}"
                self._persona_map[label] = p
                self.persona_combo.addItem(label)
        default_key = self.app.settings.get("team.default_specialist", "world_builder")
        for i in range(self.persona_combo.count()):
            p = self._persona_map.get(self.persona_combo.itemText(i))
            if p and p.get("key") == default_key:
                self.persona_combo.setCurrentIndex(i)
                break

    def _refresh_tasks(self):
        if not hasattr(self, "task_list"):
            return
        store = self._store_for_project()
        store.load()
        title = store.data.get("title") or "Project plan"
        tasks = store.data.get("tasks") or []
        pending = sum(1 for t in tasks if t.get("status") == "pending")
        done = sum(1 for t in tasks if t.get("status") == "done")
        self.plan_title.setText(
            f"{title}  —  {len(tasks)} tasks ({pending} pending, {done} done)")
        self.run_plan_btn.setText(
            f"Run pending tasks ({pending})" if pending else "Run pending tasks")
        self.run_plan_btn.setEnabled(pending > 0 and not self._busy)
        self.task_list.clear()
        for task in sorted(tasks, key=lambda t: t.get("priority", 99)):
            status = task.get("status", "pending")
            prefix = _STATUS_PREFIX.get(status, "[ ]")
            assignee = task.get("assignee") or "auto"
            label = (
                f"{prefix} {task.get('title', 'Untitled')}  "
                f"({task.get('type', 'general')} → {assignee})")
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, task.get("id"))
            if status == "done":
                item.setForeground(QColor("#6a9e6a"))
            elif status == "in_progress":
                item.setForeground(QColor("#c9a227"))
            self.task_list.addItem(item)
        if self.tabs.currentIndex() == self.TAB_TEAM_JOB:
            pending = sum(1 for t in tasks if t.get("status") == "pending")
            if pending:
                self.run_btn.setText(f"Run pending ({pending})")
            elif hasattr(self, "save_plan_cb") and self.save_plan_cb.isChecked():
                self.run_btn.setText("Generate & save plan")
            else:
                self.run_btn.setText("Run team job")

    # ----------------------- plan task context menu -------------------------
    def _show_task_menu(self, pos):
        from PySide6.QtWidgets import QMenu
        item = self.task_list.itemAt(pos)
        if item is None:
            return
        task_id = item.data(Qt.UserRole)
        store = self._store_for_project()
        store.load()
        task = store.task_by_id(task_id)
        if not task:
            return
        menu = QMenu(self)
        run_act = menu.addAction("Run this task")
        run_act.setEnabled(not self._busy)
        edit_act = menu.addAction("Edit instruction…")
        reassign_act = menu.addAction("Reassign specialist…")
        menu.addSeparator()
        done_act = menu.addAction("Mark done")
        done_act.setEnabled(task.get("status") != "done")
        delete_act = menu.addAction("Delete task")
        chosen = menu.exec(self.task_list.mapToGlobal(pos))
        if chosen is run_act:
            self._run_single_task(task_id)
        elif chosen is edit_act:
            self._edit_task_instruction(store, task)
        elif chosen is reassign_act:
            self._reassign_task(store, task)
        elif chosen is done_act:
            store.set_task_status(task_id, "done")
            self._refresh_tasks()
        elif chosen is delete_act:
            store.data["tasks"] = [
                t for t in store.data.get("tasks", [])
                if t.get("id") != task_id]
            store.save()
            store.export_markdown()
            self._refresh_tasks()

    def _edit_task_instruction(self, store: PlanStateStore, task: dict):
        text, ok = QInputDialog.getMultiLineText(
            self, "Edit task instruction",
            task.get("title", "Task"),
            task.get("instruction", ""))
        if not ok:
            return
        store.upsert_task({"id": task["id"], "instruction": text.strip()})
        self._refresh_tasks()

    def _reassign_task(self, store: PlanStateStore, task: dict):
        options = []
        keys = []
        for plist in self.app.engine.get_personas_grouped().values():
            for p in plist:
                options.append(f"{p['display_name']} ({p['key']})")
                keys.append(p["key"])
        if not options:
            return
        current = task.get("assignee") or ""
        idx = keys.index(current) if current in keys else 0
        choice, ok = QInputDialog.getItem(
            self, "Reassign specialist", "Assign this task to:",
            options, idx, False)
        if not ok or not choice:
            return
        key = keys[options.index(choice)]
        from src.orchestration.task_types import task_type_for_agent
        patch = {"id": task["id"], "assignee": key}
        new_type = task_type_for_agent(key)
        if new_type:
            patch["type"] = new_type
        store.upsert_task(patch)
        self._refresh_tasks()

    def _run_single_task(self, task_id: str):
        if self._busy:
            return
        store = self._store_for_project()
        store.load()
        task = store.task_by_id(task_id)
        if not task:
            return
        if task.get("status") in ("done", "in_progress"):
            store.set_task_status(task_id, "pending")
        self.app.engine.clear_cancel()
        self._init_loop()
        self._current = ""
        self._begin_report("Task run", task.get("title", ""))
        self._append_block("Plan", f"Running task: {task.get('title', task_id)}")
        self._set_busy(True, f"Running {task.get('title', 'task')}…")
        self._plan_worker = PlanWorker(
            self.app.engine, "execute",
            loop=self._loop, show_think=self.show_think.isChecked(),
            task_id=task_id)
        self._plan_worker.event.connect(
            self._on_plan_event, Qt.ConnectionType.QueuedConnection)
        self._plan_worker.finished_ok.connect(
            self._on_plan_finished, Qt.ConnectionType.QueuedConnection)
        self._plan_worker.start()

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
        from ui_qt.widgets.clarify_dialog import ClarifyDialog
        dlg = ClarifyDialog(
            self, [], title="The team needs your input", preamble=prompt)
        if dlg.exec() == ClarifyDialog.Accepted:
            callback(dlg.freeform_answer())
        else:
            callback("")

    def _toggle_inject(self, checked):
        self.app.engine.context_inject = checked
        self.app.settings.set("context.inject", checked)

    def _preview_setting(self):
        paths = self.app.engine.paths
        if not paths:
            self.app.show_toast("No project loaded.", error=True)
            return
        text = worldcontext.assemble(
            paths,
            max_chars=int(self.app.settings.get("context.inject_max_chars", 6000)))
        dlg = QDialog(self)
        dlg.setWindowTitle("Setting preview")
        dlg.resize(560, 420)
        v = QVBoxLayout(dlg)
        v.addWidget(QLabel(f"{len(text):,} characters (pinned + active lore)"))
        view = QPlainTextEdit()
        view.setReadOnly(True)
        view.setPlainText(text or "(empty)")
        v.addWidget(view)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dlg.reject)
        buttons.accepted.connect(dlg.accept)
        v.addWidget(buttons)
        dlg.exec()

    def _insert_into_manuscript(self):
        text = (self.last_response or self.chat.toPlainText()).strip()
        if not text:
            self.app.show_toast("No output to insert.", error=True)
            return
        editor = getattr(self.app, "editor", None)
        if editor and hasattr(editor, "insert_ai_draft"):
            editor.insert_ai_draft(text)
            self.app.show_toast("Inserted into manuscript.")
        else:
            self.app.show_toast("Editor is not available.", error=True)

    def _capture_from_text(self):
        paths = self.app.engine.paths
        if not paths:
            return
        dlg = _CaptureDialog(self, self.last_response)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        raw = dlg.text.toPlainText().strip()
        if not raw:
            return
        summary = worldcontext.capture_from_agent(
            paths, raw,
            bible_mode=self.app.settings.get("context.capture_bible_mode", "empty"))
        msg = worldcontext.format_capture_summary(summary)
        if msg:
            self.app.show_toast(msg)
            self.app.refresh_canon_panels()
        else:
            self.app.show_toast("No capture markers found in text.")

    def run(self):
        tab = self.tabs.currentIndex()
        if tab == self.TAB_TEAM_JOB:
            pending = self._pending_task_count()
            if pending and not self.entry.text().strip() and not self.goal.toPlainText().strip():
                self._execute_plan()
                return
            if self.save_plan_cb.isChecked() and not pending:
                self._generate_plan()
                return
            msg = self.entry.text().strip() or self.goal.toPlainText().strip()
            if not msg:
                if pending:
                    self._execute_plan()
                else:
                    self.app.show_toast("Enter a team job goal.", error=True)
                return
            proceed, enriched = run_ambiguity_gate(
                self, self.app, msg, interactive_questions=True)
            if not proceed:
                return
            msg = enriched
            self.entry.clear()
            self._begin_report("Team job", msg)
            self._append_block("You", msg)
            self._current = ""
            show = self.show_think.isChecked()
            self.app.engine.clear_cancel()
            self._set_busy(True)
            self._init_loop()
            self._agent_worker = AgentWorker(
                self.app.engine, "orchestrate", msg, show_think=show)
            self._agent_worker.set_ask_user(self._ask_user_blocking)
            self._agent_worker.set_loop(self._loop)
            self.status.set_status("Liaison → planner → specialists…", active=True)
            self._agent_worker.event.connect(
                self._on_agent_event, Qt.ConnectionType.QueuedConnection)
            self._agent_worker.finished_ok.connect(
                self._on_agent_finished, Qt.ConnectionType.QueuedConnection)
            self._agent_worker.start()
            return
        if self._busy:
            return
        msg = self.entry.text().strip()
        if not msg:
            return
        proceed, enriched = run_ambiguity_gate(
            self, self.app, msg, interactive_questions=False)
        if not proceed:
            return
        msg = enriched
        self.entry.clear()
        self._append_block("You", msg)
        self._current = ""
        show = self.show_think.isChecked()
        self.app.engine.clear_cancel()
        self._set_busy(True)

        p = self._current_persona()
        if not p:
            self._set_busy(False, "No specialist selected.")
            return
        self._agent_worker = AgentWorker(
            self.app.engine, "single", msg,
            persona_key=p["key"], show_think=show)
        self.status.set_status(f"{p['display_name']} is thinking…", active=True)

        self._agent_worker.event.connect(
            self._on_agent_event, Qt.ConnectionType.QueuedConnection)
        self._agent_worker.finished_ok.connect(
            self._on_agent_finished, Qt.ConnectionType.QueuedConnection)
        self._agent_worker.start()

    def _current_persona(self):
        return self._persona_map.get(self.persona_combo.currentText())

    def _generate_plan(self):
        if self._busy:
            return
        goal = self.goal.toPlainText().strip() or self.entry.text().strip()
        if not goal:
            self.app.show_toast("Enter a goal for the plan.", error=True)
            return
        proceed, enriched = run_ambiguity_gate(
            self, self.app, goal, interactive_questions=True)
        if not proceed:
            return
        goal = enriched
        self.goal.setPlainText(goal)
        self.app.engine.clear_cancel()
        self._current = ""
        self.chat.clear()
        self._set_busy(True, "Planner is drafting the plan…")
        store = self._store_for_project()
        self._plan_worker = PlanWorker(
            self.app.engine, "generate",
            goal=goal, store=store, show_think=self.show_think.isChecked(),
            ask_user_fn=self._ask_user_blocking)
        self._plan_worker.event.connect(
            self._on_plan_event, Qt.ConnectionType.QueuedConnection)
        self._plan_worker.finished_ok.connect(
            self._on_plan_finished, Qt.ConnectionType.QueuedConnection)
        self._plan_worker.start()

    def _execute_plan(self):
        if self._busy:
            return
        pending = self._pending_task_count()
        if not pending:
            self.app.show_toast("No pending tasks.", error=True)
            return
        self.app.engine.clear_cancel()
        self._init_loop()
        self._current = ""
        self.chat.clear()
        self._begin_report("Plan run", self.goal.toPlainText().strip())
        self._append_block("Plan", f"Running {pending} pending task(s)…")
        self._set_busy(True, f"Running {pending} pending task(s)…")
        self._plan_worker = PlanWorker(
            self.app.engine, "execute",
            loop=self._loop, show_think=self.show_think.isChecked())
        self._plan_worker.event.connect(
            self._on_plan_event, Qt.ConnectionType.QueuedConnection)
        self._plan_worker.finished_ok.connect(
            self._on_plan_finished, Qt.ConnectionType.QueuedConnection)
        self._plan_worker.start()

    def _save_md(self):
        store = self._store_for_project()
        try:
            summary = store.import_markdown(self.md_editor.toPlainText())
            self._refresh_tasks()
            self.app.show_toast(f"Plan saved ({summary['tasks_updated']} tasks).")
        except Exception as exc:
            log.exception("Plan import failed")
            self.app.show_toast(str(exc), error=True)

    def _rebuild_md(self):
        store = self._store_for_project()
        self.md_editor.setPlainText(store.rebuild_markdown_from_json())
        self.app.show_toast("Plan.md rebuilt from plan.json.")

    def stop(self):
        self.app.engine.request_cancel()
        if self._loop:
            self._loop.cancel()
        self.status.set_status("Stopping…", active=True)

    def _set_busy(self, busy: bool, status: str = "Ready."):
        self._busy = busy
        self.run_btn.setVisible(not busy)
        self.stop_btn.setVisible(busy)
        self.generate_btn.setEnabled(not busy)
        self.run_plan_btn.setEnabled(not busy and self._pending_task_count() > 0)
        self.status.set_status(status, active=busy)

    def _on_agent_event(self, kind, a, b):
        if kind == "task":
            self._append_block("Task", str(a))
            self._current = ""
        elif kind == "block":
            self._append_block(a, b or "")
            self._current = ""
        elif kind == "delta":
            self._current += b
            self._stream_throttle.append(b)
            self._record_delta(b)
            self.last_response = self._current.strip()
            self._pending_status = f"Streaming…  {len(self._current.split())} words"
            if not self._status_timer.isActive():
                self._status_timer.start(400)
        elif kind == "status":
            self.status.set_status(str(a), active=True)
        elif kind == "step_done":
            self._stream_throttle.flush_now()
        elif kind == "done":
            self._stream_throttle.flush_now()
            summary = worldcontext.format_capture_summary(
                self.app.engine._last_capture_summary)
            if summary:
                self.app.show_toast(summary)
            self._write_run_report()
            self._set_busy(False, f"Done.  {len(self.last_response.split())} words.")
            self._refresh_event_log()
        elif kind == "cancelled":
            self._stream_throttle.flush_now()
            self._report_kind = None
            self._set_busy(False, "Cancelled.")
        elif kind == "error":
            self._stream_throttle.flush_now()
            self._append_block(a, f"[ERROR] {b}")
            self._report_kind = None
            self._set_busy(False, "Error.")

    def _on_plan_event(self, kind, a, b):
        if kind == "status":
            self.status.set_status(str(a), active=True)
        elif kind == "plan_ready":
            self._append_block("Planner", f"Plan ready: {a} ({b} tasks)")
            self._refresh_tasks()
            self.md_editor.setPlainText(self._store_for_project().export_markdown())
            self.app.show_toast(f"Plan created: {b} tasks.")
            self._set_busy(False, "Plan ready — run pending tasks when ready.")
        elif kind == "task":
            self._append_block("Task", str(a))
            self._refresh_tasks()
        elif kind == "block":
            self._append_block(a, b or "")
            self._current = ""
        elif kind == "delta":
            self._current += b
            self._stream_throttle.append(b)
            self._record_delta(b)
            self.last_response = self._current.strip()
        elif kind == "step_done":
            self._stream_throttle.flush_now()
            self._refresh_tasks()
        elif kind == "done":
            self._stream_throttle.flush_now()
            summary = worldcontext.format_capture_summary(
                self.app.engine._last_capture_summary)
            if summary:
                self.app.show_toast(summary)
                self.app.refresh_canon_panels()
            self._write_run_report()
            self._refresh_tasks()
            self.md_editor.setPlainText(self._store_for_project().export_markdown())
            self._set_busy(False, "Plan execution finished.")
        elif kind == "cancelled":
            self._stream_throttle.flush_now()
            self._report_kind = None
            self._refresh_tasks()
            self._set_busy(False, "Cancelled.")
        elif kind == "error":
            self._stream_throttle.flush_now()
            self._append_block(a, f"[ERROR] {b}")
            self._report_kind = None
            self._set_busy(False, "Error.")
            self.app.show_toast(str(b), error=True)

    def _on_agent_finished(self):
        self._stream_throttle.flush_now()
        self._flush_status()

    def _on_plan_finished(self):
        self._stream_throttle.flush_now()

    def _append_block(self, who: str, text: str):
        cur = self.chat.toPlainText()
        prefix = "\n\n" if cur else ""
        self.chat.appendPlainText(f"{prefix}[{who}]\n{text}")
        scroll_to_end(self.chat, self.app)
        if self._report_kind is not None and who != "You":
            self._transcript.append([str(who), text or ""])

    # ----------------------- run reports -----------------------------------
    def _begin_report(self, kind: str, goal: str):
        self._report_kind = kind
        self._run_goal = goal
        self._transcript = []

    def _record_delta(self, text: str):
        if self._report_kind is not None and self._transcript:
            self._transcript[-1][1] += text

    def _write_run_report(self):
        kind = self._report_kind
        self._report_kind = None
        if not kind or not self._transcript:
            return
        paths = self.app.engine.paths
        if not paths:
            return
        try:
            from src.run_report import write_run_report
            path = write_run_report(
                paths, self._run_goal,
                [tuple(sec) for sec in self._transcript], kind=kind)
            self.app.show_toast(f"Run report saved: {path}")
        except Exception:
            log.exception("Run report write failed")

    def _append_text_chunk(self, text: str):
        cursor = self.chat.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertText(text)
        self.chat.setTextCursor(cursor)
        scroll_to_end(self.chat, self.app)

    def _flush_status(self):
        if self._pending_status and self._busy:
            self.status.set_status(self._pending_status, active=True)

    def _refresh_event_log(self):
        if not self._loop:
            return
        self.event_log.clear()
        for ev in self._loop.log.read_all()[-15:]:
            self.event_log.appendPlainText(f"{ev.timestamp}  {ev.type.value}")

    def on_show(self):
        self._refresh_tasks()
        store = self._store_for_project()
        try:
            with open(store.md_path, "r", encoding="utf-8") as fh:
                self.md_editor.setPlainText(fh.read())
        except OSError:
            self.md_editor.setPlainText(store.export_markdown())
        self._on_tab_changed(self.tabs.currentIndex())

    def on_project_change(self):
        self._store = None
        self._refresh_personas()
        self._init_loop()
        self.on_show()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape and self._busy:
            self.stop()
        else:
            super().keyPressEvent(event)
