# Sigma Materialization Advisor

Find the Sigma workbooks, data models, and elements driving the most **Snowflake
compute**, quantify them in **dollars**, and act — either **improve the query** in the
data model or **materialize** it via the Sigma API. Read-only analysis; remediation is
explicit and opt-in.

It answers: *"Which of our Sigma dashboards are actually costing us money in Snowflake,
and what's the highest-leverage fix for each?"*

> Works as a [Claude Code / Agent skill](https://docs.claude.com/en/docs/claude-code)
> (via `SKILL.md`) **and** as a standalone CLI (Python 3 stdlib + the `snow` CLI). The
> cost-analysis SQL also runs natively in **Snowflake / Cortex Code** — see below.

<p align="center"><i>Sample report (synthetic data): <a href="example/sample-report.html"><code>example/sample-report.html</code></a></i></p>

## How it works

Sigma stamps every warehouse query's `QUERY_TAG` with `Sigma Σ {sourceUrl, email, kind}`.
Snowflake's `QUERY_ATTRIBUTION_HISTORY` gives **real compute credits per query**. Join the
two and you can attribute Snowflake cost to the exact Sigma object that caused it.

```
analyze.py ─► SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY  ⨝  QUERY_ATTRIBUTION_HISTORY
           ─► parse QUERY_TAG → org / workbook|data-model / element
           ─► rank candidates, convert credits→$  → inventory.json + REPORT.md
render-html.py ─► report.html         materialize.py ─► trigger/monitor via Sigma API
```

## Two remediation levers (per candidate)
- **A — Improve the query** *(in the data model)*: push heavy calc columns upstream,
  declare relationships instead of cross-element `Lookup()`, drop unused columns,
  pre-aggregate. Fix it once in the data model and every workbook benefits. Best when a
  single run is slow or scans a lot.
- **B — Materialize via the Sigma API**: cache an element's result so repeat views read a
  stored table. Best when an object is *repetitive*. The schedule is created once in the
  Sigma UI (no create-schedule API endpoint); the **refresh is then fully API-driven** —
  `materialize.py run` triggers and polls it.

An object is only flagged **Materialize** when it's genuinely repetitive **and** non-trivial
(`runs ≥ N` **and** (`avg ≥ S sec` **or** `≥ C credits`)). Caching a fast, cheap query costs
more to refresh than it saves — so most objects correctly come back **Monitor**.

## Intake (ask before the first run)
Thresholds depend on the customer's economics/SLAs. The skill asks:
1. **How fresh must dashboards be?** (real-time → materialization mostly off the table)
2. **Primary goal?** cut cost / speed up dashboards / both → sets ranking weight (`--goal`)
3. **How aggressive?** conservative / balanced / aggressive → sets the candidate bar

**$/credit is auto-detected** from `SNOWFLAKE.ORGANIZATION_USAGE` (effective rate); only
asked if that's unavailable. Persist answers in `advisor-config.json` (see
`advisor-config.example.json`) and pass `--config`.

## Quick start (CLI)
Requires Python 3.8+ (stdlib only) and the [`snow` CLI](https://docs.snowflake.com/en/developer-guide/snowflake-cli/index)
with read access to `SNOWFLAKE.ACCOUNT_USAGE`.

```bash
# analyze (read-only)
python3 scripts/analyze.py --conn <snow-conn> --days 30 --goal both --out out
#   add --org <slug> to scope to one Sigma org; thresholds: --mat-min-runs / -avg-sec / -credits

# report
python3 scripts/render-html.py --inv out/inventory.json --out out/report.html --customer "Acme"

# remediate (opt-in) — needs Sigma REST creds:
eval "$(/path/to/get-token.sh)"          # sets SIGMA_API_TOKEN + SIGMA_BASE_URL
python3 scripts/materialize.py list --workbook <workbookId>          # find sheetId
python3 scripts/materialize.py run  --workbook <workbookId> --sheet <sheetId>
```

## Running in Snowflake / Cortex Code
The cost analysis is portable SQL — no external CLI needed, and the data never leaves the
account:

1. Open `sql/sigma_cost.sql` in a Snowflake worksheet **or Cortex Code**, set the three
   `SET` vars (`days`, `org`, `min_runs`), and run it.
2. (Optional, to get the formatted report/HTML) export the result rows as JSON and render:
   ```bash
   python3 scripts/analyze.py --from-rows rows.json --goal both --out out
   python3 scripts/render-html.py --inv out/inventory.json --out out/report.html --customer "Acme"
   ```

So the heavy lifting can stay fully in-warehouse (Cortex Code), while the Sigma-side
mapping/remediation runs wherever you have the Sigma API.

## Scripts
| File | Purpose |
|---|---|
| `scripts/analyze.py` | credit attribution → ranked candidates → `inventory.json` + `REPORT.md` (`--from-rows` for the Cortex path) |
| `scripts/materialize.py` | `list` / `run` (trigger + poll) a Sigma materialization via REST |
| `scripts/render-html.py` | `inventory.json` → customer-facing `report.html` |
| `sql/sigma_cost.sql` | the attribution query, standalone for Snowflake/Cortex Code |
| `example/make-sample.py` | regenerate the synthetic example |

## Privacy & safety
Read-only by construction; `materialize.py run` is the only state-changing action and only
when you invoke it. See [`PRIVACY.md`](PRIVACY.md). The committed [`example/`](example/) is
**fully synthetic** (fictional "Northwind Trading Co.") — no real data. Real outputs are
customer-confidential; `.gitignore` keeps `*-out/` and creds out of git.

## License
MIT — see [`LICENSE`](LICENSE).
