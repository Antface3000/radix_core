"""rgthree Power Lora Loader helpers - ported from unblocker/lora-panel.js.

Read/write the lora_N entries in a Power Lora Loader node inside an API-format
workflow, and list LoRAs installed in ComfyUI via /object_info.
"""

import os
import re

import requests

POWER_LORA_CLASS = "Power Lora Loader (rgthree)"


def is_power_lora_node(node):
    return isinstance(node, dict) and node.get("class_type") == POWER_LORA_CLASS


def _lora_key_num(key):
    digits = re.sub(r"\D", "", str(key))
    return int(digits) if digits else 0


def _parse_lora_entry(value, key):
    if not isinstance(value, dict) or "lora" not in value:
        return None
    return {
        "key": key,
        "on": bool(value.get("on")),
        "lora": str(value.get("lora") or ""),
        "strength": float(value.get("strength") or 0),
        "strengthTwo": (float(value["strengthTwo"])
                        if value.get("strengthTwo") is not None else None),
    }


def find_power_lora_nodes(workflow_json):
    if not isinstance(workflow_json, dict):
        return []
    nodes = []
    for node_id, node in workflow_json.items():
        if not is_power_lora_node(node):
            continue
        inputs = node.get("inputs") or {}
        keys = sorted([k for k in inputs if re.fullmatch(r"lora_\d+", k, re.I)],
                      key=_lora_key_num)
        loras = [e for e in (_parse_lora_entry(inputs[k], k) for k in keys) if e]
        nodes.append({"nodeId": str(node_id), "loras": loras})
    return sorted(nodes, key=lambda n: int(n["nodeId"]) if n["nodeId"].isdigit() else 0)


def update_power_lora_node(workflow_json, node_id, new_loras):
    node = (workflow_json or {}).get(str(node_id))
    if not node or not is_power_lora_node(node):
        raise ValueError(f'Power Lora Loader node "{node_id}" not found in workflow')
    inputs = dict(node.get("inputs") or {})
    for key in list(inputs):
        if re.fullmatch(r"lora_\d+", key, re.I):
            del inputs[key]
    for idx, row in enumerate(new_loras or []):
        entry = {
            "on": bool(row.get("on")),
            "lora": str(row.get("lora") or ""),
            "strength": float(row.get("strength") or 0),
        }
        if row.get("strengthTwo") is not None:
            try:
                entry["strengthTwo"] = float(row["strengthTwo"])
            except (TypeError, ValueError):
                pass
        inputs[f"lora_{idx + 1}"] = entry
    node["inputs"] = inputs
    return workflow_json


def _extract_lora_names(data):
    def try_node(node_info):
        required = (node_info or {}).get("input", {}).get("required") \
            or (node_info or {}).get("input_required") or {}
        ln = required.get("lora_name")
        if isinstance(ln, list) and ln and isinstance(ln[0], list):
            return [x for x in ln[0] if isinstance(x, str)]
        if isinstance(ln, list):
            return [x for x in ln if isinstance(x, str)]
        return []

    if not isinstance(data, dict):
        return []
    if data.get("LoraLoader"):
        names = try_node(data["LoraLoader"])
        if names:
            return names
    for key, val in data.items():
        if re.search(r"lora", key, re.I) and key != POWER_LORA_CLASS:
            names = try_node(val)
            if names:
                return names
    return []


def list_installed_loras(comfy_url, timeout=5):
    base = str(comfy_url or "http://127.0.0.1:8188").rstrip("/")
    data = None
    try:
        r = requests.get(f"{base}/object_info/LoraLoader", timeout=timeout)
        r.raise_for_status()
        data = r.json()
    except requests.RequestException:
        try:
            r = requests.get(f"{base}/object_info", timeout=timeout)
            r.raise_for_status()
            data = r.json()
        except requests.RequestException as exc:
            raise RuntimeError(f"Could not list LoRAs from ComfyUI: {exc}")
    names = list(dict.fromkeys(str(n) for n in _extract_lora_names(data)))
    names.sort(key=lambda a: os.path.basename(a).lower())
    return names
