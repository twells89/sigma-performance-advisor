# Privacy & posture

**Analysis is read-only.** `analyze.py` issues only `SELECT`s against
`SNOWFLAKE.ACCOUNT_USAGE` (`QUERY_HISTORY`, `QUERY_ATTRIBUTION_HISTORY`). It reads
query *metadata* (tags, elapsed time, bytes, attributed credits) — not query results or
warehouse row data. Nothing is written to Snowflake.

**Remediation is explicit and opt-in.** Four `materialize.py` subcommands change state,
and only when you invoke one explicitly with a specific `--sheet`/`--workbook`/
`--datamodel`: `create` and `update` set a schedule's cron cadence (private-beta REST
API — see `refs/materialization-playbook.md` for exact shapes and a live-deployment
caveat); `delete` removes a schedule outright and cancels all its future runs — it has
no undo, and prompts for confirmation unless you pass `--yes`; `run` triggers an
on-demand refresh of an existing schedule. `materialize.py list` is read-only.

**Data sensitivity.** On a shared account, `ACCOUNT_USAGE` spans every org/user in that
account. Scope to a single org with `--org <slug>` for customer-facing output, and treat
`inventory.json` / reports (which contain workbook names, emails, and `sourceUrl`s) as
confidential — keep real outputs out of shared/public locations.
