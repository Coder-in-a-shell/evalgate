"""Suites and cases: what you ask the agent, and what a good answer must satisfy."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from .scorers import SCORERS


class SuiteError(ValueError):
    """The suite file is malformed. The message says where."""


@dataclass(frozen=True)
class Case:
    id: str
    input: dict
    expect: dict  # scorer name -> params
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class Suite:
    name: str
    cases: tuple[Case, ...]
    digest: str = field(default="", compare=False)  # fingerprint of the cases, to spot a changed suite


def parse_suite(raw: dict) -> Suite:
    if not isinstance(raw, dict) or not isinstance(raw.get("cases"), list) or not raw["cases"]:
        raise SuiteError("suite must be an object with a non-empty 'cases' list")
    seen, cases = set(), []
    for i, c in enumerate(raw["cases"]):
        where = f"case #{i + 1}" + (f" ({c.get('id')})" if isinstance(c, dict) and c.get("id") else "")
        if not isinstance(c, dict):
            raise SuiteError(f"{where}: must be an object")
        cid = c.get("id")
        if not isinstance(cid, str) or not cid:
            raise SuiteError(f"{where}: needs a string 'id'")
        if cid in seen:
            raise SuiteError(f"{where}: duplicate id")
        seen.add(cid)
        if not isinstance(c.get("input"), dict):
            raise SuiteError(f"{where}: 'input' must be an object")
        expect = c.get("expect")
        if not isinstance(expect, dict) or not expect:
            raise SuiteError(f"{where}: 'expect' must be a non-empty object of scorer names")
        for name in expect:
            if name not in SCORERS:
                raise SuiteError(f"{where}: unknown scorer '{name}' (known: {', '.join(sorted(SCORERS))})")
        tags = c.get("tags", [])
        if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
            raise SuiteError(f"{where}: 'tags' must be a list of strings")
        cases.append(Case(cid, c["input"], expect, tuple(tags)))
    digest = hashlib.sha256(json.dumps(raw["cases"], sort_keys=True).encode()).hexdigest()[:16]
    return Suite(str(raw.get("name", "suite")), tuple(cases), digest)


def load_suite(path: str | Path) -> Suite:
    try:
        raw = json.loads(Path(path).read_text())
    except json.JSONDecodeError as exc:
        raise SuiteError(f"{path}: not valid JSON ({exc})") from None
    return parse_suite(raw)
