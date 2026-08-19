"""LLM streaming runner extracted from AgentEngine."""

from __future__ import annotations

import gc
import os
import re
import time
from typing import Any, Generator

import config
from src.cancel_token import CancelToken

try:
    from llama_cpp import Llama
    LLAMA_AVAILABLE = True
except Exception:
    Llama = None
    LLAMA_AVAILABLE = False

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def mock_mode_reason(settings) -> str | None:
    """Why generation would run mocked, or None when a real model can load."""
    if not LLAMA_AVAILABLE:
        return "llama-cpp-python is not installed"
    registry = settings.model_registry() or {}
    if not registry:
        return "no models are registered"
    for spec in registry.values():
        path = (spec or {}).get("path", "")
        if path and os.path.exists(path):
            return None
    return "no model files found in models/"


class LlmRunner:
    """Single-slot model loader and streaming generator."""

    def __init__(self, settings):
        self.settings = settings
        self.current_key: str | None = None
        self.current_llm = None
        self.cancel_token = CancelToken()
        self._last_generation = ("", "")

    def request_cancel(self) -> None:
        self.cancel_token.cancel()

    def clear_cancel(self) -> None:
        self.cancel_token.clear()

    def is_cancelled(self) -> bool:
        return self.cancel_token.is_cancelled

    @property
    def last_generation(self) -> tuple[str, str]:
        return self._last_generation

    def unload(self) -> None:
        if self.current_llm is not None:
            del self.current_llm
        self.current_llm = None
        self.current_key = None
        gc.collect()

    def _load_model(self, model_key: str):
        if self.current_key == model_key:
            return self.current_llm
        self.unload()
        spec = self.settings.model_spec(model_key)
        if spec is None:
            raise KeyError(f"No model registered for key {model_key!r}")
        path = spec.get("path", "")
        if not LLAMA_AVAILABLE or not os.path.exists(path):
            self.current_key = model_key
            self.current_llm = None
            return None
        self.current_llm = Llama(
            model_path=path,
            n_ctx=spec.get("n_ctx", 4096),
            n_gpu_layers=spec.get("n_gpu_layers", -1),
            verbose=False,
            **spec.get("extra", {}),
        )
        self.current_key = model_key
        return self.current_llm

    def _temp(self, persona: dict) -> float:
        return persona.get("temperature") or self.settings.get(
            "generation.temperature", config.DEFAULT_TEMPERATURE)

    def _max_tokens(self, persona: dict, override=None) -> int:
        return (override or persona.get("max_tokens")
                or self.settings.get("generation.max_tokens", config.DEFAULT_MAX_TOKENS))

    def _repeat_penalty(self, persona: dict) -> float:
        return float(persona.get("repeat_penalty")
                     or self.settings.get("generation.repeat_penalty",
                                          config.DEFAULT_REPEAT_PENALTY))

    def stream(
        self,
        persona: dict[str, Any],
        messages: list[dict[str, str]],
        show_think: bool = False,
        max_tokens: int | None = None,
        cancel_token: CancelToken | None = None,
    ) -> Generator[str, None, None]:
        token = cancel_token or self.cancel_token
        llm = self._load_model(persona["model_key"])
        raw_parts: list[str] = []
        emitted = 0

        if llm is None:
            mock = self._mock_response(persona, messages[-1]["content"])
            for chunk in self._word_chunks(mock):
                token.check()
                raw_parts.append(chunk)
                time.sleep(0.02)
                yield chunk
            raw = "".join(raw_parts)
            visible = raw
        else:
            kwargs = {
                "messages": messages,
                "temperature": self._temp(persona),
                "max_tokens": self._max_tokens(persona, max_tokens),
                "stream": True,
            }
            rp = self._repeat_penalty(persona)
            if abs(rp - 1.0) > 0.001:
                kwargs["repeat_penalty"] = rp
            try:
                stream = llm.create_chat_completion(**kwargs)
            except TypeError:
                kwargs.pop("repeat_penalty", None)
                stream = llm.create_chat_completion(**kwargs)
            for chunk in stream:
                token.check()
                delta = chunk["choices"][0].get("delta", {}).get("content")
                if not delta:
                    continue
                raw_parts.append(delta)
                raw = "".join(raw_parts)
                visible = raw if show_think else self._clean_stream(raw)
                new = visible[emitted:]
                if new:
                    emitted = len(visible)
                    yield new
            raw = "".join(raw_parts)
            visible = raw if show_think else self._strip_think(raw)

        self._last_generation = (raw, visible.strip())

    @staticmethod
    def _strip_think(text: str) -> str:
        cleaned = _THINK_RE.sub("", text)
        if "<think>" in cleaned:
            cleaned = cleaned.split("<think>", 1)[0]
        return cleaned.replace("</think>", "").strip()

    @staticmethod
    def _clean_stream(buffer: str) -> str:
        cleaned = _THINK_RE.sub("", buffer)
        if "<think>" in cleaned:
            cleaned = cleaned.split("<think>", 1)[0]
        return cleaned.replace("</think>", "")

    @staticmethod
    def _word_chunks(text: str) -> list[str]:
        return re.findall(r"\S+\s*", text)

    def _mock_response(self, persona: dict, user_input: str) -> str:
        reason = ("llama-cpp-python not installed"
                  if not LLAMA_AVAILABLE else
                  f"model file not found for key '{persona['model_key']}'")
        return (
            f"[MOCK - {persona['display_name']}] ({reason})\n"
            f"Drop the .gguf in models/ (see config.MODEL_REGISTRY) to go live.\n"
            f"--- echo ---\n{user_input}"
        )
