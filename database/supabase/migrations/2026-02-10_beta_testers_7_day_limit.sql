-- FALAI - Backfill drift: beta_testers_7_day_limit
-- Date: 2026-02-10 (source-of-truth from PROD)
-- Safe to execute multiple times.

-- 1) New users/self-heal receive beta entitlement window of 7 days.
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
    effective_from,
    effective_until
  )
  values (
    new.id,
    true,
    true,
    15,
    450,
    'plan',
    timezone('utc', now()),
    timezone('utc', now()) + interval '7 days'
  )
  on conflict (user_id) do nothing;

  return new;
end;
$$;

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
    effective_from,
    effective_until
  )
  values (
    v_uid,
    true,
    true,
    15,
    450,
    'plan',
    timezone('utc', now()),
    timezone('utc', now()) + interval '7 days'
  )
  on conflict (user_id) do nothing;

  return v_row;
end;
$$;

-- 2) Backfill existing beta users once (same semantics used in PROD rollout).
update public.user_entitlements
set
  effective_until = timezone('utc', now()) + interval '7 days',
  updated_at = timezone('utc', now())
where source = 'plan'
  and effective_until is null;
