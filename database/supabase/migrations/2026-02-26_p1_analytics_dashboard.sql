-- P1: Analytics schema for DB performance + backend health dashboard.
-- Safe to apply in production: read-mostly objects and auxiliary snapshot tables.

create schema if not exists analytics;

-- ---------------------------------------------------------------------------
-- Snapshot tables
-- ---------------------------------------------------------------------------
create table if not exists analytics.db_perf_snapshots (
  id bigserial primary key,
  captured_at timestamptz not null default timezone('utc', now()),
  dbname text not null,
  xact_commit bigint not null default 0,
  xact_rollback bigint not null default 0,
  deadlocks bigint not null default 0,
  blks_read bigint not null default 0,
  blks_hit bigint not null default 0,
  temp_files bigint not null default 0,
  temp_bytes bigint not null default 0,
  tup_returned bigint not null default 0,
  tup_fetched bigint not null default 0,
  tup_inserted bigint not null default 0,
  tup_updated bigint not null default 0,
  tup_deleted bigint not null default 0,
  total_calls bigint not null default 0,
  total_exec_ms numeric not null default 0,
  mean_exec_ms numeric not null default 0,
  total_rows bigint not null default 0,
  stats_reset timestamptz null
);

create index if not exists ix_db_perf_snapshots_captured_at
  on analytics.db_perf_snapshots (captured_at desc);

create table if not exists analytics.query_perf_snapshots (
  id bigserial primary key,
  captured_at timestamptz not null default timezone('utc', now()),
  queryid bigint not null,
  query_sample text not null,
  calls bigint not null default 0,
  total_exec_ms numeric not null default 0,
  mean_exec_ms numeric not null default 0,
  rows bigint not null default 0
);

create index if not exists ix_query_perf_snapshots_queryid_time
  on analytics.query_perf_snapshots (queryid, captured_at desc);

create index if not exists ix_query_perf_snapshots_captured_at
  on analytics.query_perf_snapshots (captured_at desc);

-- ---------------------------------------------------------------------------
-- Alert state (dedupe/ack lifecycle for n8n alerts)
-- ---------------------------------------------------------------------------
create table if not exists analytics.alert_state (
  alert_key text primary key,
  status text not null check (status in ('open', 'closed')),
  opened_at timestamptz null,
  last_notified_at timestamptz null,
  last_value numeric null,
  metadata jsonb not null default '{}'::jsonb,
  updated_at timestamptz not null default timezone('utc', now())
);

create index if not exists ix_alert_state_status_updated
  on analytics.alert_state (status, updated_at desc);

create or replace function analytics.set_updated_at()
returns trigger
language plpgsql
set search_path to 'analytics', 'public'
as $$
begin
  new.updated_at := timezone('utc', now());
  return new;
end;
$$;

drop trigger if exists trg_alert_state_updated_at on analytics.alert_state;
create trigger trg_alert_state_updated_at
before update on analytics.alert_state
for each row execute function analytics.set_updated_at();

-- ---------------------------------------------------------------------------
-- Snapshot capture function
-- ---------------------------------------------------------------------------
create or replace function analytics.capture_perf_snapshot()
returns void
language plpgsql
security definer
set search_path to 'analytics', 'public', 'extensions'
as $$
declare
  v_now timestamptz := timezone('utc', now());
begin
  insert into analytics.db_perf_snapshots (
    captured_at,
    dbname,
    xact_commit,
    xact_rollback,
    deadlocks,
    blks_read,
    blks_hit,
    temp_files,
    temp_bytes,
    tup_returned,
    tup_fetched,
    tup_inserted,
    tup_updated,
    tup_deleted,
    total_calls,
    total_exec_ms,
    mean_exec_ms,
    total_rows,
    stats_reset
  )
  select
    v_now,
    current_database(),
    coalesce(d.xact_commit, 0),
    coalesce(d.xact_rollback, 0),
    coalesce(d.deadlocks, 0),
    coalesce(d.blks_read, 0),
    coalesce(d.blks_hit, 0),
    coalesce(d.temp_files, 0),
    coalesce(d.temp_bytes, 0),
    coalesce(d.tup_returned, 0),
    coalesce(d.tup_fetched, 0),
    coalesce(d.tup_inserted, 0),
    coalesce(d.tup_updated, 0),
    coalesce(d.tup_deleted, 0),
    coalesce(s.total_calls, 0),
    coalesce(s.total_exec_ms, 0),
    coalesce(s.mean_exec_ms, 0),
    coalesce(s.total_rows, 0),
    d.stats_reset
  from (
    select *
    from pg_stat_database
    where datname = current_database()
    limit 1
  ) d
  cross join (
    select
      sum(calls)::bigint as total_calls,
      sum(total_exec_time)::numeric as total_exec_ms,
      case when sum(calls) > 0
        then (sum(total_exec_time) / sum(calls))::numeric
        else 0::numeric
      end as mean_exec_ms,
      sum(rows)::bigint as total_rows
    from pg_stat_statements
  ) s;

  insert into analytics.query_perf_snapshots (
    captured_at,
    queryid,
    query_sample,
    calls,
    total_exec_ms,
    mean_exec_ms,
    rows
  )
  select
    v_now,
    queryid::bigint,
    left(regexp_replace(query, '\s+', ' ', 'g'), 800) as query_sample,
    calls::bigint,
    total_exec_time::numeric,
    mean_exec_time::numeric,
    rows::bigint
  from pg_stat_statements
  where queryid is not null
  order by total_exec_time desc
  limit 200;
end;
$$;

-- ---------------------------------------------------------------------------
-- KPI views
-- ---------------------------------------------------------------------------
create or replace view analytics.kpi_db_minutely as
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
),
q as (
  select
    date_trunc('minute', captured_at) as bucket_minute,
    percentile_cont(0.95) within group (order by mean_exec_ms) as p95_query_mean_exec_ms
  from analytics.query_perf_snapshots
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

create materialized view if not exists analytics.kpi_top_queries_24h as
with bounds as (
  select
    queryid,
    min(captured_at) as first_seen,
    max(captured_at) as last_seen
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
    greatest(l.calls - coalesce(f.calls, 0), 0)::bigint as calls_24h,
    greatest(l.total_exec_ms - coalesce(f.total_exec_ms, 0), 0)::numeric as total_exec_ms_24h,
    greatest(l.rows - coalesce(f.rows, 0), 0)::bigint as rows_24h
  from last_vals l
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

create or replace view analytics.kpi_transcribe_latency_5m as
select
  date_bin('5 minutes', created_at, '1970-01-01 00:00:00+00'::timestamptz) as bucket_5m,
  coalesce(metadata->>'tier_applied', 'unknown') as tier_applied,
  coalesce(metadata->>'correction_mode', 'unknown') as correction_mode,
  count(*)::bigint as count_total,
  avg(coalesce((metadata->>'total_ms')::numeric, 0))::numeric as avg_total_ms,
  percentile_cont(0.95) within group (order by coalesce((metadata->>'total_ms')::numeric, 0))::numeric as p95_total_ms,
  avg(coalesce((metadata->>'correction_ms')::numeric, 0))::numeric as avg_correction_ms
from public.transcriptions
where created_at >= timezone('utc', now()) - interval '30 days'
group by 1, 2, 3
order by bucket_5m desc;

create or replace view analytics.kpi_app_errors_5m as
select
  date_bin('5 minutes', created_at, '1970-01-01 00:00:00+00'::timestamptz) as bucket_5m,
  event_type,
  severity,
  count(*)::bigint as count_events
from public.client_events
where created_at >= timezone('utc', now()) - interval '30 days'
group by 1, 2, 3
order by bucket_5m desc;

create or replace view analytics.kpi_lead_webhook_15m as
select
  date_bin('15 minutes', created_at, '1970-01-01 00:00:00+00'::timestamptz) as bucket_15m,
  event_name,
  count(*)::bigint as count_events
from public.lead_events
where created_at >= timezone('utc', now()) - interval '30 days'
group by 1, 2
order by bucket_15m desc;

-- ---------------------------------------------------------------------------
-- pg_cron schedules (best effort)
-- ---------------------------------------------------------------------------
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
      'refresh materialized view analytics.kpi_top_queries_24h;'
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

-- Prime one snapshot and one top-query refresh so dashboard is not empty.
select analytics.capture_perf_snapshot();
refresh materialized view analytics.kpi_top_queries_24h;
