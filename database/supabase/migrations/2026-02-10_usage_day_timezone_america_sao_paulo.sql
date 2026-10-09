-- FALAI - Backfill drift: usage_day_timezone_america_sao_paulo
-- Date: 2026-02-10 (source-of-truth from PROD)
-- Safe to execute multiple times.

create or replace function public.check_transcription_access(p_user_id uuid default null::uuid)
returns table(
  allowed boolean,
  reason text,
  daily_limit_seconds numeric,
  used_today_seconds numeric,
  remaining_seconds numeric
)
language plpgsql
set search_path = 'public'
as $$
declare
  v_uid uuid := coalesce(p_user_id, auth.uid());
  v_now timestamptz := timezone('utc', now());
  v_usage_date date := (timezone('America/Sao_Paulo', now()))::date;
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
    and d.usage_date = v_usage_date
  limit 1;

  v_used_seconds := coalesce(v_used_seconds, 0);

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

create or replace function public.register_transcription_usage(
  p_audio_seconds numeric,
  p_words_count int default 0,
  p_transcriptions_count int default 1,
  p_user_id uuid default null
)
returns public.daily_usage
language plpgsql
set search_path = 'public'
as $$
declare
  v_uid uuid := coalesce(p_user_id, auth.uid());
  v_usage_date date := (timezone('America/Sao_Paulo', now()))::date;
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
