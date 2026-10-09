-- Fix: kpi_db_minutely view times out via PostgREST because percentile_cont
-- over query_perf_snapshots is too slow for the REST API statement timeout.
--
-- Solution: convert from regular view to materialized view with 3h window.
-- pg_cron refreshes it every minute alongside capture_perf_snapshot.

-- Drop the existing view first
drop view if exists analytics.kpi_db_minutely;

-- Create as materialized view with a bounded 3h window
create materialized view analytics.kpi_db_minutely as
with base as (
  select
    captured_at,
    date_trunc('minute', captured_at) as bucket_minute,
    xact_commit,
    xact_rollback,
    deadlocks,
    blks_read,
    blks_hit,
    temp_files,
    temp_bytes,
    total_calls,
    total_exec_ms,
    total_rows,
    lag(xact_commit) over (order by captured_at) as prev_xact_commit,
    lag(xact_rollback) over (order by captured_at) as prev_xact_rollback,
    lag(deadlocks) over (order by captured_at) as prev_deadlocks,
    lag(blks_read) over (order by captured_at) as prev_blks_read,
    lag(blks_hit) over (order by captured_at) as prev_blks_hit,
    lag(temp_files) over (order by captured_at) as prev_temp_files,
    lag(temp_bytes) over (order by captured_at) as prev_temp_bytes,
    lag(total_calls) over (order by captured_at) as prev_total_calls,
    lag(total_exec_ms) over (order by captured_at) as prev_total_exec_ms,
    lag(total_rows) over (order by captured_at) as prev_total_rows
  from analytics.db_perf_snapshots
  where captured_at >= timezone('utc', now()) - interval '3 hours'
),
q as (
  select
    date_trunc('minute', captured_at) as bucket_minute,
    percentile_cont(0.95) within group (order by mean_exec_ms) as p95_query_mean_exec_ms
  from analytics.query_perf_snapshots
  where captured_at >= timezone('utc', now()) - interval '3 hours'
  group by 1
)
select
  b.bucket_minute,
  greatest(b.total_calls - coalesce(b.prev_total_calls, b.total_calls), 0)::bigint as calls_total,
  greatest(b.total_exec_ms - coalesce(b.prev_total_exec_ms, b.total_exec_ms), 0)::numeric as exec_total_ms,
  case
    when greatest(b.total_calls - coalesce(b.prev_total_calls, b.total_calls), 0) > 0
      then (greatest(b.total_exec_ms - coalesce(b.prev_total_exec_ms, b.total_exec_ms), 0)
            / greatest(b.total_calls - coalesce(b.prev_total_calls, b.total_calls), 0))::numeric
    else 0::numeric
  end as mean_exec_ms,
  coalesce(q.p95_query_mean_exec_ms, 0)::numeric as p95_query_mean_exec_ms,
  greatest(b.total_rows - coalesce(b.prev_total_rows, b.total_rows), 0)::bigint as rows_total,
  greatest(b.blks_read - coalesce(b.prev_blks_read, b.blks_read), 0)::bigint as shared_blks_read,
  greatest(b.blks_hit - coalesce(b.prev_blks_hit, b.blks_hit), 0)::bigint as shared_blks_hit,
  case
    when (greatest(b.blks_hit - coalesce(b.prev_blks_hit, b.blks_hit), 0)
          + greatest(b.blks_read - coalesce(b.prev_blks_read, b.blks_read), 0)) > 0
      then (
        greatest(b.blks_hit - coalesce(b.prev_blks_hit, b.blks_hit), 0)::numeric
        / (
          greatest(b.blks_hit - coalesce(b.prev_blks_hit, b.blks_hit), 0)
          + greatest(b.blks_read - coalesce(b.prev_blks_read, b.blks_read), 0)
        )::numeric
      )
    else 1::numeric
  end as cache_hit_ratio,
  greatest(b.xact_commit - coalesce(b.prev_xact_commit, b.xact_commit), 0)::bigint as db_xact_commit,
  greatest(b.xact_rollback - coalesce(b.prev_xact_rollback, b.xact_rollback), 0)::bigint as db_xact_rollback,
  greatest(b.deadlocks - coalesce(b.prev_deadlocks, b.deadlocks), 0)::bigint as db_deadlocks,
  greatest(b.temp_files - coalesce(b.prev_temp_files, b.temp_files), 0)::bigint as temp_files,
  greatest(b.temp_bytes - coalesce(b.prev_temp_bytes, b.temp_bytes), 0)::bigint as temp_bytes
from base b
left join q on q.bucket_minute = b.bucket_minute
order by b.bucket_minute desc;

-- Unique index required for CONCURRENTLY refresh
create unique index if not exists ix_kpi_db_minutely_bucket
  on analytics.kpi_db_minutely (bucket_minute);

-- Schedule concurrent refresh every 2 minutes (runs alongside capture_perf_snapshot)
do $$
declare
  v_job_id bigint;
begin
  if exists (select 1 from pg_extension where extname = 'pg_cron') then
    select jobid into v_job_id from cron.job where jobname = 'analytics_refresh_kpi_db_minutely_v1' limit 1;
    if v_job_id is not null then
      perform cron.unschedule(v_job_id);
    end if;
    perform cron.schedule(
      'analytics_refresh_kpi_db_minutely_v1',
      '*/2 * * * *',
      'refresh materialized view concurrently analytics.kpi_db_minutely;'
    );
  end if;
end
$$;
