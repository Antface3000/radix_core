"""Sync Assets - push assets bundled WITH Radix into the user's existing
service installs (ComfyUI, AllTalk).

The SOURCE is always Radix's own folders (radix_core/assets and
radix_core/workflows) - nothing is fetched from the internet. The bundled
workflow is already wired as Radix's default (Settings -> Image), so it is sent
to ComfyUI over the API and does NOT need to be copied. Custom nodes are best
installed via ComfyUI Manager's "Install Missing Custom Nodes" rather than
copied here. In practice the main remaining use of Sync Assets is pushing
voices into AllTalk; the node/workflow copy paths stay available for advanced
users.

Design goals:
- Non-destructive: copy-only, never deletes anything in the target.
- Path-driven: targets come from settings (services.comfyui_dir / alltalk_dir).
- Previewable: plan_sync() returns the exact actions before run_sync() does them.
- Safe: if a target root is missing/unset, the related group is reported as
  "blocked" with a clear reason instead of guessing a path.

Source layout (bundled in the repo, may be empty):
    assets/comfyui/custom_nodes/<node folders>   -> <ComfyUI>/custom_nodes/   (optional/advanced; prefer ComfyUI Manager)
    workflows/*.json                             -> <ComfyUI>/user/default/workflows/  (optional; Radix sends its default over the API)
    assets/voices/*                              -> <AllTalk>/voices/  (primary use)

Each plan item is a dict:
    {group, kind, name, src, dst, action}
where action is one of: "copy" (new), "overwrite" (exists), "blocked" (no
target / no source). run_sync() additionally fills {ok, detail}.
"""

import os
import shutil

import config


def _comfy_dir(settings):
    return (settings.get("services.comfyui_dir", config.COMFYUI_DIR) or "").strip()


def _alltalk_dir(settings):
    return (settings.get("services.alltalk_dir", config.ALLTALK_DIR) or "").strip()


def _comfy_workflows_target(comfy_root):
    """Prefer the modern ComfyUI user workflows folder, else a top-level one."""
    user_dir = os.path.join(comfy_root, "user", "default", "workflows")
    if os.path.isdir(os.path.join(comfy_root, "user")):
        return user_dir
    return os.path.join(comfy_root, "workflows")


def _list_dir_entries(src, predicate=None):
    if not src or not os.path.isdir(src):
        return []
    names = []
    for name in sorted(os.listdir(src)):
        if name.lower() == "readme.md":
            continue
        if predicate is not None and not predicate(os.path.join(src, name)):
            continue
        names.append(name)
    return names


def _blocked(group, kind, name, src, reason):
    return {"group": group, "kind": kind, "name": name, "src": src,
            "dst": "", "action": "blocked", "reason": reason}


def _group_plan(group, src, target_root, kind, predicate=None):
    """Build plan items for one source dir -> one target dir."""
    items = []
    entries = _list_dir_entries(src, predicate)
    if not entries:
        items.append(_blocked(group, kind, "(nothing bundled)", src,
                              f"No source assets in {src}"))
        return items
    if not target_root:
        for name in entries:
            items.append(_blocked(group, kind, name, os.path.join(src, name),
                                  "Target path not set - configure it in Setup"))
        return items
    if not os.path.isdir(target_root):
        for name in entries:
            items.append(_blocked(group, kind, name, os.path.join(src, name),
                                  f"Target folder does not exist: {target_root}"))
        return items
    for name in entries:
        s = os.path.join(src, name)
        d = os.path.join(target_root, name)
        action = "overwrite" if os.path.exists(d) else "copy"
        items.append({"group": group, "kind": kind, "name": name,
                      "src": s, "dst": d, "action": action})
    return items


def plan_sync(settings):
    """Return the list of planned sync actions (no filesystem changes)."""
    comfy = _comfy_dir(settings)
    alltalk = _alltalk_dir(settings)
    plan = []
    plan += _group_plan(
        "ComfyUI custom nodes", config.COMFY_NODES_SRC,
        os.path.join(comfy, "custom_nodes") if comfy else "", "dir",
        predicate=os.path.isdir)
    plan += _group_plan(
        "ComfyUI workflows", config.COMFY_WORKFLOWS_SRC,
        _comfy_workflows_target(comfy) if comfy else "", "file",
        predicate=lambda p: p.lower().endswith(".json"))
    plan += _group_plan(
        "AllTalk voices", config.VOICES_SRC,
        os.path.join(alltalk, "voices") if alltalk else "", "file",
        predicate=os.path.isfile)
    return plan


def run_sync(settings, items=None, overwrite=True):
    """Execute the plan. Skips 'blocked' items and (optionally) 'overwrite'.

    Returns (results, summary) where summary = {copied, overwritten, skipped,
    blocked, failed}.
    """
    if items is None:
        items = plan_sync(settings)
    results = []
    summary = {"copied": 0, "overwritten": 0, "skipped": 0,
               "blocked": 0, "failed": 0}
    for it in items:
        action = it.get("action")
        if action == "blocked":
            summary["blocked"] += 1
            results.append({**it, "ok": False,
                            "detail": it.get("reason", "blocked")})
            continue
        if action == "overwrite" and not overwrite:
            summary["skipped"] += 1
            results.append({**it, "ok": True, "detail": "skipped (exists)"})
            continue
        try:
            dst_parent = os.path.dirname(it["dst"])
            os.makedirs(dst_parent, exist_ok=True)
            if it.get("kind") == "dir":
                # Merge into the target (overwrites matching files, keeps the
                # rest) - never wipes the existing folder.
                shutil.copytree(it["src"], it["dst"], dirs_exist_ok=True)
            else:
                shutil.copy2(it["src"], it["dst"])
            if action == "overwrite":
                summary["overwritten"] += 1
                detail = "overwritten"
            else:
                summary["copied"] += 1
                detail = "copied"
            results.append({**it, "ok": True, "detail": detail})
        except Exception as exc:
            summary["failed"] += 1
            results.append({**it, "ok": False, "detail": str(exc)})
    return results, summary
