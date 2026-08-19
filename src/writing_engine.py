"""WritingEngine - the editor-facing prose pipelines.

Kept separate from AgentEngine (agents/orchestration) for a cleaner CMV-style
split: the View (editor panel) talks to this Model for prose, while the heavy
model loading + agent roster live in AgentEngine. There is still only ONE model
slot - WritingEngine borrows the shared AgentEngine for all low-level inference
(stream_prompt / orchestrate / _stream_generate), so nothing is duplicated.
"""


class WritingEngine:
    def __init__(self, engine):
        self.engine = engine

    def _critic_review_prompt(self, critic_key: str, ctx_text: str, draft: str) -> str:
        head = f"{ctx_text}\n\nDRAFT PASSAGE:\n{draft}\n\n"
        if critic_key == "lore_curator":
            return (head +
                    "Canon check only. Fix factual contradictions with minimal "
                    "edits. Do not add lore exposition, recap the bible, or repeat "
                    "STORY SO FAR. If canon is fine, return the DRAFT unchanged. "
                    "Output ONLY the passage.")
        if critic_key == "prose_critic":
            return (head +
                    "Polish the draft: improve rhythm and clarity; cut filler, "
                    "cliché, and any sentence that repeats an idea or echoes "
                    "STORY SO FAR. Keep events, POV, and tense. "
                    "Output ONLY the revised passage.")
        if critic_key == "pessimistic_critic":
            return (head +
                    "Critique the draft for clichés, tropes, and false notes. "
                    "Name specific lines and why they fail. "
                    "Output bullet findings only — do not rewrite the passage.")
        if critic_key == "optimistic_critic":
            return (head +
                    "Elevate the draft: sharpen mood, rhythm, and imagery while "
                    "keeping the author's intent. "
                    "Output ONLY the revised passage of prose.")
        if critic_key == "horny_critic":
            return (head +
                    "Critique the draft for chemistry, tension, and physical "
                    "presence. Point out what falls flat and how to land it. "
                    "Output bullet findings only — do not rewrite the passage.")
        if critic_key == "voice_lock":
            return (head +
                    "Match the AUTHOR VOICE SAMPLES below in diction, rhythm, "
                    "and sentence length. Do not copy sentences. "
                    "Output ONLY the revised passage.\n\n"
                    + (self._voice_samples() or "(no samples yet)"))
        return (head +
                "Revise the DRAFT PASSAGE according to your role. Do not repeat "
                "STORY SO FAR. Output ONLY the revised passage of prose.")

    @property
    def settings(self):
        return self.engine.settings

    @property
    def project_id(self):
        return self.engine.project_id

    @property
    def paths(self):
        return self.engine.paths

    # ----------------------- editor AI pipelines ---------------------------
    def editor_write(self, before_cursor, chapter_id, author_note="",
                     direction="", show_think=False):
        """Ghostwriter draft -> critics review (or full team if configured).

        Yields the same event tuples as orchestrate(), plus:
            ("final", text)   the insertable result
        """
        from src import story_context
        eng = self.engine
        s = self.settings
        ctx = story_context.build_story_context(
            self.paths, before_cursor=before_cursor, chapter_id=chapter_id,
            author_note=author_note, inject_mode="smart",
            max_cards=s.get("editor.lore_max_cards", 5),
            use_retrieval=bool(s.get("plugins.llm", False)))

        gw = eng._resolve_persona(s.get("editor.write_persona", "ghostwriter"))
        system, user = story_context.build_write_prompt(
            ctx["text"],
            voice_preset=s.get("editor.voice_preset", "my"),
            style_my=s.get("editor.style_guide_my", ""),
            style_alt=s.get("editor.style_guide_alt", ""),
            direction=direction,
            system_override=gw["system_prompt"])
        max_tokens = s.get("editor.write_max_tokens", 1600)
        repeat_penalty = s.get("generation.repeat_penalty", 1.15)
        write_temp = s.get("editor.write_temperature", 0.58)

        yield ("step", gw, "Drafting the next passage")
        for delta in eng.stream_prompt(
                gw["model_key"], system, user,
                temperature=write_temp,
                max_tokens=max_tokens,
                repeat_penalty=repeat_penalty,
                show_think=show_think):
            yield ("delta", gw, delta)
        _, draft = eng._last_generation
        yield ("stage_draft", gw, draft)
        yield ("step_done", gw)

        for ck in (s.get("editor.write_critics", []) or []):
            critic = s.persona(self.project_id, ck)
            if not critic:
                continue
            review_user = self._critic_review_prompt(ck, ctx["text"], draft)
            yield ("step", critic, "Reviewing the draft")
            for _delta in eng.stream_prompt(
                    critic["model_key"], critic["system_prompt"], review_user,
                    temperature=critic.get("temperature") or 0.45,
                    max_tokens=max_tokens,
                    repeat_penalty=repeat_penalty,
                    show_think=show_think):
                pass
            _, draft = eng._last_generation
            yield ("stage_draft", critic, draft)
            yield ("step_done", critic)

        if s.get("plugins.llm") and self._voice_samples():
            critic = s.persona(self.project_id, "prose_critic") or gw
            review_user = self._critic_review_prompt("voice_lock", ctx["text"], draft)
            yield ("step", {**critic, "display_name": "Voice lock"}, "Matching your accepted pages")
            for _delta in eng.stream_prompt(
                    critic["model_key"], critic["system_prompt"], review_user,
                    temperature=0.4, max_tokens=max_tokens,
                    repeat_penalty=repeat_penalty, show_think=show_think):
                pass
            _, draft = eng._last_generation
            yield ("stage_draft", {**critic, "display_name": "Voice lock"}, draft)
            yield ("step_done", critic)

        yield ("final", story_context.sanitize_write_output(
            draft, story_tail=before_cursor))

    def _voice_samples(self) -> str:
        import os
        path = os.path.join(self.paths["root"], "voice_lock.txt")
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return fh.read()[-4000:]
        except OSError:
            return ""

    def editor_query_blurb(self, kind: str, extra: str = "", show_think=False):
        """Named job: query letter, synopsis, or cover blurb — never manuscript prose."""
        from src import story_context
        eng = self.engine
        s = self.settings
        ctx = story_context.build_story_context(
            self.paths, before_cursor="", chapter_id=None,
            inject_mode="pinnedAndActive", max_cards=20,
            use_retrieval=True)
        persona = eng._resolve_persona(
            s.get("team.ideas_persona", "quest_architect"))
        kind = (kind or "blurb").lower()
        if kind == "query":
            task = ("Write a one-page query letter for this project. "
                    "Hook, stakes, word-count placeholder, comparable titles. "
                    "Do not write manuscript prose.")
        elif kind == "synopsis":
            task = ("Write a 500–800 word spoiler synopsis covering the full plot. "
                    "Do not write manuscript prose.")
        else:
            task = ("Write a 150-word cover blurb. Mood and stakes only. "
                    "Do not write manuscript prose.")
        if extra.strip():
            task += "\n\nAuthor notes:\n" + extra.strip()
        user = ctx["text"] + "\n\n" + task
        yield ("step", persona, f"Drafting {kind}")
        for delta in eng.stream_prompt(
                persona["model_key"], persona["system_prompt"], user,
                temperature=0.55,
                max_tokens=s.get("team.ideas_max_tokens", 2200),
                show_think=show_think):
            yield ("delta", persona, delta)
        _, visible = eng._last_generation
        yield ("step_done", persona)
        yield ("final", visible)

    def editor_brainstorm(self, recent_text, selection="", instruction="",
                          show_think=False):
        """Brainstorm ideas (single agent or full team). Yields events + final."""
        from src import story_context
        eng = self.engine
        s = self.settings
        if s.get("editor.brainstorm_mode", "single") == "team":
            task = ("Brainstorm 3 creative directions for this story.\n\n"
                    + recent_text[-2000:]
                    + (("\n\nSelected passage: " + selection) if selection else ""))
            final = ""
            for ev in eng.orchestrate(task, show_think=show_think):
                if ev[0] == "delta":
                    final += ev[2]
                yield ev
            yield ("final", final)
            return

        persona = eng._resolve_persona(
            s.get("editor.brainstorm_persona", "quest_architect"))
        prompt = story_context.build_brainstorm_prompt(
            recent_text, selection, instruction)
        yield ("step", persona, "Brainstorming")
        for delta in eng.stream_prompt(
                persona["model_key"], persona["system_prompt"], prompt,
                temperature=0.9,
                max_tokens=s.get("editor.brainstorm_max_tokens", 2200),
                show_think=show_think):
            yield ("delta", persona, delta)
        _, visible = eng._last_generation
        yield ("step_done", persona)
        yield ("final", visible)

    def editor_chat(self, system_prompt, history, user_msg, show_think=False):
        """Stream one turn of the project chat. `history` = [(role, content)]."""
        eng = self.engine
        persona = eng._resolve_persona(
            self.settings.get("editor.chat_persona", "quest_architect"))
        messages = [{"role": "system", "content": system_prompt}]
        for role, content in history:
            messages.append({"role": role, "content": content})
        messages.append({"role": "user", "content": user_msg})
        pseudo = {"model_key": persona["model_key"],
                  "temperature": persona.get("temperature") or 0.5,
                  "display_name": persona["display_name"], "capture_kind": None}
        for delta in eng._stream_generate(
                pseudo, messages, show_think,
                self.settings.get("editor.chat_max_tokens", 1200)):
            yield delta
