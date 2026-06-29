"""Project management - ported from unblocker's src/projects.js.

A "project" is an isolated workspace (formerly radix_core's "profile") with its
own data: lore, story bible, world state, outlines, chapters, agent overrides,
memory, and generated images. Everything lives under radix_core's own data/
directory so this app is fully self-contained.

Layout:
    data/
        projects.json                  # index {projects:[], activeProjectId}
        global.json                    # system/service settings (settings.py)
        agents.json                    # stable global agent overrides (settings.py)
        projects/<id>/
            config.json                # per-project misc config
            agents.json                # per-project agent overrides (settings.py)
            lore.json                  # {characters:[], world:[]}
            story_bible.json
            world_state.json
            outlines.json              # {chapters:{}}
            memory.json                # per-persona turn history
            chapters/                  # <name>.txt + _order.json + *.draft.json
            portraits/                 # generated character images
            backgrounds/               # generated world/scene images
"""

import json
import os
import re
import uuid
from datetime import datetime, timezone

import config

DATA_DIR = config.DATA_DIR
PROJECTS_DIR = os.path.join(DATA_DIR, "projects")
PROJECTS_INDEX_PATH = os.path.join(DATA_DIR, "projects.json")
GLOBAL_CONFIG_PATH = os.path.join(DATA_DIR, "global.json")

PROJECT_FILE_NAMES = {
    "config": "config.json",
    "agents": "agents.json",
    "lore": "lore.json",
    "bible": "story_bible.json",
    "outlines": "outlines.json",
    "world_state": "world_state.json",
    "memory": "memory.json",
    "chapters": "chapters",
    "portraits": "portraits",
    "backgrounds": "backgrounds",
}

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _now():
    return datetime.now(timezone.utc).isoformat()


def _ensure_dir(path):
    if not os.path.exists(path):
        os.makedirs(path, exist_ok=True)


def read_json_safe(path, fallback):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return fallback


def write_json(path, data):
    _ensure_dir(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def slugify_name(value):
    slug = _SLUG_RE.sub("-", str(value or "project").lower()).strip("-")[:50]
    return slug or "project"


def make_project_id():
    return str(uuid.uuid4())


def project_paths(project_id):
    root = os.path.join(PROJECTS_DIR, project_id)
    return {
        "root": root,
        "config": os.path.join(root, PROJECT_FILE_NAMES["config"]),
        "agents": os.path.join(root, PROJECT_FILE_NAMES["agents"]),
        "lore": os.path.join(root, PROJECT_FILE_NAMES["lore"]),
        "bible": os.path.join(root, PROJECT_FILE_NAMES["bible"]),
        "outlines": os.path.join(root, PROJECT_FILE_NAMES["outlines"]),
        "world_state": os.path.join(root, PROJECT_FILE_NAMES["world_state"]),
        "memory": os.path.join(root, PROJECT_FILE_NAMES["memory"]),
        "chapters": os.path.join(root, PROJECT_FILE_NAMES["chapters"]),
        "portraits": os.path.join(root, PROJECT_FILE_NAMES["portraits"]),
        "backgrounds": os.path.join(root, PROJECT_FILE_NAMES["backgrounds"]),
    }


def ensure_project_layout(project_id):
    p = project_paths(project_id)
    _ensure_dir(p["root"])
    _ensure_dir(p["chapters"])
    _ensure_dir(p["portraits"])
    _ensure_dir(p["backgrounds"])
    if not os.path.exists(p["config"]):
        write_json(p["config"], {})
    if not os.path.exists(p["agents"]):
        write_json(p["agents"], {})
    if not os.path.exists(p["lore"]):
        write_json(p["lore"], {"characters": [], "world": []})
    if not os.path.exists(p["bible"]):
        write_json(p["bible"], {})
    if not os.path.exists(p["outlines"]):
        write_json(p["outlines"], {"chapters": {}})
    if not os.path.exists(p["world_state"]):
        write_json(p["world_state"], {})
    if not os.path.exists(p["memory"]):
        write_json(p["memory"], {})
    return p


def read_projects_index():
    data = read_json_safe(
        PROJECTS_INDEX_PATH,
        {"projects": [], "activeProjectId": None},
    )
    if not isinstance(data.get("projects"), list):
        data["projects"] = []
    return data


def write_projects_index(index):
    write_json(PROJECTS_INDEX_PATH, {
        "projects": index.get("projects", []),
        "activeProjectId": index.get("activeProjectId"),
    })


def ensure_initialized():
    _ensure_dir(DATA_DIR)
    _ensure_dir(PROJECTS_DIR)
    if not os.path.exists(GLOBAL_CONFIG_PATH):
        write_json(GLOBAL_CONFIG_PATH, {})

    index = read_projects_index()
    if not index["projects"]:
        now = _now()
        default = {
            "id": "default",
            "name": "Default",
            "slug": "default",
            "createdAt": now,
            "lastOpenedAt": now,
        }
        index["projects"] = [default]
        index["activeProjectId"] = default["id"]
        ensure_project_layout(default["id"])
        write_projects_index(index)
    else:
        for project in index["projects"]:
            ensure_project_layout(project["id"])
        if (not index.get("activeProjectId")
                or not any(p["id"] == index["activeProjectId"]
                           for p in index["projects"])):
            index["activeProjectId"] = index["projects"][0]["id"]
            write_projects_index(index)
    return index


def list_projects():
    return ensure_initialized()["projects"]


def create_project(name):
    ensure_initialized()
    trimmed = str(name or "").strip()
    if not trimmed:
        raise ValueError("Project name is required")
    index = read_projects_index()
    now = _now()
    project = {
        "id": make_project_id(),
        "name": trimmed,
        "slug": slugify_name(trimmed),
        "createdAt": now,
        "lastOpenedAt": now,
    }
    index["projects"].append(project)
    write_projects_index(index)
    ensure_project_layout(project["id"])
    return project


def rename_project(project_id, name):
    ensure_initialized()
    trimmed = str(name or "").strip()
    if not project_id or not trimmed:
        raise ValueError("project id and name are required")
    index = read_projects_index()
    project = next((p for p in index["projects"] if p["id"] == project_id), None)
    if not project:
        raise ValueError("Project not found")
    project["name"] = trimmed
    project["slug"] = slugify_name(trimmed)
    write_projects_index(index)
    return project


def delete_project(project_id):
    import shutil
    ensure_initialized()
    if not project_id:
        raise ValueError("project id is required")
    index = read_projects_index()
    if index.get("activeProjectId") == project_id:
        raise ValueError("Cannot delete the active project")
    before = len(index["projects"])
    index["projects"] = [p for p in index["projects"] if p["id"] != project_id]
    if len(index["projects"]) == before:
        raise ValueError("Project not found")
    root = project_paths(project_id)["root"]
    if os.path.exists(root):
        shutil.rmtree(root, ignore_errors=True)
    write_projects_index(index)
    return True


def get_active_project_id():
    return ensure_initialized()["activeProjectId"]


def set_active_project_id(project_id):
    ensure_initialized()
    index = read_projects_index()
    project = next((p for p in index["projects"] if p["id"] == project_id), None)
    if not project:
        raise ValueError("Project not found")
    index["activeProjectId"] = project_id
    project["lastOpenedAt"] = _now()
    write_projects_index(index)
    ensure_project_layout(project_id)
    return project


def get_active_project():
    index = ensure_initialized()
    active = index.get("activeProjectId")
    return (next((p for p in index["projects"] if p["id"] == active), None)
            or (index["projects"][0] if index["projects"] else None))


def get_project(project_id):
    index = ensure_initialized()
    return next((p for p in index["projects"] if p["id"] == project_id), None)
