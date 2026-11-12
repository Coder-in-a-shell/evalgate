import threading

from evalgate import AgentResult, run_suite

from conftest import good_agent, make_suite


def test_runs_every_case_and_scores_it(suite):
    run = run_suite(suite, good_agent, label="v1")
    assert [c["id"] for c in run["cases"]] == ["a", "b", "c"]
    assert run["summary"]["passed"] == 3 and run["summary"]["pass_rate"] == 1.0
    assert run["meta"]["suite_digest"] == suite.digest


def test_a_crashing_agent_fails_the_case_but_not_the_run(suite):
    def agent(case):
        if case.id == "b":
            raise RuntimeError("boom")
        return good_agent(case)

    run = run_suite(suite, agent, label="x")
    assert [c["passed"] for c in run["cases"]] == [True, False, True]
    failing = run["cases"][1]["attempts"][0]
    assert "RuntimeError: boom" in failing["error"]
    assert "agent error" in failing["checks"][0]["detail"]


def test_wrong_return_type_is_reported_not_swallowed(suite):
    run = run_suite(suite, lambda case: "just a string", label="x")
    assert not run["cases"][0]["passed"] and "expected AgentResult" in run["cases"][0]["attempts"][0]["error"]


def test_a_misconfigured_scorer_is_a_loud_failure(suite):
    s = make_suite([{"id": "z", "input": {}, "expect": {"max_latency_ms": {"ms": "soon"}}}])
    run = run_suite(s, good_agent, label="x")
    assert "scorer error" in run["cases"][0]["attempts"][0]["checks"][0]["detail"]


def test_repeats_require_every_attempt_to_pass():
    s = make_suite([{"id": "flaky", "input": {}, "expect": {"contains": {"all": ["ok"]}}}])
    lock, count = threading.Lock(), {"n": 0}

    def flaky(case):
        with lock:
            count["n"] += 1
            n = count["n"]
        return AgentResult(output="ok" if n % 2 else "nope")

    run = run_suite(s, flaky, label="x", repeats=4, workers=1)
    case = run["cases"][0]
    assert case["pass_count"] == 2 and case["passed"] is False and len(case["attempts"]) == 4


def test_latency_tool_calls_and_cost_are_recorded():
    s = make_suite([{"id": "a", "tags": ["t"], "input": {}, "expect": {"contains": {"all": ["x"]}}}])
    run = run_suite(s, lambda c: AgentResult(output="x", tool_calls=[{"name": "a"}, {"name": "b"}], cost_usd=0.25), label="x")
    sm = run["summary"]
    assert sm["mean_tool_calls"] == 2 and sm["total_cost_usd"] == 0.25
    assert sm["by_tag"]["t"] == {"total": 1, "passed": 1, "pass_rate": 1.0}
    assert run["cases"][0]["attempts"][0]["latency_ms"] >= 0


def test_repeats_must_be_positive(suite):
    import pytest
    with pytest.raises(ValueError):
        run_suite(suite, good_agent, label="x", repeats=0)
