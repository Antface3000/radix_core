"""Schema-gated tool execution."""

from __future__ import annotations

import json
import re
from typing import Any, Callable

_TOOL_BLOCK = re.compile(r'\{"tool"\s*:\s*"([^"]+)"\s*,\s*"args"\s*:\s*(\{.*?\})\}', re.DOTALL)


class ToolGatekeeper:
    def __init__(self, tools: dict[str, Callable[..., Any]] | None = None):
        self._tools = tools or {}
        self._policies: dict[str, str] = {}  # auto | confirm | disabled

    def register(self, name: str, fn: Callable[..., Any], policy: str = "auto") -> None:
        self._tools[name] = fn
        self._policies[name] = policy

    def set_policy(self, name: str, policy: str) -> None:
        self._policies[name] = policy

    def policy(self, name: str) -> str:
        return self._policies.get(name, "auto")

    def list_tools(self) -> list[str]:
        return list(self._tools.keys())

    def parse_tool_calls(self, text: str) -> list[dict[str, Any]]:
        calls = []
        for match in _TOOL_BLOCK.finditer(text):
            name, args_json = match.group(1), match.group(2)
            try:
                args = json.loads(args_json)
            except json.JSONDecodeError:
                continue
            calls.append({"tool": name, "args": args})
        return calls

    def execute(self, name: str, args: dict[str, Any]) -> Any:
        if self.policy(name) == "disabled":
            raise PermissionError(f"Tool {name!r} is disabled")
        fn = self._tools.get(name)
        if fn is None:
            raise KeyError(f"Unknown tool: {name!r}")
        return fn(**args)

    def run_parsed(self, call: dict[str, Any]) -> dict[str, Any]:
        name = call.get("tool", "")
        args = call.get("args") or {}
        try:
            result = self.execute(name, args)
            return {"tool": name, "ok": True, "result": result}
        except Exception as exc:
            return {"tool": name, "ok": False, "error": str(exc)}
