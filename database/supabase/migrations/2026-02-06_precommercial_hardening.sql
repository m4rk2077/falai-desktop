-- FALAI - Pre-commercial hardening (Task 1)
-- Date: 2026-02-06
-- Safe to execute multiple times.

-- ----------------------------------------------------
-- 1) Bootstrap profile + default entitlement on signup
-- ----------------------------------------------------
create or replace function public.handle_new_auth_user()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.profiles (id, email, full_name, role)
  values (
    new.id,
    coalesce(new.email, ''),
    coalesce(new.raw_user_meta_data ->> 'full_name', ''),
    'user'
  )
  on conflict (id) do update
    set email = excluded.email,
        updated_at = timezone('utc', now());

  insert into public.user_entitlements (
    user_id,
    can_transcribe,
    can_correct,
    daily_minutes_limit,
    monthly_minutes_limit,
    source,
    effective_from
  )
  values (
    new.id,
    true,
    true,
    15,
    450,
    'plan',
    timezone('utc', now())
  )
  on conflict (user_id) do nothing;

  return new;
end;
$$;

drop trigger if exists trg_auth_user_created on auth.users;
create trigger trg_auth_user_created
after insert on auth.users
for each row
execute function public.handle_new_auth_user();

-- ----------------------------------------------------
-- 2) Backfill existing users (safe and idempotent)
-- ----------------------------------------------------
insert into public.profiles (id, email, full_name, role)
select
  u.id,
  coalesce(u.email, ''),
  coalesce(u.raw_user_meta_data ->> 'full_name', ''),
  'user'
from auth.users u
left join public.profiles p on p.id = u.id
where p.id is null;

insert into public.user_entitlements (
  user_id,
  can_transcribe,
  can_correct,
  daily_minutes_limit,
  monthly_minutes_limit,
  source,
  effective_from
)
select
  p.id,
  true,
  true,
  15,
  450,
  'plan',
  timezone('utc', now())
from public.profiles p
left join public.user_entitlements ue on ue.user_id = p.id
where ue.user_id is null;

-- ----------------------------------------------------
-- 3) Self-heal helper (can be called after login)
-- ----------------------------------------------------
create or replace function public.ensure_current_user_profile()
returns public.profiles
language plpgsql
security invoker
set search_path = public
as $$
declare
  v_uid uuid := auth.uid();
  v_email text := coalesce(auth.jwt() ->> 'email', '');
  v_row public.profiles;
begin
  if v_uid is null then
    raise exception 'Sessao nao autenticada';
  end if;

  insert into public.profiles (id, email, role)
  values (v_uid, v_email, 'user')
  on conflict (id) do update
    set email = coalesce(excluded.email, public.profiles.email),
        updated_at = timezone('utc', now())
  returning * into v_row;

  insert into public.user_entitlements (
    user_id,
    can_transcribe,
    can_correct,
    daily_minutes_limit,
    monthly_minutes_limit,
    source,
    effective_from
  )
  values (
    v_uid,
    true,
    true,
    15,
    450,
    'plan',
    timezone('utc', now())
  )
  on conflict (user_id) do nothing;

  return v_row;
end;
$$;

-- ----------------------------------------------------
-- 4) Access check for transcription gate (RPC-ready)
-- ----------------------------------------------------
create or replace function public.check_transcription_access(p_user_id uuid default null)
returns table (
  allowed boolean,
  reason text,
  daily_limit_seconds numeric,
  used_today_seconds numeric,
  remaining_seconds numeric
)
language plpgsql
security invoker
set search_path = public
as $$
declare
  v_uid uuid := coalesce(p_user_id, auth.uid());
  v_now timestamptz := timezone('utc', now());
  v_ent public.user_entitlements%rowtype;
  v_used_seconds numeric(10, 2) := 0;
  v_limit_seconds numeric(10, 2);
begin
  if v_uid is null then
    return query select false, 'unauthenticated', null::numeric, 0::numeric, 0::numeric;
    return;
  end if;

  select *
  into v_ent
  from public.user_entitlements
  where user_id = v_uid
  limit 1;

  if v_ent.user_id is null then
    return query select false, 'no_entitlement', 0::numeric, 0::numeric, 0::numeric;
    return;
  end if;

  if not v_ent.can_transcribe then
    return query
      select false, 'transcription_disabled', coalesce(v_ent.daily_minutes_limit, 0)::numeric * 60, 0::numeric, 0::numeric;
    return;
  end if;

  if v_ent.effective_from is not null and v_now < v_ent.effective_from then
    return query select false, 'entitlement_not_started', 0::numeric, 0::numeric, 0::numeric;
    return;
  end if;

  if v_ent.effective_until is not null and v_now > v_ent.effective_until then
    return query select false, 'entitlement_expired', 0::numeric, 0::numeric, 0::numeric;
    return;
  end if;

  select coalesce(d.audio_seconds, 0)::numeric(10, 2)
  into v_used_seconds
  from public.daily_usage d
  where d.user_id = v_uid
    and d.usage_date = v_now::date
  limit 1;

  if v_ent.daily_minutes_limit is null then
    return query select true, 'ok', null::numeric, v_used_seconds, null::numeric;
    return;
  end if;

  v_limit_seconds := greatest(v_ent.daily_minutes_limit, 0)::numeric * 60;

  if v_used_seconds >= v_limit_seconds then
    return query select false, 'daily_limit_reached', v_limit_seconds, v_used_seconds, 0::numeric;
    return;
  end if;

  return query
    select true, 'ok', v_limit_seconds, v_used_seconds, greatest(v_limit_seconds - v_used_seconds, 0::numeric);
end;
$$;

-- ----------------------------------------------------
-- 5) Usage register helper (atomic daily counter update)
-- ----------------------------------------------------
create or replace function public.register_transcription_usage(
  p_audio_seconds numeric,
  p_words_count int default 0,
  p_transcriptions_count int default 1
)
returns public.daily_usage
language plpgsql
security invoker
set search_path = public
as $$
declare
  v_uid uuid := auth.uid();
  v_usage_date date := timezone('utc', now())::date;
  v_row public.daily_usage;
begin
  if v_uid is null then
    raise exception 'Sessao nao autenticada';
  end if;

  insert into public.daily_usage (
    user_id,
    usage_date,
    transcriptions_count,
    words_count,
    audio_seconds
  )
  values (
    v_uid,
    v_usage_date,
    greatest(coalesce(p_transcriptions_count, 1), 0),
    greatest(coalesce(p_words_count, 0), 0),
    greatest(coalesce(p_audio_seconds, 0), 0)
  )
  on conflict (user_id, usage_date) do update
    set transcriptions_count = public.daily_usage.transcriptions_count + excluded.transcriptions_count,
        words_count = public.daily_usage.words_count + excluded.words_count,
        audio_seconds = public.daily_usage.audio_seconds + excluded.audio_seconds,
        updated_at = timezone('utc', now())
  returning * into v_row;

  return v_row;
end;
$$;
