import pytest

from evalgate import AgentResult
from evalgate.scorers import SCORERS, register_scorer


def score(name, params, **result):
    return SCORERS[name](AgentResult(**result), params, None)


def test_contains_all_and_any():
    assert score("contains", {"all": ["a", "b"]}, output="A and B")[0]
    assert not score("contains", {"all": ["a", "z"]}, output="a b")[0]
    assert score("contains", {"any": ["x", "b"]}, output="b")[0]
    assert not score("contains", {"any": ["x", "y"]}, output="b")[0]
    with pytest.raises(ValueError):
        score("contains", {}, output="b")


def test_contains_looks_inside_structured_output():
    assert score("contains", {"all": ["pool exhausted"]}, output={"summary": "Pool Exhausted!"})[0]


def test_not_contains():
    assert score("not_contains", {"values": ["secret"]}, output="all good")[0]
    ok, detail = score("not_contains", {"values": ["secret"]}, output="the SECRET is out")
    assert not ok and "secret" in detail


def test_field_equals_walks_dotted_paths_and_handles_null():
    out = {"root_cause": {"service": "payments"}, "x": None}
    assert score("field_equals", {"path": "root_cause.service", "value": "payments"}, output=out)[0]
    assert score("field_equals", {"path": "x", "value": None}, output=out)[0]
    ok, detail = score("field_equals", {"path": "root_cause.version", "value": "1"}, output=out)
    assert not ok and "not present" in detail
    assert not score("field_equals", {"path": "a", "value": 1}, output="text")[0]


def test_tool_scorers():
    calls = [{"name": "a"}, {"name": "b"}, {"name": "a"}]
    assert score("tool_called", {"name": "a"}, tool_calls=calls)[0]
    assert score("tool_not_called", {"name": "z"}, tool_calls=calls)[0]
    assert not score("tool_not_called", {"name": "a"}, tool_calls=calls)[0]
    assert score("max_tool_calls", {"n": 3}, tool_calls=calls)[0]
    assert not score("max_tool_calls", {"n": 2}, tool_calls=calls)[0]


def test_citation_scorers():
    r = {"citations": ["d1", "d2"]}
    assert score("citations_include", {"values": ["d1"]}, **r)[0]
    assert not score("citations_include", {"values": ["d3"]}, **r)[0]
    assert score("citations_within", {"allowed": ["d1", "d2", "d3"]}, **r)[0]
    ok, detail = score("citations_within", {"allowed": ["d1"]}, **r)
    assert not ok and "d2" in detail


def test_budget_scorers():
    assert score("max_latency_ms", {"ms": 100}, latency_ms=40)[0]
    assert not score("max_latency_ms", {"ms": 100}, latency_ms=140)[0]
    assert score("max_cost_usd", {"usd": 0.01}, cost_usd=0.002)[0]
    assert not score("max_cost_usd", {"usd": 0.01}, cost_usd=0.5)[0]
    with pytest.raises(ValueError):
        score("max_latency_ms", {"ms": "fast"}, latency_ms=1)
    with pytest.raises(ValueError):
        score("max_cost_usd", {"usd": True}, cost_usd=1)


@pytest.mark.parametrize(
    "text, kind",
    [
        ("mail jane.doe@example.com", "email"),
        ("call +91 98765 43210", "phone"),
        ("Authorization: Bearer abcdefgh12345", "secret"),
        ("token eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.abc123def456", "secret"),
        ("key " + "AKIA" + "ABCDEFGHIJKLMNOP", "secret"),
    ],
)
def test_no_pii_catches_the_usual_suspects(text, kind):
    ok, detail = score("no_pii", {}, output=text)
    assert not ok and kind in detail


def test_no_pii_ignores_versions_and_counts():
    assert score("no_pii", {}, output="payments v2.14.0 deployed 4 minutes before errors (x71)")[0]


def test_custom_scorers_can_be_registered():
    @register_scorer("shorter_than")
    def _shorter(result, params, case):
        return len(str(result.output)) < params["n"], "length"

    assert score("shorter_than", {"n": 5}, output="abc")[0]
    del SCORERS["shorter_than"]
