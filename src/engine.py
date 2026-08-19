"""AgentEngine - the cognitive backend.

Maps personas to models, lazily loads GGUF weights through llama-cpp-python,
and runs chat completions. Designed for an 8GB GPU via SINGLE-SLOT loading:
only one model is ever resident; switching to a persona on a different tier
unloads the previous model first.

Project-aware: memory, lore, story bible and world state all come from the
active project (src/projects.py). The "setting" is injected at runtime from
src/worldcontext.py so the personas stay genre-agnostic. All tunables are read
through src/settings.py so the Settings Control Center is authoritative.

If llama-cpp-python isn't installed or the GGUF file is missing, the engine
returns a clearly-labeled MOCK response so the GUI still runs end-to-end.
"""

import gc
import os
import re
import time

import config
from src import personas, projects, worldcontext
from src.logutil import get_logger
from src.memory import Memory
from src.settings import Settings
from src.llm_runner import LlmRunner

log = get_logger("engine")

try:
    from llama_cpp import Llama
    LLAMA_AVAILABLE = True
except Exception:  # pragma: no cover - import guard
    Llama = None
    LLAMA_AVAILABLE = False

# Matches DeepSeek-R1 style reasoning blocks: <think> ... </think>
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)

_ANTI_REPEAT = (
    "\n\nDo not repeat or paraphrase facts already present in SETTING above. "
    "Add only new, task-specific information."
)

_STEP_NO_CAPTURE = (
    "\n\nDo not use [[REMEMBER]], [[BIBLE:*]], [[CHARACTER]], or other canon "
    "markers in this step. Focus on your assignment only."
)


class RunCancelled(Exception):
    """Raised when the user stops an in-flight agent run."""


class AgentEngine:
    def __init__(self, settings=None, project_id=None):
        self.settings = settings or Settings()
        self.current_key = None      # model_key of the resident model
        self.current_llm = None      # llama_cpp.Llama instance, or None in mock
        self._last_generation = ("", "")  # (raw, visible) from last generate

        # Quick toggles mirror settings; GUI may flip them at runtime.
        self.context_inject = self.settings.get("context.inject", True)
        self.context_auto_capture = self.settings.get("context.auto_capture", True)
        self.flush_callback = None  # optional GUI hook: flush unsaved story data
        self.capture_callback = None  # optional GUI hook: refresh canon panels
        self._last_capture_summary = worldcontext.empty_capture_summary()
        self._cancel_requested = False
        self.llm = LlmRunner(self.settings)

        self.project_id = None
        self.paths = None
        self.memory = None
        self.set_project(project_id or projects.get_active_project_id())

    # ----------------------- projects --------------------------------------
    def set_project(self, project_id):
        """Switch the active project: rewire paths + memory."""
        projects.ensure_project_layout(project_id)
        projects.set_active_project_id(project_id)
        self.project_id = project_id
        self.paths = projects.project_paths(project_id)
        from src import series
        self.paths = series.overlay_canon_paths(self.paths, project_id)
        self.memory = Memory(self.paths["memory"])
        log.info("Project active: %s", project_id)
        return project_id

    def list_projects(self):
        return projects.list_projects()

    def create_project(self, name):
        project = projects.create_project(name)
        return project

    def active_project(self):
        return projects.get_active_project()

    # ----------------------- persona helpers -------------------------------
    def get_personas_grouped(self):
        return personas.get_personas_grouped(
            self.settings.selectable_personas(self.project_id))

    def _resolve_persona(self, identifier):
        p = self.settings.persona(self.project_id, identifier)
        if p is None:
            raise ValueError(f"Unknown persona: {identifier!r}")
        return p

    @staticmethod
    def _dispatch_system_prompt(persona):
        """Orchestration dispatch: drop persistence marker block (see _STEP_NO_CAPTURE)."""
        from src import personas
        text = persona.get("system_prompt") or ""
        note = personas._REMEMBER_NOTE
        if note in text:
            text = text.replace(note, "")
        return text.strip()

    # ----------------------- model loading ---------------------------------
    def _load_model(self, model_key):
        return self.llm._load_model(model_key)

    def unload(self):
        self.llm.unload()

    # ----------------------- generation params -----------------------------
    def _temp(self, persona):
        return persona.get("temperature") or self.settings.get(
            "generation.temperature", config.DEFAULT_TEMPERATURE)

    def _max_tokens(self, persona, override=None):
        return (override or persona.get("max_tokens")
                or self.settings.get("generation.max_tokens",
                                     config.DEFAULT_MAX_TOKENS))

    def _flush_context(self):
        if callable(self.flush_callback):
            try:
                self.flush_callback()
            except Exception:
                pass

    def clear_cancel(self):
        self._cancel_requested = False
        self.llm.clear_cancel()

    def request_cancel(self):
        self._cancel_requested = True
        self.llm.request_cancel()

    def is_cancelled(self):
        return self._cancel_requested or self.llm.is_cancelled()

    def _check_cancel(self):
        if self.is_cancelled():
            raise RunCancelled()

    # ----------------------- inference -------------------------------------
    def execute_task(self, persona_identifier, user_input, show_think=False,
                     max_tokens=None):
        """Run one persona and return the (cleaned) response text."""
        self._flush_context()
        self._last_capture_summary = worldcontext.empty_capture_summary()
        p = self._resolve_persona(persona_identifier)
        messages = self._build_messages(p, user_input)
        chunks = list(self._stream_generate(p, messages, show_think, max_tokens))
        _, visible = self._last_generation
        self._finalize(p, user_input)
        return visible if visible else "".join(chunks)

    def stream_task(self, persona_identifier, user_input, show_think=False,
                    max_tokens=None):
        """Generator yielding visible text deltas as they are produced."""
        self.clear_cancel()
        self._flush_context()
        self._last_capture_summary = worldcontext.empty_capture_summary()
        p = self._resolve_persona(persona_identifier)
        messages = self._build_messages(p, user_input)
        try:
            for delta in self._stream_generate(p, messages, show_think, max_tokens):
                yield delta
        except RunCancelled:
            return
        self._finalize(p, user_input)

    def _stream_generate(self, persona, messages, show_think=False,
                         max_tokens=None):
        """Core generator: stream one completion for `persona`."""
        for delta in self.llm.stream(
                persona, messages, show_think, max_tokens, self.llm.cancel_token):
            yield delta
        self._last_generation = self.llm.last_generation
        self.current_key = self.llm.current_key
        self.current_llm = self.llm.current_llm

    def specialist_system_prompt(self, persona):
        """Specialist chat prompt: drop persistence markers when capture is off."""
        if self.context_auto_capture:
            return persona["system_prompt"]
        return self._dispatch_system_prompt(persona)

    def stream_persona(self, persona_key, instruction, show_think=False, *,
                       orchestration=False):
        """OrchestratorLoop adapter."""
        if orchestration:
            yield from self._stream_orchestration_dispatch(
                persona_key, instruction, show_think=show_think)
            return
        yield from self.stream_task(persona_key, instruction, show_think=show_think)

    def _stream_orchestration_dispatch(self, persona_key, instruction,
                                       show_think=False):
        """Scoped dispatch: task instruction + setting only (no persona memory)."""
        self.clear_cancel()
        self._flush_context()
        self._last_capture_summary = worldcontext.empty_capture_summary()
        p = self._resolve_persona(persona_key)
        sys_prompt = self._dispatch_system_prompt(p)
        messages = [{"role": "system", "content": sys_prompt}]
        setting = self._setting_block()
        if setting:
            messages.append({"role": "system", "content": setting})
        user_content = instruction
        if setting:
            user_content = instruction + _STEP_NO_CAPTURE
        messages.append({"role": "user", "content": user_content})
        try:
            for delta in self._stream_generate(p, messages, show_think):
                yield delta
        except RunCancelled:
            return
        self._finalize(p, instruction)

    def run_persona(self, persona_key, instruction, show_think=False, *,
                    orchestration=False):
        if orchestration:
            return "".join(self._stream_orchestration_dispatch(
                persona_key, instruction, show_think=show_think))
        return self.execute_task(persona_key, instruction, show_think=show_think)

    def finalize_persona(self, persona_key, instruction, raw):
        p = self._resolve_persona(persona_key)
        self._last_generation = (raw, raw)
        self.memory.append(p["key"], instruction, raw.strip())
        self._capture(p, raw)

    # ----------------------- orchestration ---------------------------------
    def build_orchestrator_loop(self, ask_user=None):
        from src.orchestration.loop import OrchestratorLoop
        from src.orchestration.registry import AgentRegistry
        from src.tools import build_tools

        registry = AgentRegistry()
        registry.populate_from_settings(self.settings, self.project_id)
        loop = OrchestratorLoop(
            self.project_id,
            registry,
            self,
            self.settings,
            ask_user=ask_user,
        )
        if self.paths:
            match_mode = self.settings.get("editor.lore_match_mode", "substring")
            for name, fn in build_tools(self.paths, match_mode=match_mode).items():
                loop.gatekeeper.register(name, fn)
        return loop

    def orchestrate(self, task, show_think=False, ask_user=None):
        """Planner + specialist dispatch via OrchestratorLoop (no silent synthesis rewrite)."""
        from src.orchestration.runner import run_one_shot_team

        self.clear_cancel()
        self._flush_context()
        self._last_capture_summary = worldcontext.empty_capture_summary()
        loop = self.build_orchestrator_loop(ask_user=ask_user)
        yield from run_one_shot_team(
            loop, self, task, show_think=show_think, ask_user=ask_user)
        summary = self._last_capture_summary
        if (summary.get("lore") or summary.get("bible") or summary.get("world_state")):
            if callable(self.capture_callback):
                try:
                    self.capture_callback()
                except Exception:
                    pass

    # ----------------------- message assembly ------------------------------
    @staticmethod
    def _compose(pairs):
        return [{"role": r, "content": c} for r, c in pairs]

    def _setting_block(self):
        if not self.context_inject:
            return None
        text = worldcontext.assemble(
            self.paths,
            max_chars=self.settings.get("context.inject_max_chars", 6000))
        return text or None

    def _build_messages(self, persona, user_input):
        messages = [{"role": "system",
                     "content": self.specialist_system_prompt(persona)}]
        setting = self._setting_block()
        if setting:
            messages.append({"role": "system", "content": setting})
        turns = self.settings.get("context.memory_recent_turns",
                                  config.MEMORY_RECENT_TURNS)
        for turn in self.memory.recent(persona["key"], turns):
            messages.append({"role": "user", "content": turn["user"]})
            messages.append({"role": "assistant", "content": turn["response"]})
        user_content = user_input
        if setting:
            user_content = user_input + _ANTI_REPEAT
        messages.append({"role": "user", "content": user_content})
        return messages

    def _build_orchestration_messages(self, persona, task, instruction, working):
        messages = [{"role": "system", "content": persona["system_prompt"]}]
        setting = self._setting_block()
        if setting:
            messages.append({"role": "system", "content": setting})
        brief = f"MISSION TASK:\n{task}\n"
        if working:
            brief += "\nWORK SO FAR (from other agents - cross-reference it):\n"
            for name, out in working:
                brief += f"\n[{name}]:\n{out}\n"
        brief += f"\nYOUR ASSIGNMENT:\n{instruction}"
        if setting:
            brief += _STEP_NO_CAPTURE
        messages.append({"role": "user", "content": brief})
        return messages

    def _build_synthesis_messages(self, task, working, system=None):
        system = system or (
            "You are The Manager. Synthesize the agents' work into one coherent "
            "final result for the task. Resolve conflicts, surface any "
            "unresolved fact-check flags, and keep it tight and actionable.\n\n"
            "CANON EXPORT (optional): Wrap only genuinely NEW facts not already "
            "in SETTING in plain markers (no markdown inside tags). If nothing "
            "new was discovered, omit all markers entirely:\n"
            "- [[CHARACTER:Name]]...[[/CHARACTER]] for new character profiles\n"
            "- [[WORLD]]...[[/WORLD]] for new places/factions\n"
            "- [[BIBLE:premise]]...[[/BIBLE]], etc. only for new bible facts\n"
            "- [[REMEMBER]]...[[/REMEMBER]] for short new lore snippets\n"
            "Do not re-export premise, synopsis, or lore already in SETTING.")
        user = f"TASK:\n{task}\n\nAGENT OUTPUTS:\n"
        for name, out in working:
            user += f"\n[{name}]:\n{out}\n"
        user += "\nProduce the final result."
        pairs = [("system", system)]
        setting = self._setting_block()
        if setting:
            pairs.append(("system", setting))
        pairs.append(("user", user))
        return self._compose(pairs)

    # ----------------------- persistence -----------------------------------
    def _finalize(self, persona, user_input):
        raw, visible = self._last_generation
        self.memory.append(persona["key"], user_input, visible)
        self._capture(persona, raw)

    def _capture(self, persona, raw_text, *, notify_ui=True):
        if not self.context_auto_capture or not raw_text:
            return
        bible_mode = self.settings.get("context.capture_bible_mode", "empty")
        if bible_mode == "replace":
            bible_mode = "merge"
        stage = None
        if self.settings.get("context.capture_review", True):
            from src.capture_queue import CaptureQueue
            stage = CaptureQueue(self.paths).stage
        summary = worldcontext.capture_from_agent(
            self.paths, raw_text,
            default_kind=persona.get("capture_kind") or "world",
            source=persona.get("display_name", "agent"),
            bible_mode=bible_mode,
            stage=stage,
        )
        self._last_capture_summary = worldcontext.merge_capture_summaries(
            self._last_capture_summary, summary)
        if notify_ui and callable(self.capture_callback):
            try:
                self.capture_callback()
            except Exception:
                pass

    # ----------------------- utilities -------------------------------------
    @staticmethod
    def _strip_think(text):
        cleaned = _THINK_RE.sub("", text)
        if "<think>" in cleaned:
            cleaned = cleaned.split("<think>", 1)[0]
        cleaned = cleaned.replace("</think>", "")
        return cleaned.strip()

    @staticmethod
    def _clean_stream(buffer):
        cleaned = _THINK_RE.sub("", buffer)
        if "<think>" in cleaned:
            cleaned = cleaned.split("<think>", 1)[0]
        return cleaned.replace("</think>", "")

    @staticmethod
    def _word_chunks(text):
        return re.findall(r"\S+\s*", text)

    def _mock_response(self, persona, user_input):
        reason = ("llama-cpp-python not installed"
                  if not LLAMA_AVAILABLE else
                  f"model file not found for key '{persona['model_key']}'")
        return (
            f"[MOCK - {persona['display_name']}] ({reason})\n"
            f"Drop the .gguf in models/ (see config.MODEL_REGISTRY) to go live.\n"
            f"--- echo ---\n{user_input}"
        )

    # ----------------------- generic LLM tool helper -----------------------
    def run_tool(self, system_prompt, user_prompt, model_key="operator",
                 temperature=0.3, max_tokens=512):
        """One-shot completion for internal tools (e.g. SDXL tagger).

        Not tied to a persona; not persisted. Returns the cleaned text.
        """
        pseudo = {"model_key": model_key, "temperature": temperature,
                  "display_name": "Tool", "capture_kind": None}
        messages = self._compose([("system", system_prompt),
                                   ("user", user_prompt)])
        list(self._stream_generate(pseudo, messages, show_think=False,
                                   max_tokens=max_tokens))
        _, visible = self._last_generation
        return visible

    def stream_prompt(self, model_key, system_prompt, user_prompt,
                      temperature=0.7, max_tokens=None, show_think=False,
                      repeat_penalty=None):
        """Stream a one-shot (system,user) completion with no memory/injection.

        Used by the editor AI pipelines, which assemble their own context via
        src/story_context.py. Yields visible text deltas.
        """
        self._flush_context()
        pseudo = {"model_key": model_key, "temperature": temperature,
                  "display_name": "Editor", "capture_kind": None}
        if repeat_penalty is not None:
            pseudo["repeat_penalty"] = repeat_penalty
        messages = self._compose([("system", system_prompt),
                                   ("user", user_prompt)])
        for delta in self._stream_generate(pseudo, messages, show_think,
                                           max_tokens):
            yield delta

    # ----------------------- editor AI pipelines (delegated) ----------------
    # The prose pipelines live in src/writing_engine.py (WritingEngine) for a
    # cleaner split; these shims keep older call sites working and share this
    # engine's single model slot.
    def _writing(self):
        we = getattr(self, "_writing_engine", None)
        if we is None:
            from src.writing_engine import WritingEngine
            we = self._writing_engine = WritingEngine(self)
        return we

    def editor_write(self, *args, **kwargs):
        return self._writing().editor_write(*args, **kwargs)

    def editor_brainstorm(self, *args, **kwargs):
        return self._writing().editor_brainstorm(*args, **kwargs)

    def editor_chat(self, *args, **kwargs):
        return self._writing().editor_chat(*args, **kwargs)
