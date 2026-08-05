#!/usr/bin/env python3
"""inventory.json -> customer-facing report.html for the materialization advisor.
   python3 scripts/render-html.py --inv out/inventory.json --out out/report.html --customer "Acme"
"""
import argparse, html, json, datetime


def esc(s):
    return html.escape(str(s), quote=True)


def render(inv, customer):
    t = inv["totals"]
    cands = inv["candidates"]
    mat = [c for c in cands if c["RECOMMENDATION"].startswith("Materialize")]
    imp = [c for c in cands if c["RECOMMENDATION"].startswith("Improve")]
    gen = inv.get("generated", "")[:10] or datetime.date.today().isoformat()
    cfg = inv.get("config", {})
    dollars = t.get("dollars")
    kpis = [
        ("Sigma queries", f"{t['queries']:,}", f"last {inv['days']} days"),
        ("Compute cost", f"${dollars:,.0f}" if dollars else f"{t['credits']:.2f} cr",
         f"{t['credits']:.1f} credits @ ${cfg.get('credit_price','?')}"),
        ("Materialize", f"{len(mat)}", "repetitive + non-trivial"),
        ("Improve query", f"{len(imp)}", "slow / large single runs"),
    ]
    kpi_html = "".join(
        f"<div class='kpi'><div class='kpi-v'>{esc(v)}</div><div class='kpi-l'>{esc(l)}</div>"
        f"<div class='kpi-s'>{esc(s)}</div></div>" for l, v, s in kpis)
    rows = ""
    for i, c in enumerate(cands[:25], 1):
        obj = (c["OBJECT"] or "").replace("/workbook/", "wb: ").replace("/data-model/", "dm: ").replace("/report/", "rpt: ")
        url = c.get("SAMPLE_URL")
        obj_cell = f"<a href='{esc(url)}' target='_blank' rel='noopener'>{esc(obj)}</a>" if url else esc(obj)
        rec = c["RECOMMENDATION"]
        if rec.startswith("Materialize"):
            badge, cls = "B · Materialize", "mat"
        elif rec.startswith("Improve"):
            badge, cls = "A · Improve query", "imp"
        else:
            badge, cls = "Monitor", "rev"
        rows += (f"<tr><td>{i}</td><td class='obj'>{obj_cell}</td><td>{esc(c['ELEMENT'])}</td>"
                 f"<td class='num'>{c['RUNS']}</td><td class='num'>{c['CREDITS']:.4f}</td>"
                 f"<td class='num'>{c['AVG_SEC']:.2f}</td><td class='num'>{c['MAX_SEC']:.2f}</td>"
                 f"<td><span class='pill {cls}'>{esc(badge)}</span><div class='why'>{esc(c['WHY'])}</div></td></tr>")
    return PAGE.format(customer=esc(customer), gen=esc(gen), scope=esc(inv["scope"]),
                       days=inv["days"], kpis=kpi_html, rows=rows)


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sigma → Snowflake Materialization — {customer}</title><style>
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
.pill.mat{{background:var(--mat)}}.pill.imp{{background:#1971c2}}.pill.rev{{background:var(--rev)}}
.why{{color:var(--mut);font-size:11.5px;margin-top:4px}}
.card{{background:#fff;border:1px solid var(--line);border-radius:12px;padding:18px 22px;margin-top:14px}}
.card h3{{margin:0 0 6px;font-size:16px}}.opt{{border-left:4px solid var(--mat);padding-left:14px;margin:12px 0}}
.opt.a{{border-left-color:#1971c2}}code{{background:#eef1f8;padding:1px 5px;border-radius:4px;font-family:"SF Mono",Menlo,Consolas,monospace;font-size:12px}}
.note{{color:var(--mut);font-size:12.5px}}footer{{color:var(--mut);font-size:12.5px;margin-top:36px;border-top:1px solid var(--line);padding-top:14px}}
</style></head><body>
<header><div class="wrap"><p class="eyebrow">Sigma · Snowflake Cost &amp; Materialization</p>
<h1>{customer}</h1><div class="sub">High-compute Sigma queries and how to reduce them · scope: {scope} · last {days} days</div>
<span class="ro">🔒 Read-only analysis — no changes made to Snowflake or Sigma</span></div></header>
<div class="wrap">
<div class="kpis">{kpis}</div>
<h2>Top compute candidates</h2>
<p class="note">Ranked by attributed Snowflake credits × frequency. <b>A · Improve query</b> lowers cost per run;
<b>B · Materialize</b> removes redundant runs; <b>Monitor</b> = too cheap to be worth either today.
An object is only flagged <b>Materialize</b> when it is genuinely repetitive <i>and</i> non-trivial per run —
caching a fast, cheap query costs more to refresh than it saves.</p>
<table><thead><tr><th>#</th><th>Object</th><th>Element</th><th class="num">Runs</th><th class="num">Credits</th>
<th class="num">Avg s</th><th class="num">Max s</th><th>Recommended remediation</th></tr></thead>
<tbody>{rows}</tbody></table>

<h2>Two ways to remediate</h2>
<div class="card">
<div class="opt a"><h3>Option A — Improve the query (workbook / data model)</h3>
Pull the object's spec via the Sigma API and fix what makes a single run expensive: push heavy
calc-column logic upstream, declare relationships instead of cross-element <code>Lookup()</code>,
drop unused columns, pre-aggregate. Best when one run is slow or scans a lot.</div>
<div class="opt"><h3>Option B — Materialize via the Sigma API</h3>
Cache an element's result so repeat views read a stored table instead of recomputing — best for
<i>repetitive</i> objects. Create, update, and delete a schedule's cron cadence (no destination
field) end to end via the API, then trigger/monitor refreshes:
<div style="margin-top:8px"><code>materialize.py list --workbook &lt;id&gt;</code> → <code>materialize.py create --workbook &lt;id&gt; --sheet &lt;elementId&gt; --cron "0 0 * * *"</code> → <code>materialize.py run --workbook &lt;id&gt; --sheet &lt;elementId&gt;</code></div>
<div class="note" style="margin-top:8px">Note: schedule create/update/delete are a private-beta REST surface — see refs/materialization-playbook.md for exact shapes and a live-deployment caveat.</div></div>
</div>
<footer>Read-only: <code>SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY</code> + <code>QUERY_ATTRIBUTION_HISTORY</code>,
joined on query_id; Sigma objects resolved from each query's <code>QUERY_TAG</code>. Prepared for {customer}.</footer>
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
