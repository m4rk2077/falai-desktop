-- FALAI - Backfill drift: fix_function_search_path_mutable_public_functions
-- Date: 2026-02-11 (source-of-truth from PROD)
-- Safe to execute multiple times.

do $$
begin
  if exists (
    select 1
    from pg_proc p
    join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'public'
      and p.proname = 'check_transcription_access'
      and pg_get_function_identity_arguments(p.oid) = 'p_user_id uuid'
  ) then
    execute 'alter function public.check_transcription_access(uuid) set search_path = public';
  end if;

  if exists (
    select 1
    from pg_proc p
    join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'public'
      and p.proname = 'register_transcription_usage'
      and pg_get_function_identity_arguments(p.oid) = 'p_audio_seconds numeric, p_words_count integer, p_transcriptions_count integer, p_user_id uuid'
  ) then
    execute 'alter function public.register_transcription_usage(numeric, integer, integer, uuid) set search_path = public';
  end if;

  if exists (
    select 1
    from pg_proc p
    join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'public'
      and p.proname = 'current_user_role'
      and pg_get_function_identity_arguments(p.oid) = ''
  ) then
    execute 'alter function public.current_user_role() set search_path = public';
  end if;

  if exists (
    select 1
    from pg_proc p
    join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'public'
      and p.proname = 'ensure_current_user_profile'
      and pg_get_function_identity_arguments(p.oid) = ''
  ) then
    execute 'alter function public.ensure_current_user_profile() set search_path = public';
  end if;

  if exists (
    select 1
    from pg_proc p
    join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'public'
      and p.proname = 'handle_new_auth_user'
      and pg_get_function_identity_arguments(p.oid) = ''
  ) then
    execute 'alter function public.handle_new_auth_user() set search_path = public';
  end if;
end;
$$;
