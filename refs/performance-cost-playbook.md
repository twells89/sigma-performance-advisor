# Sigma performance-and-cost playbook

The objective is not “remove materializations” or “materialize more.” It is:

> Meet the workload's latency and freshness targets at the lowest sustainable total cost.

## Evidence

| Signal | Source | Meaning |
|---|---|---|
| Query credits / QAS | `QUERY_ATTRIBUTION_HISTORY` | Attributed execution cost; excludes idle and other cost pools |
| p50 / p95 / scan / spill / queue / pruning | `QUERY_HISTORY` | User-path performance and query-efficiency evidence |
| Refresh cost | Sigma `kind=materialization` tags + query attribution | Materialization build/refresh compute |
| Observed served reads | `ACCESS_HISTORY.objects_modified` → `direct_objects_accessed` | Queries that accessed an object built by a materialization job |
| Warehouse idle | `WAREHOUSE_METERING_HISTORY` | Warehouse-level upper bound, not automatically Sigma savings |
| Schedule / controls / lineage | Sigma REST | Cadence, control-risk flag, and dependencies |

Keep unmatched reads explicit. A failed object match can mean bypass, object rotation,
incomplete history, or missing privileges; it is not proof that the schedule is unused.
The current `ACCESS_HISTORY` utilization query matches workbook materializations only;
data-model schedules require consumer-lineage review and remain `Investigate`.

## Decisions

1. **Keep** when observed read utilization is healthy, cached p95 meets the SLO, and
   refresh cost is justified.
2. **Retune** when a schedule is useful but refreshes too frequently for user demand or
   source updates.
3. **Investigate** when utilization is low, controls are present, lineage is incomplete,
   or the workload stays slow despite materialization.
4. **Remove candidate** only when a measured no-materialization window remains within
   the latency allowance and produces material savings. Preserve schedule configuration
   and define rollback before removal.
5. **Add candidate** when repeated live-query cost and latency exceed expected refresh
   compute + storage and the freshness requirement permits snapshots.
6. **Optimize query/model** when the query itself has poor pruning, spill, costly joins,
   excess columns, or expensive calculations. Lower the floor before caching.

## Controls and freshness

- A control targeting a materialized element causes live queries. Prefer controls on
  child elements.
- Current list-elements and lineage APIs reveal control presence but not target
  bindings. Mark control-bearing workbooks `review required`.
- Dynamic date controls can force full refreshes; parameters use initial values.
- Schedule upstream materializations before dependent children.

## Savings math

Keep cost pools separate:

`materialization value = avoided live-query credits - refresh credits - incremental storage`

`warehouse idle opportunity = warehouse compute - attributed query compute`

Report low/expected/high savings. Never add overlapping query, materialization, and idle
estimates into one uncapped number.

## Validation sequence

1. Capture current schedule, freshness, ownership, cost, served reads, and p95.
2. Use a natural failed/paused/pre-schedule window or an explicitly approved benchmark.
3. Compare equivalent query cohorts and business periods.
4. Require owner approval for any mutation.
5. Monitor latency, freshness, and credits through a rollback window.
