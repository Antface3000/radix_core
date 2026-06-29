"""Central configuration / code defaults for Radix Core.

These are the *baseline* values. At runtime they are layered under:
    code defaults (this file)
      < stable global settings (data/global.json, data/agents.json)
      < per-project overrides (data/projects/<id>/agents.json)
via src/settings.py - so the Settings Control Center is the single source of
truth while these remain a safe fallback.

Sized for an 8GB RTX 4070: each model is an ~5GB Q4_K_M GGUF and only ONE is
resident at a time (single-slot loading), so peak VRAM stays under 8GB.
"""

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(BASE_DIR, "models")
DATA_DIR = os.path.join(BASE_DIR, "data")
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
WORKFLOWS_DIR = os.path.join(BASE_DIR, "workflows")
THEME_PATH = os.path.join(ASSETS_DIR, "theme", "radix_theme.json")
USER_GUIDE_PATH = os.path.join(BASE_DIR, "USER_GUIDE.txt")
INSTALL_PATH = os.path.join(BASE_DIR, "INSTALL.txt")

# --- Model registry ---------------------------------------------------------
# Drop the .gguf files in models/ (or run scripts/download_models.py).
# If a path is missing the engine falls back to a labeled MOCK response so the
# GUI still runs for layout / prompt testing.
MODEL_REGISTRY = {
    # Tier 1 - Architects: heavy reasoning / canon integrity
    "architect": {
        "path": os.path.join(MODELS_DIR, "deepseek-ai_DeepSeek-R1-0528-Qwen3-8B-Q4_K_M.gguf"),
        "n_ctx": 8192,
        "n_gpu_layers": -1,
        "extra": {},
    },
    # Tier 2 - Operators: the glue (manager, liaison, historian, quest logic)
    "operator": {
        "path": os.path.join(MODELS_DIR, "Qwen3-8B-Q4_K_M.gguf"),
        "n_ctx": 8192,
        "n_gpu_layers": -1,
        "extra": {},
    },
    # Tier 3 - Flavor: gritty, uncensored style work
    "flavor": {
        "path": os.path.join(MODELS_DIR, "L3-8B-Stheno-v3.2-Q4_K_M.gguf"),
        "n_ctx": 8192,
        "n_gpu_layers": -1,
        "extra": {},
    },
}

# --- Generation defaults ----------------------------------------------------
DEFAULT_TEMPERATURE = 0.7
DEFAULT_MAX_TOKENS = 2400
STREAMING = True

# Writing style presets for the Write pipeline (not TTS voice).
STYLE_PRESET_OPTIONS = (
    ("my", "My Style"),
    ("alt", "Alt Style"),
    ("neutral", "Neutral Style"),
)
STYLE_PRESET_LABEL = {key: label for key, label in STYLE_PRESET_OPTIONS}
STYLE_PRESET_KEY = {label: key for key, label in STYLE_PRESET_OPTIONS}
STYLE_PRESET_LABELS = tuple(STYLE_PRESET_LABEL[key] for key, _ in STYLE_PRESET_OPTIONS)


def style_preset_display(key):
    """Map stored preset key (my/alt/neutral) to a UI label."""
    return STYLE_PRESET_LABEL.get(key, STYLE_PRESET_LABEL["my"])


def style_preset_from_display(label):
    """Map a UI label back to the stored preset key."""
    return STYLE_PRESET_KEY.get(label, "my")

# --- Auto-orchestration -----------------------------------------------------
ORCHESTRATION_MAX_STEPS = 5
ORCHESTRATION_SYNTHESIS = True
ORCHESTRATION_MANAGER_KEY = "manager"
ORCHESTRATION_LIAISON_KEY = "user_liaison"
# Human-in-the-loop: Liaison asks clarifying questions before planning and
# summarizes for the user before synthesis.
ORCHESTRATION_HITL = False

# How many prior turns of a persona's memory to inject as context.
MEMORY_RECENT_TURNS = 4

# --- Setting / context injection --------------------------------------------
# The "setting" block (story bible + pinned lore + world state) is injected into
# every persona prompt by src/worldcontext.py. [[REMEMBER]] blocks in replies
# are auto-filed back into the project's lore.json.
CONTEXT_INJECT = True
CONTEXT_AUTO_CAPTURE = True
CONTEXT_INJECT_MAX_CHARS = 6000

# --- Services (local, self-hosted) ------------------------------------------
COMFYUI_URL = "http://127.0.0.1:8188"
ALLTALK_URL = "http://127.0.0.1:7851"
TTS_ENGINE = "alltalk"          # "alltalk" | "piper" | "off"
TTS_VOICE = "female_01.wav"     # AllTalk voice id
PIPER_EXE = os.path.join(ASSETS_DIR, "piper", "piper.exe")
PIPER_VOICE = os.path.join(ASSETS_DIR, "piper", "en_US-amy-medium.onnx")
# Optional styles.csv. Defaults to the starter bundled in assets/ when present
# (a no-op for workflows without a "Load Styles CSV" node, kept for those that
# do). Override the path in Settings -> Image.
_BUNDLED_STYLES = os.path.join(ASSETS_DIR, "styles.csv")
STYLES_CSV = _BUNDLED_STYLES if os.path.isfile(_BUNDLED_STYLES) else ""

# Filesystem roots of the user's existing service installs (for Sync Assets).
# Left blank by default; set them in the Service Setup panel.
COMFYUI_DIR = ""                # e.g. C:\\ComfyUI  (the folder with main.py)
ALLTALK_DIR = ""                # e.g. C:\\alltalk_tts

# How often (seconds) the background heartbeat re-checks service health.
HEARTBEAT_INTERVAL_S = 30

# Bundled asset sources that Sync Assets injects into the service installs.
COMFY_NODES_SRC = os.path.join(ASSETS_DIR, "comfyui", "custom_nodes")
COMFY_WORKFLOWS_SRC = WORKFLOWS_DIR
VOICES_SRC = os.path.join(ASSETS_DIR, "voices")

# --- Image generation defaults ----------------------------------------------
IMAGE_WORKFLOW = "default_workflow.json"
IMAGE_WIDTH = 1024
IMAGE_HEIGHT = 1024
IMAGE_STYLE_PREFIX = ""
IMAGE_SEED_BEHAVIOR = "randomize"   # "randomize" | "fixed"

# --- Editor defaults --------------------------------------------------------
EDITOR_FONT_FAMILY = "Georgia"
EDITOR_FONT_SIZE = 18
EDITOR_LINE_HEIGHT = 1.6
EDITOR_WORD_GOAL = 1000

# --- UI ---------------------------------------------------------------------
APP_TITLE = "Radix Core"
APP_VERSION = "0.1.0"
APP_GEOMETRY = "1280x820"
APPEARANCE_MODE = "dark"        # "dark" | "light" | "system"
COLOR_THEME = "radix"           # custom theme (THEME_PATH) or a CTk built-in
