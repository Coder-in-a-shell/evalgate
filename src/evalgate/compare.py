"""Compare a candidate run with a baseline, and decide whether it may ship."""

from __future__ import annotations

import math


class GateError(ValueError):
    """The gate configuration is wrong (for example, a misspelt key)."""


def wilson(passed: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for a pass rate. With a small suite the interval is wide,
    which is the honest way to show how little a one-case change proves."""
    if total == 0:
        return (0.0, 0.0)
    p = passed / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denom
    return (round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4))


def compare(base: dict, cand: dict) -> dict:
    b = {c["id"]: c for c in base["cases"]}
    c = {x["id"]: x for x in cand["cases"]}
    both = [i for i in c if i in b]
    bs, cs = base["summary"], cand["summary"]

    def delta(x, y):
        return round(y - x, 4)

    tags = {}
    for t in sorted(set(bs["by_tag"]) | set(cs["by_tag"])):
        bt, ct = bs["by_tag"].get(t), cs["by_tag"].get(t)
        tags[t] = {"base": bt["pass_rate"] if bt else None, "cand": ct["pass_rate"] if ct else None}
    return {
        "base_label": base["meta"]["label"], "cand_label": cand["meta"]["label"],
        "same_suite": base["meta"]["suite_digest"] == cand["meta"]["suite_digest"],
        "regressions": [i for i in both if b[i]["passed"] and not c[i]["passed"]],
        "fixes": [i for i in both if not b[i]["passed"] and c[i]["passed"]],
        "still_failing": [i for i in both if not b[i]["passed"] and not c[i]["passed"]],
        "new_cases": [i for i in c if i not in b],
        "missing_cases": [i for i in b if i not in c],
        "pass_rate": {
            "base": bs["pass_rate"], "cand": cs["pass_rate"], "delta": delta(bs["pass_rate"], cs["pass_rate"]),
            "base_ci": wilson(bs["passed"], bs["total"]), "cand_ci": wilson(cs["passed"], cs["total"]),
            "base_counts": [bs["passed"], bs["total"]], "cand_counts": [cs["passed"], cs["total"]],
        },
        "by_tag": tags,
        "latency_p95_ms": {"base": bs["latency_ms"]["p95"], "cand": cs["latency_ms"]["p95"]},
        "cost_usd": {"base": bs["total_cost_usd"], "cand": cs["total_cost_usd"]},
    }


_GATE_KEYS = {"min_pass_rate", "max_regressions", "tag_floors", "max_p95_latency_ms",
              "max_cost_increase_pct", "require_same_suite"}


def check_gate(cmp: dict, gate: dict) -> dict:
    """Apply a gate config. Unknown keys are an error, so a typo cannot silently disable a check."""
    unknown = sorted(set(gate) - _GATE_KEYS)
    if unknown:
        raise GateError(f"unknown gate keys: {', '.join(unknown)} (known: {', '.join(sorted(_GATE_KEYS))})")
    checks = []

    def add(name, ok, message):
        checks.append({"name": name, "passed": bool(ok), "message": message})

    if gate.get("require_same_suite", True):
        add("same_suite", cmp["same_suite"] and not cmp["new_cases"] and not cmp["missing_cases"],
            "suites match" if cmp["same_suite"] else "the suite changed since the baseline was recorded; re-run the baseline")
    pr = cmp["pass_rate"]
    if "min_pass_rate" in gate:
        add("min_pass_rate", pr["cand"] >= gate["min_pass_rate"],
            f"pass rate {pr['cand']:.0%} ({pr['cand_counts'][0]}/{pr['cand_counts'][1]}), required {gate['min_pass_rate']:.0%}")
    if "max_regressions" in gate:
        n = len(cmp["regressions"])
        add("max_regressions", n <= gate["max_regressions"],
            f"{n} regression(s), allowed {gate['max_regressions']}" + (f": {', '.join(cmp['regressions'])}" if n else ""))
    for tag, floor in (gate.get("tag_floors") or {}).items():
        rate = cmp["by_tag"].get(tag, {}).get("cand")
        add(f"tag_floor:{tag}", rate is not None and rate >= floor,
            f"'{tag}' pass rate " + ("not found in the run" if rate is None else f"{rate:.0%}") + f", required {floor:.0%}")
    if "max_p95_latency_ms" in gate:
        v = cmp["latency_p95_ms"]["cand"]
        add("max_p95_latency_ms", v <= gate["max_p95_latency_ms"], f"p95 latency {v:.0f}ms, limit {gate['max_p95_latency_ms']}ms")
    if "max_cost_increase_pct" in gate:
        base, cand = cmp["cost_usd"]["base"], cmp["cost_usd"]["cand"]
        if base > 0:
            pct = (cand - base) / base * 100
            add("max_cost_increase_pct", pct <= gate["max_cost_increase_pct"], f"cost {pct:+.1f}% vs baseline, limit +{gate['max_cost_increase_pct']}%")
        else:
            add("max_cost_increase_pct", True, "baseline cost is zero; check skipped")
    return {"passed": all(c["passed"] for c in checks), "checks": checks}
