-- P1 performance pass:
-- 1) Add covering indexes for foreign keys flagged by advisor.
-- 2) Rewrite RLS policies that call auth.uid() directly to (select auth.uid())
--    to avoid per-row auth function re-evaluation.

-- ---------------------------------------------------------------------------
-- FK covering indexes
-- ---------------------------------------------------------------------------
create index if not exists ix_audit_logs_user_id on public.audit_logs (user_id);
create index if not exists ix_audit_logs_device_id on public.audit_logs (device_id);
create index if not exists ix_billing_events_user_id on public.billing_events (user_id);
create index if not exists ix_subscriptions_plan_id on public.subscriptions (plan_id);
create index if not exists ix_transcription_feedback_user_id on public.transcription_feedback (user_id);
create index if not exists ix_transcriptions_device_id on public.transcriptions (device_id);

-- ---------------------------------------------------------------------------
-- RLS auth.uid() initplan optimization
-- ---------------------------------------------------------------------------
do $$
declare
  p record;
  roles_sql text;
  command_sql text;
  qual_sql text;
  with_check_sql text;
  create_sql text;
begin
  for p in
    select
      schemaname,
      tablename,
      policyname,
      permissive,
      roles,
      cmd,
      qual,
      with_check
    from pg_policies
    where schemaname = 'public'
      and tablename in (
        'profiles',
        'user_devices',
        'plans',
        'subscriptions',
        'user_entitlements',
        'billing_events',
        'transcriptions',
        'transcription_feedback',
        'user_settings',
        'support_tickets',
        'audit_logs',
        'daily_usage',
        'client_events',
        'device_settings'
      )
      and (
        coalesce(qual, '') like '%auth.uid()%'
        or coalesce(with_check, '') like '%auth.uid()%'
      )
    order by tablename, policyname
  loop
    roles_sql := array_to_string(
      array(
        select quote_ident(r::text)
        from unnest(p.roles) as r
      ),
      ', '
    );

    command_sql := case when upper(p.cmd) = 'ALL' then 'all' else lower(p.cmd) end;
    qual_sql := regexp_replace(coalesce(p.qual, ''), 'auth\.uid\(\)', '(select auth.uid())', 'g');
    with_check_sql := regexp_replace(coalesce(p.with_check, ''), 'auth\.uid\(\)', '(select auth.uid())', 'g');

    create_sql := format(
      'create policy %I on %I.%I as %s for %s to %s',
      p.policyname,
      p.schemaname,
      p.tablename,
      lower(p.permissive),
      command_sql,
      roles_sql
    );

    if nullif(qual_sql, '') is not null then
      create_sql := create_sql || format(' using (%s)', qual_sql);
    end if;

    if nullif(with_check_sql, '') is not null then
      create_sql := create_sql || format(' with check (%s)', with_check_sql);
    end if;

    execute format('drop policy if exists %I on %I.%I', p.policyname, p.schemaname, p.tablename);
    execute create_sql;
  end loop;
end
$$;

