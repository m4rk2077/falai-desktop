-- P1.1: Enable pg_cron scheduling and improve top-queries view behavior
-- when there is only one snapshot in the last 24h window.

create extension if not exists pg_cron;

create or replace function analytics.refresh_kpi_top_queries_24h()
returns void
language plpgsql
security definer
set search_path to 'analytics', 'public'
as $$
begin
  refresh materialized view analytics.kpi_top_queries_24h;
end;
$$;

drop materialized view if exists analytics.kpi_top_queries_24h;

create materialized view analytics.kpi_top_queries_24h as
with bounds as (
  select
    queryid,
    min(captured_at) as first_seen,
    max(captured_at) as last_seen,
    count(*)::int as snap_count
  from analytics.query_perf_snapshots
  where captured_at >= timezone('utc', now()) - interval '24 hours'
  group by queryid
),
first_vals as (
  select distinct on (q.queryid)
    q.queryid,
    q.query_sample,
    q.calls,
    q.total_exec_ms,
    q.rows
  from analytics.query_perf_snapshots q
  join bounds b on b.queryid = q.queryid and q.captured_at = b.first_seen
  order by q.queryid, q.captured_at asc
),
last_vals as (
  select distinct on (q.queryid)
    q.queryid,
    q.query_sample,
    q.calls,
    q.total_exec_ms,
    q.rows
  from analytics.query_perf_snapshots q
  join bounds b on b.queryid = q.queryid and q.captured_at = b.last_seen
  order by q.queryid, q.captured_at desc
),
deltas as (
  select
    l.queryid,
    coalesce(l.query_sample, f.query_sample) as query_sample,
    case
      when b.snap_count > 1 then greatest(l.calls - coalesce(f.calls, 0), 0)::bigint
      else greatest(l.calls, 0)::bigint
    end as calls_24h,
    case
      when b.snap_count > 1 then greatest(l.total_exec_ms - coalesce(f.total_exec_ms, 0), 0)::numeric
      else greatest(l.total_exec_ms, 0)::numeric
    end as total_exec_ms_24h,
    case
      when b.snap_count > 1 then greatest(l.rows - coalesce(f.rows, 0), 0)::bigint
      else greatest(l.rows, 0)::bigint
    end as rows_24h
  from last_vals l
  join bounds b on b.queryid = l.queryid
  left join first_vals f on f.queryid = l.queryid
)
select
  queryid,
  query_sample,
  calls_24h as calls,
  total_exec_ms_24h as total_exec_ms,
  case when calls_24h > 0 then (total_exec_ms_24h / calls_24h)::numeric else 0::numeric end as mean_exec_ms,
  case when calls_24h > 0 then (rows_24h::numeric / calls_24h)::numeric else 0::numeric end as rows_per_call
from deltas
where calls_24h > 0
order by total_exec_ms_24h desc
limit 20;

create unique index if not exists ix_kpi_top_queries_24h_queryid
  on analytics.kpi_top_queries_24h (queryid);

do $$
declare
  v_job_id bigint;
begin
  if exists (select 1 from pg_extension where extname = 'pg_cron') then
    select jobid into v_job_id from cron.job where jobname = 'analytics_capture_perf_snapshot_v1' limit 1;
    if v_job_id is not null then
      perform cron.unschedule(v_job_id);
    end if;
    perform cron.schedule(
      'analytics_capture_perf_snapshot_v1',
      '* * * * *',
      'select analytics.capture_perf_snapshot();'
    );

    select jobid into v_job_id from cron.job where jobname = 'analytics_refresh_top_queries_24h_v1' limit 1;
    if v_job_id is not null then
      perform cron.unschedule(v_job_id);
    end if;
    perform cron.schedule(
      'analytics_refresh_top_queries_24h_v1',
      '*/15 * * * *',
      'select analytics.refresh_kpi_top_queries_24h();'
    );

    select jobid into v_job_id from cron.job where jobname = 'analytics_cleanup_alert_state_v1' limit 1;
    if v_job_id is not null then
      perform cron.unschedule(v_job_id);
    end if;
    perform cron.schedule(
      'analytics_cleanup_alert_state_v1',
      '10 3 * * *',
      'delete from analytics.alert_state where status = ''closed'' and updated_at < timezone(''utc'', now()) - interval ''30 days'';'
    );
  end if;
end
$$;

-- Prime one more snapshot and refresh for immediate visibility.
select analytics.capture_perf_snapshot();
select analytics.refresh_kpi_top_queries_24h();

