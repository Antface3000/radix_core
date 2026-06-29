"""TTS panel - speak text via the configured local engine (AllTalk/Piper)."""

import threading

import customtkinter as ctk

from gui import theme
from gui import panel_text
from gui.panels.base import BasePanel


class TTSPanel(BasePanel):
    title = "Voice (TTS)"

    def __init__(self, master, app):
        super().__init__(master, app)
        self.grid_rowconfigure(1, weight=1)
        self.header("Voice / TTS", "Speak text aloud with your local engine. "
                                   "Configure engine + voice in Settings.")
        box = ctk.CTkFrame(self, fg_color=theme.BG_CARD)
        box.grid(row=1, column=0, sticky="nsew", padx=16, pady=(4, 8))
        box.grid_rowconfigure(0, weight=1)
        box.grid_columnconfigure(0, weight=1)
        self.text = panel_text.new_textbox(box, self.app.settings, wrap="word")
        self.text.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        self.text.insert("1.0", "The city never sleeps; neither do its debts.")

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 16))
        self.speak_btn = ctk.CTkButton(bar, text="Speak", width=120, command=self._speak)
        self.speak_btn.pack(side="left")
        self.status_lbl = ctk.CTkLabel(bar, text="", text_color=theme.TEXT_MUTED)
        self.status_lbl.pack(side="left", padx=12)

    def _speak(self):
        text = self.text.get("1.0", "end").strip()
        if not text:
            return
        self.speak_btn.configure(state="disabled", text="Speaking...")
        self.status_lbl.configure(text="Generating speech...")
        threading.Thread(target=self._worker, args=(text,), daemon=True).start()

    def _worker(self, text):
        try:
            result = self.app.tts.speak(text, play=True)
            msg = ("Played via " + result["engine"]) if result else "TTS is off."
        except Exception as exc:
            msg = f"Error: {exc}"
        self.after(0, lambda: (self.speak_btn.configure(state="normal", text="Speak"),
                               self.status_lbl.configure(text=msg)))
