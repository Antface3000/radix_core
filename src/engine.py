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
from src.memory import Memory
from src.settings import Settings

try:
    from llama_cpp import Llama
    LLAMA_AVAILABLE = True
except Exception:  # pragma: no cover - import guard
    Llama = None
    LLAMA_AVAILABLE = False

# Matches DeepSeek-R1 style reasoning blocks: <think> ... </think>
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


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
        self.memory = Memory(self.paths["memory"])
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
        return personas.get_personas_grouped(self.settings.enabled_personas(self.project_id))

    def _resolve_persona(self, identifier):
        p = self.settings.persona(self.project_id, identifier)
        if p is None:
            raise ValueError(f"Unknown persona: {identifier!r}")
        return p

    # ----------------------- model loading ---------------------------------
    def _load_model(self, model_key):
        if self.current_key == model_key:
            return self.current_llm
        self.unload()  # single-slot

        spec = self.settings.model_spec(model_key)
        if spec is None:
            raise KeyError(f"No model registered for key {model_key!r}")
        path = spec.get("path", "")
        if not LLAMA_AVAILABLE or not os.path.exists(path):
            self.current_key = model_key
            self.current_llm = None
            return None

        self.current_llm = Llama(
            model_path=path,
            n_ctx=spec.get("n_ctx", 4096),
            n_gpu_layers=spec.get("n_gpu_layers", -1),
            verbose=False,
            **spec.get("extra", {}),
        )
        self.current_key = model_key
        return self.current_llm

    def unload(self):
        if self.current_llm is not None:
            del self.current_llm
        self.current_llm = None
        self.current_key = None
        gc.collect()

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
        self._flush_context()
        self._last_capture_summary = worldcontext.empty_capture_summary()
        p = self._resolve_persona(persona_identifier)
        messages = self._build_messages(p, user_input)
        for delta in self._stream_generate(p, messages, show_think, max_tokens):
            yield delta
        self._finalize(p, user_input)

    def _stream_generate(self, persona, messages, show_think=False,
                         max_tokens=None):
        """Core generator: stream one completion for `persona`.

        Yields visible text deltas and stashes (raw, visible) in
        self._last_generation for the caller to persist.
        """
        llm = self._load_model(persona["model_key"])
        raw_parts = []
        emitted = 0

        if llm is None:
            mock = self._mock_response(persona, messages[-1]["content"])
            for chunk in self._word_chunks(mock):
                raw_parts.append(chunk)
                time.sleep(0.02)
                yield chunk
            raw = "".join(raw_parts)
            visible = raw
        else:
            stream = llm.create_chat_completion(
                messages=messages,
                temperature=self._temp(persona),
                max_tokens=self._max_tokens(persona, max_tokens),
                stream=True,
            )
            for chunk in stream:
                delta = chunk["choices"][0].get("delta", {}).get("content")
                if not delta:
                    continue
                raw_parts.append(delta)
                raw = "".join(raw_parts)
                visible = raw if show_think else self._clean_stream(raw)
                new = visible[emitted:]
                if new:
                    emitted = len(visible)
                    yield new
            raw = "".join(raw_parts)
            visible = raw if show_think else self._strip_think(raw)

        self._last_generation = (raw, visible.strip())

    # ----------------------- orchestration ---------------------------------
    def orchestrate(self, task, show_think=False, ask_user=None):
        """Manager-driven multi-agent pipeline (optionally human-in-the-loop).

        Yields event tuples for the GUI:
            ("plan", [ {persona, instruction}, ... ])
            ("step", persona, instruction)
            ("delta", persona, text)
            ("step_done", persona)
            ("await_user", prompt)   # (informational; answer comes via ask_user)
            ("user", answer)
            ("synthesis", manager_persona)
            ("done",)

        `ask_user(prompt) -> str` is a blocking callback supplied by the GUI; if
        provided and HITL is enabled, the Liaison gathers requirements before
        planning and checks in before synthesis.
        """
        self._flush_context()
        self._last_capture_summary = worldcontext.empty_capture_summary()
        manager = self._resolve_persona(
            self.settings.get("orchestration.manager_key", "manager"))
        hitl = bool(self.settings.get("orchestration.hitl", False)) and callable(ask_user)

        augmented_task = task

        # --- HITL: requirements gathering by the Liaison ---
        if hitl:
            liaison = self.settings.persona(
                self.project_id,
                self.settings.get("orchestration.liaison_key", "user_liaison"))
            if liaison:
                yield ("step", liaison, "Gather requirements from the user.")
                msgs = self._compose([
                    ("system", liaison["system_prompt"]),
                ])
                setting = self._setting_block()
                if setting:
                    msgs.append({"role": "system", "content": setting})
                msgs.append({"role": "user", "content":
                    "The user wants to: " + task +
                     "\n\nAsk up to 3 focused clarifying questions before the "
                     "team begins. If the request is already clear, say so."})
                for delta in self._stream_generate(liaison, msgs, show_think):
                    yield ("delta", liaison, delta)
                _, questions = self._last_generation
                yield ("step_done", liaison)
                yield ("await_user", "Answer the Liaison's questions (or leave blank to proceed):")
                answer = ask_user("Answer the Liaison's questions:") or ""
                if answer.strip():
                    yield ("user", answer)
                    augmented_task = (task + "\n\nUSER CLARIFICATIONS:\n" + answer)

        plan = self._make_plan(augmented_task, manager)
        yield ("plan", plan)

        working = []  # list of (display_name, output)
        for step in plan:
            p = step["persona"]
            instruction = step["instruction"]
            yield ("step", p, instruction)
            messages = self._build_orchestration_messages(
                p, augmented_task, instruction, working)
            for delta in self._stream_generate(p, messages, show_think):
                yield ("delta", p, delta)
            raw, visible = self._last_generation
            self.memory.append(p["key"], instruction, visible)
            self._capture(p, raw)
            working.append((p["display_name"], visible))
            yield ("step_done", p)

        # --- HITL: pre-synthesis check-in by the Liaison ---
        if hitl and working:
            liaison = self.settings.persona(
                self.project_id,
                self.settings.get("orchestration.liaison_key", "user_liaison"))
            if liaison:
                yield ("step", liaison, "Summarize progress for the user.")
                msgs = self._build_synthesis_messages(
                    augmented_task, working,
                    system=liaison["system_prompt"] +
                    "\nSummarize the team's work so far for the user in plain "
                    "language and ask if they want any changes before the final "
                    "result.")
                for delta in self._stream_generate(liaison, msgs, show_think):
                    yield ("delta", liaison, delta)
                yield ("step_done", liaison)
                yield ("await_user", "Any changes before the final result? (blank = proceed):")
                feedback = ask_user("Any changes before the final result?") or ""
                if feedback.strip():
                    yield ("user", feedback)
                    working.append(("User feedback", feedback))

        if self.settings.get("orchestration.synthesis", True) and working:
            yield ("synthesis", manager)
            messages = self._build_synthesis_messages(augmented_task, working)
            for delta in self._stream_generate(manager, messages, show_think):
                yield ("delta", manager, delta)
            raw, visible = self._last_generation
            self.memory.append(manager["key"], "[synthesis] " + task, visible)
            self._capture(manager, raw)

        yield ("done",)

    def _make_plan(self, task, manager):
        roster_personas = [p for p in self.settings.enabled_personas(self.project_id)]
        roster = personas.roster_for_planner(
            roster_personas,
            exclude_keys=(self.settings.get("orchestration.manager_key", "manager"),))
        max_steps = self.settings.get("orchestration.max_steps", 5)
        planner_sys = (
            "You are The Manager, an orchestration planner. Given a TASK, choose "
            "an ordered pipeline of agents to accomplish it. Prefer to end with a "
            "review/fact-check step (e.g. lore_curator) when correctness matters.\n"
            "Respond with ONLY a JSON array, no prose. Each element:\n"
            '  {"agent": "<exact agent key>", "instruction": "<what they do>"}\n'
            f"Use at most {max_steps} steps."
        )
        planner_user = (
            f"TASK:\n{task}\n\nAVAILABLE AGENTS (key: role):\n{roster}\n\n"
            "Return ONLY the JSON plan."
        )
        pairs = [("system", planner_sys)]
        setting = self._setting_block()
        if setting:
            pairs.append(("system", setting))
        pairs.append(("user", planner_user))
        messages = self._compose(pairs)
        text = "".join(self._stream_generate(manager, messages, show_think=False))
        plan = self._parse_plan(text)
        return plan or self._default_plan(task)

    def _parse_plan(self, text):
        import json
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except (json.JSONDecodeError, ValueError):
            return None
        if not isinstance(data, list):
            return None
        max_steps = self.settings.get("orchestration.max_steps", 5)
        steps = []
        for item in data:
            if not isinstance(item, dict):
                continue
            agent = item.get("agent") or item.get("persona") or item.get("key")
            instruction = (item.get("instruction") or item.get("task") or "").strip()
            persona = self.settings.persona(self.project_id, agent) if agent else None
            if persona and instruction:
                steps.append({"persona": persona, "instruction": instruction})
            if len(steps) >= max_steps:
                break
        return steps or None

    def _default_plan(self, task):
        steps = []
        builder = self.settings.persona(self.project_id, "world_builder")
        curator = self.settings.persona(self.project_id, "lore_curator")
        if builder:
            steps.append({"persona": builder, "instruction": task})
        if curator:
            steps.append({
                "persona": curator,
                "instruction": ("Fact-check the previous output against "
                                "established canon and flag inconsistencies."),
            })
        if not steps:
            any_persona = self.settings.enabled_personas(self.project_id)[0]
            steps.append({"persona": any_persona, "instruction": task})
        return steps

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
        messages = [{"role": "system", "content": persona["system_prompt"]}]
        setting = self._setting_block()
        if setting:
            messages.append({"role": "system", "content": setting})
        turns = self.settings.get("context.memory_recent_turns",
                                  config.MEMORY_RECENT_TURNS)
        for turn in self.memory.recent(persona["key"], turns):
            messages.append({"role": "user", "content": turn["user"]})
            messages.append({"role": "assistant", "content": turn["response"]})
        messages.append({"role": "user", "content": user_input})
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
        messages.append({"role": "user", "content": brief})
        return messages

    def _build_synthesis_messages(self, task, working, system=None):
        system = system or (
            "You are The Manager. Synthesize the agents' work into one coherent "
            "final result for the task. Resolve conflicts, surface any "
            "unresolved fact-check flags, and keep it tight and actionable.\n\n"
            "CANON EXPORT: Wrap durable facts in plain markers (no markdown inside "
            "tags):\n"
            "- [[CHARACTER:Name]]...[[/CHARACTER]] for character profiles\n"
            "- [[WORLD]]...[[/WORLD]] for places/factions\n"
            "- [[BIBLE:premise]]...[[/BIBLE]], [[BIBLE:synopsis]]...[[/BIBLE]], "
            "[[BIBLE:genreTone]]...[[/BIBLE]], [[BIBLE:worldRules]]...[[/BIBLE]]\n"
            "- [[WORLDSTATE:currentLocation]]...[[/WORLDSTATE]], "
            "[[WORLDSTATE:currentDate]]...[[/WORLDSTATE]]\n"
            "Include these markers in your synthesis so the project canon updates.")
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

    def _capture(self, persona, raw_text):
        if not self.context_auto_capture or not raw_text:
            return
        bible_mode = self.settings.get("context.capture_bible_mode", "empty")
        if bible_mode == "replace":
            bible_mode = "merge"
        summary = worldcontext.capture_from_agent(
            self.paths, raw_text,
            default_kind=persona.get("capture_kind") or "world",
            source=persona.get("display_name", "agent"),
            bible_mode=bible_mode,
        )
        self._last_capture_summary = worldcontext.merge_capture_summaries(
            self._last_capture_summary, summary)
        if callable(self.capture_callback):
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
                      temperature=0.7, max_tokens=None, show_think=False):
        """Stream a one-shot (system,user) completion with no memory/injection.

        Used by the editor AI pipelines, which assemble their own context via
        src/story_context.py. Yields visible text deltas.
        """
        self._flush_context()
        pseudo = {"model_key": model_key, "temperature": temperature,
                  "display_name": "Editor", "capture_kind": None}
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
