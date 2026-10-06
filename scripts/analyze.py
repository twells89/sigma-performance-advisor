#!/usr/bin/env python3
"""Sigma performance-and-cost advisor.

Read Snowflake ACCOUNT_USAGE via the `snow` CLI, report complete Sigma-tagged cost
coverage, attribute actionable workload to Sigma objects, measure materialization
refresh cost and observed reads, and emit keep/retune/investigate/remove/add/query-
optimization decisions.

Read-only: SELECTs against SNOWFLAKE.ACCOUNT_USAGE only.

    python3 scripts/analyze.py --conn default --days 30 --out out [--org <org-slug>]
"""
import argparse, json, os, subprocess, sys
from datetime import datetime, timezone

from cost_model import DEFAULT_CONFIG, coerce_row, merge_config, recommend, score

# Aggregates in-warehouse (cheap) at workbook+element grain, joining real per-query
# credits from QUERY_ATTRIBUTION_HISTORY. {DAYS} and {ORG_FILTER} are injected.
SQL = r"""
with qh as (
  select query_id, query_parameterized_hash, total_elapsed_time, bytes_scanned,
         bytes_spilled_to_local_storage, bytes_spilled_to_remote_storage,
         queued_overload_time, partitions_scanned, partitions_total,
         iff(position('{' in query_tag) > 0,
             try_parse_json(substr(query_tag, position('{' in query_tag))), null) as j
  from snowflake.account_usage.query_history
  where start_time > dateadd('day', -{DAYS}, current_timestamp())
    and query_tag ilike 'Sigma %'
    and execution_status = 'SUCCESS'
),
s as (
  select query_id, query_parameterized_hash, total_elapsed_time, bytes_scanned,
         bytes_spilled_to_local_storage, bytes_spilled_to_remote_storage,
         queued_overload_time, partitions_scanned, partitions_total,
         j:"sourceUrl"::string  as source_url,
         j:"kind"::string       as kind,
         split_part(j:"sourceUrl"::string, '/', 4) as org,
         regexp_substr(j:"sourceUrl"::string, '/(workbook|report|data-model)/[^?]+') as object,
         regexp_substr(j:"sourceUrl"::string, '[?&]:displayNodeId=([^&]+)', 1, 1, 'e', 1) as element
  from qh
  where j:"sourceUrl" is not null
    and coalesce(j:"kind"::string, '') <> 'materialization'
    {ORG_FILTER}
),
att as (
  select query_id, sum(credits_attributed_compute) as credits,
         sum(credits_used_query_acceleration) as qas_credits
  from snowflake.account_usage.query_attribution_history
  where start_time > dateadd('day', -{DAYS}, current_timestamp())
  group by 1
)
select
  s.org,
  s.object,
  coalesce(s.element, '(workbook load)')          as element,
  count(*)                                        as runs,
  round(sum(coalesce(att.credits, 0)), 4)         as credits,
  round(sum(coalesce(att.qas_credits, 0)), 4)     as qas_credits,
  round(avg(s.total_elapsed_time)/1000.0, 2)      as avg_sec,
  round(approx_percentile(s.total_elapsed_time/1000.0, .5), 2) as p50_sec,
  round(approx_percentile(s.total_elapsed_time/1000.0, .95), 2) as p95_sec,
  round(max(s.total_elapsed_time)/1000.0, 2)      as max_sec,
  round(sum(s.total_elapsed_time)/1000.0, 1)      as total_sec,
  sum(s.bytes_scanned)                             as bytes_scanned,
  max(s.bytes_scanned)                            as max_bytes,
  sum(coalesce(s.bytes_spilled_to_local_storage,0) +
      coalesce(s.bytes_spilled_to_remote_storage,0)) as bytes_spilled,
  round(sum(coalesce(s.queued_overload_time,0))/1000.0, 1) as queued_overload_sec,
  round(sum(s.partitions_scanned)/nullif(sum(s.partitions_total),0)*100, 2)
                                                   as partition_scan_pct,
  count(distinct s.query_parameterized_hash)       as query_patterns,
  max(s.source_url)                               as sample_url
from s
left join att using (query_id)
group by 1, 2, 3
having count(*) >= {MIN_RUNS}
order by credits desc, total_sec desc
limit {LIMIT};
"""


COVERAGE_SQL = r"""
with parsed as (
  select query_id,
         iff(position('{' in query_tag) > 0,
             try_parse_json(substr(query_tag, position('{' in query_tag))), null) as j
  from snowflake.account_usage.query_history
  where start_time > dateadd('day', -{DAYS}, current_timestamp())
    and query_tag ilike 'Sigma %'
    and execution_status = 'SUCCESS'
),
qh as (
  select * from parsed where 1=1
    {ORG_FILTER}
),
att as (
  select query_id, sum(credits_attributed_compute) credits,
         sum(credits_used_query_acceleration) qas_credits
  from snowflake.account_usage.query_attribution_history
  where start_time > dateadd('day', -{DAYS}, current_timestamp())
  group by 1
)
select count(*) all_sigma_queries,
       round(sum(coalesce(att.credits,0)),4) all_sigma_credits,
       round(sum(coalesce(att.qas_credits,0)),4) all_qas_credits,
       count_if(qh.j:"sourceUrl"::string is not null
                and coalesce(qh.j:"kind"::string,'') <> 'materialization')
         attributable_queries,
       round(sum(iff(qh.j:"sourceUrl"::string is not null
                     and coalesce(qh.j:"kind"::string,'') <> 'materialization',
                     coalesce(att.credits,0),0)),4) attributable_credits,
       round(sum(iff(qh.j:"sourceUrl"::string is not null
                     and coalesce(qh.j:"kind"::string,'') <> 'materialization',
                     coalesce(att.qas_credits,0),0)),4) attributable_qas_credits,
       count_if(qh.j:"kind"::string = 'materialization') materialization_queries,
       round(sum(iff(qh.j:"kind"::string = 'materialization',
                     coalesce(att.credits,0),0)),4) materialization_credits,
       round(sum(iff(qh.j:"kind"::string = 'materialization',
                     coalesce(att.qas_credits,0),0)),4) materialization_qas_credits,
       count_if(qh.j:"sourceUrl"::string is null
                and coalesce(qh.j:"kind"::string,'') <> 'materialization')
         unattributed_queries,
       round(sum(iff(qh.j:"sourceUrl"::string is null
                     and coalesce(qh.j:"kind"::string,'') <> 'materialization',
                     coalesce(att.credits,0),0)),4) unattributed_credits,
       round(sum(iff(qh.j:"sourceUrl"::string is null
                     and coalesce(qh.j:"kind"::string,'') <> 'materialization',
                     coalesce(att.qas_credits,0),0)),4) unattributed_qas_credits
from qh left join att using(query_id);
"""


MATERIALIZATION_SQL = r"""
with tagged as (
  select query_id, total_elapsed_time/1000.0 sec,
         regexp_substr(j:"sourceUrl"::string, '/(workbook|report)/[^?]+') wb_path,
         j:"sourceUrl"::string source_url, j:"kind"::string kind,
         split_part(j:"sourceUrl"::string, '/', 4) org,
         regexp_substr(j:"sourceUrl"::string, '/(workbook|report|data-model)/[^?]+') object,
         regexp_substr(j:"sourceUrl"::string, '[?&]:displayNodeId=([^&]+)',
                       1, 1, 'e', 1) element
  from (
    select query_id, total_elapsed_time,
           iff(position('{' in query_tag) > 0,
               try_parse_json(substr(query_tag, position('{' in query_tag))), null) j
    from snowflake.account_usage.query_history
    where start_time > dateadd('day', -{DAYS}, current_timestamp())
      and query_tag ilike 'Sigma %' and execution_status='SUCCESS'
  )
  where j:"sourceUrl"::string is not null
    {ORG_FILTER}
),
att as (
  select query_id, sum(credits_attributed_compute) credits,
         sum(credits_used_query_acceleration) qas_credits
  from snowflake.account_usage.query_attribution_history
  where start_time > dateadd('day', -{DAYS}, current_timestamp())
  group by 1
),
mat_runs as (
  select source_url, wb_path, org, object, coalesce(element,'(workbook load)') element,
         count(*) materialization_runs,
         round(sum(coalesce(att.credits,0)),4) materialization_credits,
         round(sum(coalesce(att.qas_credits,0)),4) materialization_qas_credits,
         round(approx_percentile(sec,.95),2) materialization_p95_sec
  from tagged left join att using(query_id)
  where kind='materialization' and wb_path is not null
  group by 1,2,3,4,5
),
mat_objects as (
  select distinct t.source_url, t.wb_path,
         coalesce(f.value:"objectId"::string, f.value:"objectName"::string) obj
  from tagged t
  join snowflake.account_usage.access_history ah using(query_id),
       lateral flatten(input=>ah.objects_modified) f
  where t.kind='materialization' and t.wb_path is not null
    and coalesce(f.value:"objectId"::string, f.value:"objectName"::string) is not null
),
read_objects as (
  select t.query_id, t.wb_path,
         coalesce(f.value:"objectId"::string, f.value:"objectName"::string) obj
  from tagged t
  join snowflake.account_usage.access_history ah using(query_id),
       lateral flatten(input=>ah.direct_objects_accessed) f
  where t.kind='adhoc'
),
matched_queries as (
  select distinct m.source_url, t.query_id, t.sec, coalesce(att.credits,0) credits,
         coalesce(att.qas_credits,0) qas_credits
  from read_objects r
  join tagged t using(query_id, wb_path)
  join mat_objects m on m.wb_path=r.wb_path and m.obj=r.obj
  left join att using(query_id)
),
matched as (
  select source_url, count(*) matched_materialized_reads,
         round(sum(credits),4) matched_read_credits,
         round(sum(qas_credits),4) matched_read_qas_credits,
         round(approx_percentile(sec,.95),2) matched_read_p95_sec
  from matched_queries group by 1
),
workbook_reads as (
  select wb_path, count(*) workbook_reads,
         round(sum(coalesce(att.credits,0)),4) workbook_read_credits,
         round(sum(coalesce(att.qas_credits,0)),4) workbook_read_qas_credits,
         round(approx_percentile(sec,.95),2) workbook_read_p95_sec
  from tagged left join att using(query_id)
  where kind='adhoc' group by 1
)
select m.org, m.object, m.element, m.source_url sample_url,
       m.materialization_runs, m.materialization_credits,
       m.materialization_qas_credits, m.materialization_p95_sec,
       coalesce(x.matched_materialized_reads,0) matched_materialized_reads,
       coalesce(x.matched_read_credits,0) matched_read_credits,
       coalesce(x.matched_read_qas_credits,0) matched_read_qas_credits,
       x.matched_read_p95_sec,
       greatest(coalesce(w.workbook_reads,0) -
                coalesce(x.matched_materialized_reads,0),0) workbook_unmatched_reads,
       greatest(coalesce(w.workbook_read_credits,0) -
                coalesce(x.matched_read_credits,0),0) workbook_unmatched_read_credits,
       greatest(coalesce(w.workbook_read_qas_credits,0) -
                coalesce(x.matched_read_qas_credits,0),0)
         workbook_unmatched_read_qas_credits,
       w.workbook_read_p95_sec workbook_unmatched_read_p95_sec
from mat_runs m
left join matched x using(source_url)
left join workbook_reads w using(wb_path)
order by m.materialization_credits desc;
"""


WAREHOUSE_SQL = r"""
select round(sum(credits_used_compute),4) warehouse_compute_credits,
       round(sum(credits_attributed_compute_queries),4) attributed_query_credits,
       round(sum(credits_used_compute)-sum(credits_attributed_compute_queries),4)
         estimated_idle_credits,
       round((sum(credits_used_compute)-sum(credits_attributed_compute_queries)) /
             nullif(sum(credits_used_compute),0)*100,2) estimated_idle_pct,
       count(distinct warehouse_name) warehouses
from snowflake.account_usage.warehouse_metering_history
where start_time > dateadd('day', -{DAYS}, current_timestamp());
"""


def detect_credit_price(conn):
    """Best-effort: read the account's effective $/credit from ORGANIZATION_USAGE.
    Returns float or None (no access / internal account with no billing data)."""
    queries = [
        "select round(sum(usage_in_currency)/nullif(sum(usage),0),4) as rate "
        "from snowflake.organization_usage.usage_in_currency_daily "
        "where usage_type='compute' and usage_date > dateadd('day',-30,current_date())",
        "select round(avg(effective_rate),4) as rate "
        "from snowflake.organization_usage.rate_sheet_daily "
        "where usage_type ilike '%compute%' and date > dateadd('day',-90,current_date())",
    ]
    for q in queries:
        try:
            r = run_sql(conn, q)
            v = r[0].get("RATE") if r else None
            if v not in (None, "", 0):
                return float(v)
        except Exception:
            pass
    return None


def run_sql(conn, sql):
    p = subprocess.run(["snow", "sql", "-c", conn, "--format", "json", "--stdin"],
                       input=sql, capture_output=True, text=True)
    out = p.stdout.strip()
    # SSO/info lines go to stderr; stdout should be JSON. Be defensive anyway.
    i = out.find("[")
    if i < 0:
        raise RuntimeError(
            f"snow returned no JSON.\nstdout:\n{out[:500]}\nstderr:\n{p.stderr[-800:]}"
        )
    return json.loads(out[i:])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--conn", default="default", help="snow CLI connection name")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--org", default=None, help="Sigma org slug to scope to (else account-wide)")
    ap.add_argument("--min-runs", type=int, default=2, help="min runs to appear at all")
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--out", default="cost-optimization-out")
    ap.add_argument("--mat-min-runs", type=int, default=DEFAULT_CONFIG["mat_min_runs"])
    ap.add_argument("--mat-min-avg-sec", type=float,
                    default=DEFAULT_CONFIG["mat_min_avg_sec"])
    ap.add_argument("--mat-min-credits", type=float,
                    default=DEFAULT_CONFIG["mat_min_credits"])
    ap.add_argument("--latency-slo-sec", type=float,
                    default=DEFAULT_CONFIG["latency_slo_sec"])
    ap.add_argument("--freshness", default=DEFAULT_CONFIG["freshness"],
                    help="real-time / <=1h / <=1day / varies")
    ap.add_argument("--acceptable-slowdown-sec", type=float,
                    default=DEFAULT_CONFIG["acceptable_slowdown_sec"])
    ap.add_argument("--credit-price", type=float, default=None,
                    help="$ per Snowflake credit (default: auto-detect from ORGANIZATION_USAGE, else 3.0)")
    ap.add_argument("--goal", choices=["cost", "latency", "performance_per_dollar", "both"],
                    default=DEFAULT_CONFIG["goal"])
    ap.add_argument("--from-rows", help="JSON array of workload rows, or a v2 bundle with "
                    "workload/coverage/materializations/warehouses")
    ap.add_argument("--config", help="JSON file with any of the above (intake answers); flags win")
    a = ap.parse_args()
    file_config = {}
    if a.config and os.path.exists(a.config):
        with open(a.config) as f:
            file_config = json.load(f)
        def explicitly_supplied(key):
            flag = "--" + key.replace("_", "-")
            return any(arg == flag or arg.startswith(flag + "=")
                       for arg in sys.argv[1:])
        for key in (
            "mat_min_runs", "mat_min_avg_sec", "mat_min_credits", "credit_price",
            "days", "goal", "latency_slo_sec", "freshness",
            "acceptable_slowdown_sec", "org", "min_runs", "limit",
        ):
            if key in file_config and not explicitly_supplied(key):
                setattr(a, key, file_config[key])
    model_config = merge_config({
        **file_config,
        "mat_min_runs": a.mat_min_runs,
        "mat_min_avg_sec": a.mat_min_avg_sec,
        "mat_min_credits": a.mat_min_credits,
        "latency_slo_sec": a.latency_slo_sec,
        "freshness": a.freshness,
        "acceptable_slowdown_sec": a.acceptable_slowdown_sec,
        "goal": "performance_per_dollar" if a.goal == "both" else a.goal,
    })

    price_source = "provided"
    if a.credit_price is None:
        a.credit_price = None if a.from_rows else detect_credit_price(a.conn)
        price_source = "auto-detected" if a.credit_price else "assumed"
        if a.credit_price is None:
            a.credit_price = 3.0
    os.makedirs(a.out, exist_ok=True)

    org_filter = ""
    if a.org:
        safe_org = str(a.org).replace("'", "''")
        org_filter = f"and j:\"sourceUrl\"::string ilike '%/{safe_org}/%'"
    sql = (SQL.replace("{DAYS}", str(a.days)).replace("{ORG_FILTER}", org_filter)
              .replace("{MIN_RUNS}", str(a.min_runs)).replace("{LIMIT}", str(a.limit)))

    coverage_rows, materialization_rows, warehouse_rows, warnings = [], [], [], []
    if a.org:
        warnings.append(
            "Org-scoped totals exclude Sigma-tagged queries without a sourceUrl "
            "because those queries cannot be assigned safely to an org."
        )
        warnings.append(
            "Warehouse idle context is omitted for org scope because warehouse "
            "metering cannot be safely assigned to one Sigma org."
        )
    if a.from_rows:
        with open(a.from_rows) as f:
            supplied = json.load(f)
        if isinstance(supplied, dict) and "workload" in supplied:
            rows = supplied.get("workload", [])
            coverage_rows = supplied.get("coverage", [])
            materialization_rows = supplied.get("materializations", [])
            if not a.org:
                warehouse_rows = supplied.get("warehouses", [])
        else:
            rows = supplied.get("rows", supplied) if isinstance(supplied, dict) else supplied
    else:
        print(f"querying Snowflake ACCOUNT_USAGE ({a.days}d, "
              f"{'org='+a.org if a.org else 'account-wide'}) ...", file=sys.stderr)
        rows = run_sql(a.conn, sql)
        coverage_rows = run_sql(
            a.conn, COVERAGE_SQL.replace("{DAYS}", str(a.days))
            .replace("{ORG_FILTER}", org_filter)
        )
        mat_sql = (MATERIALIZATION_SQL.replace("{DAYS}", str(a.days))
                   .replace("{ORG_FILTER}", org_filter))
        try:
            materialization_rows = run_sql(a.conn, mat_sql)
        except Exception as e:
            warnings.append("Materialization utilization unavailable: " + str(e)[:240])
        if not a.org:
            try:
                warehouse_rows = run_sql(
                    a.conn, WAREHOUSE_SQL.replace("{DAYS}", str(a.days))
                )
            except Exception as e:
                warnings.append("Warehouse idle analysis unavailable: " + str(e)[:240])

    rows = [coerce_row(r) for r in rows]
    materialization_rows = [coerce_row(r) for r in materialization_rows]
    by_key = {(r.get("OBJECT"), r.get("ELEMENT")): r for r in rows}
    for mat in materialization_rows:
        key = (mat.get("OBJECT"), mat.get("ELEMENT"))
        target = by_key.get(key)
        if target is None:
            target = {
                "ORG": mat.get("ORG"),
                "OBJECT": mat.get("OBJECT"),
                "ELEMENT": mat.get("ELEMENT"),
                "SAMPLE_URL": mat.get("SAMPLE_URL"),
                "RUNS": mat.get("MATCHED_MATERIALIZED_READS", 0),
                "CREDITS": mat.get("MATCHED_READ_CREDITS", 0),
                "QAS_CREDITS": mat.get("MATCHED_READ_QAS_CREDITS", 0),
                "AVG_SEC": 0.0,
                "P50_SEC": 0.0,
                "P95_SEC": mat.get("MATCHED_READ_P95_SEC", 0),
                "MAX_SEC": 0.0,
                "TOTAL_SEC": 0.0,
                "MAX_BYTES": 0.0,
            }
            rows.append(target)
            by_key[key] = target
        target.update({
            k: v for k, v in mat.items()
            if k.startswith("MATERIALIZATION_") or k.startswith("MATCHED_")
            or k.startswith("UNMATCHED_") or k.startswith("WORKBOOK_UNMATCHED_")
            or k in {"HAS_CONTROLS", "CONTROL_TARGETS_RESOLVED",
                     "LINEAGE_COMPLETE"}
        })
        target["HAS_EXISTING_SCHEDULE"] = True

    for r in rows:
        rec = recommend(r, model_config, a.days, a.credit_price)
        r.update(rec)
        r["SCORE"] = round(score(r, model_config), 2)
        r["DOLLARS"] = round(
            (r.get("CREDITS", 0) + r.get("QAS_CREDITS", 0)
             + r.get("MATERIALIZATION_CREDITS", 0)
             + r.get("MATERIALIZATION_QAS_CREDITS", 0))
            * a.credit_price, 2
        )
        r["TOTAL_CREDITS"] = round(
            r.get("CREDITS", 0) + r.get("QAS_CREDITS", 0)
            + r.get("MATERIALIZATION_CREDITS", 0)
            + r.get("MATERIALIZATION_QAS_CREDITS", 0), 4
        )
        r["CURRENT_MONTHLY_COST"] = round(
            r["DOLLARS"] * 30.0 / max(a.days, 1), 2
        )
        r["PROJECTED_MONTHLY_COST"] = round(
            max(r["CURRENT_MONTHLY_COST"] - r["SAVINGS_EXPECTED"], 0), 2
        )
    rows.sort(key=lambda r: -r["SCORE"])

    coverage = {str(k).lower(): v for k, v in
                (coverage_rows[0].items() if coverage_rows else [])}
    candidate_credits = round(sum(
        r.get("CREDITS", 0) + r.get("QAS_CREDITS", 0)
        + r.get("MATERIALIZATION_CREDITS", 0)
        + r.get("MATERIALIZATION_QAS_CREDITS", 0)
        for r in rows
    ), 4)
    all_credits = (
        float(coverage.get("all_sigma_credits", candidate_credits) or 0)
        + float(coverage.get("all_qas_credits", 0) or 0)
    )
    all_queries = int(float(coverage.get(
        "all_sigma_queries", sum(r.get("RUNS", 0) for r in rows)
    ) or 0))
    attributable_credits = (
        float(coverage.get("attributable_credits", candidate_credits) or 0)
        + float(coverage.get("attributable_qas_credits", 0) or 0)
    )
    materialization_credits = (
        float(coverage.get("materialization_credits", 0) or 0)
        + float(coverage.get("materialization_qas_credits", 0) or 0)
    )
    mapped_credits = attributable_credits + materialization_credits
    warehouse = ({str(k).lower(): v for k, v in warehouse_rows[0].items()}
                 if warehouse_rows else {})
    action_counts = {}
    for r in rows:
        action_counts[r["ACTION"]] = action_counts.get(r["ACTION"], 0) + 1
    for r in rows:
        r.pop("_IGNORE", None)
    totals = {
        "queries": all_queries,
        "credits": round(all_credits, 4),
        "dollars": round(all_credits * a.credit_price, 2),
        "candidate_credits": candidate_credits,
        "attributable_credits": round(attributable_credits, 4),
        "credit_coverage_pct": round(
            mapped_credits / all_credits * 100, 2
        ) if all_credits else None,
        "objects": len({r.get("OBJECT") for r in rows if r.get("OBJECT")}),
        "orgs": len({r.get("ORG") for r in rows if r.get("ORG")}),
        "actions": action_counts,
        "estimated_monthly_savings": round(
            sum(r.get("SAVINGS_EXPECTED", 0) for r in rows), 2
        ),
    }
    inv = {
        "schema_version": 2,
        "generated": datetime.now(timezone.utc).isoformat(),
        "days": a.days,
        "scope": a.org or "account-wide",
        "totals": totals,
        "coverage": {
            "all_sigma_queries": all_queries,
            "all_sigma_credits": round(all_credits, 4),
            "attributable_queries": int(float(
                coverage.get("attributable_queries", sum(r["RUNS"] for r in rows))
            ) or 0),
            "attributable_credits": round(attributable_credits, 4),
            "materialization_queries": int(float(
                coverage.get("materialization_queries", 0) or 0
            )),
            "materialization_credits": round(materialization_credits, 4),
            "unattributed_queries": int(float(
                coverage.get("unattributed_queries", 0) or 0
            )),
            "unattributed_credits": round(
                float(coverage.get("unattributed_credits", 0) or 0)
                + float(coverage.get("unattributed_qas_credits", 0) or 0), 4
            ),
        },
        "warehouse": warehouse,
        "warnings": warnings,
        "candidates": rows,
        "config": {
            **model_config,
            "credit_price": a.credit_price,
            "credit_price_source": price_source,
        },
    }
    with open(os.path.join(a.out, "inventory.json"), "w") as f:
        json.dump(inv, f, indent=2)
    write_md(a.out, inv)
    print(f"\nReport: {os.path.join(a.out, 'REPORT.md')}", file=sys.stderr)


def write_md(outdir, inv):
    L, w = [], lambda s="": L.append(s)
    t = inv["totals"]
    cfg = inv.get("config", {})
    coverage = inv.get("coverage", {})
    warehouse = inv.get("warehouse", {})
    w("# Sigma Performance & Cost Opportunities\n")
    w(f"_Scope: **{inv['scope']}** · last {inv['days']} days · "
      f"{t['queries']:,} Sigma queries · {t['credits']:.2f} credits "
      f"(~${t.get('dollars',0):,.0f}) · generated {inv['generated'][:10]} · "
      f"**analysis is read-only**_\n")
    pct = t.get("credit_coverage_pct")
    w(f"Attribution coverage: **{pct if pct is not None else 'unknown'}%** of Sigma "
      f"query credits map to a source URL. Unattributed/system activity remains a separate "
      f"cost pool and is not silently dropped.\n")
    w("## Recommended decisions\n")
    w("| # | Object | Element | Action | Runs | Credits | p95 s | Refreshes | "
      "Matched reads | Confidence |")
    w("|---:|---|---|---|---:|---:|---:|---:|---:|---|")
    for i, r in enumerate(inv["candidates"][:25], 1):
        obj = (r.get("OBJECT") or "").replace("/workbook/", "wb: ").replace(
            "/data-model/", "dm: ").replace("/report/", "rpt: ")
        url = r.get("SAMPLE_URL")
        obj_cell = f"[{obj}]({url})" if url else obj
        w(f"| {i} | {obj_cell} | {r.get('ELEMENT','')} | {r['ACTION']} | "
          f"{r.get('RUNS',0)} | "
          f"{r.get('TOTAL_CREDITS',r.get('CREDITS',0)):.4f} | "
          f"{r.get('P95_SEC',0):.2f} | {r.get('MATERIALIZATION_RUNS',0)} | "
          f"{r.get('MATCHED_MATERIALIZED_READS',0)} | {r['CONFIDENCE']} |")
    w("")
    for r in inv["candidates"][:10]:
        w(f"### {r['ACTION']}: {r.get('OBJECT','')} / {r.get('ELEMENT','')}\n")
        w(f"- Why: {r['WHY']}")
        w(f"- Performance: {r['PERFORMANCE_IMPACT']}")
        w(f"- Validate: {r['VALIDATION']}\n")
    if warehouse:
        w("## Warehouse context\n")
        w(f"- Compute: {warehouse.get('warehouse_compute_credits','?')} credits")
        w(f"- Estimated idle: {warehouse.get('estimated_idle_credits','?')} credits "
          f"({warehouse.get('estimated_idle_pct','?')}%)")
        w("- Idle is a warehouse-level upper bound; it is not automatically attributed "
          "to Sigma or to any one workbook.\n")
    w("## Method & caveats\n")
    w("- Query cost comes from `QUERY_ATTRIBUTION_HISTORY`; materialization utilization "
      "matches `ACCESS_HISTORY.objects_modified` to `direct_objects_accessed`.")
    w("- A removal recommendation requires a measured no-materialization baseline. "
      "Refresh cost alone is never treated as proof that removal is safe.")
    w("- Controls can bypass materialization. Unresolved target bindings force manual review.")
    w("- `ACCOUNT_USAGE` is delayed and query attribution excludes idle, storage, transfer, "
      "cloud services, and most serverless costs.")
    if inv.get("warnings"):
        w("\n## Warnings\n")
        for warning in inv["warnings"]:
            w(f"- {warning}")
    with open(os.path.join(outdir, "REPORT.md"), "w") as f:
        f.write("\n".join(L))


if __name__ == "__main__":
    main()
