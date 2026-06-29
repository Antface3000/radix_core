"""Service health checks for the Settings Control Center.

Lightweight reachability probes for the local services radix_core talks to:
ComfyUI and AllTalk, plus a Piper file-presence check. Each returns a small
dict {ok, detail} so the GUI can show a status dot + tooltip.
"""

import os

import requests

import config


def _ok(detail=""):
    return {"ok": True, "detail": detail}


def _bad(detail=""):
    return {"ok": False, "detail": detail}


def check_comfyui(url=None, timeout=4):
    base = str(url or config.COMFYUI_URL).rstrip("/")
    try:
        r = requests.get(f"{base}/system_stats", timeout=timeout)
        if r.ok:
            try:
                data = r.json()
                name = (data.get("system", {}) or {}).get("comfyui_version") \
                    or "ComfyUI"
                return _ok(f"{name} reachable")
            except ValueError:
                return _ok("reachable")
        # /system_stats missing on some builds; try root.
        r = requests.get(base, timeout=timeout)
        return _ok("reachable") if r.ok else _bad(f"HTTP {r.status_code}")
    except requests.RequestException as exc:
        return _bad(f"unreachable: {exc}")


def check_alltalk(url=None, timeout=4):
    base = str(url or config.ALLTALK_URL).rstrip("/")
    for path in ("/api/ready", "/api/voices", "/"):
        try:
            r = requests.get(f"{base}{path}", timeout=timeout)
            if r.ok:
                return _ok("ready")
        except requests.RequestException:
            continue
    return _bad(f"unreachable at {base}")


def check_piper(piper_exe=None, piper_voice=None):
    exe = piper_exe or config.PIPER_EXE
    voice = piper_voice or config.PIPER_VOICE
    if not os.path.exists(exe):
        return _bad("piper.exe not found")
    if not os.path.exists(voice):
        return _bad("voice model not found")
    return _ok("installed")


def check_all(settings=None):
    if settings is not None:
        comfy = settings.get("services.comfyui_url", config.COMFYUI_URL)
        alltalk = settings.get("services.alltalk_url", config.ALLTALK_URL)
        piper_exe = settings.get("services.piper_exe", config.PIPER_EXE)
        piper_voice = settings.get("services.piper_voice", config.PIPER_VOICE)
    else:
        comfy, alltalk = config.COMFYUI_URL, config.ALLTALK_URL
        piper_exe, piper_voice = config.PIPER_EXE, config.PIPER_VOICE
    return {
        "comfyui": check_comfyui(comfy),
        "alltalk": check_alltalk(alltalk),
        "piper": check_piper(piper_exe, piper_voice),
    }
