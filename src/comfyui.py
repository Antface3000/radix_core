"""ComfyUI integration - ported from unblocker/comfyui.js.

Self-contained, local-only image generation. Builds SDXL/Pony bracket prompts
(LLM tagger via the radix_core engine, heuristic fallback), injects them into a
workflow (API or frontend/graph format), submits to ComfyUI, and streams
progress over the WebSocket with /history recovery. Decodes the result image to
base64 for the GUI (Pillow/CTkImage).

Public entry point: ComfyClient(settings, engine).render(...).
"""

import base64
import copy
import json
import os
import random
import re
import time
import uuid

import requests

import config
from src import workflow_map, lora_panel
from src.sdxl_tagifier import tagify_scene

try:
    import websocket  # websocket-client
    WEBSOCKET_AVAILABLE = True
except Exception:  # pragma: no cover
    websocket = None
    WEBSOCKET_AVAILABLE = False

# --- Size presets (KJNodes custom-latent) -----------------------------------
PRESET_TABLE = [
    {"label": "512 x 512 (1:1)", "w": 512, "h": 512},
    {"label": "768 x 512 (1.5:1)", "w": 768, "h": 512},
    {"label": "1024 x 576 (1.778:1)", "w": 1024, "h": 576},
    {"label": "1216 x 832 (1.46:1)", "w": 1216, "h": 832},
    {"label": "1152 x 896 (1.286:1)", "w": 1152, "h": 896},
    {"label": "1024 x 1024 (1:1)", "w": 1024, "h": 1024},
]

SKIP_NODE_TYPES = {"MarkdownNote", "Note", "PrimitiveNode", "Reroute"}

PONY_POSITIVE_SCORE_TAGS = "score_9, score_8_up, score_7_up, score_6_up"
PONY_QUALITY_TAGS = f"{PONY_POSITIVE_SCORE_TAGS}, ultra-detailed, hyper-realistic"
PONY_NEGATIVE_SCORE_TAGS = "score_5, score_4, score_3, score_2, score_1"
PONY_NEGATIVE_DEFAULT = ", ".join([
    PONY_NEGATIVE_SCORE_TAGS,
    "lowres, blurry, outoffocus, oversharpen, jpegartifacts, watermark, text, logo, signature",
    "grainy, noise, distortion, deformed, malformed",
    "extraarms, extralegs, extrafingers, bad anatomy, bad proportions",
    "mutation, duplicate, censored, sketch, cartoon",
    "badhands, extra fingers, missing fingers, extra limbs, missing limbs, ugly",
])

REFINER_TEMPLATES = {
    "character": "[fix the hands, face, eyes, arms and legs, refine details, fix textures, fix skin and hair, enhance background, remove animal features from humans]",
    "background": "[refine architectural and environmental details, fix textures, fix spelling on signs, correct perspective and scale, enhance lighting and atmosphere]",
    "location": "[refine architectural and material details, preserve signature landmarks, fix textures, correct perspective, enhance lighting and atmosphere]",
    "item": "[refine surface details and craftsmanship, fix material textures, sharpen silhouette and edges, enhance lighting and reflections, clean background, no humans]",
    "faction": "[fix the hands, faces, arms and legs of all figures, refine uniforms and insignia, enhance group composition and lighting]",
    "event": "[fix the hands, faces, arms and legs of all figures, refine action poses and motion, enhance scene cohesion and lighting]",
    "world": "[refine architectural and environmental details, fix textures, correct perspective and scale, enhance lighting and atmosphere]",
}

SDXL_SEGMENT_TEMPLATES = {
    "character": {"seg2": "detailed_outfit, character_focus, expressive_pose",
                  "seg3": "dynamic_scene, intentional_action",
                  "seg4": "cinematic_lighting, detailed_background"},
    "background": {"seg2": "environment_detail, no_humans, scenery_focus, wide_view",
                   "seg3": "establishing_shot, atmospheric_scene, no_humans",
                   "seg4": "cinematic_lighting, volumetric_light, detailed_background, depth_of_field"},
    "location": {"seg2": "architectural_detail, environment_detail, no_humans",
                 "seg3": "establishing_shot, place_focus, no_humans",
                 "seg4": "cinematic_lighting, volumetric_light, detailed_background"},
    "item": {"seg2": "material_detail, surface_texture, craftsmanship, no_humans",
             "seg3": "product_shot, centered_composition, no_humans",
             "seg4": "studio_lighting, soft_shadows, neutral_background, depth_of_field"},
    "faction": {"seg2": "uniformed_group, faction_insignia, coordinated_outfits",
                "seg3": "group_shot, formation, intentional_pose",
                "seg4": "cinematic_lighting, detailed_background, dramatic_atmosphere"},
    "event": {"seg2": "crowd, multiple_people, expressive_action",
              "seg3": "dynamic_scene, motion, intentional_action",
              "seg4": "cinematic_lighting, detailed_background, volumetric_atmosphere"},
    "world": {"seg2": "environment_detail, world_building",
              "seg3": "establishing_shot, atmospheric_scene",
              "seg4": "cinematic_lighting, detailed_background, volumetric_light"},
}
SUBJECT_KINDS = set(SDXL_SEGMENT_TEMPLATES) | {"character"}


# ----------------------- prompt helpers ------------------------------------
def ensure_sdxl_positive_score_tags(text):
    t = str(text or "").strip()
    if re.match(r"^\s*\[?\s*score_9\b", t, re.I):
        return t or PONY_POSITIVE_SCORE_TAGS
    if t.startswith("["):
        return f"[{PONY_POSITIVE_SCORE_TAGS}, {t[1:]}"
    return f"{PONY_POSITIVE_SCORE_TAGS}, {t}" if t else PONY_POSITIVE_SCORE_TAGS


def ensure_sdxl_negative_score_tags(text):
    t = str(text or "").strip()
    if re.match(r"^\s*score_5\b", t, re.I):
        return t or PONY_NEGATIVE_SCORE_TAGS
    return f"{PONY_NEGATIVE_SCORE_TAGS}, {t}" if t else PONY_NEGATIVE_SCORE_TAGS


def normalize_subject_kind(value):
    v = str(value or "").strip().lower()
    if v in SUBJECT_KINDS:
        return v
    if v in ("environment", "scene", "place"):
        return "background"
    return "character"


def prose_to_comma_tags(text, max_tags=16):
    raw = re.sub(r"\s+", " ", re.sub(r"[^\w\s,;|/()-]", " ",
                 str(text or "").lower())).strip()
    if not raw:
        return ""
    chunks = []
    for part in re.split(r"[,;|]+", raw):
        p = part.strip()
        if not p:
            continue
        chunks.append(p.replace(" ", "_") if " " in p else p)
    seen, tags = set(), []
    for chunk in chunks:
        tag = re.sub(r"_+", "_", chunk).strip("_")
        if not tag or len(tag) < 2 or tag in seen:
            continue
        seen.add(tag)
        tags.append(tag)
        if len(tags) >= max_tags:
            break
    return ", ".join(tags)


def build_sdxl_tag_prompt(ctx):
    kind = normalize_subject_kind(ctx.get("subjectKind"))
    tpl = SDXL_SEGMENT_TEMPLATES.get(kind, SDXL_SEGMENT_TEMPLATES["character"])
    main = prose_to_comma_tags(ctx.get("selectedText"), 18)
    outfit = prose_to_comma_tags(ctx.get("loreContext") or "", 12)
    action = prose_to_comma_tags(
        ", ".join(p for p in [ctx.get("selectedText"), ctx.get("locationHint")] if p), 16)
    bg = prose_to_comma_tags(
        ", ".join(p for p in [ctx.get("stylePrefix"), ctx.get("timeStyle"),
                              ctx.get("locationHint")] if p), 14)
    return "\n".join([
        f"[{', '.join(p for p in [PONY_QUALITY_TAGS, main] if p)}]|",
        f"[{outfit or tpl['seg2']}]|",
        f"[{action or tpl['seg3']}]|",
        f"[{bg or tpl['seg4']}]",
    ])


def build_sdxl_tag_prompt_from_segments(segments, tpl):
    subject = ", ".join(segments.get("subject") or [])
    details = ", ".join(segments.get("details") or [])
    scene = ", ".join(segments.get("scene") or [])
    lighting = ", ".join(segments.get("lighting") or [])
    return "\n".join([
        f"[{', '.join(p for p in [PONY_QUALITY_TAGS, subject] if p)}]|",
        f"[{details or tpl['seg2']}]|",
        f"[{scene or tpl['seg3']}]|",
        f"[{lighting or tpl['seg4']}]",
    ])


def build_refiner_director_prompt(ctx):
    kind = normalize_subject_kind(ctx.get("subjectKind"))
    return REFINER_TEMPLATES.get(kind, REFINER_TEMPLATES["character"])


def build_legacy_comma_prompt(ctx):
    lore = ctx.get("loreContext") or ""
    return ", ".join(p for p in [
        ctx.get("stylePrefix"), ctx.get("timeStyle"), ctx.get("locationHint"),
        ctx.get("selectedText"), lore[:100] if lore else ""] if p)


def get_time_style(time_key):
    return {
        "dawn": "golden hour dawn light, morning mist, soft warm glow",
        "day": "bright natural daylight, clear sky",
        "dusk": "sunset orange sky, golden hour, dusk light",
        "night": "moonlight, deep shadows, night scene, stars visible",
        "storm": "dramatic storm clouds, lightning in sky, heavy rain",
    }.get(time_key, "bright natural daylight, clear sky")


def resolve_preset_for_dims(width, height):
    w, h = float(width or 0), float(height or 0)
    if not w or not h:
        return {"preset": PRESET_TABLE[0]["label"], "invert": False, "warned": False}
    target = w / h
    best, best_score, best_invert, best_diff = PRESET_TABLE[0], float("inf"), False, float("inf")
    for preset in PRESET_TABLE:
        for invert, cw, ch in ((False, preset["w"], preset["h"]),
                               (True, preset["h"], preset["w"])):
            ratio = cw / ch
            diff = abs(ratio - target) / target
            pixel = abs(cw - w) + abs(ch - h)
            score = diff * 10 + pixel / 2000
            if score < best_score:
                best, best_score, best_invert, best_diff = preset, score, invert, diff
    return {"preset": best["label"], "invert": best_invert, "warned": best_diff > 0.08}


def _cap_words(raw, max_words):
    words = [w for w in str(raw or "").strip().split() if w]
    return " ".join(words[:max_words])


# ----------------------- prompt bundle resolution ---------------------------
def resolve_prompt_bundle(mapping, ctx, render_options, engine=None,
                          styles_csv_path=""):
    family = (mapping or {}).get("workflowFamily", "generic")
    is_pony = family == "pony-flux2-ref"
    use_split = (family in ("sdxl-flux2-ref", "pony-flux2-ref")
                 or (mapping.get("refinerPrompt") and mapping.get("negativePrompt")))

    def pick(*cands):
        for c in cands:
            if c is None:
                continue
            s = str(c).strip()
            if s:
                return s
        return ""

    positive_override = pick(render_options.get("positivePromptOverride"))
    negative_override = pick(render_options.get("negativePromptOverride"))
    subject_kind = normalize_subject_kind(ctx.get("subjectKind"))

    if use_split:
        refiner = (pick(render_options.get("refinerPromptOverride"),
                        render_options.get("entryRefinerOverride"),
                        render_options.get("refinerPrompt"))
                   or build_refiner_director_prompt(ctx))
        if positive_override:
            positive = positive_override
        else:
            tpl = SDXL_SEGMENT_TEMPLATES.get(subject_kind,
                                             SDXL_SEGMENT_TEMPLATES["character"])
            try:
                segments = tagify_scene(
                    engine, ctx.get("selectedText"),
                    subject_kind=subject_kind,
                    lore_context=", ".join(p for p in [
                        ctx.get("loreContext"), ctx.get("stylePrefix"),
                        ctx.get("timeStyle"), ctx.get("locationHint")] if p)[:500])
                if not segments.get("fellBack"):
                    positive = ensure_sdxl_positive_score_tags(
                        build_sdxl_tag_prompt_from_segments(segments, tpl))
                else:
                    positive = ensure_sdxl_positive_score_tags(build_sdxl_tag_prompt(ctx))
            except Exception:
                positive = ensure_sdxl_positive_score_tags(build_sdxl_tag_prompt(ctx))
        negative = negative_override or ensure_sdxl_negative_score_tags(PONY_NEGATIVE_DEFAULT)
        return {"positivePrompt": positive, "negativePrompt": negative,
                "refinerPrompt": refiner, "subjectKind": subject_kind}

    positive = positive_override or build_legacy_comma_prompt(ctx)
    negative = negative_override or ("blurry, low quality, text, watermark, "
                                     "deformed, bad anatomy")
    refiner = pick(render_options.get("refinerPromptOverride"),
                   render_options.get("refinerPrompt"))
    return {"positivePrompt": positive, "negativePrompt": negative,
            "refinerPrompt": refiner, "subjectKind": subject_kind}


# ----------------------- workflow loading / injection -----------------------
def load_workflow_source(workflow_name=None, workflow_json=None):
    """Return {kind: 'frontend'|'api', workflow: dict}. Loads from a bundled
    workflows/ file by name, or a raw JSON string/dict."""
    if workflow_json:
        parsed = (json.loads(workflow_json) if isinstance(workflow_json, str)
                  else workflow_json)
        if isinstance(parsed.get("nodes"), list):
            return {"kind": "frontend", "workflow": parsed}
        return {"kind": "api", "workflow": parsed}

    candidates = []
    if workflow_name:
        candidates.append(os.path.join(config.WORKFLOWS_DIR, workflow_name))
    candidates += [
        os.path.join(config.WORKFLOWS_DIR, "sdxl_flux2_reference_workflow.api.json"),
        os.path.join(config.WORKFLOWS_DIR, "sdxl_flux2_reference_workflow.json"),
        os.path.join(config.WORKFLOWS_DIR, "default_workflow.json"),
    ]
    for path in candidates:
        if path and os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                parsed = json.load(f)
            if isinstance(parsed.get("nodes"), list):
                return {"kind": "frontend", "workflow": parsed}
            return {"kind": "api", "workflow": parsed}
    raise FileNotFoundError(
        "No ComfyUI workflow found. Copy a workflow .json into "
        f"{config.WORKFLOWS_DIR} (see README).")


def _apply_mapped_value(workflow, mapping, value, field):
    if not mapping or value is None:
        return
    if isinstance(workflow.get("nodes"), list):
        node = next((n for n in workflow["nodes"]
                     if int(n.get("id")) == int(mapping["nodeId"])), None)
    else:
        node = workflow.get(str(mapping["nodeId"]))
    if not node:
        raise ValueError(f"Workflow mapping error: node not found for {field}")
    path = mapping.get("path", "")
    if path.startswith("inputs."):
        key = path[len("inputs."):]
        node.setdefault("inputs", {})[key] = value
        return
    if path.startswith("widgets_values."):
        idx = int(path.split(".")[1])
        wv = node.setdefault("widgets_values", [])
        while len(wv) <= idx:
            wv.append(None)
        wv[idx] = value
        return
    raise ValueError(f"Workflow mapping error: unsupported path for {field}")


def _apply_placeholders(workflow, mapping, values):
    _apply_mapped_value(workflow, mapping.get("positivePrompt"),
                        values.get("positivePrompt"), "positivePrompt")
    if (mapping.get("negativePrompt") and mapping.get("negativePromptMode") != "auto-zero"
            and values.get("negativePrompt") is not None):
        _apply_mapped_value(workflow, mapping["negativePrompt"],
                            values["negativePrompt"], "negativePrompt")
    if values.get("refinerPrompt") and str(values["refinerPrompt"]).strip():
        _apply_mapped_value(workflow, mapping.get("refinerPrompt"),
                            values["refinerPrompt"], "refinerPrompt")
    _apply_mapped_value(workflow, mapping.get("seed"), values.get("seed"), "seed")
    if values.get("sizePreset") and mapping.get("sizePreset"):
        _apply_mapped_value(workflow, mapping["sizePreset"], values["sizePreset"], "sizePreset")
    elif values.get("customSizePreset") and mapping.get("customSizePreset"):
        _apply_mapped_value(workflow, mapping["customSizePreset"],
                            values["customSizePreset"], "customSizePreset")
        if mapping.get("customSizeInvert") and values.get("customSizePresetInvert") is not None:
            _apply_mapped_value(workflow, mapping["customSizeInvert"],
                                bool(values["customSizePresetInvert"]), "customSizeInvert")
    else:
        if values.get("width"):
            _apply_mapped_value(workflow, mapping.get("width"), values["width"], "width")
        if values.get("height"):
            _apply_mapped_value(workflow, mapping.get("height"), values["height"], "height")
    if values.get("batchSize"):
        _apply_mapped_value(workflow, mapping.get("batchSize"), values["batchSize"], "batchSize")
    if isinstance(mapping.get("referenceImages"), list) and isinstance(values.get("referenceImages"), list):
        for i, ref_map in enumerate(mapping["referenceImages"]):
            if i < len(values["referenceImages"]) and values["referenceImages"][i]:
                _apply_mapped_value(workflow, ref_map, values["referenceImages"][i],
                                    f"referenceImages[{i}]")


_TYPE_WIDGET_MAP = {
    "CLIPTextEncode": ["text"],
    "KSampler": ["seed", "control_after_generate", "steps", "cfg",
                 "sampler_name", "scheduler", "denoise"],
    "UNETLoader": ["unet_name", "weight_dtype"],
    "UnetLoaderGGUF": ["unet_name"],
    "CLIPLoader": ["clip_name", "type", "device"],
    "CLIPLoaderGGUF": ["clip_name", "type"],
    "DualCLIPLoaderGGUF": ["clip_name1", "clip_name2", "type"],
    "VAELoader": ["vae_name"],
    "SaveImage": ["filename_prefix"],
    "easy int": ["value"],
    "easy positive": ["positive"],
    "easy negative": ["negative"],
    "easy globalSeed": ["value", "mode", "action", "last_seed"],
    "EmptyLatentImage": ["width", "height", "batch_size"],
    "EmptySD3LatentImage": ["width", "height", "batch_size"],
    "EmptyFlux2LatentImage": ["width", "height", "batch_size"],
    "EmptyLatentImagePresets": ["resolution", "swap_dimensions", "batch_size"],
    "EmptyLatentImageCustomPresets": ["dimensions", "invert", "batch_size"],
    "CLIPSetLastLayer": ["stop_at_clip_layer"],
    "LoadImage": ["image", "upload"],
    "Text Concatenate": ["delimiter", "clean_whitespace"],
}
_LATENT_TYPES = ("EmptyFlux2LatentImage", "EmptyLatentImage", "EmptySD3LatentImage")


def _resolve_link_source(frontend, from_node_id, from_slot):
    nodes_by_id = {int(n["id"]): n for n in frontend.get("nodes", [])}
    node_id, slot, seen = int(from_node_id), int(from_slot), set()
    while len(seen) < 32:
        key = f"{node_id}:{slot}"
        if key in seen:
            break
        seen.add(key)
        node = nodes_by_id.get(node_id)
        if not node or node.get("type") != "Reroute":
            return str(node_id), slot
        incoming = next((l for l in frontend.get("links", []) if int(l[3]) == node_id), None)
        if not incoming:
            return str(node_id), slot
        node_id, slot = int(incoming[1]), int(incoming[2])
    return str(from_node_id), from_slot


def convert_frontend_to_api(frontend):
    incoming = {}
    for link in frontend.get("links", []):
        _, from_node, from_slot, to_node, to_slot = link[:5]
        incoming.setdefault(int(to_node), []).append(
            {"fromNodeId": int(from_node), "fromSlot": int(from_slot), "toSlot": int(to_slot)})

    prompt = {}
    for node in frontend.get("nodes", []):
        ntype = node.get("type")
        if not ntype or ntype in SKIP_NODE_TYPES:
            continue
        node_id = str(node["id"])
        api_node = {"class_type": ntype, "inputs": {}}

        if ntype == lora_panel.POWER_LORA_CLASS:
            idx = 0
            for entry in (node.get("widgets_values") or []):
                if not isinstance(entry, dict) or "lora" not in entry:
                    continue
                idx += 1
                api_node["inputs"][f"lora_{idx}"] = {
                    "on": bool(entry.get("on")), "lora": entry.get("lora"),
                    "strength": entry.get("strength"),
                    "strengthTwo": entry.get("strengthTwo")}

        input_widget_names = [i["widget"]["name"] for i in (node.get("inputs") or [])
                              if i.get("widget", {}).get("name")]
        type_widget_names = _TYPE_WIDGET_MAP.get(ntype, [])
        widget_names = list(dict.fromkeys(input_widget_names + type_widget_names))
        wv = node.get("widgets_values") or []
        for name in widget_names:
            idx = (type_widget_names.index(name) if name in type_widget_names
                   else input_widget_names.index(name) if name in input_widget_names else -1)
            if 0 <= idx < len(wv):
                api_node["inputs"][name] = wv[idx]
        if ntype in _LATENT_TYPES and api_node["inputs"].get("batch_size") in (None,):
            api_node["inputs"]["batch_size"] = 1

        links_in = incoming.get(int(node["id"]), [])
        sorted_inputs = sorted(node.get("inputs") or [],
                               key=lambda a: a.get("slot_index", 0))
        for i, inp in enumerate(sorted_inputs):
            name = inp.get("name")
            if not name:
                continue
            slot = inp.get("slot_index", i)
            lm = next((l for l in links_in if l["toSlot"] == slot), None)
            if lm:
                src_id, src_slot = _resolve_link_source(frontend, lm["fromNodeId"], lm["fromSlot"])
                api_node["inputs"][name] = [src_id, src_slot]
        prompt[node_id] = api_node

    if not prompt:
        raise ValueError("No executable nodes found in workflow JSON")
    return prompt


def _is_final_image_class(class_type):
    ct = str(class_type or "")
    return bool(re.search(r"(^|[\s_])save[\s_]?image($|[\s_])", ct, re.I)
                or re.fullmatch(r"saveimage", ct, re.I))


# ----------------------- ComfyClient ----------------------------------------
class ComfyClient:
    def __init__(self, settings=None, engine=None):
        self.settings = settings
        self.engine = engine

    def _url(self):
        if self.settings is not None:
            return str(self.settings.get("services.comfyui_url", config.COMFYUI_URL)).rstrip("/")
        return config.COMFYUI_URL.rstrip("/")

    def _styles_csv_path(self):
        if self.settings is not None:
            return self.settings.get("services.styles_csv", "")
        return ""

    # --- service helpers ---
    def upload_image(self, file_path):
        if not file_path or not os.path.exists(file_path):
            return None
        with open(file_path, "rb") as f:
            files = {"image": (os.path.basename(file_path), f.read())}
        data = {"overwrite": "true"}
        r = requests.post(f"{self._url()}/upload/image", files=files, data=data, timeout=30)
        r.raise_for_status()
        return r.json().get("name", os.path.basename(file_path))

    def resolve_reference_filenames(self, reference_images):
        out = [None, None, None]
        if not isinstance(reference_images, list):
            return []
        for i in range(min(3, len(reference_images))):
            ref = reference_images[i]
            if not ref:
                continue
            p = str(ref).strip()
            if os.path.isabs(p) or ":\\" in p or p.startswith("/"):
                uploaded = self.upload_image(p)
                if uploaded:
                    out[i] = uploaded
            else:
                out[i] = os.path.basename(p)
        return out

    def list_latent_preset_options(self):
        try:
            r = requests.get(f"{self._url()}/object_info/EmptyLatentImageCustomPresets", timeout=5)
            r.raise_for_status()
            data = r.json()
            node = data.get("EmptyLatentImageCustomPresets", data)
            dims = node.get("input", {}).get("required", {}).get("dimensions")
            options = dims[0] if isinstance(dims, list) else None
            return [o for o in options if isinstance(o, str)] if isinstance(options, list) else []
        except (requests.RequestException, ValueError, KeyError, TypeError):
            return []

    def list_loras(self):
        try:
            return lora_panel.list_installed_loras(self._url())
        except RuntimeError:
            return []

    # --- main render ---
    def render(self, text, lore_context="", world_state=None, render_options=None,
               on_progress=None, on_image=None, on_error=None):
        """Submit a render and block until an image arrives (or error/timeout).

        Calls on_image(base64_png, prompt_id) on success. Returns the prompt_id.
        """
        render_options = render_options or {}
        world_state = world_state or {}
        comfy_url = self._url()
        style_prefix = (self.settings.get("image.style_prefix", config.IMAGE_STYLE_PREFIX)
                        if self.settings else config.IMAGE_STYLE_PREFIX) \
            or "cinematic, moody, detailed, atmospheric"
        workflow_name = (self.settings.get("image.workflow", config.IMAGE_WORKFLOW)
                         if self.settings else config.IMAGE_WORKFLOW)

        seed = self._resolve_seed(render_options)
        source = load_workflow_source(workflow_name, render_options.get("workflowJson"))
        location = world_state.get("location")
        location_hint = f"{location}, " if location and location != "unknown" else ""
        ctx = {
            "selectedText": _cap_words(text, 100),
            "stylePrefix": style_prefix,
            "timeStyle": get_time_style(world_state.get("time")),
            "locationHint": location_hint,
            "loreContext": str(lore_context or "")[:200],
            "subjectKind": render_options.get("subjectKind")
            or ("character" if render_options.get("mode") == "character" else "background"),
        }

        ref_filenames = self.resolve_reference_filenames(render_options.get("referenceImages"))
        dims_w = int(render_options.get("width") or 0) or None
        dims_h = int(render_options.get("height") or 0) or None

        if source["kind"] == "frontend":
            working = copy.deepcopy(source["workflow"])
            mapping = workflow_map.detect_workflow_mapping(working)
            prompts = resolve_prompt_bundle(mapping, ctx, render_options,
                                            engine=self.engine,
                                            styles_csv_path=self._styles_csv_path())
            self._apply_dims(working, mapping, prompts, seed, dims_w, dims_h, ref_filenames, render_options)
            workflow_prompt = convert_frontend_to_api(working)
        else:
            workflow_prompt = copy.deepcopy(source["workflow"])
            workflow_prompt.pop("_readme", None)
            mapping = workflow_map.detect_workflow_mapping(workflow_prompt)
            prompts = resolve_prompt_bundle(mapping, ctx, render_options,
                                            engine=self.engine,
                                            styles_csv_path=self._styles_csv_path())
            self._apply_dims(workflow_prompt, mapping, prompts, seed, dims_w, dims_h, ref_filenames, render_options)

        client_id = str(uuid.uuid4())
        try:
            r = requests.post(f"{comfy_url}/prompt",
                              json={"prompt": workflow_prompt, "client_id": client_id},
                              timeout=15)
        except requests.RequestException as exc:
            if on_error:
                on_error({"message": f"ComfyUI unreachable at {comfy_url}: {exc}"})
            return None
        if not r.ok:
            msg = workflow_map.parse_comfyui_error(r.status_code, r.text)
            if on_error:
                on_error({"message": msg})
            return None
        resp = r.json()
        if not resp.get("prompt_id") or resp.get("node_errors"):
            msg = workflow_map.parse_comfyui_error(r.status_code, json.dumps(resp))
            if on_error:
                on_error({"message": msg})
            return None

        prompt_id = resp["prompt_id"]
        node_class = {nid: n.get("class_type", "") for nid, n in workflow_prompt.items()}
        final_nodes = {nid for nid, ct in node_class.items() if _is_final_image_class(ct)}
        self._listen(comfy_url, prompt_id, client_id, node_class, final_nodes,
                     on_progress, on_image, on_error)
        return prompt_id

    def _apply_dims(self, workflow, mapping, prompts, seed, w, h, refs, render_options):
        values = {
            "positivePrompt": prompts["positivePrompt"],
            "refinerPrompt": prompts.get("refinerPrompt"),
            "seed": seed,
            "batchSize": 1,
            "referenceImages": refs,
        }
        if mapping.get("negativePromptMode") == "mapped":
            values["negativePrompt"] = prompts["negativePrompt"]
        if mapping.get("sizePreset") and w and h:
            resolved = resolve_preset_for_dims(w, h)
            values["sizePreset"] = resolved["preset"]
        elif mapping.get("customSizePreset") and render_options.get("customSizePreset"):
            values["customSizePreset"] = render_options["customSizePreset"]
            values["customSizePresetInvert"] = render_options.get("customSizePresetInvert")
        else:
            values["width"], values["height"] = w, h
        _apply_placeholders(workflow, mapping, values)

    def _resolve_seed(self, render_options):
        raw = render_options.get("seedOverride")
        if raw not in (None, "") and str(raw).strip():
            try:
                n = int(float(raw))
                if n >= 0:
                    return n
            except (TypeError, ValueError):
                pass
        behavior = (self.settings.get("image.seed_behavior", "randomize")
                    if self.settings else "randomize")
        if behavior == "fixed":
            return 42
        return random.randint(0, 999999999)

    # --- websocket listen + history recovery ---
    def _emit(self, cb, payload):
        if cb:
            try:
                cb(payload)
            except Exception:
                pass

    def _fetch_image(self, comfy_url, prompt_id, images, on_image):
        img = (images or [{}])[0]
        if not img.get("filename"):
            raise ValueError("ComfyUI result has no image filename")
        url = (f"{comfy_url}/view?filename={requests.utils.quote(img['filename'])}"
               f"&subfolder={img.get('subfolder', '')}&type={img.get('type', 'output')}")
        r = requests.get(url, timeout=30)
        r.raise_for_status()
        b64 = base64.b64encode(r.content).decode("ascii")
        if on_image:
            on_image(b64, prompt_id)

    def _pick_images(self, outputs, final_nodes):
        if not isinstance(outputs, dict):
            return None
        if final_nodes:
            for nid in final_nodes:
                images = (outputs.get(str(nid)) or {}).get("images")
                if images:
                    return images
            return None
        for nid in outputs:
            images = (outputs.get(nid) or {}).get("images")
            if images:
                return images
        return None

    def _history_recover(self, comfy_url, prompt_id, final_nodes, on_image,
                         deadline, poll=5):
        while time.time() < deadline:
            try:
                r = requests.get(f"{comfy_url}/history/{requests.utils.quote(prompt_id)}", timeout=15)
                if r.ok:
                    entry = r.json().get(prompt_id)
                    if entry and entry.get("status", {}).get("completed"):
                        images = self._pick_images(entry.get("outputs"), final_nodes)
                        if images:
                            self._fetch_image(comfy_url, prompt_id, images, on_image)
                            return True
                        return False
            except requests.RequestException:
                pass
            time.sleep(poll)
        return False

    def _listen(self, comfy_url, prompt_id, client_id, node_class, final_nodes,
                on_progress, on_image, on_error):
        total = len(node_class)
        completed = set()
        self._emit(on_progress, {"phase": "queued", "label": "Queued",
                                 "nodesCompleted": 0, "totalNodes": total,
                                 "value": 0, "max": 0})
        wall_deadline = time.time() + 1800  # 30 min

        if not WEBSOCKET_AVAILABLE:
            if not self._history_recover(comfy_url, prompt_id, final_nodes, on_image, wall_deadline):
                self._emit(on_error, {"message": "Render did not complete (no websocket-client; history poll timed out)."})
            return

        ws_url = comfy_url.replace("http://", "ws://").replace("https://", "wss://")
        try:
            ws = websocket.create_connection(f"{ws_url}/ws?clientId={client_id}", timeout=600)
        except Exception:
            if not self._history_recover(comfy_url, prompt_id, final_nodes, on_image, wall_deadline):
                self._emit(on_error, {"message": "Could not open ComfyUI websocket and history poll timed out."})
            return

        last_node = None
        try:
            while time.time() < wall_deadline:
                try:
                    raw = ws.recv()
                except Exception:
                    break
                if not raw or not isinstance(raw, str):
                    continue
                try:
                    msg = json.loads(raw)
                except (json.JSONDecodeError, ValueError):
                    continue
                data = msg.get("data") or {}
                if data.get("prompt_id") and data["prompt_id"] != prompt_id:
                    continue
                mtype = msg.get("type")
                if mtype == "executing":
                    node = data.get("node")
                    if node is None:
                        self._emit(on_progress, {"phase": "done", "label": "Finishing...",
                                                 "nodesCompleted": total, "totalNodes": total,
                                                 "value": 0, "max": 0})
                    else:
                        if last_node is not None:
                            completed.add(str(last_node))
                        last_node = str(node)
                        ct = node_class.get(str(node), "")
                        self._emit(on_progress, {"phase": "executing",
                                                 "label": f"{ct} (node {node})" if ct else f"Node {node}",
                                                 "nodesCompleted": len(completed),
                                                 "totalNodes": total, "value": 0, "max": 0})
                elif mtype == "progress":
                    self._emit(on_progress, {"phase": "step", "label": "Working",
                                             "nodesCompleted": len(completed), "totalNodes": total,
                                             "value": int(data.get("value") or 0),
                                             "max": int(data.get("max") or 0)})
                elif mtype == "executed":
                    images = (data.get("output") or {}).get("images")
                    if not images:
                        continue
                    executed_node = str(data.get("node")) if data.get("node") is not None else None
                    if final_nodes and executed_node not in final_nodes:
                        continue
                    self._emit(on_progress, {"phase": "complete", "label": "Complete",
                                             "nodesCompleted": total, "totalNodes": total,
                                             "value": 0, "max": 0})
                    try:
                        self._fetch_image(comfy_url, prompt_id, images, on_image)
                    except Exception as exc:
                        self._emit(on_error, {"message": str(exc)})
                    return
                elif mtype == "execution_error":
                    self._emit(on_error, {"message": "ComfyUI execution error: "
                                          + json.dumps(data)[:400]})
                    return
        finally:
            try:
                ws.close()
            except Exception:
                pass
        # Fell out of loop without an image -> try history.
        if not self._history_recover(comfy_url, prompt_id, final_nodes, on_image, wall_deadline):
            self._emit(on_error, {"message": "ComfyUI render timed out."})
