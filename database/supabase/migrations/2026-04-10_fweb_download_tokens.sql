-- FWEB-006 — download_tokens table
-- Audit trail for premium desktop downloads. Each generated signed URL gets a row.

begin;

create table if not exists public.download_tokens (
  id              uuid primary key default gen_random_uuid(),
  user_id         uuid not null references auth.users(id) on delete cascade,
  artifact        text not null,
  platform        text not null check (platform in ('windows','macos','linux')),
  generated_at    timestamptz not null default now(),
  expires_at      timestamptz not null,
  downloaded_at   timestamptz,
  ip_hash         text,
  user_agent      text,
  signed_url_hash text
);

create index if not exists download_tokens_user_idx
  on public.download_tokens(user_id, generated_at desc);

create index if not exists download_tokens_expires_idx
  on public.download_tokens(expires_at)
  where downloaded_at is null;

alter table public.download_tokens enable row level security;

-- Users can view their own download history (for UI in /downloads).
drop policy if exists "downloads owner select" on public.download_tokens;
create policy "downloads owner select"
  on public.download_tokens
  for select
  to authenticated
  using (user_id = auth.uid());

-- Only service role inserts (via generate_desktop_download_url edge function).
drop policy if exists "downloads service insert" on public.download_tokens;
create policy "downloads service insert"
  on public.download_tokens
  for insert
  to service_role
  with check (true);

drop policy if exists "downloads service update" on public.download_tokens;
create policy "downloads service update"
  on public.download_tokens
  for update
  to service_role
  using (true)
  with check (true);

comment on table public.download_tokens is
  'FWEB-006 — audit of premium desktop artifact downloads. One row per signed URL generated.';

commit;
