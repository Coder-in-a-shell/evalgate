"""Scorers: small, deterministic checks on what an agent did and said.

A scorer takes ``(result, params, case)`` and returns ``(passed, detail)``. Add your own with
``@register_scorer("name")``. There is deliberately no built-in LLM judge: a judge is just a
scorer that calls a model, and which model, prompt and tolerance to use is a decision the
suite's owner should make visibly rather than inherit from a library default.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

SCORERS: dict[str, Callable[[Any, dict, Any], tuple[bool, str]]] = {}


def register_scorer(name: str):
    def deco(fn):
        SCORERS[name] = fn
        return fn
    return deco


def _text(result) -> str:
    out = result.output
    return (out if isinstance(out, str) else json.dumps(out, sort_keys=True, default=str)).lower()


def _need(params: dict, key: str, kind: type):
    if key not in params or not isinstance(params[key], kind):
        raise ValueError(f"param '{key}' must be {kind.__name__}")
    return params[key]


def _num(params: dict, key: str) -> float:
    v = params.get(key)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ValueError(f"param '{key}' must be a number")
    return v


@register_scorer("contains")
def _contains(result, params, case):
    text = _text(result)
    all_of = [v.lower() for v in params.get("all", [])]
    any_of = [v.lower() for v in params.get("any", [])]
    if not all_of and not any_of:
        raise ValueError("contains needs 'all' and/or 'any'")
    missing = [v for v in all_of if v not in text]
    if missing:
        return False, f"missing: {', '.join(missing)}"
    if any_of and not any(v in text for v in any_of):
        return False, f"none of: {', '.join(any_of)}"
    return True, "found"


@register_scorer("not_contains")
def _not_contains(result, params, case):
    text = _text(result)
    found = [v for v in _need(params, "values", list) if v.lower() in text]
    return (not found), ("clean" if not found else f"found: {', '.join(found)}")


@register_scorer("regex")
def _regex(result, params, case):
    pattern = _need(params, "pattern", str)
    return (re.search(pattern, _text(result), re.I) is not None), f"pattern {pattern!r}"


@register_scorer("field_equals")
def _field_equals(result, params, case):
    path, want = _need(params, "path", str), params.get("value")
    cur: Any = result.output
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return False, f"{path}: not present"
        cur = cur[part]
    return cur == want, f"{path} = {cur!r}, wanted {want!r}"


@register_scorer("tool_called")
def _tool_called(result, params, case):
    name = _need(params, "name", str)
    n = sum(1 for c in result.tool_calls if c.get("name") == name)
    return n > 0, f"{name} called {n}x"


@register_scorer("tool_not_called")
def _tool_not_called(result, params, case):
    name = _need(params, "name", str)
    n = sum(1 for c in result.tool_calls if c.get("name") == name)
    return n == 0, f"{name} called {n}x"


@register_scorer("max_tool_calls")
def _max_tool_calls(result, params, case):
    limit = _need(params, "n", int)
    return len(result.tool_calls) <= limit, f"{len(result.tool_calls)} calls (limit {limit})"


@register_scorer("citations_include")
def _citations_include(result, params, case):
    missing = [v for v in _need(params, "values", list) if v not in result.citations]
    return (not missing), ("all present" if not missing else f"missing: {', '.join(missing)}")


@register_scorer("citations_within")
def _citations_within(result, params, case):
    allowed = set(_need(params, "allowed", list))
    extra = [c for c in result.citations if c not in allowed]
    return (not extra), ("all grounded" if not extra else f"not in the allowed sources: {', '.join(extra)}")


@register_scorer("max_latency_ms")
def _max_latency(result, params, case):
    limit = _num(params, "ms")
    return (result.latency_ms or 0) <= limit, f"{(result.latency_ms or 0):.0f}ms (limit {limit}ms)"


@register_scorer("max_cost_usd")
def _max_cost(result, params, case):
    limit = _num(params, "usd")
    return result.cost_usd <= limit, f"${result.cost_usd:.4f} (limit ${limit})"


# A deliberately small PII/secret detector for the output of the agent under test. It is
# independent of whatever redaction the system being tested does, so it can catch that
# redaction being bypassed.
_PII = {
    "email": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    "phone": re.compile(r"(?<!\w)\+?\d[\d ()-]{8,}\d(?!\w)"),
    "secret": re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}|\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b|\bAKIA[0-9A-Z]{16}\b"),
}


@register_scorer("no_pii")
def _no_pii(result, params, case):
    text = result.output if isinstance(result.output, str) else json.dumps(result.output, default=str)
    hits = sorted(k for k, rx in _PII.items() if rx.search(text))
    return (not hits), ("clean" if not hits else f"leaked: {', '.join(hits)}")
