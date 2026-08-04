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
**Retracted 2026-08:** earlier revisions of this playbook (and `materialize.py`'s module
docstring) claimed *"Create schedule: Sigma UI only … No create-schedule REST endpoint as
of 2026-06."* That was false — Sigma's public OpenAPI spec documents full create/update/
delete for materialization schedules (private beta), and the exact paths/body shape below
are independently confirmed against Sigma's own help-center reference pages for these 4
endpoints (fetched directly, not just the OpenAPI asset) — those pages explicitly label
this "a private beta feature." Prefer Sigma's stable `help.sigmacomputing.com/reference/`
per-endpoint pages over any pinned OpenAPI JSON asset URL for future citations here — the
latter has already rotated/gone stale twice in this doc set's history. Read the
live-deployment caveat below before relying on this against a given org.

- **List** (pre-existing, unchanged — the two calls below are correct as written, do NOT
  "fix" them to match the create/update/delete shape below):
  - Workbook element: `GET /v2/workbooks/{workbookId}/materialization-schedules`
    (unscoped — whole workbook, no `elementId` segment, **hyphenated** path).
  - Data-model element: `GET /v2/dataModels/{dataModelId}/materializationSchedules`
    (unscoped — whole data model, **camelCase** path).
  - Both return entries shaped `{sheetId, elementName, schedule: {cronSpec, timezone},
    paused}`.
- **Create / Update / Delete** (private beta, new) — nested under the *element*, and
  **camelCase** (`materializationSchedules`, no hyphen) on **both** sides. This is the
  key asymmetry to know about: on the workbook side, LIST stays unscoped+hyphenated
  (above) while create/update/delete are element-scoped+camelCase — two different paths
  for the same feature area, neither one a bug:
  - Workbook element: `POST` / `PATCH` / `DELETE
    /v2/workbooks/{workbookId}/elements/{elementId}/materializationSchedules`
  - Data-model element: `GET` / `POST` / `PATCH` / `DELETE
    /v2/dataModels/{dataModelId}/elements/{elementId}/materializationSchedules` — the
    data-model side additionally exposes `GET` at this nested path; the workbook side
    does not (use the unscoped workbook list above instead).
  - **Body — identical for create and update, both element types:**
    `{"schedule": {"cronSpec": "<cron expression>", "timezone": "<IANA tz, optional>"}}`.
    Only `cronSpec` is required. **There is no destination/target field** — the UI's
    "pick element + destination + cadence" framing overstates what the API needs;
    materialization always writes back to Sigma's own internal cache, never a
    user-chosen table.
  - `DELETE` takes no body and hits the same element-scoped path — one schedule per
    element, no separate schedule-id to track.
  - **Live-deployment caveat (verified 2026-08-04):** all three nested create/update/
    delete endpoints — on *every* verb tried, including read-only `GET` on the
    data-model side — returned `404` with header `errorcause: UnmatchedHandler` against
    a live test org, for both a real element ID and a fabricated one (identical
    response), while a known-good sibling endpoint returns a proper `400` JSON error for
    a malformed ID rather than a bare `404`. The shape above is confirmed correct
    (matches Sigma's own live help-center reference pages) — this 404 is a rollout gap
    on the org tested, not a wrong path/body. Read it as *"correctly documented,
    private beta, rollout not yet visible on the org tested"* — not *"confirmed broken
    forever."* Re-test before depending on create/update/delete for a given org;
    `list`/`run`/`monitor` are unaffected and already live-verified working.
- **Run/refresh** (pre-existing, unchanged): `POST /v2/workbooks/{id}/materializations
  {sheetId}` or `POST /v2/dataModels/{id}:materialize {sheetId}` → returns
  `materializationId`.
- **Monitor** (pre-existing, unchanged): `GET .../materializations/{materializationId}`.

## Cost math
`monthly_savings ≈ (credits_in_window / window_days × 30) × fraction_removed × $/credit`.
For a materialized repetitive element, `fraction_removed` ≈ the share of runs that would
hit the cache instead of the warehouse, minus the materialization refresh cost.
