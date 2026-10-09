-- DASH-015: Cadence Queue Processor (pg_cron)

create or replace function analytics.process_cadence_queue()
returns int
language plpgsql
security definer
set search_path to 'public', 'analytics'
as $$
declare
  v_processed int := 0;
  v_enrollment record;
  v_next_step record;
  v_lead record;
  v_should_send boolean;
begin
  for v_enrollment in
    select ce.*, ec.is_active as cadence_active
    from public.cadence_enrollments ce
    join public.email_cadences ec on ec.id = ce.cadence_id
    where ce.status = 'active'
      and ce.next_step_at <= timezone('utc', now())
      and ec.is_active = true
    order by ce.next_step_at asc
    limit 100
    for update of ce skip locked
  loop
    select * into v_next_step
    from public.cadence_steps
    where cadence_id = v_enrollment.cadence_id
      and step_order = v_enrollment.current_step + 1
      and is_active = true;

    if v_next_step is null then
      update public.cadence_enrollments
      set status = 'completed', completed_at = timezone('utc', now())
      where id = v_enrollment.id;
      v_processed := v_processed + 1;
      continue;
    end if;

    select * into v_lead
    from public.leads_beta
    where id = v_enrollment.lead_id;

    if v_lead is null then
      update public.cadence_enrollments
      set status = 'cancelled', cancel_reason = 'lead_not_found'
      where id = v_enrollment.id;
      continue;
    end if;

    if v_lead.status in ('convertido', 'desqualificado') then
      update public.cadence_enrollments
      set status = 'cancelled', cancel_reason = 'lead_status_' || v_lead.status
      where id = v_enrollment.id;
      continue;
    end if;

    v_should_send := true;
    if v_next_step.condition_sql is not null and v_next_step.condition_sql <> '' then
      execute format(
        'select exists(select 1 from public.leads_beta where id = $1 and (%s))',
        v_next_step.condition_sql
      ) into v_should_send using v_enrollment.lead_id;
    end if;

    insert into public.email_sends (
      enrollment_id, step_id, lead_id, status, channel, to_address, subject
    ) values (
      v_enrollment.id,
      v_next_step.id,
      v_enrollment.lead_id,
      case when v_should_send then 'pending' else 'skipped' end,
      v_next_step.channel,
      coalesce(v_lead.email_normalized, v_lead.email),
      v_next_step.subject
    );

    update public.cadence_enrollments
    set
      current_step = v_next_step.step_order,
      next_step_at = case
        when exists (
          select 1 from public.cadence_steps
          where cadence_id = v_enrollment.cadence_id
            and step_order = v_next_step.step_order + 1
            and is_active = true
        )
        then timezone('utc', now()) + (
          select (delay_hours || ' hours')::interval
          from public.cadence_steps
          where cadence_id = v_enrollment.cadence_id
            and step_order = v_next_step.step_order + 1
          limit 1
        )
        else null
      end
    where id = v_enrollment.id;

    v_processed := v_processed + 1;
  end loop;

  return v_processed;
end;
$$;

-- Schedule: run every 15 minutes
select cron.schedule(
  'process-cadence-queue',
  '*/15 * * * *',
  'select analytics.process_cadence_queue()'
);
