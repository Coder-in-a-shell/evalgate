"""Command line: run a suite, compare to a baseline, gate a build."""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

from . import report
from .cases import SuiteError, load_suite
from .compare import GateError, check_gate, compare
from .runner import run_suite


def _load_agent(spec: str, extra_paths: list[str]):
    if ":" not in spec:
        raise SystemExit("--agent must look like module:function")
    mod, _, attr = spec.partition(":")
    for entry in [*extra_paths, str(Path.cwd())]:
        sys.path.insert(0, entry)
    try:
        return getattr(importlib.import_module(mod), attr)
    except (ImportError, AttributeError) as exc:
        raise SystemExit(f"cannot load agent {spec}: {exc}") from None


def _read(path: str) -> dict:
    try:
        return json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"cannot read {path}: {exc}") from None


def _cmd_run(args) -> int:
    try:
        suite = load_suite(args.suite)
    except SuiteError as exc:
        print(f"suite error: {exc}", file=sys.stderr)
        return 2
    run = run_suite(suite, _load_agent(args.agent, args.path), label=args.label or Path(args.out).stem,
                    agent_name=args.agent, repeats=args.repeats, workers=args.workers)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(report.dumps(run))
    print(report.terminal_run(run))
    if args.html:
        Path(args.html).write_text(report.html_report(run))
    return 0


def _cmd_compare(args) -> int:
    base, cand, gate_cfg = _read(args.baseline), _read(args.candidate), _read(args.gate)
    try:
        cmp = compare(base, cand)
        gate = check_gate(cmp, gate_cfg)
    except GateError as exc:
        print(f"gate config error: {exc}", file=sys.stderr)
        return 2
    print(report.terminal_compare(cmp, gate))
    if args.markdown:
        Path(args.markdown).write_text(report.markdown_compare(cmp, gate, cand))
    if args.html:
        Path(args.html).write_text(report.html_report(cand, cmp, gate))
    return 0 if gate["passed"] else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="evalgate", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run a suite against an agent")
    r.add_argument("--suite", required=True)
    r.add_argument("--agent", required=True, help="module:function returning an AgentResult for a Case")
    r.add_argument("--out", required=True, help="where to write the run JSON")
    r.add_argument("--path", action="append", default=[], help="extra directory to import the agent from (repeatable)")
    r.add_argument("--label", help="a name for this run (defaults to the output file name)")
    r.add_argument("--repeats", type=int, default=1, help="run each case N times; all must pass")
    r.add_argument("--workers", type=int, default=4)
    r.add_argument("--html", help="also write a standalone HTML report")
    r.set_defaults(func=_cmd_run)

    c = sub.add_parser("compare", help="compare a candidate run to a baseline and apply the gate (exit 1 if it fails)")
    c.add_argument("--baseline", required=True)
    c.add_argument("--candidate", required=True)
    c.add_argument("--gate", required=True)
    c.add_argument("--markdown", help="write a Markdown summary, e.g. for a PR comment")
    c.add_argument("--html", help="write a standalone HTML report")
    c.set_defaults(func=_cmd_compare)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
