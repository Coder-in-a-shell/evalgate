"""Three versions of an incident-triage agent, to show the gate working.

These are deterministic, rule-based stand-ins, not LLM agents. That is on purpose: it makes the
example runnable offline with exact, repeatable numbers. They talk to the ops-mcp service
(install it with `pip install -e ../ops-mcp`), and they are written to look like the sequence
of changes a real agent goes through:

* triage_v1  the first attempt: looks at one metric, blames whatever service is unhealthy, and
             crashes on input it did not expect.
* triage_v2  uses the incident_timeline tool, names the deploy, cites its evidence, and handles
             bad input.
* triage_v3  a "small improvement" that adds the incident duration, and, to save a round trip,
             reads error samples straight from the data store instead of through the tool. That
             bypasses the redaction in the tool layer: the kind of regression a release gate
             exists to catch.

To test a real agent, write a function with the same shape: take a Case, return an AgentResult.
"""

from __future__ import annotations

from evalgate import AgentResult, Case
from ops_mcp.auth import Principal
from ops_mcp.data import Dataset
from ops_mcp.guard import Guard, InvalidInput, RateLimit
from ops_mcp.service import OpsService

_DATASET = Dataset.build()
_TRIAGE = Principal(
    "triage-agent", frozenset({"read:catalog", "read:logs", "read:metrics", "read:deploys"}), "triage"
)


class _Recording:
    """Wraps the service so every tool call the agent makes is recorded for the scorers."""

    def __init__(self):
        self.svc = OpsService(_DATASET, Guard(rate_limit=RateLimit(capacity=1000)))
        self.calls: list[dict] = []

    def __getattr__(self, name):
        method = getattr(self.svc, name)

        def call(*args, **kwargs):
            self.calls.append({"name": name, "args": {"args": list(args), **kwargs}})
            return method(_TRIAGE, *args, **kwargs)

        return call


def _finish(output, rec: _Recording, citations=None) -> AgentResult:
    return AgentResult(output=output, tool_calls=rec.calls, citations=citations or [])


def triage_v1(case: Case) -> AgentResult:
    rec = _Recording()
    service = case.input["service"]
    metric = rec.get_metric(service, "error_rate_pct")  # raises on an unknown service: no handling yet
    if metric["anomaly"]:
        out = {"status": "incident", "root_cause": {"service": service, "version": None},
               "summary": f"Error rate is abnormal on {service}."}
    else:
        out = {"status": "healthy", "root_cause": None, "summary": f"{service} looks healthy."}
    return _finish(out, rec)


def _triage_with_timeline(case: Case, *, report_duration: bool, raw_samples: bool) -> AgentResult:
    rec = _Recording()
    service = case.input["service"]
    try:
        t = rec.incident_timeline(service)
    except InvalidInput:
        # Deliberately does not echo the input back: it may be an attempt to inject text.
        return _finish({"status": "unknown_service", "root_cause": None,
                        "summary": "That service is not in the catalog."}, rec)

    anomalies = [e for e in t["events"] if e["type"] == "anomaly"]
    sample = ""
    if raw_samples:
        # The "optimisation": read recent error lines straight from the data store.
        lines = [l.message for l in _DATASET.logs if l.service in t["scope"] and l.level in ("ERROR", "WARN") and l.minute < 120]
        sample = " Recent lines: " + " | ".join(sorted(set(lines))[:6]) if lines else ""

    if not t["suspects"] and not anomalies:
        return _finish({"status": "healthy", "root_cause": None,
                        "summary": f"No anomalies for {service} or its dependencies in the last 3 hours." + sample}, rec)

    s = t["suspects"][0] if t["suspects"] else None
    parts = []
    citations = []
    if s:
        parts.append(f"{s['service']} {s['version']} was deployed {s['minutes_before_first_anomaly']} minutes before errors began.")
        citations.append(f"deploy:{s['service']}:{s['version']}")
        citations += [f"anomaly:{a.replace(' ', ':')}" for a in s["anomalies"]]
    if t["top_errors"]:
        parts.append("Top errors: " + "; ".join(f"{e['service']}: {e['message']} (x{e['count']})" for e in t["top_errors"][:2]) + ".")
    if report_duration and anomalies:
        parts.append(f"The incident began about {max(a['minutes_before_now'] for a in anomalies)} minutes ago.")
    out = {"status": "incident",
           "root_cause": {"service": s["service"], "version": s["version"]} if s else None,
           "summary": " ".join(parts) + sample}
    return _finish(out, rec, citations)


def triage_v2(case: Case) -> AgentResult:
    return _triage_with_timeline(case, report_duration=False, raw_samples=False)


def triage_v3(case: Case) -> AgentResult:
    return _triage_with_timeline(case, report_duration=True, raw_samples=True)
