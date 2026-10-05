-- Full Sigma-tagged query-cost coverage. Run alongside sigma_cost.sql so the report
-- distinguishes all Sigma cost from the subset attributable to a workbook/data model.
set days = 30;

with qh as (
  select query_id,
         iff(position('{' in query_tag) > 0,
             try_parse_json(substr(query_tag, position('{' in query_tag))), null) as j
  from snowflake.account_usage.query_history
  where start_time > dateadd('day', -$days, current_timestamp())
    and query_tag ilike 'Sigma %'
    and execution_status = 'SUCCESS'
),
att as (
  select query_id, sum(credits_attributed_compute) credits,
         sum(credits_used_query_acceleration) qas_credits
  from snowflake.account_usage.query_attribution_history
  where start_time > dateadd('day', -$days, current_timestamp())
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
       count_if(qh.j:"sourceUrl"::string is null) unattributed_queries,
       round(sum(iff(qh.j:"sourceUrl"::string is null,
                     coalesce(att.credits,0),0)),4) unattributed_credits
from qh left join att using(query_id);
