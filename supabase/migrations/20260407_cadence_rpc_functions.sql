-- =============================================================
-- FALAI Cadence: RPC Functions for n8n HTTP integration
-- These functions are called via Supabase REST API from n8n
-- =============================================================

-- 1. Claim pending email sends (atomic, skip locked)
CREATE OR REPLACE FUNCTION public.cadence_claim_pending_sends(p_limit int DEFAULT 30)
RETURNS TABLE(
  id uuid,
  enrollment_id uuid,
  step_id uuid,
  lead_id uuid,
  channel text,
  to_address text,
  subject text
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public'
AS $$
BEGIN
  RETURN QUERY
  UPDATE public.email_sends es
  SET status = 'sending', updated_at = timezone('utc', now())
  WHERE es.id IN (
    SELECT es2.id FROM public.email_sends es2
    WHERE es2.status = 'pending'
    ORDER BY es2.created_at ASC
    LIMIT p_limit
    FOR UPDATE SKIP LOCKED
  )
  RETURNING es.id, es.enrollment_id, es.step_id, es.lead_id, es.channel, es.to_address, es.subject;
END;
$$;

-- 2. Get lead data for template rendering
CREATE OR REPLACE FUNCTION public.cadence_get_lead(p_lead_id uuid)
RETURNS TABLE(
  id uuid,
  nome text,
  email text,
  email_normalized text,
  whatsapp text,
  whatsapp_normalized text,
  status text,
  trial_started_at timestamptz,
  trial_ends_at timestamptz,
  first_login_at timestamptz,
  first_transcription_at timestamptz,
  converted_at timestamptz
)
LANGUAGE sql
SECURITY DEFINER
SET search_path TO 'public'
AS $$
  SELECT lb.id, lb.nome, lb.email, lb.email_normalized,
         lb.whatsapp, lb.whatsapp_normalized, lb.status,
         lb.trial_started_at, lb.trial_ends_at, lb.first_login_at,
         lb.first_transcription_at, lb.converted_at
  FROM public.leads_beta lb
  WHERE lb.id = p_lead_id;
$$;

-- 3. Get step template
CREATE OR REPLACE FUNCTION public.cadence_get_step_template(p_step_id uuid)
RETURNS TABLE(
  subject text,
  body_template text,
  channel text,
  step_order int,
  cadence_name text
)
LANGUAGE sql
SECURITY DEFINER
SET search_path TO 'public'
AS $$
  SELECT cs.subject, cs.body_template, cs.channel, cs.step_order,
         ec.name as cadence_name
  FROM public.cadence_steps cs
  JOIN public.email_cadences ec ON ec.id = cs.cadence_id
  WHERE cs.id = p_step_id;
$$;

-- 4. Mark send as delivered
CREATE OR REPLACE FUNCTION public.cadence_mark_delivered(p_send_id uuid)
RETURNS void
LANGUAGE sql
SECURITY DEFINER
SET search_path TO 'public'
AS $$
  UPDATE public.email_sends
  SET status = 'delivered',
      delivered_at = timezone('utc', now()),
      updated_at = timezone('utc', now())
  WHERE id = p_send_id;
$$;

-- 5. Mark send as failed
CREATE OR REPLACE FUNCTION public.cadence_mark_failed(p_send_id uuid, p_error text DEFAULT 'Unknown error')
RETURNS void
LANGUAGE sql
SECURITY DEFINER
SET search_path TO 'public'
AS $$
  UPDATE public.email_sends
  SET status = 'failed',
      error_message = p_error,
      updated_at = timezone('utc', now())
  WHERE id = p_send_id;
$$;

-- 6. Check if lead is already enrolled in a cadence
CREATE OR REPLACE FUNCTION public.cadence_check_enrolled(p_lead_id uuid, p_trigger_event text)
RETURNS TABLE(id uuid, status text, cadence_name text)
LANGUAGE sql
SECURITY DEFINER
SET search_path TO 'public'
AS $$
  SELECT ce.id, ce.status, ec.name as cadence_name
  FROM public.cadence_enrollments ce
  JOIN public.email_cadences ec ON ec.id = ce.cadence_id
  WHERE ce.lead_id = p_lead_id
    AND ec.trigger_event = p_trigger_event
    AND ce.status = 'active'
  LIMIT 1;
$$;

-- 7. Cancel conflicting cadences
CREATE OR REPLACE FUNCTION public.cadence_cancel_conflicting(
  p_lead_id uuid,
  p_trigger_event text
)
RETURNS int
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public'
AS $$
DECLARE
  v_cancelled int;
BEGIN
  IF p_trigger_event = 'subscription_activated' THEN
    -- Cancel ALL active cadences
    UPDATE public.cadence_enrollments
    SET status = 'cancelled',
        cancel_reason = 'converted',
        cancelled_at = timezone('utc', now()),
        updated_at = timezone('utc', now())
    WHERE lead_id = p_lead_id AND status = 'active';
  ELSIF p_trigger_event = 'trial_expired' THEN
    -- Cancel Trial Onboarding + Activation Nudge
    UPDATE public.cadence_enrollments
    SET status = 'cancelled',
        cancel_reason = 'trial_expired',
        cancelled_at = timezone('utc', now()),
        updated_at = timezone('utc', now())
    WHERE lead_id = p_lead_id
      AND status = 'active'
      AND cadence_id IN (
        SELECT id FROM public.email_cadences
        WHERE trigger_event IN ('account_created', 'activation_nudge')
      );
  END IF;

  GET DIAGNOSTICS v_cancelled = ROW_COUNT;
  RETURN v_cancelled;
END;
$$;

-- 8. Enroll lead in cadence
CREATE OR REPLACE FUNCTION public.cadence_enroll(p_lead_id uuid, p_trigger_event text)
RETURNS TABLE(enrollment_id uuid, cadence_name text)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public'
AS $$
DECLARE
  v_cadence_id uuid;
  v_cadence_name text;
  v_first_delay int;
  v_enrollment_id uuid;
BEGIN
  -- Find active cadence
  SELECT ec.id, ec.name INTO v_cadence_id, v_cadence_name
  FROM public.email_cadences ec
  WHERE ec.trigger_event = p_trigger_event AND ec.is_active = true
  LIMIT 1;

  IF v_cadence_id IS NULL THEN
    RETURN;
  END IF;

  -- Get first step delay
  SELECT cs.delay_hours INTO v_first_delay
  FROM public.cadence_steps cs
  WHERE cs.cadence_id = v_cadence_id AND cs.step_order = 1 AND cs.is_active = true
  LIMIT 1;

  -- Insert enrollment
  INSERT INTO public.cadence_enrollments (cadence_id, lead_id, status, current_step, next_step_at)
  VALUES (
    v_cadence_id, p_lead_id, 'active', 0,
    timezone('utc', now()) + (coalesce(v_first_delay, 0) || ' hours')::interval
  )
  ON CONFLICT DO NOTHING
  RETURNING id INTO v_enrollment_id;

  IF v_enrollment_id IS NOT NULL THEN
    -- Log event
    INSERT INTO public.lead_events (lead_id, event_name, event_source, event_payload)
    VALUES (p_lead_id, 'cadence_enrolled', 'n8n',
      json_build_object('cadence_trigger', p_trigger_event)::jsonb);

    RETURN QUERY SELECT v_enrollment_id, v_cadence_name;
  END IF;
END;
$$;

-- 9. Find expired trials
CREATE OR REPLACE FUNCTION public.cadence_find_expired_trials(p_limit int DEFAULT 50)
RETURNS TABLE(id uuid, email text, nome text, status text, trial_ends_at timestamptz)
LANGUAGE sql
SECURITY DEFINER
SET search_path TO 'public'
AS $$
  SELECT lb.id, lb.email, lb.nome, lb.status, lb.trial_ends_at
  FROM public.leads_beta lb
  WHERE lb.trial_ends_at < timezone('utc', now())
    AND lb.status NOT IN ('convertido', 'desqualificado', 'trial_expirado', 'erro')
    AND lb.converted_at IS NULL
    AND NOT EXISTS (
      SELECT 1 FROM public.cadence_enrollments ce
      JOIN public.email_cadences ec ON ec.id = ce.cadence_id
      WHERE ce.lead_id = lb.id
        AND ec.trigger_event = 'trial_expired'
        AND ce.status IN ('active', 'completed')
    )
  ORDER BY lb.trial_ends_at ASC
  LIMIT p_limit;
$$;

-- 10. Mark lead as trial expired
CREATE OR REPLACE FUNCTION public.cadence_mark_trial_expired(p_lead_id uuid)
RETURNS void
LANGUAGE sql
SECURITY DEFINER
SET search_path TO 'public'
AS $$
  UPDATE public.leads_beta
  SET status = 'trial_expirado', updated_at = timezone('utc', now())
  WHERE id = p_lead_id
    AND status NOT IN ('convertido', 'desqualificado');
$$;

-- 11. Find activation nudge candidates
CREATE OR REPLACE FUNCTION public.cadence_find_nudge_candidates(p_limit int DEFAULT 30)
RETURNS TABLE(id uuid, email text, nome text)
LANGUAGE sql
SECURITY DEFINER
SET search_path TO 'public'
AS $$
  SELECT lb.id, lb.email, lb.nome
  FROM public.leads_beta lb
  WHERE lb.first_login_at IS NOT NULL
    AND lb.first_login_at < timezone('utc', now()) - interval '24 hours'
    AND lb.first_transcription_at IS NULL
    AND lb.status NOT IN ('convertido', 'desqualificado', 'trial_expirado', 'erro')
    AND lb.converted_at IS NULL
    AND NOT EXISTS (
      SELECT 1 FROM public.cadence_enrollments ce
      JOIN public.email_cadences ec ON ec.id = ce.cadence_id
      WHERE ce.lead_id = lb.id
        AND ec.trigger_event = 'activation_nudge'
        AND ce.status IN ('active', 'completed')
    )
  ORDER BY lb.first_login_at ASC
  LIMIT p_limit;
$$;

-- 12. Find dormant paid users
CREATE OR REPLACE FUNCTION public.cadence_find_dormant_paid(p_limit int DEFAULT 20)
RETURNS TABLE(id uuid, email text, nome text, auth_user_id text)
LANGUAGE sql
SECURITY DEFINER
SET search_path TO 'public'
AS $$
  SELECT lb.id, lb.email, lb.nome, lb.auth_user_id
  FROM public.leads_beta lb
  WHERE lb.status = 'convertido'
    AND lb.auth_user_id IS NOT NULL
    AND NOT EXISTS (
      SELECT 1 FROM public.transcriptions t
      WHERE t.user_id = lb.auth_user_id::uuid
        AND t.created_at > timezone('utc', now()) - interval '7 days'
    )
    AND NOT EXISTS (
      SELECT 1 FROM public.cadence_enrollments ce
      JOIN public.email_cadences ec ON ec.id = ce.cadence_id
      WHERE ce.lead_id = lb.id
        AND ec.trigger_event = 'dormant_paid'
        AND ce.status = 'active'
    )
    AND EXISTS (
      SELECT 1 FROM public.subscriptions s
      WHERE s.user_id = lb.auth_user_id::uuid
        AND s.status = 'active'
    )
  ORDER BY lb.converted_at DESC
  LIMIT p_limit;
$$;
