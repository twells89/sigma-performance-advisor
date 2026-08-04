# Sigma → Snowflake Materialization Opportunities

_Scope: **account-wide** · last 30 days · 889 Sigma queries · 35.68 credits (~$107.04) · 8 objects · generated 2026-08-04 · **read-only**_

_Found **3** materialize + **2** improve candidates. Thresholds: materialize when runs ≥ 12 AND (avg ≥ 3.0s OR ≥ 0.5 cr); $3.0/credit (provided)._

Top candidates ranked by attributed compute credits × frequency. Credits come from `QUERY_ATTRIBUTION_HISTORY`; objects are resolved from each query's Sigma `QUERY_TAG`.

| # | Object | Element | Runs | Credits | Avg s | Max s | Recommended fix |
|---:|---|---|---:|---:|---:|---:|---|
| 1 | [dm: Sales-Mart-DM-aaa111](https://app.sigmacomputing.com/northwind/data-model/Sales-Mart-DM-aaa111) | (workbook load) | 240 | 18.4 | 2.1 | 6.0 | Materialize (data model) |
| 2 | [wb: Exec-Revenue-Daily-bbb222](https://app.sigmacomputing.com/northwind/workbook/Exec-Revenue-Daily-bbb222?:displayNodeId=master) | master | 132 | 9.6 | 4.8 | 9.1 | Materialize (workbook element) |
| 3 | [wb: Ops-Live-Tiles-ccc333](https://app.sigmacomputing.com/northwind/workbook/Ops-Live-Tiles-ccc333?:displayNodeId=kpi-row) | kpi-row | 410 | 5.2 | 0.7 | 1.9 | Materialize (workbook element) |
| 4 | [wb: Adhoc-Cohort-Explorer-ddd444](https://app.sigmacomputing.com/northwind/workbook/Adhoc-Cohort-Explorer-ddd444?:displayNodeId=cohort-tbl) | cohort-tbl | 5 | 1.1 | 14.7 | 22.0 | Improve the query |
| 5 | [dm: Web-Events-DM-eee555](https://app.sigmacomputing.com/northwind/data-model/Web-Events-DM-eee555) | (workbook load) | 7 | 0.9 | 8.2 | 12.4 | Improve the query |
| 6 | [wb: Finance-Snapshot-hhh888](https://app.sigmacomputing.com/northwind/workbook/Finance-Snapshot-hhh888?:displayNodeId=master) | master | 9 | 0.21 | 1.1 | 2.0 | Monitor — not worth materializing |
| 7 | [wb: Marketing-Overview-fff666](https://app.sigmacomputing.com/northwind/workbook/Marketing-Overview-fff666?:displayNodeId=chart-1) | chart-1 | 64 | 0.18 | 0.4 | 0.9 | Monitor — not worth materializing |
| 8 | [wb: HR-Headcount-ggg777](https://app.sigmacomputing.com/northwind/workbook/HR-Headcount-ggg777?:displayNodeId=table-main) | table-main | 22 | 0.09 | 0.3 | 0.7 | Monitor — not worth materializing |

## Two ways to remediate each candidate

For every candidate above you have two levers — one reduces the cost *per run*, the other removes redundant runs entirely:

**Option A — Improve the query (in the workbook / data model).** Pull the object's spec via the Sigma API and fix what makes it expensive: push heavy calc-column logic upstream, declare relationships instead of cross-element `Lookup()`, drop unused columns, or pre-aggregate. Best when a single run is slow/large. (Pairs with the `sigma-data-model-assessment` skill, which already flags these patterns.)

**Option B — Materialize via the Sigma API.** Cache the element's result so repeat views read a stored table instead of recomputing. Best when an object is *repetitive*. Mechanics:

```
eval "$(~/.claude/skills/tableau-to-sigma/scripts/get-token.sh)"
python3 scripts/materialize.py list   --workbook <workbookId>                          # find the elementId
python3 scripts/materialize.py create --workbook <workbookId> --sheet <elementId> --cron "0 0 * * *"   # one-time
python3 scripts/materialize.py run    --workbook <workbookId> --sheet <elementId>       # refresh + poll
# data models:  materialize.py create/run --datamodel <dataModelId> --sheet <elementId>
```

> **API note:** the Sigma API can *create*, *update*, *delete*, *list*, *trigger*, and *monitor* materialization schedules end to end — no UI step required. Schedule create/update/delete (cron cadence only, no destination field) are a **private-beta** REST surface; see `refs/materialization-playbook.md` for exact shapes and a live-deployment caveat before depending on them for a given org. `list`/`run`/monitor are stable and already live-verified.

## How to read this

- **Credits** = real attributed compute for that object's queries over the window. Multiply by your $/credit rate for dollars.

- **Materialization candidates** are objects that are both *expensive* and *repetitive* — caching their result removes redundant warehouse runs. Data-model elements rank highest because one materialization benefits every workbook built on them.

## Method & caveats

- Read-only `SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY` + `QUERY_ATTRIBUTION_HISTORY`, joined on `query_id`; Sigma objects parsed from `QUERY_TAG` (`Sigma Σ {sourceUrl,email,kind}`).

- Only `kind` carrying a `sourceUrl` is attributable; pure scheduler/system queries (`SigmaSchedulerRobot`, schema introspection) are excluded.

- `ACCOUNT_USAGE` has up to ~3h latency and `QUERY_ATTRIBUTION_HISTORY` covers warehouse compute (not cloud-services-only queries).
