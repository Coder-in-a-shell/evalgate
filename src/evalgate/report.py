"""Turn runs and comparisons into text, Markdown (for a PR comment) and a standalone HTML page."""

from __future__ import annotations

import html
import json


def _pct(x: float) -> str:
    return f"{x:.0%}"


def _failed_checks(case: dict) -> list[str]:
    out = []
    for a in case["attempts"]:
        for c in a["checks"]:
            if not c["passed"]:
                out.append(f"{c['scorer']}: {c['detail']}")
    return sorted(set(out))


# ---- terminal ------------------------------------------------------------------------

def terminal_run(run: dict) -> str:
    s, m = run["summary"], run["meta"]
    lines = [f"{m['label']}  ({m['agent'] or 'agent'}, suite '{m['suite']}', x{m['repeats']})",
             f"  passed {s['passed']}/{s['total']} = {_pct(s['pass_rate'])}   "
             f"p95 latency {s['latency_ms']['p95']:.0f}ms   mean tool calls {s['mean_tool_calls']}"]
    for t, v in s["by_tag"].items():
        lines.append(f"  [{t}] {v['passed']}/{v['total']}")
    for c in run["cases"]:
        if not c["passed"]:
            lines.append(f"  FAIL {c['id']}")
            lines += [f"       - {d}" for d in _failed_checks(c)]
    return "\n".join(lines)


def terminal_compare(cmp: dict, gate: dict) -> str:
    pr = cmp["pass_rate"]
    lines = [f"{cmp['base_label']} -> {cmp['cand_label']}",
             f"  pass rate {_pct(pr['base'])} -> {_pct(pr['cand'])} ({pr['delta']:+.0%})"]
    if cmp["regressions"]:
        lines.append("  regressions: " + ", ".join(cmp["regressions"]))
    if cmp["fixes"]:
        lines.append("  fixed: " + ", ".join(cmp["fixes"]))
    lines.append("")
    for c in gate["checks"]:
        lines.append(f"  {'PASS' if c['passed'] else 'FAIL'}  {c['message']}")
    lines.append("")
    lines.append("GATE: " + ("PASSED" if gate["passed"] else "FAILED"))
    return "\n".join(lines)


# ---- markdown ------------------------------------------------------------------------

def markdown_compare(cmp: dict, gate: dict, cand: dict) -> str:
    pr = cmp["pass_rate"]
    out = [f"### Eval gate: {'passed' if gate['passed'] else 'FAILED'}", "",
           f"`{cmp['base_label']}` → `{cmp['cand_label']}`  ·  pass rate **{_pct(pr['base'])} → {_pct(pr['cand'])}** "
           f"({pr['cand_counts'][0]}/{pr['cand_counts'][1]}, 95% CI {_pct(pr['cand_ci'][0])}–{_pct(pr['cand_ci'][1])})", "",
           "| Check | Result | Detail |", "|---|---|---|"]
    out += [f"| {c['name']} | {'✅' if c['passed'] else '❌'} | {c['message']} |" for c in gate["checks"]]
    if cmp["regressions"]:
        out += ["", "**Regressions**", ""]
        by_id = {c["id"]: c for c in cand["cases"]}
        for i in cmp["regressions"]:
            out.append(f"- `{i}`: " + "; ".join(_failed_checks(by_id[i])))
    if cmp["fixes"]:
        out += ["", "**Fixed:** " + ", ".join(f"`{i}`" for i in cmp["fixes"])]
    return "\n".join(out) + "\n"


# ---- html ----------------------------------------------------------------------------

_CSS = """
:root{--bg:#f5f6f8;--card:#fff;--ink:#12141a;--muted:#5d6472;--line:#dfe2e8;--ok:#0a7a4b;--okbg:#dcf5e8;--bad:#b3261e;--badbg:#fde3e1}
@media(prefers-color-scheme:dark){:root{--bg:#0e1014;--card:#171a20;--ink:#eef0f3;--muted:#a0a7b4;--line:#2a2e37;--ok:#62e2ab;--okbg:#0f2b20;--bad:#ff8f87;--badbg:#3a1614}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 system-ui,-apple-system,Segoe UI,sans-serif;padding:32px 16px}
main{max-width:920px;margin:0 auto}h1{font-size:1.6rem;margin:0 0 4px}h2{font-size:1.1rem;margin:28px 0 10px}
.muted{color:var(--muted)}.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px 18px;margin:12px 0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px}.big{font-size:1.9rem;font-weight:700;letter-spacing:-.03em;line-height:1.1}
.pill{display:inline-block;padding:2px 10px;border-radius:99px;font-size:.8rem;font-weight:600}.ok{background:var(--okbg);color:var(--ok)}.bad{background:var(--badbg);color:var(--bad)}
table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:8px 6px;border-top:1px solid var(--line);vertical-align:top}th{color:var(--muted);font-weight:600;font-size:.85rem;border-top:0}
code{font:13px ui-monospace,Menlo,monospace}
"""


def html_report(run: dict, cmp: dict | None = None, gate: dict | None = None) -> str:
    e = html.escape
    s, m = run["summary"], run["meta"]
    parts = [f"<h1>{e(m['label'])}</h1><p class='muted'>{e(m['agent'] or 'agent')} · suite {e(m['suite'])} · "
             f"{e(m['created'])} · each case run {m['repeats']}×</p>"]
    if gate:
        parts.append(f"<div class='card'><span class='pill {'ok' if gate['passed'] else 'bad'}'>gate {'passed' if gate['passed'] else 'failed'}</span>"
                     f" <span class='muted'>{e(cmp['base_label'])} → {e(cmp['cand_label'])}</span><table><tbody>"
                     + "".join(f"<tr><td><span class='pill {'ok' if c['passed'] else 'bad'}'>{'pass' if c['passed'] else 'fail'}</span></td><td>{e(c['message'])}</td></tr>" for c in gate["checks"])
                     + "</tbody></table></div>")
    parts.append("<div class='grid'>"
                 f"<div class='card'><div class='big'>{_pct(s['pass_rate'])}</div><div class='muted'>{s['passed']} of {s['total']} cases pass</div></div>"
                 f"<div class='card'><div class='big'>{s['latency_ms']['p95']:.0f} ms</div><div class='muted'>p95 latency</div></div>"
                 f"<div class='card'><div class='big'>{s['mean_tool_calls']}</div><div class='muted'>mean tool calls</div></div>"
                 f"<div class='card'><div class='big'>${s['total_cost_usd']:.4f}</div><div class='muted'>total cost</div></div></div>")
    if s["by_tag"]:
        parts.append("<h2>By tag</h2><div class='card'><table><thead><tr><th>Tag</th><th>Passed</th><th>Rate</th></tr></thead><tbody>"
                     + "".join(f"<tr><td>{e(t)}</td><td>{v['passed']}/{v['total']}</td><td>{_pct(v['pass_rate'])}</td></tr>" for t, v in s["by_tag"].items())
                     + "</tbody></table></div>")
    ordered = sorted(run["cases"], key=lambda c: c["passed"])  # failures first
    parts.append("<h2>Cases</h2><div class='card'><table><thead><tr><th></th><th>Case</th><th>Tags</th><th>Why it failed</th></tr></thead><tbody>")
    for c in ordered:
        why = "<br>".join(e(d) for d in _failed_checks(c)) or "<span class='muted'>all checks passed</span>"
        parts.append(f"<tr><td><span class='pill {'ok' if c['passed'] else 'bad'}'>{'pass' if c['passed'] else 'fail'}</span></td>"
                     f"<td><code>{e(c['id'])}</code></td><td class='muted'>{e(', '.join(c['tags']))}</td><td>{why}</td></tr>")
    parts.append("</tbody></table></div>")
    return ("<!doctype html><html lang='en'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{e(m['label'])} · evalgate</title><style>{_CSS}</style><main>{''.join(parts)}</main></html>")


def dumps(obj) -> str:
    return json.dumps(obj, indent=2, sort_keys=False)
