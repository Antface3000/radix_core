RADIX CORE
==========

A self-contained, local-only novelist studio. The default install is a
manuscript workspace with Story Bible, Lorebook, World State, binder, compile,
and spellcheck — no AI until you enable a pack in Add Ons.

Three optional packs (all off by default):
  Local LLM  — Write, Chat, Team, Brainstorm, Ask Agent, retrieval, continuity
  Image      — Image Gen, Visualize, ComfyUI launch + sync assets
  Audio      — Voice / Listen (Piper / AllTalk speech, not music)

PySide6 (Qt) desktop app. No cloud APIs. Models download only after you enable
the Local LLM pack.

The left toolbar opens feature lightboxes. The manuscript binder is the primary
chapter nav. Status bar: project, pending canon, world state, pack heartbeat
(dots only for enabled packs), session/daily words, MOCK MODE only if LLM is on
and no GGUF is available.

The Tension Reader specialist critiques chemistry and tension; its internal
persona key remains horny_critic for compatibility.


DOCUMENTATION
=============

  USER_GUIDE.txt - full manual for every panel and feature (also in-app: Help
                   panel / the ? button in the top bar).
  INSTALL.txt    - step-by-step Windows installation tutorial (Python, venv,
                   GPU wheel, models, optional ComfyUI + TTS).
  CHANGELOG.txt  - release history (see VERSION for current release).
  RELEASE.txt    - maintainer release workflow (scripts/release.py).

Most non-obvious controls also show a hover tooltip. On first launch a Projects
window opens so you can continue or pick a project; ? in the top bar opens the
in-app User Guide.


STRUCTURE
=========

radix_core/
    Start Radix Core.bat  # double-click launcher (venv + app)
    install.bat           # Python venv + studio deps (LLM wheel optional)
    get_models.bat        # optional console GGUF download (or use Add Ons)
    VERSION               # current semver (read by config.py)
    version.json          # update manifest for GitHub checks
    run.py                # launcher: python run.py
    config.py             # code defaults: model registry, services, image, UI
    requirements.txt      # studio packages (llama-cpp via bootstrap_deps)
    scripts/
        bootstrap_deps.py   # pip install studio + CPU/CUDA llama wheel
        install_llama.py    # llama wheel only (Add Ons)
        download_models.py  # GGUF fetch (Add Ons or CLI)
        setup_piper.py      # Piper binary + voice (Add Ons)
        start_services.py   # AllTalk/Comfy/Piper only if those packs are on
    src/
        engine.py writing_engine.py personas.py settings.py projects.py
        plugins/ pack_install.py snapshots.py retrieval.py series.py
        export.py import_docs.py project_search.py
        orchestration/      # team jobs, HITL, tools
    ui_qt/                  # PySide6 GUI
        main_window.py app.py
        widgets/editor.py spellcheck.py binder.py
        panels/addons_panel.py storybible_panel.py ...
    assets/theme/radix.qss  # Qt dark theme
    assets/piper/           # piper.exe + voice (run scripts/setup_piper.py)
    assets/styles.csv
    workflows/              # bundled default_workflow.json
    models/                 # GGUF weights (gitignored)
    data/                   # runtime: projects/, global.json, agents.json


THE ROSTER (3 TIERS / 3 MODELS)
===============================

Only one model is loaded at a time (single-slot), so each about 5GB Q4_K_M GGUF
fits on an 8GB GPU; switching tiers swaps the resident model.

  Tier 1 - Architects | DeepSeek-R1-0528-Qwen3-8B (architect)
    Canon Checker, Species Designer, Character Profiler, Setting Designer,
    Prose Writer, Line Editor, Dialogue Writer

  Tier 2 - Operators | Qwen3-8B (operator)
    Session Summarizer, Plot Designer
    (System Planner / System Liaison are hidden orchestration personas)

  Tier 3 - Flavor | L3-8B-Stheno-v3.2 (flavor)
    Cliché Hunter, Spark Editor, Tension Reader, Dialect Writer

The Ghostwriter (DeepSeek) drafts prose for Write; Lore Curator + Prose Critic
then review/refine it (the default critics).

NOTE: VRAM: all three 8B Q4 models are about 4.6GB each, so no two fit in 8GB
at once. To co-resident two tiers, drop the flavor tier to a 3-4B model in
Settings -> Models.


QUICK START
===========

Windows:
1. Install Python 3.10+ from python.org (tick Add to PATH).
2. Double-click install.bat or Start Radix Core.bat.
3. Write. Optional AI/image/speech: Add Ons → enable pack → Install.

Until you enable Local LLM and download a model, there is no Write dock —
that is intentional.

See INSTALL.txt for the "Windows protected your PC" popup and GPU notes.

Manual / terminal (venv is still auto-created on first run.py launch):


python run.py


Or download models first:


.venv\Scripts\python.exe scripts/download_models.py


Requires Python 3.10+ (tested on 3.11 and 3.13). The writing studio runs with
no models. Enable Local LLM in Add Ons and install the engine + a GGUF for Write.


SETUP DETAILS
=============

Python dependencies

On first launch, run.py creates .venv and runs scripts/bootstrap_deps.py
(studio packages, then a llama-cpp-python CPU or CUDA wheel if possible).
Refresh manually:

  .venv\Scripts\python.exe scripts\bootstrap_deps.py


Add Ons → Install inference engine retries the llama wheel only.


Models

Drop GGUF files into models/ or use Add Ons → Download writing models
(or get_models.bat). Paths are editable in Settings → Models.

Image generation (ComfyUI) - optional

Add Ons → Image pack: Browse to ComfyUI, Launch, Sync assets.

Voice (TTS) - optional

Add Ons → Audio pack: Install Piper. AllTalk folder is optional.


USING IT (EDITOR-FIRST)
=======================

See USER_GUIDE.txt. Highlights: binder, Story Bible lightbox, Add Ons packs,
Export compile, no AI chrome until a pack is on.


SETTINGS CONTROL CENTER
=======================

One panel (Settings on the left toolbar) controls the whole unit; changes persist to
data/global.json / data/agents.json. See USER_GUIDE.txt section 10 for details.
