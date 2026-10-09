-- =============================================================
-- FALAI Email Cadence: Full Lifecycle System
-- Date: 2026-04-07
-- Description: Inserts all cadence steps for 5 lifecycle cadences,
--              adds 2 new cadence definitions, and creates
--              auto-enrollment trigger on lead_events.
-- =============================================================

-- -----------------------------------------------
-- 1. New cadence definitions (activation_nudge, dormant_paid)
-- -----------------------------------------------
INSERT INTO public.email_cadences (name, trigger_event, description) VALUES
  ('Activation Nudge', 'activation_nudge', 'Nudge para usuario que logou mas nao fez primeira transcricao'),
  ('Dormant Paid User', 'dormant_paid', 'Re-engajamento de usuario pago inativo 7+ dias')
ON CONFLICT DO NOTHING;


-- -----------------------------------------------
-- 2. CADENCE STEPS: Trial Onboarding (account_created)
-- -----------------------------------------------
WITH cad AS (
  SELECT id FROM public.email_cadences
  WHERE trigger_event = 'account_created' AND is_active = true
  LIMIT 1
)
INSERT INTO public.cadence_steps (cadence_id, step_order, delay_hours, channel, subject, body_template, condition_sql)
SELECT cad.id, v.step_order, v.delay_hours, v.channel, v.subject, v.body_template, v.condition_sql
FROM cad, (VALUES

-- Step 1: D0 Welcome email (immediate)
(1, 0, 'email',
 'Bem-vindo ao FALAI, {{primeiro_nome}}! Seu acesso esta liberado',
 '<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:24px;">
<p>Ola, {{primeiro_nome}}!</p>
<p>Seu teste gratuito de <strong>7 dias</strong> do FALAI ja esta ativo. Voce tem <strong>15 minutos por dia</strong> de transcricao por voz.</p>
<h3>Proximo passo:</h3>
<p>1. <a href="{{app_download_url}}" style="color:#ffb86b;font-weight:bold;">Baixe o FALAI para Windows</a></p>
<p>2. Instale normalmente (se o SmartScreen aparecer, clique em "Mais informacoes" &rarr; "Executar assim mesmo")</p>
<p>3. Faca login com este e-mail: <strong>{{email}}</strong></p>
<p>4. Pressione <strong>Ctrl+Shift</strong> e comece a falar!</p>
<p><a href="{{app_tutorial_url}}" style="display:inline-block;padding:12px 24px;background:#ffb86b;color:#08111c;border-radius:8px;text-decoration:none;font-weight:bold;">Ver tutorial em video (2 min)</a></p>
<p>Qualquer duvida: <a href="{{support_whatsapp}}">WhatsApp de suporte</a></p>
<p>&mdash; Equipe FALAI</p>
</div>',
 NULL),

-- Step 2: D0 WhatsApp welcome
(2, 0, 'whatsapp',
 NULL,
 'Ola, {{primeiro_nome}}! Seu acesso ao FALAI esta liberado. Baixe aqui: {{app_download_url}}

Qualquer duvida sobre instalacao, responde aqui que te ajudo!',
 NULL),

-- Step 3: D1 Installation reminder (only if never logged in)
(3, 24, 'email',
 '{{primeiro_nome}}, ja instalou o FALAI? Leva 2 minutos',
 '<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:24px;">
<p>Oi, {{primeiro_nome}}!</p>
<p>Vi que voce ainda nao fez login no FALAI. Sem problemas &mdash; a instalacao leva menos de 2 minutos.</p>
<h3>Passo a passo rapido:</h3>
<p>1. <a href="{{app_download_url}}" style="color:#ffb86b;font-weight:bold;">Clique aqui para baixar</a></p>
<p>2. Abra o instalador (.exe) que foi baixado</p>
<p>3. Se o Windows SmartScreen aparecer: clique em "Mais informacoes" &rarr; "Executar assim mesmo"</p>
<p>4. Faca login com: <strong>{{email}}</strong></p>
<p>Seu trial de 7 dias ja esta correndo &mdash; nao perca tempo!</p>
<p><a href="{{app_download_url}}" style="display:inline-block;padding:12px 24px;background:#ffb86b;color:#08111c;border-radius:8px;text-decoration:none;font-weight:bold;">Baixar FALAI agora</a></p>
<p>Precisa de ajuda? <a href="{{support_whatsapp}}">Fale com a gente no WhatsApp</a></p>
</div>',
 'first_login_at IS NULL'),

-- Step 4: D2 First transcription guide (logged in but no transcription)
(4, 48, 'email',
 '{{primeiro_nome}}, faca sua primeira transcricao em 30 segundos',
 '<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:24px;">
<p>Oi, {{primeiro_nome}}!</p>
<p>Vi que voce ja instalou o FALAI &mdash; otimo! Agora falta so o passo que vai mudar tudo: <strong>sua primeira transcricao</strong>.</p>
<h3>Como fazer (30 segundos):</h3>
<p>1. Abra o FALAI (icone na bandeja do sistema)</p>
<p>2. Pressione <strong>Ctrl+Shift</strong> e segure</p>
<p>3. Fale normalmente &mdash; como se estivesse ditando uma mensagem</p>
<p>4. Solte a tecla e veja o texto aparecer no cursor</p>
<p><strong>Dica:</strong> Experimente no WhatsApp, em um e-mail ou no Google Docs. O texto aparece direto onde seu cursor estiver.</p>
<p><a href="{{app_tutorial_url}}" style="display:inline-block;padding:12px 24px;background:#ffb86b;color:#08111c;border-radius:8px;text-decoration:none;font-weight:bold;">Ver tutorial rapido</a></p>
</div>',
 'first_login_at IS NOT NULL AND first_transcription_at IS NULL'),

-- Step 5: D3 Social proof + tips
(5, 72, 'email',
 'Como profissionais estao economizando 2h por dia com o FALAI',
 '<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:24px;">
<p>Oi, {{primeiro_nome}}!</p>
<p>Voce sabia que os usuarios do FALAI economizam em media <strong>2 horas por dia</strong> ao substituir digitacao por voz?</p>
<h3>Como estao usando:</h3>
<p>&#x1f4cb; <strong>Advogados:</strong> Ditam peticoes e pareceres direto no Word</p>
<p>&#x1f3e5; <strong>Medicos:</strong> Preenchem prontuarios sem parar de olhar o paciente</p>
<p>&#x1f4bc; <strong>Consultores:</strong> Respondem e-mails 5x mais rapido</p>
<p>&#x1f4dd; <strong>Escritores:</strong> Transcrevem ideias sem travar na tela em branco</p>
<p>O FALAI funciona em <strong>qualquer aplicativo</strong> &mdash; WhatsApp, Google Docs, Notion, e-mail, CRM...</p>
<p><a href="{{access_link}}" style="display:inline-block;padding:12px 24px;background:#ffb86b;color:#08111c;border-radius:8px;text-decoration:none;font-weight:bold;">Abrir o FALAI e testar agora</a></p>
</div>',
 NULL),

-- Step 6: D5 Feature highlight
(6, 120, 'email',
 '{{primeiro_nome}}, como esta indo com o FALAI?',
 '<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:24px;">
<p>Oi, {{primeiro_nome}}!</p>
<p>Ja faz alguns dias desde que voce comecou a testar o FALAI. Como esta indo?</p>
<h3>Voce ja experimentou estes recursos?</h3>
<p>&#x2728; <strong>Correcao inteligente:</strong> O FALAI corrige automaticamente o que voce fala</p>
<p>&#x1f3af; <strong>Estilos de correcao:</strong> Escolha entre Neutro, Casual ou Formal para cada contexto</p>
<p>&#x2328; <strong>Atalhos personalizaveis:</strong> Configure a tecla que preferir para ativar</p>
<p>Seu trial termina em <strong>{{dias_restantes}} dias</strong>. Aproveite ao maximo!</p>
<p><a href="{{access_link}}" style="display:inline-block;padding:12px 24px;background:#ffb86b;color:#08111c;border-radius:8px;text-decoration:none;font-weight:bold;">Continuar usando o FALAI</a></p>
<p>Duvidas ou feedback? <a href="{{support_whatsapp}}">Estamos no WhatsApp</a></p>
</div>',
 NULL),

-- Step 7: D6 Trial ending tomorrow
(7, 144, 'email',
 '{{primeiro_nome}}, seu trial do FALAI termina amanha',
 '<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:24px;">
<p>Oi, {{primeiro_nome}}!</p>
<p>Seu periodo de teste do FALAI <strong>termina amanha</strong>.</p>
<p>Para continuar usando sem interrupcao, escolha o plano ideal:</p>
<table style="width:100%;border-collapse:collapse;margin:16px 0;">
<tr style="background:#f8f9fa;">
<td style="padding:12px;border:1px solid #ddd;"><strong>Start</strong><br>R$ 29/mes<br>30 min/dia, correcao inteligente</td>
<td style="padding:12px;border:1px solid #ddd;"><strong>Pro</strong><br>R$ 79/mes<br>Ilimitado, prioridade no processamento</td>
</tr>
</table>
<p><a href="{{upgrade_url}}" style="display:inline-block;padding:14px 28px;background:#ffb86b;color:#08111c;border-radius:8px;text-decoration:none;font-weight:bold;font-size:16px;">Assinar agora e nao perder acesso</a></p>
<p>Duvida sobre qual plano? <a href="{{support_whatsapp}}">Fale com a gente</a></p>
</div>',
 NULL),

-- Step 8: D6 WhatsApp trial ending
(8, 144, 'whatsapp',
 NULL,
 '{{primeiro_nome}}, seu teste do FALAI termina amanha!

Para continuar usando, assine aqui: {{upgrade_url}}

Duvida sobre qual plano? Responde aqui que te ajudo!',
 NULL)

) AS v(step_order, delay_hours, channel, subject, body_template, condition_sql)
ON CONFLICT DO NOTHING;


-- -----------------------------------------------
-- 3. CADENCE STEPS: Activation Nudge (activation_nudge)
-- -----------------------------------------------
WITH cad AS (
  SELECT id FROM public.email_cadences
  WHERE trigger_event = 'activation_nudge' AND is_active = true
  LIMIT 1
)
INSERT INTO public.cadence_steps (cadence_id, step_order, delay_hours, channel, subject, body_template, condition_sql)
SELECT cad.id, v.step_order, v.delay_hours, v.channel, v.subject, v.body_template, v.condition_sql
FROM cad, (VALUES

-- Step 1: Immediate tutorial
(1, 0, 'email',
 '{{primeiro_nome}}, sua primeira transcricao em 30 segundos',
 '<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:24px;">
<p>Oi, {{primeiro_nome}}!</p>
<p>Vi que voce ja instalou o FALAI, mas ainda nao fez sua primeira transcricao. E super rapido &mdash; <strong>30 segundos</strong>.</p>
<h3>Faca agora:</h3>
<p>1. Abra qualquer app com campo de texto (WhatsApp Web, Google Docs, e-mail...)</p>
<p>2. Pressione <strong>Ctrl+Shift</strong> e segure</p>
<p>3. Fale: "Ola, isso e um teste do FALAI"</p>
<p>4. Solte a tecla e veja o texto aparecer!</p>
<p><a href="{{app_tutorial_url}}" style="display:inline-block;padding:12px 24px;background:#ffb86b;color:#08111c;border-radius:8px;text-decoration:none;font-weight:bold;">Ver tutorial em video</a></p>
<p>Se algo nao funcionou, <a href="{{support_whatsapp}}">fale com nosso suporte pelo WhatsApp</a> &mdash; respondemos em minutos.</p>
</div>',
 'first_transcription_at IS NULL'),

-- Step 2: 48h later - what is blocking you?
(2, 48, 'email',
 '{{primeiro_nome}}, algo travou? Posso ajudar',
 '<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:24px;">
<p>Oi, {{primeiro_nome}}!</p>
<p>Percebi que voce ainda nao fez sua primeira transcricao no FALAI. Tudo bem &mdash; as vezes a gente precisa de uma mao.</p>
<p><strong>Problemas mais comuns e como resolver:</strong></p>
<p>&#x1f507; <strong>"Nao acontece nada quando falo"</strong> &rarr; Verifique se o microfone esta ativo nas configuracoes do Windows</p>
<p>&#x1f6e1; <strong>"O antivirus bloqueou"</strong> &rarr; Adicione o FALAI como excecao</p>
<p>&#x2328; <strong>"Ctrl+Shift nao funciona"</strong> &rarr; Outro programa pode estar usando esse atalho. Mude nas configuracoes do FALAI</p>
<p>Nenhum desses? Responda este e-mail ou <a href="{{support_whatsapp}}" style="color:#ffb86b;font-weight:bold;">fale com a gente no WhatsApp</a> &mdash; resolvemos juntos!</p>
</div>',
 'first_transcription_at IS NULL')

) AS v(step_order, delay_hours, channel, subject, body_template, condition_sql)
ON CONFLICT DO NOTHING;


-- -----------------------------------------------
-- 4. CADENCE STEPS: Win-back / Trial Expired (trial_expired)
-- -----------------------------------------------
WITH cad AS (
  SELECT id FROM public.email_cadences
  WHERE trigger_event = 'trial_expired' AND is_active = true
  LIMIT 1
)
INSERT INTO public.cadence_steps (cadence_id, step_order, delay_hours, channel, subject, body_template, condition_sql)
SELECT cad.id, v.step_order, v.delay_hours, v.channel, v.subject, v.body_template, v.condition_sql
FROM cad, (VALUES

-- Step 1: D+0 Trial ended
(1, 0, 'email',
 '{{primeiro_nome}}, seu trial do FALAI acabou',
 '<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:24px;">
<p>Oi, {{primeiro_nome}}!</p>
<p>Seu periodo de teste gratuito do FALAI encerrou hoje.</p>
<p>Durante seus 7 dias, voce teve acesso a:</p>
<ul>
<li>Transcricao por voz em qualquer aplicativo</li>
<li>Correcao inteligente automatica</li>
<li>3 estilos de texto (neutro, casual, formal)</li>
</ul>
<p>Para continuar com tudo isso, escolha seu plano:</p>
<p><a href="{{upgrade_url}}" style="display:inline-block;padding:14px 28px;background:#ffb86b;color:#08111c;border-radius:8px;text-decoration:none;font-weight:bold;">Ver planos e assinar</a></p>
<p>Tem duvidas? <a href="{{support_whatsapp}}">Fale com a gente</a></p>
</div>',
 NULL),

-- Step 2: D+2 Special offer 20%
(2, 48, 'email',
 '{{primeiro_nome}}, 20% de desconto no primeiro mes do FALAI',
 '<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:24px;">
<p>Oi, {{primeiro_nome}}!</p>
<p>Tenho uma oferta especial: <strong>20% de desconto no primeiro mes</strong> de qualquer plano FALAI.</p>
<table style="width:100%;border-collapse:collapse;margin:16px 0;">
<tr>
<td style="padding:12px;border:1px solid #ddd;text-align:center;"><strong>Start</strong><br><s>R$ 29</s> &rarr; <strong style="color:#ffb86b;">R$ 23,20/mes</strong></td>
<td style="padding:12px;border:1px solid #ddd;text-align:center;"><strong>Pro</strong><br><s>R$ 79</s> &rarr; <strong style="color:#ffb86b;">R$ 63,20/mes</strong></td>
</tr>
</table>
<p>Use o cupom <strong>VOLTA20</strong> no checkout.</p>
<p><a href="{{upgrade_url}}" style="display:inline-block;padding:14px 28px;background:#ffb86b;color:#08111c;border-radius:8px;text-decoration:none;font-weight:bold;">Assinar com 20% off</a></p>
<p><em>Oferta valida por 48 horas.</em></p>
</div>',
 'converted_at IS NULL'),

-- Step 3: D+5 Social proof
(3, 120, 'email',
 '{{primeiro_nome}}, veja por que centenas de profissionais escolheram o FALAI',
 '<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:24px;">
<p>Oi, {{primeiro_nome}}!</p>
<p>Desde que voce testou o FALAI, mais profissionais assinaram e estao transformando a forma como trabalham:</p>
<blockquote style="border-left:3px solid #ffb86b;padding:12px;margin:16px 0;background:#f8f9fa;">
<p><em>"Eu costumava gastar 1 hora digitando relatorios. Com o FALAI, faco em 15 minutos."</em></p>
<p>&mdash; Advogado, Sao Paulo</p>
</blockquote>
<blockquote style="border-left:3px solid #ffb86b;padding:12px;margin:16px 0;background:#f8f9fa;">
<p><em>"Minha produtividade no atendimento ao paciente dobrou. Preencho prontuarios falando."</em></p>
<p>&mdash; Medica, Curitiba</p>
</blockquote>
<p>Volte quando quiser: <a href="{{upgrade_url}}" style="color:#ffb86b;font-weight:bold;">ver planos</a></p>
</div>',
 'converted_at IS NULL'),

-- Step 4: D+10 Last chance 30%
(4, 240, 'email',
 '{{primeiro_nome}}, ultima chance: condicao especial do FALAI',
 '<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:24px;">
<p>Oi, {{primeiro_nome}}!</p>
<p>Esta e a ultima vez que vou enviar uma oferta especial.</p>
<p><strong>30% de desconto nos 2 primeiros meses</strong> &mdash; a melhor condicao que ja oferecemos.</p>
<p>Use o cupom <strong>ULTIMA30</strong> no checkout.</p>
<p><a href="{{upgrade_url}}" style="display:inline-block;padding:14px 28px;background:#ffb86b;color:#08111c;border-radius:8px;text-decoration:none;font-weight:bold;">Assinar com 30% off</a></p>
<p><em>Essa condicao expira em 72 horas.</em></p>
</div>',
 'converted_at IS NULL'),

-- Step 5: D+14 Final goodbye + feedback
(5, 336, 'email',
 '{{primeiro_nome}}, um ultimo pedido antes de ir',
 '<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:24px;">
<p>Oi, {{primeiro_nome}}!</p>
<p>Entendi que talvez o FALAI nao seja para voce neste momento &mdash; e tudo bem.</p>
<p>Mas antes de parar de escrever, um pedido rapido: <strong>poderia me dizer o que faltou?</strong></p>
<p>Sua resposta me ajuda a melhorar o produto. Basta responder este e-mail com uma frase.</p>
<p>Se mudar de ideia no futuro, seu acesso pode ser reativado a qualquer momento: <a href="{{upgrade_url}}">falai.app/pricing</a></p>
<p>Obrigado por testar o FALAI.</p>
<p>&mdash; Equipe FALAI</p>
</div>',
 'converted_at IS NULL')

) AS v(step_order, delay_hours, channel, subject, body_template, condition_sql)
ON CONFLICT DO NOTHING;


-- -----------------------------------------------
-- 5. CADENCE STEPS: Post-Conversion (subscription_activated)
-- -----------------------------------------------
WITH cad AS (
  SELECT id FROM public.email_cadences
  WHERE trigger_event = 'subscription_activated' AND is_active = true
  LIMIT 1
)
INSERT INTO public.cadence_steps (cadence_id, step_order, delay_hours, channel, subject, body_template, condition_sql)
SELECT cad.id, v.step_order, v.delay_hours, v.channel, v.subject, v.body_template, v.condition_sql
FROM cad, (VALUES

-- Step 1: D0 Thank you
(1, 0, 'email',
 '{{primeiro_nome}}, bem-vindo ao FALAI! Seu plano esta ativo',
 '<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:24px;">
<p>Oi, {{primeiro_nome}}!</p>
<p>Obrigado por assinar o FALAI! Seu plano ja esta ativo e voce tem acesso completo a partir de agora.</p>
<h3>O que mudou:</h3>
<ul>
<li>Mais minutos de transcricao por dia</li>
<li>Suporte prioritario</li>
<li>Correcao premium com estilos avancados</li>
<li>Sem limite de dias &mdash; use o quanto precisar</li>
</ul>
<p><a href="{{dashboard_url}}" style="display:inline-block;padding:12px 24px;background:#ffb86b;color:#08111c;border-radius:8px;text-decoration:none;font-weight:bold;">Acessar meu painel</a></p>
<p>Qualquer necessidade: <a href="{{support_whatsapp}}">WhatsApp de suporte</a></p>
</div>',
 NULL),

-- Step 2: D3 Pro tips
(2, 72, 'email',
 '{{primeiro_nome}}, 3 dicas para aproveitar ao maximo o FALAI',
 '<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:24px;">
<p>Oi, {{primeiro_nome}}!</p>
<p>Agora que voce e assinante, aqui vao 3 dicas que os power users do FALAI adoram:</p>
<p><strong>1. Mude o estilo de correcao por contexto</strong><br>Use "Formal" para e-mails profissionais, "Casual" para WhatsApp e "Neutro" para documentos tecnicos.</p>
<p><strong>2. Configure para iniciar com o Windows</strong><br>Nas configuracoes, ative "Iniciar com o sistema" para nunca esquecer de abrir.</p>
<p><strong>3. Experimente ditar paragrafos inteiros</strong><br>O FALAI funciona melhor com frases completas. Fale naturalmente por 30-60 segundos e veja a magica.</p>
<p><a href="{{access_link}}" style="display:inline-block;padding:12px 24px;background:#ffb86b;color:#08111c;border-radius:8px;text-decoration:none;font-weight:bold;">Abrir o FALAI</a></p>
</div>',
 NULL),

-- Step 3: D7 Feedback + NPS
(3, 168, 'email',
 '{{primeiro_nome}}, como esta sua experiencia com o FALAI?',
 '<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:24px;">
<p>Oi, {{primeiro_nome}}!</p>
<p>Ja faz uma semana desde que voce assinou. Como esta a experiencia?</p>
<p><strong>Novo recurso:</strong> Voce pode ver seu historico de transcricoes e estatisticas no painel web: <a href="{{dashboard_url}}">falai.app/dashboard</a></p>
<p><strong>Ajude-nos a melhorar:</strong> Responda este e-mail com uma nota de 1 a 5 sobre sua experiencia ate agora. Cada feedback conta!</p>
<p>Obrigado por fazer parte do FALAI.</p>
</div>',
 NULL)

) AS v(step_order, delay_hours, channel, subject, body_template, condition_sql)
ON CONFLICT DO NOTHING;


-- -----------------------------------------------
-- 6. CADENCE STEPS: Dormant Paid User (dormant_paid)
-- -----------------------------------------------
WITH cad AS (
  SELECT id FROM public.email_cadences
  WHERE trigger_event = 'dormant_paid' AND is_active = true
  LIMIT 1
)
INSERT INTO public.cadence_steps (cadence_id, step_order, delay_hours, channel, subject, body_template, condition_sql)
SELECT cad.id, v.step_order, v.delay_hours, v.channel, v.subject, v.body_template, v.condition_sql
FROM cad, (VALUES

-- Step 1: We miss you
(1, 0, 'email',
 '{{primeiro_nome}}, o FALAI sente sua falta!',
 '<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:24px;">
<p>Oi, {{primeiro_nome}}!</p>
<p>Percebi que faz um tempo que voce nao usa o FALAI. Tudo bem por ai?</p>
<p>Lembre-se: <strong>cada minuto digitando e tempo que voce poderia estar falando</strong>. O FALAI esta pronto &mdash; basta abrir o app e pressionar Ctrl+Shift.</p>
<p>Seu plano esta ativo e todo o seu acesso continua funcionando normalmente.</p>
<p><a href="{{access_link}}" style="display:inline-block;padding:12px 24px;background:#ffb86b;color:#08111c;border-radius:8px;text-decoration:none;font-weight:bold;">Voltar a usar o FALAI</a></p>
</div>',
 NULL),

-- Step 2: New features (72h later)
(2, 72, 'email',
 '{{primeiro_nome}}, novidades no FALAI que voce pode ter perdido',
 '<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:24px;">
<p>Oi, {{primeiro_nome}}!</p>
<p>Enquanto voce esteve fora, fizemos melhorias no FALAI:</p>
<ul>
<li><strong>Transcricao mais rapida</strong> &mdash; reduzimos a latencia em 40%</li>
<li><strong>Correcao mais precisa</strong> &mdash; menos erros, texto mais natural</li>
<li><strong>Painel de uso</strong> &mdash; acompanhe suas estatisticas de transcricao</li>
</ul>
<p>Vale a pena dar uma olhada!</p>
<p><a href="{{access_link}}" style="display:inline-block;padding:12px 24px;background:#ffb86b;color:#08111c;border-radius:8px;text-decoration:none;font-weight:bold;">Experimentar as novidades</a></p>
</div>',
 NULL),

-- Step 3: Need help? (120h = 5 days later)
(3, 120, 'email',
 '{{primeiro_nome}}, precisa de ajuda com o FALAI?',
 '<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:24px;">
<p>Oi, {{primeiro_nome}}!</p>
<p>Percebi que faz um bom tempo que voce nao usa o FALAI. Se algo nao esta funcionando bem ou se o app nao esta atendendo suas expectativas, eu gostaria de saber.</p>
<p><strong>Posso ajudar com:</strong></p>
<ul>
<li>Problemas tecnicos de instalacao ou microfone</li>
<li>Duvidas sobre como usar em cenarios especificos</li>
<li>Sugestoes de melhoria no produto</li>
<li>Duvidas sobre seu plano ou cobranca</li>
</ul>
<p>Basta responder este e-mail ou <a href="{{support_whatsapp}}" style="color:#ffb86b;font-weight:bold;">chamar no WhatsApp</a>.</p>
<p>Estamos aqui para garantir que o FALAI valha cada centavo do seu investimento.</p>
</div>',
 NULL)

) AS v(step_order, delay_hours, channel, subject, body_template, condition_sql)
ON CONFLICT DO NOTHING;


-- -----------------------------------------------
-- 7. Auto-enrollment trigger on lead_events
-- -----------------------------------------------
CREATE OR REPLACE FUNCTION public.auto_enroll_on_lead_event()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public'
AS $$
DECLARE
  v_cadence_id uuid;
  v_first_step_delay int;
BEGIN
  -- Only handle specific events
  IF NEW.event_name NOT IN ('subscription_activated') THEN
    RETURN NEW;
  END IF;

  -- Find matching active cadence
  SELECT id INTO v_cadence_id
  FROM public.email_cadences
  WHERE trigger_event = NEW.event_name AND is_active = true
  LIMIT 1;

  IF v_cadence_id IS NULL THEN
    RETURN NEW;
  END IF;

  -- Cancel all conflicting cadences on conversion
  IF NEW.event_name = 'subscription_activated' THEN
    UPDATE public.cadence_enrollments
    SET status = 'cancelled',
        cancel_reason = 'converted',
        cancelled_at = timezone('utc', now()),
        updated_at = timezone('utc', now())
    WHERE lead_id = NEW.lead_id
      AND status = 'active';
  END IF;

  -- Get first step delay
  SELECT delay_hours INTO v_first_step_delay
  FROM public.cadence_steps
  WHERE cadence_id = v_cadence_id
    AND step_order = 1
    AND is_active = true
  LIMIT 1;

  -- Enroll lead
  INSERT INTO public.cadence_enrollments (
    cadence_id, lead_id, status, current_step, next_step_at
  ) VALUES (
    v_cadence_id,
    NEW.lead_id,
    'active',
    0,
    timezone('utc', now()) + (coalesce(v_first_step_delay, 0) || ' hours')::interval
  )
  ON CONFLICT DO NOTHING;

  RETURN NEW;
END;
$$;

-- Create trigger (drop first to be idempotent)
DROP TRIGGER IF EXISTS trg_auto_enroll_on_lead_event ON public.lead_events;

CREATE TRIGGER trg_auto_enroll_on_lead_event
AFTER INSERT ON public.lead_events
FOR EACH ROW
WHEN (NEW.event_name IN ('subscription_activated'))
EXECUTE FUNCTION public.auto_enroll_on_lead_event();
