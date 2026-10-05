# Sigma Performance & Cost Opportunities

_Scope: **account-wide** · last 30 days · 2,500 Sigma queries · 50.00 credits (~$150) · generated 2026-10-05 · **analysis is read-only**_

Attribution coverage: **60.74%** of Sigma query credits map to a source URL. Unattributed/system activity remains a separate cost pool and is not silently dropped.

## Recommended decisions

| # | Object | Element | Action | Runs | Credits | p95 s | Refreshes | Matched reads | Confidence |
|---:|---|---|---|---:|---:|---:|---:|---:|---|
| 1 | [dm: Sales-Mart-DM-aaa111](https://app.sigmacomputing.com/northwind/data-model/Sales-Mart-DM-aaa111) | (workbook load) | Investigate materialization | 240 | 20.4000 | 4.00 | 0 | 0 | low |
| 2 | [wb: Legacy-Snapshot-iii999](https://app.sigmacomputing.com/northwind/workbook/Legacy-Snapshot-iii999?:displayNodeId=table-main) | table-main | Remove materialization candidate | 40 | 8.5000 | 1.50 | 30 | 40 | high |
| 3 | [wb: Customer-Overview-jjj000](https://app.sigmacomputing.com/northwind/workbook/Customer-Overview-jjj000?:displayNodeId=orders) | orders | Add materialization candidate | 180 | 4.2000 | 4.50 | 0 | 0 | low |
| 4 | [wb: Ops-Live-Tiles-ccc333](https://app.sigmacomputing.com/northwind/workbook/Ops-Live-Tiles-ccc333?:displayNodeId=kpi-row) | kpi-row | Retune materialization | 80 | 2.8000 | 2.00 | 90 | 4 | medium |
| 5 | [wb: Exec-Revenue-Daily-bbb222](https://app.sigmacomputing.com/northwind/workbook/Exec-Revenue-Daily-bbb222?:displayNodeId=master) | master | Keep materialization | 510 | 2.4000 | 1.30 | 30 | 500 | medium |
| 6 | [wb: Finance-Snapshot-hhh888](https://app.sigmacomputing.com/northwind/workbook/Finance-Snapshot-hhh888?:displayNodeId=master) | master | Investigate materialization | 60 | 1.6000 | 3.00 | 30 | 20 | medium |
| 7 | [wb: Adhoc-Cohort-Explorer-ddd444](https://app.sigmacomputing.com/northwind/workbook/Adhoc-Cohort-Explorer-ddd444?:displayNodeId=cohort-tbl) | cohort-tbl | Optimize query/model | 5 | 1.1000 | 18.00 | 0 | 0 | medium |
| 8 | [wb: Marketing-Overview-fff666](https://app.sigmacomputing.com/northwind/workbook/Marketing-Overview-fff666?:displayNodeId=chart-1) | chart-1 | Monitor | 64 | 0.1800 | 0.70 | 0 | 0 | high |
| 9 | [wb: HR-Headcount-ggg777](https://app.sigmacomputing.com/northwind/workbook/HR-Headcount-ggg777?:displayNodeId=table-main) | table-main | Monitor | 22 | 0.0900 | 0.50 | 0 | 0 | high |

### Investigate materialization: /data-model/Sales-Mart-DM-aaa111 / (workbook load)

- Why: The data-model workload is repetitive and expensive, but schedule and downstream-consumer utilization are not resolved by the workbook-only materialization evidence pass.
- Performance: Potentially high fan-out; performance impact is unknown.
- Validate: Inspect the data-model schedule and consumer lineage before adding, retuning, or removing materialization.

### Remove materialization candidate: /workbook/Legacy-Snapshot-iii999 / table-main

- Why: Measured no-materialization p95 is 3.20s and remains within the latency allowance; projected monthly savings are about $24.
- Performance: Measured p95 without materialization: 3.20s.
- Validate: Remove only with owner approval, preserve the cron/timezone, and monitor latency and credits with a rollback window.

### Add materialization candidate: /workbook/Customer-Overview-jjj000 / orders

- Why: The element is repetitive (180 runs) and non-trivial (4.50s p95, 4.20 query + QAS credits).
- Performance: Likely faster repeat reads; freshness and refresh cost must be measured.
- Validate: Create only after a capped benchmark. Compare avoided live-query credits with refresh compute and storage.

### Retune materialization: /workbook/Ops-Live-Tiles-ccc333 / kpi-row

- Why: Only 4 matched read(s) were observed across 90 refresh(es) (0.04 reads/refresh).
- Performance: Expected to preserve cached performance while reducing refresh work; the exact impact requires a cadence experiment.
- Validate: Align cadence to source updates and user access. Measure one full business cycle before considering removal.

### Keep materialization: /workbook/Exec-Revenue-Daily-bbb222 / master

- Why: It serves 500 observed read(s) across 30 refresh(es), and matched-read p95 is 1.30s.
- Performance: Current cached performance meets the configured SLO.
- Validate: Continue measuring refresh cost and matched reads; retune if utilization falls.

### Investigate materialization: /workbook/Finance-Snapshot-hhh888 / master

- Why: Control targets are not resolved; observed utilization is 20 matched read(s) across 30 refresh(es). Removal safety cannot be inferred.
- Performance: Unknown until control/lineage behavior is verified.
- Validate: Review controls and lineage, then benchmark the element with and without materialization before changing the schedule.

### Optimize query/model: /workbook/Adhoc-Cohort-Explorer-ddd444 / cohort-tbl

- Why: The workload is expensive per run (p95 18.00s) and shows scan, pruning, or spill pressure. Lower the cost floor before caching it.
- Performance: Expected to reduce both live-query cost and latency.
- Validate: Inspect query insights/profile, filters, joins, projected columns, and pre-aggregation; remeasure before materializing.

### Monitor: /workbook/Marketing-Overview-fff666 / chart-1

- Why: Observed cost and latency do not justify a change (0.180 credits, 0.70s p95).
- Performance: No material performance change expected.
- Validate: Revisit if usage, cost, or the latency target changes.

### Monitor: /workbook/HR-Headcount-ggg777 / table-main

- Why: Observed cost and latency do not justify a change (0.090 credits, 0.50s p95).
- Performance: No material performance change expected.
- Validate: Revisit if usage, cost, or the latency target changes.

## Warehouse context

- Compute: 70.0 credits
- Estimated idle: 25.0 credits (35.71%)
- Idle is a warehouse-level upper bound; it is not automatically attributed to Sigma or to any one workbook.

## Method & caveats

- Query cost comes from `QUERY_ATTRIBUTION_HISTORY`; materialization utilization matches `ACCESS_HISTORY.objects_modified` to `direct_objects_accessed`.
- A removal recommendation requires a measured no-materialization baseline. Refresh cost alone is never treated as proof that removal is safe.
- Controls can bypass materialization. Unresolved target bindings force manual review.
- `ACCOUNT_USAGE` is delayed and query attribution excludes idle, storage, transfer, cloud services, and most serverless costs.