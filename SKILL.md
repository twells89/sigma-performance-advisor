---
name: sigma-performance-cost-advisor
description: >-
  Keep Sigma fast while lowering Snowflake cost. Attribute compute to Sigma objects,
  measure whether materializations serve observed reads, and recommend keep, retune,
  investigate, remove, add, or optimize-query actions against latency and freshness
  constraints. Read-only analysis; remediation is explicit and opt-in.
user-invocable: true
---

# Sigma Performance & Cost Advisor

> **STATUS: validated live** against Sigma and Snowflake: full cost coverage, schedule
> and lineage reads, `ACCESS_HISTORY` utilization matching, on-demand refresh polling,
> and capped element exports. Analysis is read-only; mutations require explicit commands.

**Read first:** `refs/performance-cost-playbook.md` (decision evidence and safeguards),
`PRIVACY.md` (read-only analysis posture).

## The key idea
Sigma stamps **every** warehouse query's `QUERY_TAG` with `Sigma Σ {json}` containing
`sourceUrl` (org + workbook/data-model + element), `email`, and `kind`. Snowflake's
`QUERY_ATTRIBUTION_HISTORY` gives real credits. `ACCESS_HISTORY` reveals whether workbook
queries read objects built by materialization jobs. Evaluate refresh TCO and observed
performance together; never infer that deletion is safe from refresh cost alone.

## Inputs / access
- **Snowflake** via the `snow` CLI (a connection with read access to
  `SNOWFLAKE.ACCOUNT_USAGE`; `ACCESS_HISTORY` requires the applicable Enterprise
  privileges). SSO (`externalbrowser`) or key-pair both work.
- **Sigma REST** (`SIGMA_BASE_URL` plus a token or client credentials) — for read-only
  schedule/control/lineage enrichment and explicit remediation actions.

## Intake — ask before the first run
Persist answers in `advisor-config.json`; do not use blind defaults for a customer.

| Ask | Maps to | Why |
|---|---|---|
| **Latency target?** p95 seconds + acceptable slowdown | recommendation constraint | Prevents cost cuts that make dashboards unusably slow |
| **How fresh?** real-time / ≤1h / ≤1 day / varies | cadence and eligibility | Real-time disables add-materialization advice |
| **Primary goal?** cost / latency / performance per dollar | ranking | Changes which opportunities lead |
| **Minimum savings?** dollars/month | removal threshold | Avoids operational work for immaterial savings |

**$ per credit is auto-detected** — `analyze.py` reads the account's effective rate from
`SNOWFLAKE.ORGANIZATION_USAGE.usage_in_currency_daily` (then `rate_sheet_daily`). Only ask
the customer if detection returns nothing (no `ORGANIZATION_USAGE` access / internal
account); then pass `--credit-price`. The report states whether the rate was
*auto-detected*, *provided*, or *assumed* ($3 default).

Suggested threshold presets:
- **conservative:** `--mat-min-runs 20 --mat-min-avg-sec 5 --mat-min-credits 2`
- **balanced (default):** `--mat-min-runs 12 --mat-min-avg-sec 3 --mat-min-credits 0.5`
- **aggressive:** `--mat-min-runs 8 --mat-min-avg-sec 1.5 --mat-min-credits 0.2`

Persist the answers in `advisor-config.json` (see `advisor-config.example.json`) and pass
`--config advisor-config.json` so re-runs are consistent.

## Phases
1. **Analyze** — full Sigma cost coverage, source-level workload, materialization
   utilization, and warehouse context → schema-v2 `inventory.json` + `REPORT.md`.
2. **Enrich** — `scripts/enrich.py` resolves schedules, controls, and lineage. Because
   current APIs do not expose control target bindings, any control-bearing workbook is
   `review required`.
3. **Report** — render keep/retune/investigate/remove/add/query-optimization decisions.
4. **Remediate (opt-in)** — use `materialize.py --dry-run` first. Removal requires a
   measured no-materialization baseline, owner approval, and rollback details.

## Scripts
| Script | Purpose |
|---|---|
| `scripts/analyze.py` | Snowflake cost/performance evidence → v2 inventory + report |
| `scripts/cost_model.py` | pure recommendation and savings logic |
| `scripts/enrich.py` | read-only Sigma API schedule/control/lineage pass |
| `scripts/materialize.py` | explicit schedule CRUD / refresh with `--dry-run` |
| `scripts/render-html.py` | `inventory.json` → customer-facing `report.html` |

Key flags (`analyze.py`): `--conn`, `--days`, `--org`, `--latency-slo-sec`,
`--freshness`, `--acceptable-slowdown-sec`, `--goal`, `--config`, and `--out`.

## Cortex Code note
The attribution SQL is portable — it runs equally well from Cortex Code / a Snowflake
notebook if a team prefers to keep the analysis in-warehouse (no creds to manage, data
never leaves the account). The Sigma-side mapping and materialization actions need the
Sigma REST API, so the end-to-end loop lives here.

## Non-negotiable safeguards
- Report all Sigma-tagged cost and the attributable percentage; never label a limited
  candidate list as total spend.
- Keep unmatched materialization reads as an explicit unknown bucket.
- Never recommend removal without a measured counterfactual inside the latency allowance.
- Treat warehouse idle as an upper bound, not as Sigma-attributable savings.
- Do not automatically act on controls, semantic changes, warehouse sizing, or deletion.
