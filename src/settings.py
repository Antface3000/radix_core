"""Central settings manager - the single runtime source of truth.

Two layers of persisted state on top of the code defaults in config.py /
personas.py:

System / service settings  -> data/global.json
Agent (persona) overrides  -> data/agents.json   (stable global default)
                              data/projects/<id>/agents.json  (project override)

Resolution order for an agent field:
    code default (personas.PERSONAS / config)
      < global agents.json
      < project agents.json
so an untouched project always inherits the stable global default.

engine.py / comfyui.py / tts.py all read their config through here, so the
Settings Control Center panel can change behavior live without code edits.
"""

import copy
import json
import os

import config
from src import personas, projects

# Persona fields the dashboard is allowed to override per agent.
AGENT_OVERRIDE_FIELDS = ("model_key", "temperature", "max_tokens",
                         "system_prompt", "enabled")

DEFAULT_GLOBAL = {
    "appearance_mode": config.APPEARANCE_MODE,
    "color_theme": config.COLOR_THEME,
    "default_project": None,
    "ui": {
        "show_welcome": True,
        "show_startup": True,
        "setup_done": False,
        "dock_width": 460,
        "panel_font_size": config.PANEL_FONT_SIZE,
        "panel_auto_scroll": config.PANEL_AUTO_SCROLL,
    },
    "generation": {
        "temperature": config.DEFAULT_TEMPERATURE,
        "max_tokens": config.DEFAULT_MAX_TOKENS,
        "streaming": config.STREAMING,
    },
    "context": {
        "inject": config.CONTEXT_INJECT,
        "auto_capture": config.CONTEXT_AUTO_CAPTURE,
        "inject_max_chars": config.CONTEXT_INJECT_MAX_CHARS,
        "memory_recent_turns": config.MEMORY_RECENT_TURNS,
    },
    "orchestration": {
        "max_steps": config.ORCHESTRATION_MAX_STEPS,
        "synthesis": config.ORCHESTRATION_SYNTHESIS,
        "manager_key": config.ORCHESTRATION_MANAGER_KEY,
        "liaison_key": config.ORCHESTRATION_LIAISON_KEY,
        "hitl": config.ORCHESTRATION_HITL,
    },
    "services": {
        "comfyui_url": config.COMFYUI_URL,
        "alltalk_url": config.ALLTALK_URL,
        "tts_engine": config.TTS_ENGINE,
        "tts_voice": config.TTS_VOICE,
        "piper_exe": config.PIPER_EXE,
        "piper_voice": config.PIPER_VOICE,
        "styles_csv": config.STYLES_CSV,
        "comfyui_dir": config.COMFYUI_DIR,
        "alltalk_dir": config.ALLTALK_DIR,
        "heartbeat_interval_s": config.HEARTBEAT_INTERVAL_S,
    },
    "image": {
        "workflow": config.IMAGE_WORKFLOW,
        "width": config.IMAGE_WIDTH,
        "height": config.IMAGE_HEIGHT,
        "style_prefix": config.IMAGE_STYLE_PREFIX,
        "seed_behavior": config.IMAGE_SEED_BEHAVIOR,
    },
    "editor": {
        "font_family": config.EDITOR_FONT_FAMILY,
        "font_size": config.EDITOR_FONT_SIZE,
        "line_height": config.EDITOR_LINE_HEIGHT,
        "word_goal": config.EDITOR_WORD_GOAL,
        "focus_mode": False,
        "typewriter": False,
        "lore_autoscan": True,
        "lore_scan_interval_ms": 3000,
        "voice_preset": "my",          # my | alt | neutral (UI: My Style / Alt Style / Neutral Style)
        "style_guide_my": "",
        "style_guide_alt": "",
        # Write pipeline (Ghostwriter draft -> critics review).
        "write_persona": "ghostwriter",
        "write_critics": ["lore_curator", "prose_critic"],
        "write_full_team": False,
        "write_max_tokens": 2400,
        "write_temperature": 0.65,
        # Brainstorm.
        "brainstorm_persona": "quest_architect",
        "brainstorm_mode": "single",   # single | team
        "brainstorm_max_tokens": 2200,
        # Project chat.
        "chat_persona": "user_liaison",
        "chat_max_tokens": 1200,
    },
    "models": {},  # per-tier overrides over MODEL_REGISTRY
    "updates": {
        "check_on_startup": True,
        "last_check_ts": 0,
        "dismissed_version": None,
    },
}


def _deep_merge(base, override):
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _read_json(path, fallback):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return fallback


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


class Settings:
    def __init__(self):
        projects.ensure_initialized()
        self.reload()

    # ----------------------- global system settings ------------------------
    def reload(self):
        raw = _read_json(projects.GLOBAL_CONFIG_PATH, {})
        self.global_data = _deep_merge(DEFAULT_GLOBAL, raw)

    def save_global(self):
        _write_json(projects.GLOBAL_CONFIG_PATH, self.global_data)

    def get(self, dotted, default=None):
        node = self.global_data
        for part in dotted.split("."):
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                return default
        return node

    def set(self, dotted, value, save=True):
        parts = dotted.split(".")
        node = self.global_data
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
        if save:
            self.save_global()

    # ----------------------- model registry --------------------------------
    def model_registry(self):
        merged = copy.deepcopy(config.MODEL_REGISTRY)
        for key, override in (self.global_data.get("models") or {}).items():
            if key in merged:
                merged[key] = {**merged[key], **override}
            else:
                merged[key] = override
        return merged

    def model_spec(self, model_key):
        return self.model_registry().get(model_key)

    # ----------------------- agent overrides -------------------------------
    @staticmethod
    def _global_agents_path():
        return os.path.join(config.DATA_DIR, "agents.json")

    @staticmethod
    def _project_agents_path(project_id):
        return projects.project_paths(project_id)["agents"]

    def _read_overrides(self, scope, project_id=None):
        if scope == "global":
            return _read_json(self._global_agents_path(), {})
        return _read_json(self._project_agents_path(project_id), {})

    def _write_overrides(self, scope, data, project_id=None):
        if scope == "global":
            _write_json(self._global_agents_path(), data)
        else:
            _write_json(self._project_agents_path(project_id), data)

    def personas(self, project_id=None):
        """Resolved persona list for a project (code < global < project)."""
        g = self._read_overrides("global")
        p = self._read_overrides("project", project_id) if project_id else {}
        out = []
        for base in personas.PERSONAS:
            merged = copy.deepcopy(base)
            merged.setdefault("enabled", True)
            for ov in (g.get(base["key"], {}), p.get(base["key"], {})):
                for field in AGENT_OVERRIDE_FIELDS:
                    if field in ov and ov[field] is not None:
                        merged[field] = ov[field]
            out.append(merged)
        return out

    def enabled_personas(self, project_id=None):
        return [p for p in self.personas(project_id) if p.get("enabled", True)]

    def persona(self, project_id, identifier):
        for p in self.personas(project_id):
            if identifier in (p["key"], p["display_name"]):
                return p
        return None

    def set_agent_field(self, scope, key, field, value, project_id=None):
        if field not in AGENT_OVERRIDE_FIELDS:
            raise ValueError("Not an overridable agent field: " + str(field))
        data = self._read_overrides(scope, project_id)
        data.setdefault(key, {})[field] = value
        self._write_overrides(scope, data, project_id)

    def clear_agent_field(self, scope, key, field, project_id=None):
        data = self._read_overrides(scope, project_id)
        if key in data and field in data[key]:
            del data[key][field]
            if not data[key]:
                del data[key]
            self._write_overrides(scope, data, project_id)

    def reset_agent(self, project_id, key):
        """Drop a project's override for one agent (revert to global default)."""
        data = self._read_overrides("project", project_id)
        if key in data:
            del data[key]
            self._write_overrides("project", data, project_id)

    def field_source(self, project_id, key, field):
        """Where a field's effective value comes from: project | global | default."""
        if project_id:
            p = self._read_overrides("project", project_id)
            if field in p.get(key, {}):
                return "project"
        g = self._read_overrides("global")
        if field in g.get(key, {}):
            return "global"
        return "default"
