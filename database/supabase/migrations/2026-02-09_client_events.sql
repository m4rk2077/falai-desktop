-- Client telemetry events (beta)
-- Purpose: allow the product owner to debug client-side issues without asking users for log files.

create table if not exists public.client_events (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.profiles(id) on delete cascade,
  device_id text null,
  app_version text null,
  event_type text not null,
  severity text not null default 'error' check (severity in ('info', 'warning', 'error')),
  message text not null,
  details jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default timezone('utc', now())
);

alter table public.client_events enable row level security;

-- Users can only insert/select their own events.
do $$
begin
  if not exists (
    select 1
    from pg_policies
    where schemaname = 'public'
      and tablename = 'client_events'
      and policyname = 'client_events_insert_own'
  ) then
    create policy client_events_insert_own
      on public.client_events
      for insert
      to authenticated
      with check (auth.uid() = user_id);
  end if;

  if not exists (
    select 1
    from pg_policies
    where schemaname = 'public'
      and tablename = 'client_events'
      and policyname = 'client_events_select_own'
  ) then
    create policy client_events_select_own
      on public.client_events
      for select
      to authenticated
      using (auth.uid() = user_id);
  end if;
end $$;

create index if not exists client_events_user_created_at_idx
  on public.client_events (user_id, created_at desc);

