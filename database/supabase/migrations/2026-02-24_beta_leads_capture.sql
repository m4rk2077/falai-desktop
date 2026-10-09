-- FALAI - Beta leads capture tables + RLS
-- Date: 2026-02-24
-- Purpose: canonical storage for LP form leads + event trail

create table if not exists public.leads_beta (
  id uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default timezone('utc', now()),
  updated_at timestamptz not null default timezone('utc', now()),

  nome text not null,
  email text not null,
  email_normalized text not null,
  whatsapp text,
  whatsapp_normalized text,
  motivo text,
  origem_form text not null,

  status text not null default 'novo'
    check (status in ('novo', 'contatado', 'ativado', 'desqualificado')),

  utm_source text,
  utm_medium text,
  utm_campaign text,
  utm_content text,
  utm_term text,
  fbclid text,
  gclid text,

  landing_variant text,
  referrer text,
  page_path text,
  ip_hash text,
  user_agent text,

  source_payload jsonb not null default '{}'::jsonb,

  first_seen_at timestamptz not null default timezone('utc', now()),
  last_seen_at timestamptz not null default timezone('utc', now()),
  submit_count int not null default 1 check (submit_count >= 1)
);

create unique index if not exists ux_leads_beta_email_norm
  on public.leads_beta(email_normalized);

create index if not exists ix_leads_beta_created_at
  on public.leads_beta(created_at desc);

create index if not exists ix_leads_beta_utm_campaign
  on public.leads_beta(utm_campaign);

create index if not exists ix_leads_beta_status
  on public.leads_beta(status);

drop trigger if exists trg_leads_beta_updated_at on public.leads_beta;
create trigger trg_leads_beta_updated_at
before update on public.leads_beta
for each row
execute function public.set_updated_at();

create table if not exists public.lead_events (
  id uuid primary key default gen_random_uuid(),
  lead_id uuid not null references public.leads_beta(id) on delete cascade,
  event_name text not null,
  event_source text not null
    check (event_source in ('site', 'edge', 'n8n', 'app', 'manual')),
  event_payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default timezone('utc', now())
);

create index if not exists ix_lead_events_lead_created
  on public.lead_events(lead_id, created_at desc);

create index if not exists ix_lead_events_name_created
  on public.lead_events(event_name, created_at desc);

-- Replay/idempotency guard for lead submit events.
create unique index if not exists ux_lead_events_submit_idempotency_key
  on public.lead_events ((event_payload ->> 'idempotency_key'))
  where event_name = 'lead_submit' and coalesce(event_payload ->> 'idempotency_key', '') <> '';

alter table public.leads_beta enable row level security;
alter table public.lead_events enable row level security;

drop policy if exists leads_beta_select_staff on public.leads_beta;
create policy leads_beta_select_staff on public.leads_beta
for select using (public.current_user_role() in ('admin', 'support'));

drop policy if exists lead_events_select_staff on public.lead_events;
create policy lead_events_select_staff on public.lead_events
for select using (public.current_user_role() in ('admin', 'support'));
