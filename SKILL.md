---
name: sigma-materialization-advisor
description: >-
  Find the Sigma workbooks / data models / elements driving the most Snowflake
  compute and recommend how to cut it — by improving the query in-place or by
  materializing via the Sigma API. Joins Snowflake ACCOUNT_USAGE credit attribution
  back to the Sigma object that issued each query (via the Sigma QUERY_TAG), ranks
  materialization candidates, and can trigger/monitor materializations through the
  REST API. Use to scope or run a Snowflake-cost / materialization project for a
  Sigma org. Read-only analysis; remediation is opt-in.
user-invocable: true
---

# Sigma Materialization Advisor

> **STATUS: working, validated live** end-to-end against a production Sigma org on
> Snowflake (cost attribution + materialization trigger). Analysis is read-only; the
> materialization *run* is an explicit opt-in action.

**Read first:** `refs/materialization-playbook.md` (which technique for which signal),
`PRIVACY.md` (read-only analysis posture).

## The key idea
Sigma stamps **every** warehouse query's `QUERY_TAG` with `Sigma Σ {json}` containing
`sourceUrl` (org + workbook/data-model + element), `email`, and `kind`. Snowflake's
`QUERY_ATTRIBUTION_HISTORY` gives **real compute credits per `query_id`**. Join the two
and you can attribute Snowflake cost to the exact Sigma object that caused it, then rank
what to materialize or fix.

## Inputs / access
- **Snowflake** via the `snow` CLI (a connection with read access to
  `SNOWFLAKE.ACCOUNT_USAGE`). SSO (`externalbrowser`) or key-pair both work.
- **Sigma REST** (`SIGMA_API_TOKEN` + `SIGMA_BASE_URL`) — only for the remediation
  actions (resolve object IDs, list/trigger materializations).

## Intake — ASK THESE before the first run
The right thresholds depend on the customer's economics and SLAs, so **ask these
questions first** (use the AskUserQuestion tool), then pass the answers as flags or a
`--config` JSON. Don't run with blind defaults on a real customer.

| Ask | Maps to | Why |
|---|---|---|
| **How fresh must dashboards be?** real-time / ≤1h / ≤1 day / varies | cadence advice; if real-time, materialization is mostly off the table | Materialized data is by definition slightly stale |
| **Primary goal?** cut cost / speed up slow dashboards / both | weights credits vs. latency in what you highlight | Changes which candidates matter |
| **How aggressive?** conservative / balanced / aggressive | `--mat-min-runs` / `--mat-min-avg-sec` / `--mat-min-credits` | Conservative = only obvious wins; aggressive = flag more |

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
1. **Analyze** — `scripts/analyze.py --conn <snow> --days 30 [--org <slug>] [--config ...]` →
   attributes credits to Sigma objects, ranks candidates → `inventory.json` + `REPORT.md`.
2. **Report** — `scripts/render-html.py` → customer-facing HTML.
3. **Remediate (opt-in), two levers per candidate:**
   - **A — Improve the query** in the workbook/data model (push calc logic upstream,
     declare relationships, drop unused columns). Pull/edit specs via the Sigma API;
     pairs with `sigma-data-model-assessment`.
   - **B — Materialize via API** — `scripts/materialize.py list|run`. The schedule is
     created once in the Sigma UI (no create-schedule endpoint); the refresh is then
     fully API-driven.

## Scripts
| Script | Purpose |
|---|---|
| `scripts/analyze.py` | Snowflake credit attribution → ranked candidates → `inventory.json` + `REPORT.md` |
| `scripts/materialize.py` | `list` / `run` (trigger + poll) a Sigma materialization via REST |
| `scripts/render-html.py` | `inventory.json` → customer-facing `report.html` |

Flags (`analyze.py`): `--conn`, `--days`, `--org <slug>` (scope to one Sigma org; omit
for account-wide), `--min-runs`, `--limit`, `--out`.

## Cortex Code note
The attribution SQL is portable — it runs equally well from Cortex Code / a Snowflake
notebook if a team prefers to keep the analysis in-warehouse (no creds to manage, data
never leaves the account). The Sigma-side mapping and materialization actions need the
Sigma REST API, so the end-to-end loop lives here.

## Open work
- **Materialization schedule creation** is UI-only today (API can list/run/monitor).
- ID resolution: `analyze.py` reports the `sourceUrl`; an optional `--resolve` pass could
  turn each candidate into a ready-to-run `materialize.py` command (workbookId + sheetId).
- `--consumers`-style fan-out: for a data-model candidate, count how many workbooks
  benefit from materializing it (raises its priority).
