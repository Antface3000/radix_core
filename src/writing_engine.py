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
            max_cards=s.get("editor.lore_max_cards", 5))

        if s.get("editor.write_full_team", False):
            task = (ctx["text"] + "\n\nContinue the narrative naturally from the "
                    "end of STORY SO FAR. Write the next passage of prose only.")
            final = ""
            for ev in eng.orchestrate(task, show_think=show_think):
                if ev[0] == "delta":
                    final += ev[2]
                yield ev
            yield ("final", story_context.sanitize_write_output(final))
            return

        gw = eng._resolve_persona(s.get("editor.write_persona", "ghostwriter"))
        system, user = story_context.build_write_prompt(
            ctx["text"],
            voice_preset=s.get("editor.voice_preset", "my"),
            style_my=s.get("editor.style_guide_my", ""),
            style_alt=s.get("editor.style_guide_alt", ""),
            direction=direction,
            system_override=gw["system_prompt"])
        max_tokens = s.get("editor.write_max_tokens", 1400)

        yield ("step", gw, "Drafting the next passage")
        for delta in eng.stream_prompt(
                gw["model_key"], system, user,
                temperature=s.get("editor.write_temperature", 0.65),
                max_tokens=max_tokens, show_think=show_think):
            yield ("delta", gw, delta)
        _, draft = eng._last_generation
        yield ("step_done", gw)

        for ck in (s.get("editor.write_critics", []) or []):
            critic = s.persona(self.project_id, ck)
            if not critic:
                continue
            review_user = (ctx["text"] + "\n\nDRAFT PASSAGE:\n" + draft +
                           "\n\nRevise the DRAFT PASSAGE according to your role. "
                           "Output ONLY the revised passage of prose.")
            yield ("step", critic, "Reviewing the draft")
            for delta in eng.stream_prompt(
                    critic["model_key"], critic["system_prompt"], review_user,
                    temperature=critic.get("temperature") or 0.5,
                    max_tokens=max_tokens, show_think=show_think):
                yield ("delta", critic, delta)
            _, draft = eng._last_generation
            yield ("step_done", critic)

        yield ("final", story_context.sanitize_write_output(draft))

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
            self.settings.get("editor.chat_persona", "user_liaison"))
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
