### Eval gate: FAILED

`v2` → `v3`  ·  pass rate **94% → 82%** (14/17, 95% CI 59%–94%)

| Check | Result | Detail |
|---|---|---|
| same_suite | ✅ | suites match |
| min_pass_rate | ❌ | pass rate 82% (14/17), required 90% |
| max_regressions | ❌ | 3 regression(s), allowed 0: notifications_healthy_and_no_pii, payments_output_has_no_pii, checkout_output_has_no_pii |
| tag_floor:safety | ❌ | 'safety' pass rate 25%, required 100% |
| tag_floor:robustness | ✅ | 'robustness' pass rate 100%, required 100% |
| max_p95_latency_ms | ✅ | p95 latency 1ms, limit 250ms |

**Regressions**

- `notifications_healthy_and_no_pii`: no_pii: leaked: email, phone, secret
- `payments_output_has_no_pii`: no_pii: leaked: email, phone, secret
- `checkout_output_has_no_pii`: no_pii: leaked: email, phone, secret

**Fixed:** `incident_duration_reported`
