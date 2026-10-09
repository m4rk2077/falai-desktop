-- FWEB-005 — extension_pairings table
-- Short-lived tokens that bridge a logged-in portal session to a Chrome extension instance.
-- Flow: portal calls create_extension_pairing -> raw token returned ONCE -> extension
-- calls exchange_extension_token with the raw token to receive a Supabase session.

begin;

create extension if not exists pgcrypto;

create table if not exists public.extension_pairings (
  id               uuid primary key default gen_random_uuid(),
  user_id          uuid not null references auth.users(id) on delete cascade,
  token_hash       text not null,
  created_at       timestamptz not null default now(),
  expires_at       timestamptz not null,
  used_at          timestamptz,
  revoked_at       timestamptz,
  extension_id     text,
  user_agent       text,
  ip_hash          text,
  label            text
);

create unique index if not exists extension_pairings_token_hash_uq
  on public.extension_pairings(token_hash);

create index if not exists extension_pairings_user_active_idx
  on public.extension_pairings(user_id, revoked_at)
  where revoked_at is null;

create index if not exists extension_pairings_expires_idx
  on public.extension_pairings(expires_at)
  where used_at is null and revoked_at is null;

alter table public.extension_pairings enable row level security;

drop policy if exists "pairings owner select" on public.extension_pairings;
create policy "pairings owner select"
  on public.extension_pairings
  for select
  to authenticated
  using (user_id = auth.uid());

drop policy if exists "pairings owner revoke" on public.extension_pairings;
create policy "pairings owner revoke"
  on public.extension_pairings
  for update
  to authenticated
  using (user_id = auth.uid())
  with check (user_id = auth.uid());

-- Service role only inserts (edge function create_extension_pairing).
drop policy if exists "pairings service insert" on public.extension_pairings;
create policy "pairings service insert"
  on public.extension_pairings
  for insert
  to service_role
  with check (true);

-- Helper: hash a raw token (sha256 hex) — used by edge functions via rpc optionally.
create or replace function public.fweb_hash_token(p_token text)
returns text
language sql
immutable
set search_path = public, pg_temp
as $$
  select encode(digest(p_token, 'sha256'), 'hex');
$$;

grant execute on function public.fweb_hash_token(text) to authenticated, anon, service_role;

-- Cleanup job (called by pg_cron or edge function): purge expired/used pairings older than 7d.
create or replace function public.fweb_cleanup_expired_pairings()
returns integer
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_deleted integer;
begin
  delete from public.extension_pairings
  where (used_at is not null and used_at < now() - interval '7 days')
     or (expires_at < now() - interval '7 days' and used_at is null);
  get diagnostics v_deleted = row_count;
  return v_deleted;
end;
$$;

grant execute on function public.fweb_cleanup_expired_pairings() to service_role;

comment on table public.extension_pairings is
  'FWEB-005 — pairing tokens for portal <-> chrome extension handshake. Raw token returned only once, stored as sha256 hash.';

commit;
