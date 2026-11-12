import pytest

from evalgate import AgentResult
from evalgate.cases import parse_suite


def make_suite(cases):
    return parse_suite({"name": "t", "cases": cases})


@pytest.fixture
def suite():
    return make_suite([
        {"id": "a", "tags": ["x"], "input": {"q": 1}, "expect": {"contains": {"all": ["hello"]}}},
        {"id": "b", "tags": ["x", "safety"], "input": {"q": 2}, "expect": {"not_contains": {"values": ["secret"]}}},
        {"id": "c", "tags": [], "input": {"q": 3}, "expect": {"field_equals": {"path": "n", "value": 3}}},
    ])


def good_agent(case):
    return AgentResult(output={"n": 3, "text": "Hello there"})
