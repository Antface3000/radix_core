"""Music panel - a local-folder audio player + a mocked Deezer widget (WIP).

The local player points at a folder of audio on disk and plays it through
sounddevice/soundfile (wav / flac / ogg; mp3 depends on the local libsndfile).
The Deezer area is a non-functional placeholder marked "work in progress".
"""

import os
import threading
from tkinter import filedialog

import customtkinter as ctk

from gui import theme
from gui.panels.base import BasePanel
from gui.tooltip import attach as _tooltip

try:
    import sounddevice as sd
    import soundfile as sf
    _AUDIO_OK = True
except Exception:
    sd = sf = None
    _AUDIO_OK = False

_EXTS = (".wav", ".flac", ".ogg", ".mp3", ".aiff", ".m4a")


class MusicPanel(BasePanel):
    title = "Music"

    def __init__(self, master, app):
        super().__init__(master, app)
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.playlist = []
        self.index = -1

        self.tabs = ctk.CTkTabview(self, fg_color=theme.BG_CARD)
        self.tabs.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)
        self.tabs.add("Local")
        self.tabs.add("Deezer")
        self._build_local(self.tabs.tab("Local"))
        self._build_deezer(self.tabs.tab("Deezer"))

    # ----------------------- local player ----------------------------------
    def _build_local(self, tab):
        tab.grid_rowconfigure(2, weight=1)
        tab.grid_columnconfigure(0, weight=1)
        top = ctk.CTkFrame(tab, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        ctk.CTkButton(top, text="Open Folder...", command=self._pick_folder,
                      **theme.primary_btn()).pack(side="left")
        self.folder_lbl = ctk.CTkLabel(top, text="No folder selected.",
                                       text_color=theme.TEXT_MUTED)
        self.folder_lbl.pack(side="left", padx=10)

        controls = ctk.CTkFrame(tab, fg_color="transparent")
        controls.grid(row=1, column=0, sticky="ew", padx=8)
        ctk.CTkButton(controls, text="\u23EE Prev", width=70, command=self._prev,
                      **theme.secondary_btn()).pack(side="left", padx=2)
        ctk.CTkButton(controls, text="\u25B6 Play", width=70, command=self._play_current,
                      **theme.primary_btn()).pack(side="left", padx=2)
        ctk.CTkButton(controls, text="\u23F9 Stop", width=70, command=self._stop,
                      **theme.secondary_btn()).pack(side="left", padx=2)
        ctk.CTkButton(controls, text="Next \u23ED", width=70, command=self._next,
                      **theme.secondary_btn()).pack(side="left", padx=2)
        self.now_lbl = ctk.CTkLabel(controls, text="", text_color=theme.LIME)
        self.now_lbl.pack(side="left", padx=10)

        self.track_frame = ctk.CTkScrollableFrame(tab, fg_color=theme.BG_APP)
        self.track_frame.grid(row=2, column=0, sticky="nsew", padx=8, pady=8)
        self.track_frame.grid_columnconfigure(0, weight=1)
        if not _AUDIO_OK:
            ctk.CTkLabel(self.track_frame, text="Audio playback needs the "
                         "'sounddevice' and 'soundfile' packages.",
                         text_color=theme.RED, wraplength=300,
                         justify="left").grid(padx=8, pady=8, sticky="w")

    def _pick_folder(self):
        folder = filedialog.askdirectory(title="Choose a music folder")
        if not folder:
            return
        self.folder_lbl.configure(text=folder)
        self.playlist = [os.path.join(folder, f) for f in sorted(os.listdir(folder))
                         if f.lower().endswith(_EXTS)]
        self._render_tracks()

    def _render_tracks(self):
        for w in self.track_frame.winfo_children():
            w.destroy()
        if not self.playlist:
            ctk.CTkLabel(self.track_frame, text="No audio files found.",
                         text_color=theme.TEXT_MUTED).grid(padx=8, pady=8)
            return
        for i, path in enumerate(self.playlist):
            ctk.CTkButton(self.track_frame, text=os.path.basename(path),
                          anchor="w", command=lambda x=i: self._play(x),
                          **theme.ghost_btn()).grid(row=i, column=0, sticky="ew",
                                                    padx=4, pady=1)

    def _play(self, i):
        if not _AUDIO_OK or not (0 <= i < len(self.playlist)):
            return
        self.index = i
        path = self.playlist[i]
        self.now_lbl.configure(text="\u266A " + os.path.basename(path))

        def worker():
            try:
                sd.stop()
                data, samplerate = sf.read(path, dtype="float32")
                sd.play(data, samplerate)
            except Exception as exc:
                self.after(0, lambda: self.app.status(f"Playback error: {exc}"))
        threading.Thread(target=worker, daemon=True).start()

    def _play_current(self):
        self._play(self.index if self.index >= 0 else 0)

    def _stop(self):
        if _AUDIO_OK:
            sd.stop()
        self.now_lbl.configure(text="")

    def _next(self):
        if self.playlist:
            self._play((self.index + 1) % len(self.playlist))

    def _prev(self):
        if self.playlist:
            self._play((self.index - 1) % len(self.playlist))

    # ----------------------- deezer mock -----------------------------------
    def _build_deezer(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(tab, text="Deezer  \u2014  work in progress",
                     font=ctk.CTkFont(size=16, weight="bold"),
                     text_color=theme.ORANGE).grid(row=0, column=0, sticky="w",
                                                  padx=12, pady=(14, 4))
        entry = ctk.CTkEntry(tab, placeholder_text="Search Deezer (coming soon)",
                             state="disabled")
        entry.grid(row=1, column=0, sticky="ew", padx=12, pady=6)
        _tooltip(entry, "Web streaming isn't wired up yet. The local player on "
                        "the Local tab works today.")
        btn = ctk.CTkButton(tab, text="Connect Deezer", state="disabled",
                            **theme.secondary_btn())
        btn.grid(row=2, column=0, sticky="w", padx=12, pady=6)
        _tooltip(btn, "Placeholder for a future embedded web player.")
        placeholder = ctk.CTkFrame(tab, fg_color=theme.BG_APP, height=180)
        placeholder.grid(row=3, column=0, sticky="ew", padx=12, pady=12)
        ctk.CTkLabel(placeholder, text="[ embedded player placeholder ]",
                     text_color=theme.TEXT_MUTED).pack(expand=True, pady=60)
