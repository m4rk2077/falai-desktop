-- FALAI - Official lead ops fields on top of beta capture table
-- Date: 2026-03-29
-- Purpose: prepare `leads_beta` for the official market flow without breaking the current beta data model.
-- Safe to execute multiple times.

alter table if exists public.leads_beta
  add column if not exists auth_user_id uuid,
  add column if not exists profile_id uuid,
  add column if not exists provisioning_status text not null default 'pending',
  add column if not exists provisioned_at timestamptz,
  add column if not exists onboarding_channel text,
  add column if not exists onboarding_sent_at timestamptz,
  add column if not exists first_login_at timestamptz,
  add column if not exists first_transcription_at timestamptz,
  add column if not exists trial_started_at timestamptz,
  add column if not exists trial_ends_at timestamptz,
  add column if not exists converted_at timestamptz,
  add column if not exists last_workflow_error text;

do $$
begin
  if exists (
    select 1
    from information_schema.tables
    where table_schema = 'public'
      and table_name = 'profiles'
  ) then
    if not exists (
      select 1
      from pg_constraint
      where conname = 'leads_beta_profile_id_fkey'
    ) then
      alter table public.leads_beta
        add constraint leads_beta_profile_id_fkey
        foreign key (profile_id) references public.profiles(id) on delete set null;
    end if;
  end if;
end $$;

do $$
declare
  v_constraint_name text;
begin
  select conname
  into v_constraint_name
  from pg_constraint
  where conrelid = 'public.leads_beta'::regclass
    and contype = 'c'
    and pg_get_constraintdef(oid) ilike '%status%'
    and pg_get_constraintdef(oid) not ilike '%provisioning_status%'
  order by conname
  limit 1;

  if v_constraint_name is not null then
    execute format('alter table public.leads_beta drop constraint %I', v_constraint_name);
  end if;

  alter table public.leads_beta
    add constraint leads_beta_status_check
    check (
      status in (
        'novo',
        'provisionando',
        'contatado',
        'ativado',
        'trial_expirado',
        'convertido',
        'desqualificado',
        'erro'
      )
    );
end $$;

do $$
begin
  if exists (
    select 1
    from pg_constraint
    where conname = 'leads_beta_provisioning_status_check'
  ) then
    alter table public.leads_beta drop constraint leads_beta_provisioning_status_check;
  end if;

  alter table public.leads_beta
    add constraint leads_beta_provisioning_status_check
    check (
      provisioning_status in (
        'pending',
        'provisioning',
        'provisioned',
        'onboarding_sent',
        'error'
      )
    );
end $$;

do $$
begin
  if exists (
    select 1
    from pg_constraint
    where conname = 'leads_beta_auth_profile_match_check'
  ) then
    alter table public.leads_beta drop constraint leads_beta_auth_profile_match_check;
  end if;

  alter table public.leads_beta
    add constraint leads_beta_auth_profile_match_check
    check (
      auth_user_id is null
      or profile_id is null
      or auth_user_id = profile_id
    );
end $$;

create unique index if not exists ux_leads_beta_auth_user_id
  on public.leads_beta(auth_user_id)
  where auth_user_id is not null;

create unique index if not exists ux_leads_beta_profile_id
  on public.leads_beta(profile_id)
  where profile_id is not null;

create index if not exists ix_leads_beta_provisioning_status
  on public.leads_beta(provisioning_status);

create index if not exists ix_leads_beta_trial_ends_at
  on public.leads_beta(trial_ends_at)
  where trial_ends_at is not null;

create index if not exists ix_leads_beta_onboarding_sent_at
  on public.leads_beta(onboarding_sent_at)
  where onboarding_sent_at is not null;

create index if not exists ix_leads_beta_first_login_at
  on public.leads_beta(first_login_at)
  where first_login_at is not null;

create index if not exists ix_leads_beta_first_transcription_at
  on public.leads_beta(first_transcription_at)
  where first_transcription_at is not null;

create index if not exists ix_leads_beta_converted_at
  on public.leads_beta(converted_at)
  where converted_at is not null;

update public.leads_beta
set provisioning_status = case
  when status = 'ativado' then 'provisioned'
  when status = 'contatado' then 'onboarding_sent'
  when status = 'erro' then 'error'
  else provisioning_status
end
where provisioning_status = 'pending'
  and status in ('contatado', 'ativado', 'erro');

comment on column public.leads_beta.auth_user_id is
  'UUID do usuario oficial no Auth; quando perfil existir, deve coincidir com profile_id.';

comment on column public.leads_beta.profile_id is
  'UUID do perfil publico vinculado ao lead provisionado.';

comment on column public.leads_beta.provisioning_status is
  'Estado tecnico do provisionamento: pending, provisioning, provisioned, onboarding_sent, error.';

comment on column public.leads_beta.trial_started_at is
  'Momento em que o trial oficial de 7 dias foi iniciado para o usuario provisionado.';

comment on column public.leads_beta.trial_ends_at is
  'Momento em que o trial oficial expira para o usuario provisionado.';
