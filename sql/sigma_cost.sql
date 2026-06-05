-- Sigma → Snowflake cost attribution (standalone / Cortex Code friendly).
-- Runs natively in a Snowflake worksheet or Cortex Code — no external CLI needed.
-- Attributes attributed compute credits to the Sigma object that issued each query.
--
-- Edit the three SET vars, run, then either read the result table or export it as JSON
-- and render with:  analyze.py --from-rows result.json --goal both
set days     = 30;     -- analysis window (days)
set org      = '';     -- '' = account-wide; else a Sigma org slug, e.g. 'acme'
set min_runs = 2;      -- ignore objects run fewer than this many times

with qh as (
  select query_id, total_elapsed_time, bytes_scanned, partitions_scanned, partitions_total,
         try_parse_json(regexp_substr(query_tag, '\\{.*\\}')) as j
  from snowflake.account_usage.query_history
  where start_time > dateadd('day', -$days, current_timestamp())
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
    and ($org = '' or j:"sourceUrl"::string ilike '%/' || $org || '/%')
),
att as (
  select query_id, sum(credits_attributed_compute) as credits
  from snowflake.account_usage.query_attribution_history
  where start_time > dateadd('day', -$days, current_timestamp())
  group by 1
)
select
  s.org,
  s.object,
  coalesce(s.element, '(workbook load)')      as element,
  count(*)                                    as runs,
  round(sum(coalesce(att.credits, 0)), 4)     as credits,
  round(avg(s.total_elapsed_time)/1000.0, 2)  as avg_sec,
  round(max(s.total_elapsed_time)/1000.0, 2)  as max_sec,
  round(sum(s.total_elapsed_time)/1000.0, 1)  as total_sec,
  max(s.bytes_scanned)                        as max_bytes,
  max(s.source_url)                           as sample_url
from s
left join att using (query_id)
group by 1, 2, 3
having count(*) >= $min_runs
order by credits desc, total_sec desc
limit 100;
