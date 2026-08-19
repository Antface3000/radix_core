"""Background workers for long-running agent tasks."""

from PySide6.QtCore import QThread, Signal


class AgentWorker(QThread):
    event = Signal(str, object, object)  # kind, a, b
    finished_ok = Signal()

    def __init__(self, engine, mode, message, persona_key=None, show_think=False):
        super().__init__()
        self.engine = engine
        self.mode = mode  # single | orchestrate | plan
        self.message = message
        self.persona_key = persona_key
        self.show_think = show_think
        self._ask_user_fn = None
        self._loop = None

    def set_ask_user(self, fn):
        self._ask_user_fn = fn

    def set_loop(self, loop):
        self._loop = loop

    def run(self):
        try:
            if self.mode == "single":
                self._run_single()
            elif self.mode == "orchestrate":
                self._run_orchestrate()
            elif self.mode == "plan":
                self._run_plan()
        except Exception as exc:
            self.event.emit("error", "worker", f"{type(exc).__name__}: {exc}")
        self.finished_ok.emit()

    def _run_single(self):
        name = self.persona_key or "agent"
        self.event.emit("block", name, None)
        for delta in self.engine.stream_task(
                self.persona_key, self.message, show_think=self.show_think):
            self.event.emit("delta", name, delta)
        if self.engine.is_cancelled():
            self.event.emit("cancelled", None, None)
        else:
            self.event.emit("done", None, None)

    def _run_orchestrate(self):
        from src.orchestration.runner import run_one_shot_team
        if self._loop is None:
            return
        for ev in run_one_shot_team(
                self._loop, self.engine, self.message,
                show_think=self.show_think,
                ask_user=self._ask_user_fn):
            kind = ev[0]
            if kind == "plan":
                lines = [
                    f"  {i+1}. {s['persona']['display_name']} → {s['instruction']}"
                    for i, s in enumerate(ev[1])
                ]
                self.event.emit("block", "Planner (plan)", "\n".join(lines) or "(empty)")
            elif kind == "task":
                self.event.emit("task", ev[1], ev[2] if len(ev) > 2 else None)
            elif kind == "step":
                self.event.emit("block", ev[1]["display_name"], f"(assignment: {ev[2]})")
            elif kind == "await_user":
                self.event.emit("status", ev[1], None)
            elif kind == "user":
                self.event.emit("block", "You", ev[1])
            elif kind == "delta":
                self.event.emit("delta", ev[1]["display_name"], ev[2])
            elif kind == "cancelled":
                self.event.emit("cancelled", None, None)
                return
            elif kind == "step_done":
                self.event.emit("step_done", ev[1]["display_name"], None)
            elif kind == "done":
                self.event.emit("done", None, None)
            elif kind == "error":
                self.event.emit("error", ev[1], ev[2])

    def _run_plan(self):
        if self._loop is None:
            return
        msg = (self.message or "").strip()
        if msg:
            from src.orchestration.plan_state import new_task_id
            task = {
                "id": new_task_id(),
                "title": msg[:80],
                "type": "general",
                "status": "pending",
                "priority": 10,
                "assignee": None,
                "dependsOn": [],
                "instruction": msg,
                "resultRef": None,
            }
            self._loop.plan.load()
            self._loop.plan.upsert_task(task)
            self._loop.plan.save()
        for ev in self._loop.run_pending(show_think=self.show_think):
            kind = ev[0]
            if kind == "task":
                task = ev[1]
                label = task.get("title") or task.get("id", "task")
                self.event.emit("task", label, task.get("type", "general"))
            elif kind == "step":
                self.event.emit("block", ev[1]["display_name"], f"(assignment: {ev[2]})")
            elif kind == "delta":
                self.event.emit("delta", ev[1]["display_name"], ev[2])
            elif kind == "user":
                self.event.emit("block", "You", ev[1])
            elif kind == "step_done":
                self.event.emit("step_done", ev[1]["display_name"], None)
            elif kind == "error":
                self.event.emit("error", ev[1], ev[2])
            elif kind == "cancelled":
                self.event.emit("cancelled", None, None)
                return
            elif kind == "done":
                self.event.emit("task_done", None, None)
        self.event.emit("done", None, None)


class PlanWorker(QThread):
    """Generate or execute plan.json tasks off the UI thread."""

    event = Signal(str, object, object)
    finished_ok = Signal()

    def __init__(
        self,
        engine,
        mode: str,
        *,
        goal: str = "",
        loop=None,
        store=None,
        show_think: bool = False,
        ask_user_fn=None,
        task_id: str | None = None,
    ):
        super().__init__()
        self.engine = engine
        self.mode = mode  # generate | execute
        self.goal = goal
        self._loop = loop
        self._store = store
        self.show_think = show_think
        self._ask_user_fn = ask_user_fn
        self.task_id = task_id

    def run(self):
        try:
            if self.mode == "generate":
                self._run_generate()
            elif self.mode == "execute":
                self._run_execute()
        except Exception as exc:
            self.event.emit("error", "plan", f"{type(exc).__name__}: {exc}")
        self.finished_ok.emit()

    def _run_generate(self):
        from src.orchestration.plan_builder import generate_plan
        from src.orchestration.registry import AgentRegistry
        from src.orchestration.runner import iter_liaison

        goal = self.goal
        for ev in iter_liaison(
                self.engine, goal, self._ask_user_fn, show_think=self.show_think):
            kind = ev[0]
            if kind == "liaison_done":
                goal = ev[1]
                continue
            if kind == "step":
                self.event.emit("block", ev[1]["display_name"], f"(assignment: {ev[2]})")
            elif kind == "delta":
                self.event.emit("delta", ev[1]["display_name"], ev[2])
            elif kind == "user":
                self.event.emit("block", "You", ev[1])
            elif kind == "step_done":
                self.event.emit("step_done", ev[1]["display_name"], None)
            elif kind == "cancelled":
                self.event.emit("cancelled", None, None)
                return

        self.event.emit("status", "Planner is drafting the plan…", None)
        registry = AgentRegistry()
        registry.populate_from_settings(self.engine.settings, self.engine.project_id)
        result = generate_plan(self.engine, goal, registry)
        if result.get("cancelled"):
            self.event.emit("cancelled", None, None)
            return
        if self._store is None:
            raise RuntimeError("Plan store not configured.")
        count = self._store.apply_generated_plan(result["title"], result["tasks"])
        self.event.emit("plan_ready", result["title"], count)

    def _run_execute(self):
        if self._loop is None:
            return
        if self.task_id:
            self._loop.plan.load()
            task = self._loop.plan.task_by_id(self.task_id)
            if not task:
                self.event.emit("error", "plan", f"Task not found: {self.task_id}")
                return
            events = self._loop.dispatch_task(task, show_think=self.show_think)
        else:
            events = self._loop.run_pending(show_think=self.show_think)
        for ev in events:
            kind = ev[0]
            if kind == "task":
                task = ev[1]
                label = task.get("title") or task.get("id", "task")
                self.event.emit("task", label, task.get("type", "general"))
            elif kind == "step":
                self.event.emit("block", ev[1]["display_name"], f"(assignment: {ev[2]})")
            elif kind == "delta":
                self.event.emit("delta", ev[1]["display_name"], ev[2])
            elif kind == "user":
                self.event.emit("block", "You", ev[1])
            elif kind == "step_done":
                self.event.emit("step_done", ev[1]["display_name"], None)
            elif kind == "error":
                self.event.emit("error", ev[1], ev[2])
            elif kind == "cancelled":
                self.event.emit("cancelled", None, None)
                return
            elif kind == "done":
                self.event.emit("task_done", None, None)
        self.event.emit("done", None, None)


class PackInstallWorker(QThread):
    """Run pack installers (llama wheel, GGUF download, Piper) off the UI thread."""

    line = Signal(str)
    finished_ok = Signal(bool)

    def __init__(self, kind: str, extra=None):
        super().__init__()
        self.kind = kind
        self.extra = extra or {}

    def run(self):
        import os
        import subprocess
        import sys
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        py = sys.executable
        env = {**os.environ, "PYTHONUNBUFFERED": "1"}
        if self.kind == "llama":
            cmd = [py, os.path.join(root, "scripts", "install_llama.py")]
        elif self.kind == "models":
            keys = self.extra.get("keys") or []
            cmd = [py, os.path.join(root, "scripts", "download_models.py")]
            if keys:
                cmd += ["--keys", ",".join(keys)]
        elif self.kind == "piper":
            cmd = [py, os.path.join(root, "scripts", "setup_piper.py")]
        else:
            self.line.emit(f"Unknown install kind: {self.kind}")
            self.finished_ok.emit(False)
            return
        try:
            proc = subprocess.Popen(
                cmd, cwd=root, env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1)
            assert proc.stdout is not None
            for raw in proc.stdout:
                self.line.emit(raw.rstrip())
            code = proc.wait()
            self.finished_ok.emit(code == 0)
        except Exception as exc:
            self.line.emit(str(exc))
            self.finished_ok.emit(False)


class ServiceCheckWorker(QThread):
    """Probe ComfyUI / AllTalk / Piper off the UI thread."""

    result = Signal(dict)

    def __init__(self, settings):
        super().__init__()
        self.settings = settings

    def run(self):
        from src import services
        try:
            self.result.emit(services.check_all(self.settings, timeout=2))
        except Exception:
            self.result.emit({})


class EditorAiWorker(QThread):
    delta = Signal(str)
    finished_ok = Signal(bool)  # cancelled

    def __init__(self, engine, stream_fn):
        super().__init__()
        self.engine = engine
        self.stream_fn = stream_fn

    def run(self):
        cancelled = False
        try:
            for delta in self.stream_fn():
                if self.engine.is_cancelled():
                    cancelled = True
                    break
                self.delta.emit(delta)
        except Exception:
            cancelled = True
        self.finished_ok.emit(cancelled)


class EditorPipelineWorker(QThread):
    """Write / Brainstorm pipelines with step, delta, and final events."""

    event = Signal(str, object, object)
    finished_ok = Signal(bool)

    def __init__(self, engine, pipeline_fn):
        super().__init__()
        self.engine = engine
        self.pipeline_fn = pipeline_fn

    def run(self):
        cancelled = False
        try:
            for ev in self.pipeline_fn():
                if self.engine.is_cancelled():
                    cancelled = True
                    break
                kind = ev[0]
                if kind == "final":
                    self.event.emit("final", ev[1], None)
                elif kind == "delta":
                    self.event.emit("delta", ev[1], ev[2])
                elif kind == "step":
                    self.event.emit("step", ev[1], ev[2])
                elif kind == "step_done":
                    self.event.emit("step_done", ev[1], None)
                elif kind == "plan":
                    self.event.emit("plan", ev[1], None)
                elif kind in ("cancelled",):
                    self.event.emit("cancelled", None, None)
                    cancelled = True
                    break
                else:
                    self.event.emit(kind, ev[1] if len(ev) > 1 else None,
                                    ev[2] if len(ev) > 2 else None)
            if self.engine.is_cancelled():
                cancelled = True
        except Exception:
            cancelled = True
        self.finished_ok.emit(cancelled)


class FieldGenerateWorker(QThread):
    delta = Signal(str)
    finished_ok = Signal(bool, str)  # cancelled, full_text

    def __init__(self, app, field_label, user_prompt, mode, existing_text,
                 exclude_bible_keys=None, ask_user_fn=None):
        super().__init__()
        self.app = app
        self.field_label = field_label
        self.user_prompt = user_prompt
        self.mode = mode
        self.existing_text = existing_text
        self.exclude_bible_keys = exclude_bible_keys
        self.ask_user_fn = ask_user_fn
        self._buffer = ""

    def run(self):
        from src import story_bible_gen
        from src import worldcontext

        cancelled = False
        engine = self.app.engine
        paths = engine.paths
        try:
            if self.mode == "Orchestrated":
                task = story_bible_gen.build_orchestrated_task(
                    paths, self.field_label, self.user_prompt,
                    self.existing_text, exclude_bible_keys=self.exclude_bible_keys)
                ask = self.ask_user_fn if self.app.settings.get("orchestration.hitl") else None
                for ev in story_bible_gen.orchestrate_field(
                        engine, task, ask_user=ask, show_think=False):
                    kind = ev[0]
                    if kind == "delta":
                        self._buffer += ev[1]
                        self.delta.emit(ev[1])
                    elif kind == "done":
                        if ev[1]:
                            self._buffer = ev[1]
                    elif kind == "cancelled":
                        cancelled = True
                        break
            else:
                for chunk in story_bible_gen.stream_field(
                        engine, paths, self.field_label, self.user_prompt,
                        self.mode, self.existing_text,
                        exclude_bible_keys=self.exclude_bible_keys):
                    if engine.is_cancelled():
                        cancelled = True
                        break
                    self._buffer += chunk
                    self.delta.emit(chunk)
            if engine.is_cancelled():
                cancelled = True
        except Exception:
            cancelled = True
        self.finished_ok.emit(cancelled, self._buffer)
