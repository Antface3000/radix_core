RADIX CORE
==========

A self-contained, local-only creative writing suite: an editor-first
CustomTkinter workspace driving local LLM agents through llama-cpp-python,
plus image generation (ComfyUI), voice (AllTalk/Piper), and a per-project data
model for lore, story bible, and world state. No cloud APIs. This is the merged
successor to the unblocker project - everything runs on your machine.

A persistent manuscript editor sits at the center. A top marquee shows the
project, Setup + Settings (left), the current World: date / location / scene,
live service heartbeat dots, and a ... More drawer on narrow windows (right).
A left tab rail opens feature panels in a resizable side dock, and any panel can
pop out into its own window for multi-monitor use. From the editor you highlight
text and Write, Brainstorm, Chat, Visualize, Listen, or Ask Agent - powered
either by a single agent or the whole orchestrated team.

As a hub, it drives your separately-running ComfyUI and AllTalk processes via
their APIs (status heartbeat + JSON payloads); the Setup panel verifies them
and syncs assets (custom nodes / workflows / voices) into your installs.

The agents are genre-agnostic: the world/setting comes from each project's Story
Bible + Lore + World State (injected at runtime), not from hardcoded prompts.


DOCUMENTATION
=============

  USER_GUIDE.txt - full manual for every panel and feature (also in-app: Help
                   panel / the ? button in the top bar).
  INSTALL.txt    - step-by-step Windows installation tutorial (Python, venv,
                   GPU wheel, models, optional ComfyUI + TTS).
  CHANGELOG.txt  - release history (currently v0.1.0).

Most non-obvious controls also show a hover tooltip. On first launch a Projects
window opens so you can continue or pick a project; ? in the top bar opens the
in-app User Guide.


STRUCTURE
=========

radix_core/
    Start Radix Core.bat  # double-click launcher (venv + services + app)
    install.bat
    get_models.bat
    run.py                # launcher: python run.py
    config.py             # code defaults: model registry, services, image, UI
    requirements.txt
    scripts/
        start_services.py # pre-launch AllTalk / ComfyUI probe / Piper (used by .bat)
        setup_piper.py    # download Piper binary + voice into assets/piper/
        download_models.py
    src/
        engine.py           # AgentEngine: single-slot loading, orchestration, HITL
        writing_engine.py   # WritingEngine: editor prose pipelines
        asset_sync.py       # Sync Assets into ComfyUI/AllTalk installs
        personas.py         # role manifest incl. Ghostwriter + Prose Critic
        story_context.py    # editor prompt assembly + lore scoring/auto-scan
        settings.py         # central settings (global.json + agent overrides)
        projects.py         # project index + per-project layout
        lore.py story_bible.py world_state.py outline.py chapters.py
        worldcontext.py     # runtime SETTING block
        memory.py           # per-persona short-term turn history
        comfyui.py          # ComfyUI client
        workflow_map.py sdxl_tagifier.py styles_csv.py lora_panel.py
        tts.py services.py  # TTS (AllTalk/Piper) + health checks
        service_launch.py   # in-app AllTalk auto-launch
    gui/
        main.py             # editor-first shell: marquee + rail + pop-out dock
        theme.py
        panels/
            editor_panel.py storybible_panel.py agents_panel.py ...
            setup_panel.py help_panel.py settings_panel.py
    assets/theme/radix_theme.json
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
    Lore Curator, Creature Developer, Character Developer, World Builder,
    Ghostwriter, Prose Critic

  Tier 2 - Operators | Qwen3-8B (operator)
    Manager, User Liaison, Chat Historian, Quest Architect

  Tier 3 - Flavor | L3-8B-Stheno-v3.2 (flavor)
    Pessimistic Critic, Optimistic Critic, Horny Critic, Slang-Smith

The Ghostwriter (DeepSeek) drafts prose for Write; Lore Curator + Prose Critic
then review/refine it (the default critics).

NOTE: VRAM: all three 8B Q4 models are about 4.6GB each, so no two fit in 8GB
at once. To co-resident two tiers, drop the flavor tier to a 3-4B model in
Settings -> Models.


QUICK START
===========

Windows (one click, no coding):
1. Install Python from https://www.python.org/downloads/ - tick "Add python.exe
   to PATH".
2. Double-click install.bat (sets everything up).
3. Double-click Start Radix Core.bat to start the app (a services console runs
   first, then the app window).
4. Optional: double-click get_models.bat to download the AI models (about 15 GB);
   until then the app runs in demo ([MOCK]) mode.

See INSTALL.txt for the friendly step-by-step (with the common "Windows protected
your PC" popup fix).

Manual / terminal (venv is still auto-created on first run.py launch):


python run.py


Or download models first:


.venv\Scripts\python.exe scripts/download_models.py


Requires Python 3.10+ (tested on 3.11 and 3.13). The app runs even with no
models, no ComfyUI, and no TTS - agents return labeled [MOCK ...] replies so
you can explore the UI first.


SETUP DETAILS
=============

Python dependencies

On first launch, run.py creates .venv and installs requirements.txt
automatically. To refresh manually:


.venv\Scripts\python.exe -m pip install -r requirements.txt


On Windows, llama-cpp-python may compile from source. For CUDA acceleration,
install a prebuilt wheel (match cuXXX to your CUDA toolkit - see INSTALL.txt):


pip install llama-cpp-python --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu124


Models

Drop the three .gguf files into models/ using the names in config.py, or run
get_models.bat / scripts/download_models.py. Paths, n_ctx, and n_gpu_layers are
editable in Settings -> Models.

Image generation (ComfyUI) - optional

See INSTALL.txt section 9. ComfyUI is not auto-started; use Setup -> Launch
ComfyUI or start it yourself.

Voice (TTS) - optional

AllTalk: set URL + folder in Setup; auto-launches at startup when configured.
Piper: run .venv\Scripts\python.exe scripts/setup_piper.py or see INSTALL.txt.


USING IT (EDITOR-FIRST)
=======================

See USER_GUIDE.txt for the full interface tour. Highlights:

- Marquee: project, Setup, Settings, World: readout, service dots, ? Help.
- Rail: Story Bible, Agents, Projects, Image Gen, Voice, Focus, Music (not
  Setup/Settings/Help - those are in the marquee).
- Editor: chapters, format toolbar, manuscript, AI bar below text, draft bar.
- Write uses My Style / Alt Style / Neutral Style presets (Settings -> Editor).


SETTINGS CONTROL CENTER
=======================

One panel (Settings in the top bar) controls the whole unit; changes persist to
data/global.json / data/agents.json. See USER_GUIDE.txt section 10 for details.
