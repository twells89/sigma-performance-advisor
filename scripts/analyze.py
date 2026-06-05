#!/usr/bin/env python3
"""
sigma-materialization-advisor — find high-compute Sigma queries in Snowflake and
recommend materialization to cut credits.

Reads Snowflake ACCOUNT_USAGE (read-only) via the `snow` CLI, attributes each query's
attributed compute credits back to the Sigma object that issued it (Sigma stamps every
warehouse query's QUERY_TAG with `Sigma Σ {json}` containing sourceUrl / email / kind),
rolls up by org → workbook/data-model → element, ranks materialization candidates, and
writes inventory.json + REPORT.md.

Read-only: SELECTs against SNOWFLAKE.ACCOUNT_USAGE only.

    python3 scripts/analyze.py --conn default --days 30 --out out [--org <org-slug>]
"""
import argparse, json, os, subprocess, sys, re
from datetime import datetime, timezone

# Aggregates in-warehouse (cheap) at workbook+element grain, joining real per-query
# credits from QUERY_ATTRIBUTION_HISTORY. {DAYS} and {ORG_FILTER} are injected.
SQL = r"""
with qh as (
  select query_id, total_elapsed_time, bytes_scanned, partitions_scanned, partitions_total,
         try_parse_json(regexp_substr(query_tag, '\\{.*\\}')) as j
  from snowflake.account_usage.query_history
  where start_time > dateadd('day', -{DAYS}, current_timestamp())
    and query_tag ilike 'Sigma %'
    and execution_status = 'SUCCESS'
    and query_type = 'SELECT'
),
s as (
  select query_id, total_elapsed_time, bytes_scanned, partitions_scanned, partitions_total,
         j:"sourceUrl"::string  as source_url,
         j:"kind"::string       as kind,
         split_part(j:"sourceUrl"::string, '/', 4) as org,
         regexp_substr(j:"sourceUrl"::string, '/(workbook|report|data-model)/[^?]+') as object,
         regexp_substr(j:"sourceUrl"::string, '[?&]:displayNodeId=([^&]+)', 1, 1, 'e', 1) as element
  from qh
  where j:"sourceUrl" is not null
    {ORG_FILTER}
),
att as (
  select query_id, sum(credits_attributed_compute) as credits
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
  round(avg(s.total_elapsed_time)/1000.0, 2)      as avg_sec,
  round(max(s.total_elapsed_time)/1000.0, 2)      as max_sec,
  round(sum(s.total_elapsed_time)/1000.0, 1)      as total_sec,
  max(s.bytes_scanned)                            as max_bytes,
  max(s.source_url)                               as sample_url
from s
left join att using (query_id)
group by 1, 2, 3
having count(*) >= {MIN_RUNS}
order by credits desc, total_sec desc
limit {LIMIT};
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
        sys.exit(f"snow returned no JSON.\nstdout:\n{out[:500]}\nstderr:\n{p.stderr[-800:]}")
    return json.loads(out[i:])


# Thresholds for *worth materializing*. Materialization has its own refresh cost +
# operational overhead, so it only pays off when an object is BOTH repetitive AND
# non-trivial per run (or non-trivial cumulative cost). Tunable via CLI flags.
CFG = {"min_runs": 12, "min_avg_sec": 3.0, "min_credits": 0.5, "big_bytes": 1_000_000_000,
       "goal": "both"}


def recommend(row):
    """Honest remediation call. Materialize only when repetitive AND non-trivial;
    improve when a single run is slow/large; otherwise leave it alone."""
    obj = row["OBJECT"] or ""
    runs, credits, avg = row["RUNS"], row["CREDITS"], row["AVG_SEC"]
    big = (row.get("MAX_BYTES") or 0) > CFG["big_bytes"]
    is_dm = "/data-model/" in obj
    repetitive = runs >= CFG["min_runs"]
    heavy_run = avg >= CFG["min_avg_sec"]
    costly = credits >= CFG["min_credits"]

    if repetitive and (heavy_run or costly):
        scope = "data model" if is_dm else "workbook element"
        lead = ("one materialization serves every workbook built on it"
                if is_dm else "repeat views read a cached table instead of recomputing")
        return (f"Materialize ({scope})",
                f"Repetitive ({runs} runs) and non-trivial "
                f"({avg:.1f}s avg, {credits:.2f} cr) — {lead}.")
    if big or (heavy_run and not repetitive):
        return ("Improve the query",
                f"Heavy per run ({avg:.1f}s avg" + (", >1 GB scanned" if big else "") +
                f") but only {runs} run(s) — fix it in the **data model** (push calc columns "
                f"upstream, declare relationships instead of cross-element Lookup, drop unused "
                f"columns / pre-aggregate) so every workbook benefits. Caching an infrequent "
                f"query won't pay off.")
    return ("Monitor — not worth materializing",
            f"Low cost & latency ({avg:.2f}s avg, {credits:.3f} cr over the window). "
            f"Materialization refresh would likely cost more than it saves; revisit if volume grows.")


def score(row):
    # Ranking reflects the customer's stated goal (intake question).
    c, t, a, r = row["CREDITS"] * 1000, row["TOTAL_SEC"], row["AVG_SEC"], row["RUNS"]
    goal = CFG.get("goal", "both")
    if goal == "cost":
        return c + t * 0.1                      # biggest credit/$ drains first
    if goal == "latency":
        return a * 80 + t * 1.0 + r * 0.1       # slowest user experience first
    return c + t * 0.3 + r * 0.05               # balanced


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--conn", default="default", help="snow CLI connection name")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--org", default=None, help="Sigma org slug to scope to (else account-wide)")
    ap.add_argument("--min-runs", type=int, default=2, help="min runs to appear at all")
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--out", default="materialization-out")
    # "worth materializing" thresholds (an object must clear these to be recommended)
    ap.add_argument("--mat-min-runs", type=int, default=CFG["min_runs"])
    ap.add_argument("--mat-min-avg-sec", type=float, default=CFG["min_avg_sec"])
    ap.add_argument("--mat-min-credits", type=float, default=CFG["min_credits"])
    ap.add_argument("--credit-price", type=float, default=None,
                    help="$ per Snowflake credit (default: auto-detect from ORGANIZATION_USAGE, else 3.0)")
    ap.add_argument("--goal", choices=["cost", "latency", "both"], default="both",
                    help="intake: cut cost / speed up dashboards / both — sets ranking weight")
    ap.add_argument("--from-rows", help="render from a JSON array of query rows (e.g. exported "
                    "from Cortex Code / a Snowflake worksheet) instead of running snow")
    ap.add_argument("--config", help="JSON file with any of the above (intake answers); flags win")
    a = ap.parse_args()
    if a.config and os.path.exists(a.config):
        cfg = json.load(open(a.config))
        for k in ("mat_min_runs", "mat_min_avg_sec", "mat_min_credits", "credit_price", "days", "goal"):
            if k in cfg and getattr(a, k) == ap.get_default(k):
                setattr(a, k, cfg[k])
    CFG["min_runs"], CFG["min_avg_sec"], CFG["min_credits"], CFG["goal"] = \
        a.mat_min_runs, a.mat_min_avg_sec, a.mat_min_credits, a.goal
    # Resolve $/credit: explicit flag/config > auto-detect from billing views > $3 default.
    price_source = "provided"
    if a.credit_price is None:
        a.credit_price = detect_credit_price(a.conn)
        price_source = "auto-detected" if a.credit_price else "assumed"
        if a.credit_price is None:
            a.credit_price = 3.0
    a.price_source = price_source
    os.makedirs(a.out, exist_ok=True)

    org_filter = ""
    if a.org:
        org_filter = f"and j:\"sourceUrl\"::string ilike '%/{a.org}/%'"
    sql = (SQL.replace("{DAYS}", str(a.days)).replace("{ORG_FILTER}", org_filter)
              .replace("{MIN_RUNS}", str(a.min_runs)).replace("{LIMIT}", str(a.limit)))

    if a.from_rows:
        # Cortex Code / worksheet path: SQL was run inside Snowflake; rows fed in as JSON.
        rows = json.load(open(a.from_rows))
        rows = rows.get("rows", rows) if isinstance(rows, dict) else rows
        rows = [{k.upper(): v for k, v in r.items()} for r in rows]
    else:
        print(f"querying Snowflake ACCOUNT_USAGE ({a.days}d, "
              f"{'org='+a.org if a.org else 'account-wide'}) ...", file=sys.stderr)
        rows = run_sql(a.conn, sql)
    # snow serializes some numeric columns as strings — coerce.
    for r in rows:
        for k in ("RUNS", "CREDITS", "AVG_SEC", "MAX_SEC", "TOTAL_SEC", "MAX_BYTES"):
            v = r.get(k)
            r[k] = float(v) if v not in (None, "") else 0.0
        r["RUNS"] = int(r["RUNS"])
    for r in rows:
        tech, why = recommend(r)
        r["RECOMMENDATION"], r["WHY"] = tech, why
        r["SCORE"] = round(score(r), 2)
        r.pop("_IGNORE", None)
    rows.sort(key=lambda r: -r["SCORE"])

    credits = round(sum(r["CREDITS"] for r in rows), 4)
    for r in rows:
        r["DOLLARS"] = round(r["CREDITS"] * a.credit_price, 2)
    totals = {
        "queries": sum(r["RUNS"] for r in rows),
        "credits": credits,
        "dollars": round(credits * a.credit_price, 2),
        "objects": len({r["OBJECT"] for r in rows}),
        "orgs": len({r["ORG"] for r in rows}),
        "materialize_candidates": sum(1 for r in rows if r["RECOMMENDATION"].startswith("Materialize")),
        "improve_candidates": sum(1 for r in rows if r["RECOMMENDATION"].startswith("Improve")),
    }
    inv = {"generated": datetime.now(timezone.utc).isoformat(), "days": a.days,
           "scope": a.org or "account-wide", "totals": totals, "candidates": rows,
           "config": {"credit_price": a.credit_price, "credit_price_source": a.price_source,
                      "goal": a.goal, "mat_min_runs": a.mat_min_runs,
                      "mat_min_avg_sec": a.mat_min_avg_sec, "mat_min_credits": a.mat_min_credits}}
    json.dump(inv, open(os.path.join(a.out, "inventory.json"), "w"), indent=2)
    write_md(a.out, inv)
    print(f"\nReport: {os.path.join(a.out, 'REPORT.md')}", file=sys.stderr)


def write_md(outdir, inv):
    L, w = [], lambda s="": L.append(s)
    t = inv["totals"]
    cfg = inv.get("config", {})
    w(f"# Sigma → Snowflake Materialization Opportunities\n")
    w(f"_Scope: **{inv['scope']}** · last {inv['days']} days · "
      f"{t['queries']} Sigma queries · {t['credits']} credits (~${t.get('dollars',0)}) · "
      f"{t['objects']} objects · generated {inv['generated'][:10]} · **read-only**_\n")
    w(f"_Found **{t.get('materialize_candidates',0)}** materialize + "
      f"**{t.get('improve_candidates',0)}** improve candidates. Thresholds: materialize when "
      f"runs ≥ {cfg.get('mat_min_runs')} AND (avg ≥ {cfg.get('mat_min_avg_sec')}s OR "
      f"≥ {cfg.get('mat_min_credits')} cr); ${cfg.get('credit_price')}/credit "
      f"({cfg.get('credit_price_source')})._\n")
    w("Top candidates ranked by attributed compute credits × frequency. Credits come from "
      "`QUERY_ATTRIBUTION_HISTORY`; objects are resolved from each query's Sigma `QUERY_TAG`.\n")
    w("| # | Object | Element | Runs | Credits | Avg s | Max s | Recommended fix |")
    w("|---:|---|---|---:|---:|---:|---:|---|")
    for i, r in enumerate(inv["candidates"][:25], 1):
        obj = (r["OBJECT"] or "").replace("/workbook/", "wb: ").replace("/data-model/", "dm: ").replace("/report/", "rpt: ")
        url = r.get("SAMPLE_URL")
        obj_cell = f"[{obj}]({url})" if url else obj
        w(f"| {i} | {obj_cell} | {r['ELEMENT']} | {r['RUNS']} | {r['CREDITS']} | "
          f"{r['AVG_SEC']} | {r['MAX_SEC']} | {r['RECOMMENDATION']} |")
    w("")
    w("## Two ways to remediate each candidate\n")
    w("For every candidate above you have two levers — one reduces the cost *per run*, the other "
      "removes redundant runs entirely:\n")
    w("**Option A — Improve the query (in the workbook / data model).** Pull the object's spec via "
      "the Sigma API and fix what makes it expensive: push heavy calc-column logic upstream, "
      "declare relationships instead of cross-element `Lookup()`, drop unused columns, or "
      "pre-aggregate. Best when a single run is slow/large. (Pairs with the "
      "`sigma-data-model-assessment` skill, which already flags these patterns.)\n")
    w("**Option B — Materialize via the Sigma API.** Cache the element's result so repeat views "
      "read a stored table instead of recomputing. Best when an object is *repetitive*. "
      "Mechanics:\n")
    w("```\n"
      "# one-time setup (Sigma UI): open the element → ⋮ → Materialization → pick destination + cadence\n"
      "eval \"$(~/.claude/skills/tableau-to-sigma/scripts/get-token.sh)\"\n"
      "python3 scripts/materialize.py list --workbook <workbookId>      # find the sheetId\n"
      "python3 scripts/materialize.py run  --workbook <workbookId> --sheet <sheetId>   # refresh + poll\n"
      "# data models:  materialize.py run --datamodel <dataModelId> --sheet <sheetId>\n"
      "```\n")
    w("> **API note:** the Sigma API can *trigger and monitor* a materialization and *list* "
      "schedules, but the schedule itself (element + destination + cadence) is created once in the "
      "UI — there is no create-schedule endpoint today. After that one-time step the refresh is "
      "fully API-driven and schedulable.\n")
    w("## How to read this\n")
    w("- **Credits** = real attributed compute for that object's queries over the window. "
      "Multiply by your $/credit rate for dollars.\n")
    w("- **Materialization candidates** are objects that are both *expensive* and *repetitive* — "
      "caching their result removes redundant warehouse runs. Data-model elements rank highest "
      "because one materialization benefits every workbook built on them.\n")
    w("## Method & caveats\n")
    w("- Read-only `SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY` + `QUERY_ATTRIBUTION_HISTORY`, joined "
      "on `query_id`; Sigma objects parsed from `QUERY_TAG` (`Sigma Σ {sourceUrl,email,kind}`).\n")
    w("- Only `kind` carrying a `sourceUrl` is attributable; pure scheduler/system queries "
      "(`SigmaSchedulerRobot`, schema introspection) are excluded.\n")
    w("- `ACCOUNT_USAGE` has up to ~3h latency and `QUERY_ATTRIBUTION_HISTORY` covers "
      "warehouse compute (not cloud-services-only queries).\n")
    open(os.path.join(outdir, "REPORT.md"), "w").write("\n".join(L))


if __name__ == "__main__":
    main()
