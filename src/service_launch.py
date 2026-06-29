"""Startup service orchestration.

Radix is a hub: it talks to ComfyUI (images) and AllTalk (voice) over HTTP.
This module checks what's running at launch and can start AllTalk from its
install folder. ComfyUI is intentionally NOT auto-started (the user starts it
themselves). Piper needs nothing - it is a per-call CLI, not a server.

Everything here is best-effort and non-fatal: if a launch fails, callers get a
clear notice and the GUI keeps running (services just show as down).
"""

import os
import subprocess
import sys
import time

import config
from src import services

# Start-script candidates, in priority order, for each launchable service.
_ALLTALK_SCRIPTS = ["start_alltalk.bat", "start_alltalk.cmd", "atsetup.bat",
                    "start_alltalk.py", "script.py"]
_COMFY_SCRIPTS = ["run_nvidia_gpu.bat", "run_cpu.bat", "run.bat", "main.py"]


def _find_script(folder, names):
    if not folder or not os.path.isdir(folder):
        return None
    for name in names:
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            return path
    return None


def _spawn(path, cwd):
    """Launch a .bat/.cmd or .py file detached, in its own console on Windows."""
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    lower = path.lower()
    if lower.endswith((".bat", ".cmd")):
        cmd = ["cmd", "/c", path]
    elif lower.endswith(".py"):
        cmd = [sys.executable, path]
    else:
        cmd = [path]
    subprocess.Popen(cmd, cwd=cwd, creationflags=creationflags,
                     close_fds=True)


def plan_startup(settings):
    """Probe services and describe what startup should do (no side effects).

    Returns a dict keyed by service -> {state, action, detail} where:
      state  in {"running", "down", "n/a"}
      action in {"none", "launch", "manual"}
    """
    health = services.check_all(settings)
    comfy_dir = (settings.get("services.comfyui_dir", config.COMFYUI_DIR) or "").strip()
    alltalk_dir = (settings.get("services.alltalk_dir", config.ALLTALK_DIR) or "").strip()

    plan = {}

    # ComfyUI: never auto-launch; if down, the user must start it.
    if health["comfyui"]["ok"]:
        plan["comfyui"] = {"state": "running", "action": "none",
                           "detail": "ComfyUI reachable"}
    else:
        plan["comfyui"] = {"state": "down", "action": "manual",
                           "detail": "ComfyUI is not running - start it to enable "
                                     "image generation"}

    # AllTalk: auto-launch from its folder when down.
    if health["alltalk"]["ok"]:
        plan["alltalk"] = {"state": "running", "action": "none",
                           "detail": "AllTalk reachable"}
    elif _find_script(alltalk_dir, _ALLTALK_SCRIPTS):
        plan["alltalk"] = {"state": "down", "action": "launch",
                           "detail": "AllTalk is down - will start it"}
    elif alltalk_dir:
        plan["alltalk"] = {"state": "down", "action": "manual",
                           "detail": "AllTalk down - no start script found in its "
                                     "folder; start it manually"}
    else:
        plan["alltalk"] = {"state": "down", "action": "manual",
                           "detail": "AllTalk down - set its install folder in "
                                     "Setup to auto-start it"}

    # Piper: per-call CLI; nothing to launch. Report presence only.
    plan["piper"] = {"state": "running" if health["piper"]["ok"] else "n/a",
                     "action": "none",
                     "detail": health["piper"]["detail"]}
    return plan


def launch_alltalk(settings, wait_s=45):
    """Start AllTalk from services.alltalk_dir and wait until reachable.

    Returns {ok, detail}. Safe to call when already running (returns ok).
    """
    if services.check_alltalk(settings.get("services.alltalk_url",
                                            config.ALLTALK_URL))["ok"]:
        return {"ok": True, "detail": "already running"}
    folder = (settings.get("services.alltalk_dir", config.ALLTALK_DIR) or "").strip()
    script = _find_script(folder, _ALLTALK_SCRIPTS)
    if not script:
        return {"ok": False,
                "detail": "no AllTalk start script found - set its install folder "
                          "in Setup"}
    try:
        _spawn(script, folder)
    except Exception as exc:
        return {"ok": False, "detail": f"failed to launch AllTalk: {exc}"}
    url = settings.get("services.alltalk_url", config.ALLTALK_URL)
    deadline = time.time() + max(5, wait_s)
    while time.time() < deadline:
        time.sleep(2)
        if services.check_alltalk(url)["ok"]:
            return {"ok": True, "detail": "AllTalk started"}
    return {"ok": False, "detail": "AllTalk launched but not reachable yet "
                                   "(it may still be loading)"}


def launch_comfyui(settings, wait_s=60):
    """Best-effort ComfyUI launch (used by the Setup button, not startup).

    Returns {ok, detail}.
    """
    if services.check_comfyui(settings.get("services.comfyui_url",
                                           config.COMFYUI_URL))["ok"]:
        return {"ok": True, "detail": "already running"}
    folder = (settings.get("services.comfyui_dir", config.COMFYUI_DIR) or "").strip()
    script = _find_script(folder, _COMFY_SCRIPTS)
    if not script:
        return {"ok": False,
                "detail": "no ComfyUI start script found - set its install folder "
                          "in Setup"}
    try:
        _spawn(script, folder)
    except Exception as exc:
        return {"ok": False, "detail": f"failed to launch ComfyUI: {exc}"}
    url = settings.get("services.comfyui_url", config.COMFYUI_URL)
    deadline = time.time() + max(5, wait_s)
    while time.time() < deadline:
        time.sleep(3)
        if services.check_comfyui(url)["ok"]:
            return {"ok": True, "detail": "ComfyUI started"}
    return {"ok": False, "detail": "ComfyUI launched but not reachable yet "
                                   "(it may still be loading)"}


def run_startup(settings):
    """Execute the startup plan: launch AllTalk if needed; collect notices.

    Returns (plan, notices) where notices is a list of human-readable strings.
    Intended to run on a background thread.
    """
    plan = plan_startup(settings)
    notices = []
    if plan["alltalk"]["action"] == "launch":
        res = launch_alltalk(settings)
        plan["alltalk"]["state"] = "running" if res["ok"] else "down"
        notices.append(("AllTalk: " + res["detail"]) if not res["ok"]
                       else "AllTalk started.")
    elif plan["alltalk"]["action"] == "manual" and \
            plan["alltalk"]["state"] == "down":
        notices.append(plan["alltalk"]["detail"])
    if plan["comfyui"]["action"] == "manual":
        notices.append(plan["comfyui"]["detail"])
    return plan, notices
