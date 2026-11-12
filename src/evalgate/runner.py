"""Run a suite against an agent and record what happened, case by case."""

from __future__ import annotations

import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from .cases import Case, Suite
from .scorers import SCORERS


@dataclass
class AgentResult:
    """What an agent hands back. Only ``output`` is required."""

    output: Any = None
    tool_calls: list[dict] = field(default_factory=list)  # [{"name": ..., "args": {...}}]
    citations: list[str] = field(default_factory=list)
    cost_usd: float = 0.0
    error: str | None = None
    latency_ms: float | None = None  # filled in by the runner


Agent = Callable[[Case], AgentResult]


def _attempt(agent: Agent, case: Case) -> dict:
    started = time.perf_counter()
    try:
        result = agent(case)
        if not isinstance(result, AgentResult):
            raise TypeError(f"agent returned {type(result).__name__}, expected AgentResult")
    except Exception as exc:  # an agent crash is a failed case, not a crashed run
        result = AgentResult(error=f"{type(exc).__name__}: {exc}")
    result.latency_ms = (time.perf_counter() - started) * 1000

    checks = []
    for name, params in case.expect.items():
        if result.error:
            checks.append({"scorer": name, "passed": False, "detail": f"agent error: {result.error}"})
            continue
        try:
            ok, detail = SCORERS[name](result, params, case)
        except Exception as exc:  # a bad scorer config is the suite author's bug; make it loud
            ok, detail = False, f"scorer error: {type(exc).__name__}: {exc}"
        checks.append({"scorer": name, "passed": bool(ok), "detail": detail})
    return {
        "passed": all(c["passed"] for c in checks),
        "checks": checks,
        "latency_ms": round(result.latency_ms, 3),
        "cost_usd": result.cost_usd,
        "tool_calls": len(result.tool_calls),
        "error": result.error,
        "output": result.output,
    }


def _rate(passed: int, total: int) -> float:
    return round(passed / total, 4) if total else 0.0


def _summarise(cases: list[dict]) -> dict:
    attempts = [a for c in cases for a in c["attempts"]]
    lat = sorted(a["latency_ms"] for a in attempts)
    p95 = lat[int(0.95 * (len(lat) - 1))] if lat else 0.0
    tags: dict[str, list[bool]] = {}
    for c in cases:
        for t in c["tags"]:
            tags.setdefault(t, []).append(c["passed"])
    return {
        "total": len(cases),
        "passed": sum(c["passed"] for c in cases),
        "pass_rate": _rate(sum(c["passed"] for c in cases), len(cases)),
        "by_tag": {t: {"total": len(v), "passed": sum(v), "pass_rate": _rate(sum(v), len(v))} for t, v in sorted(tags.items())},
        "latency_ms": {"p50": round(statistics.median(lat), 3) if lat else 0.0, "p95": round(p95, 3)},
        "mean_tool_calls": round(statistics.mean(a["tool_calls"] for a in attempts), 2) if attempts else 0.0,
        "total_cost_usd": round(sum(a["cost_usd"] for a in attempts), 6),
    }


def run_suite(suite: Suite, agent: Agent, *, label: str, agent_name: str = "", repeats: int = 1, workers: int = 4) -> dict:
    """Run every case ``repeats`` times. A case passes only if every attempt passes (so a
    flaky agent is not rewarded for getting lucky once)."""
    if repeats < 1:
        raise ValueError("repeats must be at least 1")
    jobs = [(c, k) for c in suite.cases for k in range(repeats)]
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        outcomes = list(pool.map(lambda job: _attempt(agent, job[0]), jobs))
    by_case: dict[str, list[dict]] = {}
    for (case, _), outcome in zip(jobs, outcomes):
        by_case.setdefault(case.id, []).append(outcome)
    cases = []
    for c in suite.cases:
        attempts = by_case[c.id]
        cases.append({
            "id": c.id, "tags": list(c.tags), "attempts": attempts,
            "pass_count": sum(a["passed"] for a in attempts),
            "passed": all(a["passed"] for a in attempts),
        })
    return {
        "meta": {
            "label": label, "agent": agent_name, "suite": suite.name, "suite_digest": suite.digest,
            "repeats": repeats, "created": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "summary": _summarise(cases),
        "cases": cases,
    }
