# evalgate

Evals as a release gate. Run a suite of checks against an agent, compare the result to the
last known-good baseline, and **fail the build when quality regresses**, including when the
overall score goes up but something that used to pass (a safety check, say) now fails.

The core is plain Python with no third-party dependencies. You bring an agent (any function
that takes a `Case` and returns an `AgentResult`); evalgate does the running, scoring, comparing
and gating.

> **About the example.** The agents in `examples/` are deterministic, rule-based stand-ins, not
> LLMs. That is deliberate: it makes the demo runnable offline with exact, repeatable numbers.
> They call the [ops-mcp](https://github.com/Coder-in-a-shell/ops-mcp) incident tools. The harness is what this project is
> about; the numbers below describe those stand-ins, not any language model.

## See it work

```bash
git clone https://github.com/Coder-in-a-shell/evalgate && cd evalgate
pip install -e ".[dev,examples]"   # the examples extra installs ops-mcp from GitHub
cd examples
evalgate run --suite triage_suite.json --agent triage_agents:triage_v1 --label v1 --out runs/v1.json
evalgate run --suite triage_suite.json --agent triage_agents:triage_v2 --label v2 --out runs/v2.json
evalgate run --suite triage_suite.json --agent triage_agents:triage_v3 --label v3 --out runs/v3.json

evalgate compare --baseline runs/v1.json --candidate runs/v2.json --gate gate.json   # exit 0
evalgate compare --baseline runs/v2.json --candidate runs/v3.json --gate gate.json   # exit 1
```

The three agents are meant to read like three successive pull requests:

| Version | What changed | Pass rate | Gate vs previous |
|---|---|---|---|
| `v1` | First attempt: looks at one metric, blames whichever service is unhealthy, crashes on odd input | 7/17 (41%) | n/a |
| `v2` | Uses the `incident_timeline` tool, names the deploy, cites evidence, handles bad input | 16/17 (94%) | **passes** |
| `v3` | Adds the incident duration, and reads error samples straight from the data store "to save a round trip" | 14/17 (82%) | **fails** |

`v3` is the interesting one. It fixes a case (`incident_duration_reported`) but its shortcut
bypasses the redaction in the tool layer, so personal data and secrets end up in the agent's
answer. Three safety cases that passed before now fail:

```
v2 -> v3
  pass rate 94% -> 82% (-12%)
  regressions: notifications_healthy_and_no_pii, payments_output_has_no_pii, checkout_output_has_no_pii
  fixed: incident_duration_reported

  PASS  suites match
  FAIL  pass rate 82% (14/17), required 90%
  FAIL  3 regression(s), allowed 0
  FAIL  'safety' pass rate 25%, required 100%
  PASS  p95 latency 1ms, limit 250ms

GATE: FAILED
```

A sample HTML report and the Markdown summary (the kind you would post on a pull request) are in
`examples/runs/`.

## The pieces

**Suite** (`triage_suite.json`): a list of cases. Each has an `id`, `tags`, an `input` for the
agent, and `expect`, a set of scorers that must all pass. Suites are validated on load and errors
name the case.

**Agent**: `def agent(case) -> AgentResult`. `AgentResult` carries the `output`, the `tool_calls`
made, any `citations`, and a `cost_usd`. Latency is measured by the runner. An agent that raises
is a failed case, not a crashed run.

**Scorers**: small deterministic checks.

| Scorer | Checks |
|---|---|
| `contains`, `not_contains`, `regex` | text of the output (structured output is searched as JSON) |
| `field_equals` | a dotted path into a structured output, e.g. `root_cause.service` |
| `tool_called`, `tool_not_called`, `max_tool_calls` | which tools the agent used, and how many |
| `citations_include`, `citations_within` | the agent cited what it should, and only what it was given |
| `no_pii` | no emails, phone numbers or credentials in the answer (independent of any redaction in the system under test) |
| `max_latency_ms`, `max_cost_usd` | budgets |

Add your own with `@register_scorer("name")`. There is no built-in LLM judge on purpose; a judge
is a scorer that calls a model, and which model, prompt and tolerance to use should be a visible
decision in your suite, not a library default.

**Repeats**: `--repeats N` runs every case N times and a case passes only if **all** attempts
pass, so a flaky agent is not rewarded for getting lucky once.

**Gate** (`gate.json`):

| Key | Meaning |
|---|---|
| `min_pass_rate` | overall pass rate the candidate must reach |
| `max_regressions` | how many cases that passed in the baseline may fail now |
| `tag_floors` | per-tag minimums, e.g. `{"safety": 1.0}` |
| `max_p95_latency_ms` | p95 latency ceiling |
| `max_cost_increase_pct` | cost may not grow more than this versus the baseline |
| `require_same_suite` | fail if the suite changed since the baseline was recorded (default on) |

Unknown keys are an error, so a typo cannot silently disable a check. `compare` exits `0` when the
gate passes, `1` when it fails, and `2` when the suite or gate config is invalid.

## Decisions worth explaining

**Gate on regressions and floors, not only on the average.** An average can hide a new failure in
the one place you cannot afford one. The v3 example improves a case and still must not ship.

**Small suites are noisy, and the report says so.** Pass rates come with a 95% Wilson interval. On
17 cases, the difference between 16 and 15 passing is not statistically meaningful, which is
exactly why per-case regression checks and tag floors matter more than the headline number.

**Pin the suite to the baseline.** Each run records a fingerprint of its cases. If you edit the
suite and forget to re-record the baseline, the gate fails and tells you why, instead of comparing
two things that are not comparable.

**Deterministic scorers first.** They are cheap, repeatable, and explainable to a customer. An LLM
judge is the right tool for questions like "is this summary faithful?", but it should sit on top
of a layer of checks that do not drift.

## Wiring it into CI

A sketch of a GitHub Actions job (the commands are the ones above; this workflow has not been
run on GitHub yet):

```yaml
- run: pip install -e ".[dev,examples]"
- run: pytest
- run: evalgate run --suite evals/suite.json --agent myagent:run --label pr --out pr.json
- run: evalgate compare --baseline evals/baseline.json --candidate pr.json --gate evals/gate.json --markdown pr.md
- if: always()
  run: cat pr.md >> "$GITHUB_STEP_SUMMARY"
```

Commit `baseline.json`, and re-record it deliberately (in its own commit) when you accept a new
level of quality.

## Tests

```bash
pytest
```

48 tests: suite validation, every scorer, the runner (crashing agents, flaky agents, bad scorer
config), the comparison and gate logic, and the example agents end to end through the CLI. I also
broke five behaviours on purpose (regression check, typo'd gate keys, flaky-case handling, crash
handling, the PII scorer) to confirm the suite fails when it should.

## Limits

- The example agents are rule-based stand-ins. Nothing here has been measured against a live LLM.
- No built-in LLM judge, no dataset management, no dashboard. It is a gate, not a platform.
- A 17-case suite is a demonstration. Real suites come from real failures and need to grow.

MIT licensed.
