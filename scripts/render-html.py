#!/usr/bin/env python3
"""inventory.json -> customer-facing Sigma performance-and-cost report.
   python3 scripts/render-html.py --inv out/inventory.json --out out/report.html --customer "Acme"
"""
import argparse, html, json, datetime


def esc(s):
    return html.escape(str(s), quote=True)


def render(inv, customer):
    t = inv["totals"]
    cands = inv["candidates"]
    gen = inv.get("generated", "")[:10] or datetime.date.today().isoformat()
    cfg = inv.get("config", {})
    dollars = t.get("dollars")
    coverage = t.get("credit_coverage_pct")
    action_counts = t.get("actions", {})
    kpis = [
        ("Sigma queries", f"{t['queries']:,}", f"last {inv['days']} days"),
        ("Compute cost", f"${dollars:,.0f}" if dollars else f"{t['credits']:.2f} cr",
         f"{t['credits']:.1f} credits @ ${cfg.get('credit_price','?')}"),
        ("Attribution coverage", f"{coverage:.1f}%" if coverage is not None else "unknown",
         "Sigma credits mapped to a source URL"),
        ("Modeled savings", f"${t.get('estimated_monthly_savings',0):,.0f}/mo",
         f"{sum(action_counts.values())} reviewed opportunities"),
    ]
    kpi_html = "".join(
        f"<div class='kpi'><div class='kpi-v'>{esc(v)}</div><div class='kpi-l'>{esc(l)}</div>"
        f"<div class='kpi-s'>{esc(s)}</div></div>" for l, v, s in kpis)
    rows = ""
    for i, c in enumerate(cands[:25], 1):
        obj = (c["OBJECT"] or "").replace("/workbook/", "wb: ").replace("/data-model/", "dm: ").replace("/report/", "rpt: ")
        url = c.get("SAMPLE_URL")
        obj_cell = f"<a href='{esc(url)}' target='_blank' rel='noopener'>{esc(obj)}</a>" if url else esc(obj)
        rec = c.get("ACTION") or c.get("RECOMMENDATION")
        cls = ("keep" if rec.startswith("Keep") else
               "remove" if rec.startswith("Remove") else
               "retune" if rec.startswith("Retune") else
               "investigate" if rec.startswith("Investigate") else
               "improve" if rec.startswith("Optimize") else
               "add" if rec.startswith("Add") else "monitor")
        rows += (f"<tr><td>{i}</td><td class='obj'>{obj_cell}</td><td>{esc(c['ELEMENT'])}</td>"
                 f"<td class='num'>{c.get('RUNS',0)}</td>"
                 f"<td class='num'>{c.get('TOTAL_CREDITS',c.get('CREDITS',0)):.4f}</td>"
                 f"<td class='num'>{c.get('P95_SEC',0):.2f}</td>"
                 f"<td class='num'>{c.get('MATERIALIZATION_RUNS',0)}</td>"
                 f"<td class='num'>{c.get('MATCHED_MATERIALIZED_READS',0)}</td>"
                 f"<td><span class='pill {cls}'>{esc(rec)}</span>"
                 f"<div class='why'>{esc(c['WHY'])}</div>"
                 f"<div class='why'><b>Validate:</b> {esc(c.get('VALIDATION',''))}</div></td></tr>")
    return PAGE.format(customer=esc(customer), gen=esc(gen), scope=esc(inv["scope"]),
                       days=inv["days"], kpis=kpi_html, rows=rows,
                       coverage=esc(coverage if coverage is not None else "unknown"))


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sigma Performance &amp; Cost — {customer}</title><style>
:root{{--ink:#1a2233;--mut:#5b6779;--line:#e6e9f0;--bg:#f6f8fb;--accent:#2f6f4f;--mat:#2f9e44;--rev:#868e96;}}
*{{box-sizing:border-box}}body{{margin:0;font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,Arial,sans-serif;color:var(--ink);background:var(--bg)}}
.wrap{{max-width:980px;margin:0 auto;padding:0 28px 80px}}
header{{background:linear-gradient(135deg,#173a2b,#2f9e44);color:#fff;padding:48px 0 96px}}
header .wrap{{padding-bottom:0}}.eyebrow{{text-transform:uppercase;letter-spacing:.14em;font-size:12px;opacity:.85;margin:0}}
header h1{{font-size:30px;margin:8px 0 4px}}header .sub{{opacity:.92}}
.ro{{display:inline-block;margin-top:16px;background:rgba(255,255,255,.15);border:1px solid rgba(255,255,255,.3);padding:5px 12px;border-radius:20px;font-size:12.5px}}
.kpis{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:-52px 0 0}}
.kpi{{background:#fff;border:1px solid var(--line);border-radius:12px;padding:16px;box-shadow:0 6px 20px rgba(20,30,60,.06)}}
.kpi-v{{font-size:24px;font-weight:700;color:var(--accent)}}.kpi-l{{font-size:13px;font-weight:600;margin-top:2px}}.kpi-s{{font-size:12px;color:var(--mut)}}
h2{{font-size:20px;margin:40px 0 8px;padding-bottom:8px;border-bottom:2px solid var(--line)}}
table{{width:100%;border-collapse:collapse;background:#fff;border:1px solid var(--line);border-radius:12px;overflow:hidden;font-size:13px;margin-top:12px}}
th,td{{padding:9px 11px;text-align:left;border-bottom:1px solid var(--line);vertical-align:top}}
th{{background:#eef3f0;font-size:11.5px;text-transform:uppercase;letter-spacing:.04em;color:var(--mut)}}
td.num{{text-align:right;font-variant-numeric:tabular-nums}}td.obj{{font-weight:600}}
tr:last-child td{{border-bottom:none}}
.pill{{font-size:11px;font-weight:700;padding:2px 8px;border-radius:6px;color:#fff;white-space:nowrap}}
.pill.keep{{background:#2f9e44}}.pill.add,.pill.improve{{background:#1971c2}}
.pill.retune{{background:#e67700}}.pill.investigate{{background:#f08c00}}
.pill.remove{{background:#c92a2a}}.pill.monitor{{background:var(--rev)}}
.why{{color:var(--mut);font-size:11.5px;margin-top:4px}}
.card{{background:#fff;border:1px solid var(--line);border-radius:12px;padding:18px 22px;margin-top:14px}}
.card h3{{margin:0 0 6px;font-size:16px}}.opt{{border-left:4px solid var(--mat);padding-left:14px;margin:12px 0}}
.opt.a{{border-left-color:#1971c2}}code{{background:#eef1f8;padding:1px 5px;border-radius:4px;font-family:"SF Mono",Menlo,Consolas,monospace;font-size:12px}}
.note{{color:var(--mut);font-size:12.5px}}footer{{color:var(--mut);font-size:12.5px;margin-top:36px;border-top:1px solid var(--line);padding-top:14px}}
</style></head><body>
<header><div class="wrap"><p class="eyebrow">Sigma · Performance per Dollar</p>
<h1>{customer}</h1><div class="sub">Fast results at the lowest sustainable cost · scope: {scope} · last {days} days</div>
<span class="ro">🔒 Read-only analysis — no changes made to Snowflake or Sigma</span></div></header>
<div class="wrap">
<div class="kpis">{kpis}</div>
<h2>Recommended decisions</h2>
<p class="note">Coverage is <b>{coverage}%</b> of Sigma query credits. Recommendations compare
query cost and latency with observed materialization refreshes and reads. A schedule is never
marked safe to remove from refresh cost alone.</p>
<table><thead><tr><th>#</th><th>Object</th><th>Element</th><th class="num">Runs</th><th class="num">Credits</th>
<th class="num">p95 s</th><th class="num">Refreshes</th><th class="num">Matched reads</th><th>Decision</th></tr></thead>
<tbody>{rows}</tbody></table>

<h2>Decision policy</h2>
<div class="card">
<div class="opt a"><h3>Optimize before caching</h3>Fix pruning, spill, joins, calculations,
and warehouse pressure when a single run is intrinsically expensive.</div>
<div class="opt"><h3>Keep, retune, investigate, remove, or add</h3>Use observed served reads per
refresh and p95 latency. Controls or incomplete lineage require review. Removal requires a measured
no-materialization baseline and a rollback plan.</div>
</div>
<footer>Read-only analysis: <code>QUERY_HISTORY</code>, <code>QUERY_ATTRIBUTION_HISTORY</code>,
<code>ACCESS_HISTORY</code>, and <code>WAREHOUSE_METERING_HISTORY</code>. Prepared for {customer}.</footer>
</div></body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--inv", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--customer", default="the organization")
    a = ap.parse_args()
    open(a.out, "w").write(render(json.load(open(a.inv)), a.customer))
    print("wrote", a.out)


if __name__ == "__main__":
    main()
