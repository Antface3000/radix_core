"""Tool decorator and schema helpers."""

from __future__ import annotations

import inspect
from typing import Any, Callable


def tool(name: str | None = None, description: str = ""):
    """Mark a function as a registerable tool."""

    def decorator(fn: Callable) -> Callable:
        fn._tool_name = name or fn.__name__
        fn._tool_description = description or (fn.__doc__ or "").strip()
        fn._tool_schema = _schema_from_fn(fn)
        return fn

    return decorator


def _schema_from_fn(fn: Callable) -> dict[str, Any]:
    sig = inspect.signature(fn)
    props = {}
    required = []
    for pname, param in sig.parameters.items():
        if pname == "self":
            continue
        anno = param.annotation
        ptype = "string"
        if anno is int:
            ptype = "integer"
        elif anno is float:
            ptype = "number"
        elif anno is bool:
            ptype = "boolean"
        props[pname] = {"type": ptype}
        if param.default is inspect.Parameter.empty:
            required.append(pname)
    return {
        "type": "object",
        "properties": props,
        "required": required,
    }
