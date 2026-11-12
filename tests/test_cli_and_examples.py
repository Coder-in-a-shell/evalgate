import json
from pathlib import Path

import pytest

from evalgate.cli import main

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def run_cli(tmp_path, agent, label):
    out = tmp_path / f"{label}.json"
    code = main(["run", "--suite", str(EXAMPLES / "triage_suite.json"), "--agent", f"triage_agents:{agent}",
                 "--path", str(EXAMPLES), "--label", label, "--out", str(out)])
    assert code == 0
    return out


def gate(tmp_path, base, cand):
    return main(["compare", "--baseline", str(base), "--candidate", str(cand),
                 "--gate", str(EXAMPLES / "gate.json"), "--markdown", str(tmp_path / "pr.md"),
                 "--html", str(tmp_path / "r.html")])


@pytest.fixture(scope="module")
def runs(tmp_path_factory):
    pytest.importorskip("ops_mcp")
    tmp = tmp_path_factory.mktemp("runs")
    return tmp, {v: run_cli(tmp, f"triage_{v}", v) for v in ("v1", "v2", "v3")}


def test_example_agents_score_as_documented(runs):
    _, r = runs
    got = {v: json.loads(p.read_text())["summary"] for v, p in r.items()}
    assert (got["v1"]["passed"], got["v2"]["passed"], got["v3"]["passed"]) == (7, 16, 14)
    assert got["v2"]["by_tag"]["safety"]["pass_rate"] == 1.0
    assert got["v3"]["by_tag"]["safety"]["passed"] == 1  # the redaction bypass


def test_gate_passes_the_improvement_and_blocks_the_regression(runs):
    tmp, r = runs
    assert gate(tmp, r["v1"], r["v2"]) == 0
    assert gate(tmp, r["v2"], r["v3"]) == 1
    assert "Eval gate: FAILED" in (tmp / "pr.md").read_text()
    assert "no_pii: leaked" in (tmp / "pr.md").read_text()


def test_html_report_is_standalone_and_escapes_content(runs):
    tmp, r = runs
    gate(tmp, r["v2"], r["v3"])
    page = (tmp / "r.html").read_text()
    assert page.startswith("<!doctype html>") and "<script" not in page and "http" not in page.split("</style>")[1].split("<main>")[0]


def test_bad_gate_config_exits_2(runs, tmp_path):
    _, r = runs
    bad = tmp_path / "g.json"
    bad.write_text('{"min_pass_rat": 1}')
    assert main(["compare", "--baseline", str(r["v1"]), "--candidate", str(r["v2"]), "--gate", str(bad)]) == 2


def test_bad_suite_exits_2(tmp_path):
    s = tmp_path / "s.json"
    s.write_text('{"cases": [{"id": "a", "input": {}, "expect": {"vibes": {}}}]}')
    assert main(["run", "--suite", str(s), "--agent", "triage_agents:triage_v1", "--path", str(EXAMPLES), "--out", str(tmp_path / "o.json")]) == 2
