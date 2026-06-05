# Materialization & query-cost playbook

How the advisor turns a Snowflake cost signal into a recommendation. Two levers:
**improve the query** (lower cost per run) or **materialize** (remove redundant runs).

## Signals (from the joined ACCOUNT_USAGE + Sigma tag data)
| Signal | Source |
|---|---|
| `credits` | `QUERY_ATTRIBUTION_HISTORY.credits_attributed_compute` per `query_id` |
| `runs` | count of successful SELECTs for the object in the window |
| `avg_sec` / `max_sec` | `QUERY_HISTORY.total_elapsed_time` |
| `max_bytes` | `QUERY_HISTORY.bytes_scanned` |
| object / element | parsed from `QUERY_TAG` → `Sigma Σ {sourceUrl, kind}` |

## Decision rubric
1. **Data-model element, repeated** → **materialize the data model** (`:materialize`).
   Highest leverage: one materialization serves every workbook built on it.
2. **Workbook element, high `runs` + non-trivial `avg_sec`** → **materialize the element**.
   Repeat dashboard views read the cached table instead of recomputing.
3. **Large `max_bytes` (>~1 GB) regardless of frequency** → **query improvement first**:
   the SQL itself is heavy. Push the transform into a Snowflake **dynamic table / MV**, or
   fix the Sigma object (pre-aggregate, drop unused columns, declare relationships so the
   planner stops doing per-row cross-element `Lookup()`).
4. **Low individual cost** → **review / right-size** only; warehouse auto-suspend +
   result-cache reuse usually already cover it. Don't materialize trivial elements
   (materialization has its own refresh cost).

## Improve vs. materialize — when to pick which
- **Improve** when a *single run* is slow or scans a lot — you're lowering the floor.
- **Materialize** when runs are *repetitive* and the data tolerates some staleness — you're
  removing redundant compute. Set the cadence to the data's real freshness need (hourly,
  daily); over-frequent materialization can cost more than it saves.
- Often do both: improve the underlying data-model element, then materialize it.

## Materialization mechanics (Sigma API)
- **Create schedule:** Sigma UI only — element ⋮ → *Materialization* → destination + cadence.
  (No create-schedule REST endpoint as of 2026-06.)
- **List:** `GET /v2/workbooks/{id}/materialization-schedules` →
  `GET /v2/dataModels/{id}/materializationSchedules`. Returns `sheetId`, `elementName`,
  `schedule.cronSpec`, `paused`.
- **Run/refresh:** `POST /v2/workbooks/{id}/materializations {sheetId}` or
  `POST /v2/dataModels/{id}:materialize {sheetId}` → returns `materializationId`.
- **Monitor:** `GET .../materializations/{materializationId}`.

## Cost math
`monthly_savings ≈ (credits_in_window / window_days × 30) × fraction_removed × $/credit`.
For a materialized repetitive element, `fraction_removed` ≈ the share of runs that would
hit the cache instead of the warehouse, minus the materialization refresh cost.
