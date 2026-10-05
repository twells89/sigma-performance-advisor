# Privacy & posture

**Analysis is read-only.** `analyze.py` issues only `SELECT`s against
`SNOWFLAKE.ACCOUNT_USAGE` (`QUERY_HISTORY`, `QUERY_ATTRIBUTION_HISTORY`,
`ACCESS_HISTORY`, and `WAREHOUSE_METERING_HISTORY`). It reads query/object metadata—not
query results or warehouse row data. `enrich.py` uses only Sigma `GET` endpoints.

**Remediation is explicit and opt-in.** Four `materialize.py` subcommands change state,
and only when you invoke one explicitly with a specific `--sheet`/`--workbook`/
`--datamodel`: `create` and `update` set a schedule's cron cadence (public-beta REST
API); `delete` removes a schedule outright and cancels future runs—it has no undo and
prompts unless you pass `--yes`; `run` triggers an on-demand refresh.
`materialize.py list` is read-only, and all state-changing commands support `--dry-run`.

**Data sensitivity.** On a shared account, `ACCOUNT_USAGE` spans every org/user in that
account. Scope to a single org with `--org <slug>` for customer-facing output, and treat
`inventory.json` / reports (which contain workbook names, object IDs, and `sourceUrl`s) as
confidential — keep real outputs out of shared/public locations.
