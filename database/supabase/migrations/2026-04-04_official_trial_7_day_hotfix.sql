-- FALAI - Hotfix para garantir trial oficial de 7 dias
-- Date: 2026-04-04
-- Motivo: producao estava gravando alguns entitlements com janela de 3 dias.

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

update public.user_entitlements
set
  effective_until = effective_from + interval '7 days',
  updated_at = timezone('utc', now())
where source = 'plan'
  and coalesce(daily_minutes_limit, 0) = 15
  and coalesce(monthly_minutes_limit, 0) = 450
  and effective_from is not null
  and effective_until is not null
  and effective_until = effective_from + interval '3 days';

update public.leads_beta
set
  trial_ends_at = trial_started_at + interval '7 days',
  updated_at = timezone('utc', now())
where trial_started_at is not null
  and trial_ends_at is not null
  and trial_ends_at = trial_started_at + interval '3 days';
