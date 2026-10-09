-- FALAI - Monthly usage visibility and enforcement for Start plan
-- Date: 2026-02-20
-- Safe to execute multiple times.

drop function if exists public.check_transcription_access(uuid);

create or replace function public.check_transcription_access(p_user_id uuid default null::uuid)
returns table(
  allowed boolean,
  reason text,
  daily_limit_seconds numeric,
  used_today_seconds numeric,
  remaining_seconds numeric,
  monthly_limit_seconds numeric,
  used_month_seconds numeric,
  remaining_month_seconds numeric
)
language plpgsql
set search_path = 'public'
as $$
declare
  v_uid uuid := coalesce(p_user_id, auth.uid());
  v_now timestamptz := timezone('utc', now());
  v_usage_date date := (timezone('America/Sao_Paulo', now()))::date;
  v_month_start date := date_trunc('month', timezone('America/Sao_Paulo', now()))::date;
  v_month_end date := (date_trunc('month', timezone('America/Sao_Paulo', now())) + interval '1 month')::date;
  v_ent public.user_entitlements%rowtype;
  v_used_today_seconds numeric(10, 2) := 0;
  v_used_month_seconds numeric(12, 2) := 0;
  v_daily_limit_seconds numeric(10, 2);
  v_monthly_limit_seconds numeric(12, 2);
begin
  if v_uid is null then
    return query
      select false, 'unauthenticated', null::numeric, 0::numeric, 0::numeric, null::numeric, 0::numeric, 0::numeric;
    return;
  end if;

  select *
  into v_ent
  from public.user_entitlements
  where user_id = v_uid
  limit 1;

  if v_ent.user_id is null then
    return query
      select false, 'no_entitlement', 0::numeric, 0::numeric, 0::numeric, 0::numeric, 0::numeric, 0::numeric;
    return;
  end if;

  if not v_ent.can_transcribe then
    return query
      select
        false,
        'transcription_disabled',
        coalesce(v_ent.daily_minutes_limit, 0)::numeric * 60,
        0::numeric,
        0::numeric,
        coalesce(v_ent.monthly_minutes_limit, 0)::numeric * 60,
        0::numeric,
        0::numeric;
    return;
  end if;

  if v_ent.effective_from is not null and v_now < v_ent.effective_from then
    return query
      select false, 'entitlement_not_started', 0::numeric, 0::numeric, 0::numeric, 0::numeric, 0::numeric, 0::numeric;
    return;
  end if;

  if v_ent.effective_until is not null and v_now > v_ent.effective_until then
    return query
      select false, 'entitlement_expired', 0::numeric, 0::numeric, 0::numeric, 0::numeric, 0::numeric, 0::numeric;
    return;
  end if;

  select coalesce(d.audio_seconds, 0)::numeric(10, 2)
  into v_used_today_seconds
  from public.daily_usage d
  where d.user_id = v_uid
    and d.usage_date = v_usage_date
  limit 1;

  v_used_today_seconds := coalesce(v_used_today_seconds, 0);

  select coalesce(sum(d.audio_seconds), 0)::numeric(12, 2)
  into v_used_month_seconds
  from public.daily_usage d
  where d.user_id = v_uid
    and d.usage_date >= v_month_start
    and d.usage_date < v_month_end;

  v_used_month_seconds := coalesce(v_used_month_seconds, 0);

  if v_ent.daily_minutes_limit is null then
    v_daily_limit_seconds := null::numeric;
  else
    v_daily_limit_seconds := greatest(v_ent.daily_minutes_limit, 0)::numeric * 60;
  end if;

  if v_ent.monthly_minutes_limit is null then
    v_monthly_limit_seconds := null::numeric;
  else
    v_monthly_limit_seconds := greatest(v_ent.monthly_minutes_limit, 0)::numeric * 60;
  end if;

  if v_monthly_limit_seconds is not null and v_used_month_seconds >= v_monthly_limit_seconds then
    return query
      select
        false,
        'monthly_limit_reached',
        v_daily_limit_seconds,
        v_used_today_seconds,
        case
          when v_daily_limit_seconds is null then null::numeric
          else greatest(v_daily_limit_seconds - v_used_today_seconds, 0::numeric)
        end,
        v_monthly_limit_seconds,
        v_used_month_seconds,
        0::numeric;
    return;
  end if;

  if v_daily_limit_seconds is not null and v_used_today_seconds >= v_daily_limit_seconds then
    return query
      select
        false,
        'daily_limit_reached',
        v_daily_limit_seconds,
        v_used_today_seconds,
        0::numeric,
        v_monthly_limit_seconds,
        v_used_month_seconds,
        case
          when v_monthly_limit_seconds is null then null::numeric
          else greatest(v_monthly_limit_seconds - v_used_month_seconds, 0::numeric)
        end;
    return;
  end if;

  return query
    select
      true,
      'ok',
      v_daily_limit_seconds,
      v_used_today_seconds,
      case
        when v_daily_limit_seconds is null then null::numeric
        else greatest(v_daily_limit_seconds - v_used_today_seconds, 0::numeric)
      end,
      v_monthly_limit_seconds,
      v_used_month_seconds,
      case
        when v_monthly_limit_seconds is null then null::numeric
        else greatest(v_monthly_limit_seconds - v_used_month_seconds, 0::numeric)
      end;
end;
$$;
