"""Workflow placeholder mapping detection - ported from unblocker/workflow-map.js.

Given a ComfyUI workflow (graph/frontend format with `nodes`, or API format keyed
by node id) this detects where to inject the positive/negative/refiner prompts,
seed, dimensions, and reference images. Returns a `mapping` dict consumed by
comfyui.apply_*_placeholders.
"""

import json
import re


def _has_text_input_link(node):
    return any(i.get("name") == "text" and i.get("link") is not None
              for i in (node.get("inputs") or []))


def _clip_has_usable_widget(node):
    if not node:
        return False
    w = (node.get("widgets_values") or [None])
    v = w[0] if w else None
    if v is not None and str(v).strip() != "":
        return True
    return not _has_text_input_link(node)


def _title(node):
    return str(node.get("title") or "")


def _api_title(node):
    return str((node.get("_meta") or {}).get("title") or "")


def _num_in_title(title):
    m = re.search(r"(\d+)", str(title or ""))
    return int(m.group(1)) if m else 0


def _trace_api_clip_loader_type(workflow, start_id):
    start = workflow.get(str(start_id))
    clip_in = (start or {}).get("inputs", {}).get("clip")
    if not isinstance(clip_in, list) or not clip_in:
        return None
    node_id = str(clip_in[0])
    passthrough = {"CLIPSetLastLayer", "Power Lora Loader (rgthree)", "Reroute"}
    for _ in range(24):
        node = workflow.get(node_id)
        if not node:
            return None
        ct = node.get("class_type", "")
        if ct in ("CLIPLoader", "DualCLIPLoader"):
            return str(node.get("inputs", {}).get("type", "")).strip() or None
        # SDXL/Pony checkpoints provide their CLIP via the checkpoint loader.
        if ct in ("CheckpointLoaderSimple", "CheckpointLoader",
                  "unCLIPCheckpointLoader"):
            return "sdxl"
        if ct in passthrough:
            clip_in = node.get("inputs", {}).get("clip")
            if not isinstance(clip_in, list) or not clip_in:
                keys = [k for k, v in (node.get("inputs") or {}).items()
                        if isinstance(v, list) and v]
                clip_in = node["inputs"][keys[0]] if keys else None
            if not isinstance(clip_in, list) or not clip_in:
                return None
            node_id = str(clip_in[0])
            continue
        return None
    return None


def _pick_best_sdxl_positive(cands):
    for n in cands:
        if re.search(r"positive conditioning", _api_title(n["node"]) or _title(n["node"]), re.I):
            return n
    return cands[0] if cands else None


def detect_api_workflow_mapping(workflow):
    mapping = {"negativePromptMode": "auto-zero", "workflowFamily": "generic"}
    nodes = [{"id": k, "node": v} for k, v in workflow.items() if k != "_readme"]

    sdxl_positives, flux2_positives = [], []
    for item in nodes:
        node = item["node"]
        if node.get("class_type") != "CLIPTextEncode":
            continue
        title = _api_title(node)
        if re.search(r"negative", title, re.I):
            continue
        if not re.search(r"positive", title, re.I) and not re.search(r"conditioning", title, re.I):
            continue
        clip_type = _trace_api_clip_loader_type(workflow, item["id"])
        entry = {"id": item["id"], "node": node, "title": title}
        if clip_type == "sdxl":
            sdxl_positives.append(entry)
        elif clip_type == "flux2":
            flux2_positives.append(entry)

    ref_loads = sorted(
        [it for it in nodes if it["node"].get("class_type") == "LoadImage"
         and re.search(r"reference image", _api_title(it["node"]), re.I)],
        key=lambda it: _num_in_title(_api_title(it["node"])))

    pony = _pick_best_sdxl_positive(sdxl_positives)
    flux = flux2_positives[0] if flux2_positives else None
    if pony:
        mapping["positivePrompt"] = {"nodeId": pony["id"], "path": "inputs.text"}
        mapping["positivePromptLabel"] = pony["title"] or "Positive Conditioning"
    if flux:
        mapping["refinerPrompt"] = {"nodeId": flux["id"], "path": "inputs.text"}

    neg = next((it for it in nodes if it["node"].get("class_type") == "CLIPTextEncode"
                and re.search(r"negative", _api_title(it["node"]), re.I)), None)
    if neg:
        mapping["negativePrompt"] = {"nodeId": neg["id"], "path": "inputs.text"}
        mapping["negativePromptMode"] = "mapped"

    gs = next((it for it in nodes if it["node"].get("class_type") == "easy globalSeed"), None)
    ks = next((it for it in nodes if it["node"].get("class_type") == "KSampler"), None)
    if gs:
        mapping["seed"] = {"nodeId": gs["id"], "path": "inputs.value"}
    elif ks:
        mapping["seed"] = {"nodeId": ks["id"], "path": "inputs.seed"}

    elp = next((it for it in nodes if it["node"].get("class_type") == "EmptyLatentImagePresets"), None)
    if elp:
        mapping["sizePreset"] = {"nodeId": elp["id"], "path": "inputs.dimensions"}
    clp = next((it for it in nodes if it["node"].get("class_type") == "EmptyLatentImageCustomPresets"), None)
    if clp:
        mapping["customSizePreset"] = {"nodeId": clp["id"], "path": "inputs.dimensions"}
        mapping["customSizeInvert"] = {"nodeId": clp["id"], "path": "inputs.invert"}

    if ref_loads:
        mapping["referenceImages"] = [{"nodeId": it["id"], "path": "inputs.image"}
                                      for it in ref_loads[:3]]

    has_ref_latent = any(it["node"].get("class_type") == "ReferenceLatent" for it in nodes)
    if pony and flux and ref_loads and has_ref_latent:
        mapping["workflowFamily"] = "pony-flux2-ref"
    elif mapping.get("positivePrompt") and mapping.get("refinerPrompt") and ref_loads:
        mapping["workflowFamily"] = "sdxl-flux2-ref"
    return mapping


def detect_workflow_mapping(workflow):
    """Detect mapping for either API (dict) or graph (has 'nodes') workflows."""
    is_graph = isinstance(workflow, dict) and isinstance(workflow.get("nodes"), list)
    if isinstance(workflow, dict) and not is_graph:
        return detect_api_workflow_mapping(workflow)
    if not is_graph:
        return {
            "positivePrompt": {"nodeId": 6, "path": "widgets_values.0"},
            "seed": {"nodeId": 163, "path": "widgets_values.0"},
            "width": {"nodeId": 214, "path": "widgets_values.0"},
            "height": {"nodeId": 215, "path": "widgets_values.0"},
            "negativePromptMode": "auto-zero",
            "workflowFamily": "generic",
        }

    nodes = workflow["nodes"]
    mapping = {"negativePromptMode": "auto-zero", "workflowFamily": "generic"}

    def by_type(t):
        return next((n for n in nodes if n.get("type") == t), None)

    easy_positives = [n for n in nodes if n.get("type") == "easy positive"]
    easy_negative = by_type("easy negative")
    global_seed = by_type("easy globalSeed")
    sampler = by_type("KSampler")
    empty_latent = by_type("EmptyLatentImage") or by_type("EmptySD3LatentImage")
    empty_latent_presets = by_type("EmptyLatentImagePresets")
    custom_latent_presets = by_type("EmptyLatentImageCustomPresets")
    flux_latent = by_type("EmptyFlux2LatentImage")

    ref_loads = sorted(
        [n for n in nodes if n.get("type") == "LoadImage"
         and re.search(r"reference image", _title(n), re.I)],
        key=lambda n: _num_in_title(_title(n)))

    positive_node = None
    refiner_clip = None
    sdxl_positives, flux2_positives = [], []
    if easy_positives:
        positive_node = next((n for n in easy_positives
                              if re.search(r"main|subject", _title(n), re.I)),
                             easy_positives[0])
        mapping["workflowFamily"] = "sdxl-easy-use"
    else:
        clip_positives = [n for n in nodes if n.get("type") == "CLIPTextEncode"
                          and not re.search(r"negative", _title(n), re.I)
                          and (re.search(r"positive", _title(n), re.I)
                               or re.search(r"conditioning", _title(n), re.I))
                          and _clip_has_usable_widget(n)]
        positive_node = clip_positives[0] if clip_positives else None
        refiner_clip = next((n for n in nodes if n.get("type") == "CLIPTextEncode"
                             and not re.search(r"positive|negative", _title(n), re.I)
                             and _clip_has_usable_widget(n)), None)
        if positive_node:
            mapping["workflowFamily"] = "clip-encode"

    if positive_node:
        mapping["positivePrompt"] = {"nodeId": positive_node["id"], "path": "widgets_values.0"}
        mapping["positivePromptLabel"] = str(positive_node.get("title") or positive_node.get("type"))

    clip_negative = next((n for n in nodes if n.get("type") == "CLIPTextEncode"
                          and re.search(r"negative", _title(n), re.I)), None)
    if easy_negative:
        mapping["negativePrompt"] = {"nodeId": easy_negative["id"], "path": "widgets_values.0"}
        mapping["negativePromptMode"] = "mapped"
        if mapping["workflowFamily"] == "generic":
            mapping["workflowFamily"] = "sdxl-easy-use"
    elif clip_negative:
        mapping["negativePrompt"] = {"nodeId": clip_negative["id"], "path": "widgets_values.0"}
        mapping["negativePromptMode"] = "mapped"

    if refiner_clip:
        mapping["refinerPrompt"] = {"nodeId": refiner_clip["id"], "path": "widgets_values.0"}

    has_ref_latent = any(n.get("type") == "ReferenceLatent" for n in nodes)
    if sdxl_positives and flux2_positives and ref_loads and has_ref_latent:
        mapping["workflowFamily"] = "pony-flux2-ref"
    elif mapping.get("refinerPrompt") and ref_loads and sampler and has_ref_latent:
        mapping["workflowFamily"] = "sdxl-flux2-ref"

    if global_seed:
        mapping["seed"] = {"nodeId": global_seed["id"], "path": "widgets_values.0"}
    elif sampler:
        mapping["seed"] = {"nodeId": sampler["id"], "path": "widgets_values.0"}

    if custom_latent_presets:
        mapping["customSizePreset"] = {"nodeId": custom_latent_presets["id"], "path": "widgets_values.0"}
        mapping["customSizeInvert"] = {"nodeId": custom_latent_presets["id"], "path": "widgets_values.1"}
    elif empty_latent_presets:
        mapping["sizePreset"] = {"nodeId": empty_latent_presets["id"], "path": "widgets_values.0"}
    elif empty_latent:
        mapping["width"] = {"nodeId": empty_latent["id"], "path": "widgets_values.0"}
        mapping["height"] = {"nodeId": empty_latent["id"], "path": "widgets_values.1"}
        mapping["batchSize"] = {"nodeId": empty_latent["id"], "path": "widgets_values.2"}

    if flux_latent:
        mapping["batchSize"] = {"nodeId": flux_latent["id"], "path": "widgets_values.2"}
        if not empty_latent and not empty_latent_presets:
            mapping.setdefault("width", {"nodeId": flux_latent["id"], "path": "widgets_values.0"})
            mapping.setdefault("height", {"nodeId": flux_latent["id"], "path": "widgets_values.1"})

    if ref_loads:
        mapping["referenceImages"] = [{"nodeId": n["id"], "path": "widgets_values.0"}
                                      for n in ref_loads[:3]]
    return mapping


def get_custom_latent_preset_info(workflow):
    if not isinstance(workflow, dict):
        return None
    if isinstance(workflow.get("nodes"), list):
        node = next((n for n in workflow["nodes"]
                     if n.get("type") == "EmptyLatentImageCustomPresets"), None)
        if not node:
            return None
        w = node.get("widgets_values") or []
        return {"nodeId": node.get("id"),
                "dimensions": w[0] if w and isinstance(w[0], str) else "",
                "invert": bool(w[1]) if len(w) > 1 else False}
    for node_id, node in workflow.items():
        if isinstance(node, dict) and node.get("class_type") == "EmptyLatentImageCustomPresets":
            inputs = node.get("inputs", {})
            return {"nodeId": node_id,
                    "dimensions": inputs.get("dimensions", "") if isinstance(inputs.get("dimensions"), str) else "",
                    "invert": bool(inputs.get("invert"))}
    return None


def parse_comfyui_error(status, body_text):
    raw = str(body_text or "").strip()
    if not raw:
        return f"ComfyUI /prompt failed ({status}). No error body returned."
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return f"ComfyUI /prompt failed ({status}): {raw[:400]}"
    messages = []
    err = data.get("error")
    if isinstance(err, str):
        messages.append(err)
    elif isinstance(err, dict):
        if err.get("message"):
            messages.append(err["message"])
        if err.get("type"):
            messages.append(f"type: {err['type']}")
    node_errors = data.get("node_errors")
    if isinstance(node_errors, dict):
        for node_id, ne in node_errors.items():
            ct = (ne or {}).get("class_type") or (ne or {}).get("type") or "unknown"
            errors = (ne or {}).get("errors")
            if isinstance(errors, list) and errors:
                detail = "; ".join(e.get("message") or e.get("details")
                                   or json.dumps(e) for e in errors)
                messages.append(f"Node {node_id} ({ct}): {detail}")
            elif (ne or {}).get("message"):
                messages.append(f"Node {node_id} ({ct}): {ne['message']}")
    if messages:
        return f"ComfyUI rejected workflow ({status}): {' | '.join(messages)}"
    return f"ComfyUI /prompt failed ({status}): {raw[:400]}"
