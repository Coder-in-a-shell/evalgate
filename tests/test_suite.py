import json

import pytest

from evalgate import SuiteError, load_suite
from evalgate.cases import parse_suite


def case(**over):
    base = {"id": "c1", "input": {}, "expect": {"contains": {"all": ["x"]}}}
    base.update(over)
    return base


@pytest.mark.parametrize(
    "raw, message",
    [
        ([], "non-empty 'cases'"),
        ({"cases": []}, "non-empty 'cases'"),
        ({"cases": ["nope"]}, "must be an object"),
        ({"cases": [case(id="")]}, "needs a string 'id'"),
        ({"cases": [case(), case()]}, "duplicate id"),
        ({"cases": [case(input="x")]}, "'input' must be an object"),
        ({"cases": [case(expect={})]}, "non-empty object"),
        ({"cases": [case(expect={"vibes": {}})]}, "unknown scorer 'vibes'"),
        ({"cases": [case(tags="safety")]}, "'tags' must be a list"),
    ],
)
def test_bad_suites_are_rejected_with_a_pointer_to_the_problem(raw, message):
    with pytest.raises(SuiteError, match=message):
        parse_suite(raw)


def test_error_names_the_case():
    with pytest.raises(SuiteError, match=r"case #2 \(second\)"):
        parse_suite({"cases": [case(), case(id="second", expect={"vibes": {}})]})


def test_digest_changes_when_a_case_changes():
    a = parse_suite({"cases": [case()]})
    b = parse_suite({"cases": [case(expect={"contains": {"all": ["y"]}})]})
    assert a.digest != b.digest and a.digest == parse_suite({"cases": [case()]}).digest


def test_load_reports_invalid_json(tmp_path):
    p = tmp_path / "s.json"
    p.write_text("{nope")
    with pytest.raises(SuiteError, match="not valid JSON"):
        load_suite(p)


def test_load_round_trip(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"name": "demo", "cases": [case()]}))
    assert load_suite(p).name == "demo"
