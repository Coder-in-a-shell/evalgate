import pytest

from evalgate import AgentResult, GateError, check_gate, compare, run_suite
from evalgate.compare import wilson

from conftest import good_agent, make_suite

CASES = [
    {"id": "a", "tags": ["x"], "input": {}, "expect": {"contains": {"all": ["ok"]}}},
    {"id": "b", "tags": ["x", "safety"], "input": {}, "expect": {"contains": {"all": ["ok"]}}},
    {"id": "c", "tags": [], "input": {}, "expect": {"contains": {"all": ["ok"]}}},
    {"id": "d", "tags": [], "input": {}, "expect": {"contains": {"all": ["ok"]}}},
]


def run_with(failing=(), label="r", cases=CASES, cost=0.0):
    suite = make_suite(cases)
    return run_suite(suite, lambda c: AgentResult(output="bad" if c.id in failing else "ok", cost_usd=cost), label=label)


def test_wilson_interval_is_wide_for_small_samples():
    lo, hi = wilson(15, 15)
    assert hi == 1.0 and lo < 0.85  # a perfect score on 15 cases still allows a real rate of ~80%
    assert wilson(0, 0) == (0.0, 0.0)
    lo2, hi2 = wilson(750, 1000)
    assert hi2 - lo2 < 0.06  # a bigger suite is much tighter


def test_compare_classifies_each_case():
    base = run_with(failing={"a", "b"}, label="base")
    cand = run_with(failing={"b", "c"}, label="cand")
    cmp = compare(base, cand)
    assert cmp["fixes"] == ["a"] and cmp["regressions"] == ["c"] and cmp["still_failing"] == ["b"]
    assert cmp["pass_rate"]["base"] == 0.5 and cmp["pass_rate"]["cand"] == 0.5
    assert cmp["by_tag"]["safety"] == {"base": 0.0, "cand": 0.0}


def test_gate_passes_a_clean_improvement():
    cmp = compare(run_with(failing={"a"}), run_with())
    gate = check_gate(cmp, {"min_pass_rate": 1.0, "max_regressions": 0, "tag_floors": {"safety": 1.0}})
    assert gate["passed"] and all(c["passed"] for c in gate["checks"])


def test_gate_blocks_a_regression_even_when_the_pass_rate_improves():
    base = run_with(failing={"a", "c", "d"})  # 25%
    cand = run_with(failing={"b"})  # 75%: better overall, but b is a safety case that used to pass
    cmp = compare(base, cand)
    assert cmp["pass_rate"]["cand"] > cmp["pass_rate"]["base"]
    gate = check_gate(cmp, {"max_regressions": 0})
    assert not gate["passed"] and "b" in gate["checks"][-1]["message"]


def test_tag_floor_blocks_even_when_overall_rate_is_fine():
    cmp = compare(run_with(), run_with(failing={"b"}))
    gate = check_gate(cmp, {"min_pass_rate": 0.7, "tag_floors": {"safety": 1.0}})
    by_name = {c["name"]: c for c in gate["checks"]}
    assert by_name["min_pass_rate"]["passed"] and not by_name["tag_floor:safety"]["passed"] and not gate["passed"]


def test_missing_tag_fails_the_floor_instead_of_passing_silently():
    gate = check_gate(compare(run_with(), run_with()), {"tag_floors": {"nonexistent": 1.0}})
    assert not gate["passed"] and "not found" in gate["checks"][-1]["message"]


def test_a_changed_suite_is_detected():
    base = run_with()
    cand = run_with(cases=CASES[:3])
    cmp = compare(base, cand)
    assert not cmp["same_suite"] and cmp["missing_cases"] == ["d"]
    gate = check_gate(cmp, {})
    assert not gate["passed"] and "re-run the baseline" in gate["checks"][0]["message"]
    assert check_gate(cmp, {"require_same_suite": False})["passed"]


def test_unknown_gate_keys_are_an_error_so_typos_cannot_disable_checks():
    with pytest.raises(GateError, match="min_pass_rat"):
        check_gate(compare(run_with(), run_with()), {"min_pass_rat": 0.9})


def test_latency_and_cost_limits():
    cmp = compare(run_with(cost=1.0), run_with(cost=1.5))
    assert not check_gate(cmp, {"max_cost_increase_pct": 20})["passed"]
    assert check_gate(cmp, {"max_cost_increase_pct": 60})["passed"]
    assert check_gate(compare(run_with(), run_with(cost=5.0)), {"max_cost_increase_pct": 10})["passed"]  # baseline cost 0: skipped
    assert check_gate(cmp, {"max_p95_latency_ms": 10_000})["passed"]
    assert not check_gate(cmp, {"max_p95_latency_ms": -1})["passed"]
