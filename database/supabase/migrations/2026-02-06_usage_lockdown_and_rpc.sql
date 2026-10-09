-- FALAI - Usage lockdown + RPC adjustment (Task 2 prerequisite)
-- Date: 2026-02-06
--
-- Goals:
-- 1) Prevent client-side tampering of daily usage counters (bypass risk).
-- 2) Allow backend (service role) to register usage for a specific user via RPC.

-- --------------------------------
-- 1) Lock down daily_usage writes
-- --------------------------------
-- Keep SELECT policy; remove INSERT/UPDATE/DELETE for regular users.
drop policy if exists daily_usage_modify_own on public.daily_usage;

-- --------------------------------
-- 2) Update RPC signature for backend usage registration
-- --------------------------------
-- The previous function relied on auth.uid() (user context). In the backend we use service role,
-- so we add an optional p_user_id parameter (at the end, to keep positional compatibility).
drop function if exists public.register_transcription_usage(numeric, integer, integer);

create or replace function public.register_transcription_usage(
  p_audio_seconds numeric,
  p_words_count int default 0,
  p_transcriptions_count int default 1,
  p_user_id uuid default null
)
returns public.daily_usage
language plpgsql
security invoker
set search_path = public
as $$
declare
  v_uid uuid := coalesce(p_user_id, auth.uid());
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

