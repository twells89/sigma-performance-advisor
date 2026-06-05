# Privacy & posture

**Analysis is read-only.** `analyze.py` issues only `SELECT`s against
`SNOWFLAKE.ACCOUNT_USAGE` (`QUERY_HISTORY`, `QUERY_ATTRIBUTION_HISTORY`). It reads
query *metadata* (tags, elapsed time, bytes, attributed credits) — not query results or
warehouse row data. Nothing is written to Snowflake.

**Remediation is explicit and opt-in.** `materialize.py run` is the only action that
changes state, and only when you invoke it with a specific `--sheet`; it triggers a
refresh of a materialization **you already configured in the Sigma UI**. The API cannot
create or delete a materialization schedule. `materialize.py list` is read-only.

**Data sensitivity.** On a shared account, `ACCOUNT_USAGE` spans every org/user in that
account. Scope to a single org with `--org <slug>` for customer-facing output, and treat
`inventory.json` / reports (which contain workbook names, emails, and `sourceUrl`s) as
confidential — keep real outputs out of shared/public locations.
