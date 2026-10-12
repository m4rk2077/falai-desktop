# FALAI

Ditado por voz para Windows: segure a hotkey, fale, solte — o texto aparece no campo ativo, já pontuado e revisado.

## Como funciona

```
Microfone ─► corte de silêncio ─► Whisper (Groq) ─► regras do usuário ─► revisor LLM ─► cola no app ativo
                                     ▲                                          ▲
                              vocabulário pessoal              vocabulário + ditados recentes (referência)
```

- **Modo local (BYOK):** usa a sua chave Groq direto do desktop. Sem conta, sem servidor.
- **Modo nuvem (opcional):** o desktop fala com as Edge Functions em `supabase/functions/` (transcrição, cobrança Stripe, planos). As chaves de provedores ficam no servidor.

## Instalar (Windows 10/11) — 5 minutos

### 1. Baixe e instale

Baixe o **`FALAI-Setup-1.5.7.exe`** em [Releases](https://github.com/m4rk2077/falai-desktop/releases/latest) e execute. Instala só para o seu usuário (não pede admin).

> O instalador ainda não é assinado digitalmente, então o Windows SmartScreen pode mostrar "O Windows protegeu o computador". Clique em **Mais informações → Executar assim mesmo**. Se preferir, confira o SHA-256 publicado na release ou compile você mesmo (veja *Rodando do código*).

### 2. Crie sua chave Groq (o FALAI usa o Groq para transcrever)

1. Acesse [console.groq.com](https://console.groq.com) e crie sua conta (ou entre, se já tiver).
2. No menu, abra **API Keys** — ou vá direto em [console.groq.com/keys](https://console.groq.com/keys).
3. Clique em **Create API Key**, dê um nome (ex.: `FALAI`) e confirme.
4. **Copie a chave na hora** (começa com `gsk_`). Se perder, é só apagar e criar outra.

### 3. Cole a chave no FALAI

Ao abrir o FALAI pela primeira vez, ele pede a chave: cole e clique em **Continuar**. Para trocar depois: **Configurações → Transcrição → Chave Groq**.

A chave fica **criptografada no seu PC** (Windows DPAPI). Ela não vai para nenhum servidor do FALAI — só para o Groq, para autenticar suas transcrições.

### 4. Use

Clique no campo onde quer escrever, **segure `Ctrl+Shift`, fale e solte**. Em ~1 segundo o texto aparece, já pontuado.

### Quanto custa

O FALAI é gratuito. O uso do Groq é cobrado na sua conta Groq conforme os [preços por modelo](https://console.groq.com/docs/models): a transcrição custa cerca de **US$ 0,04 por hora de áudio** e a revisão de texto, frações de centavo por ditado. Em uso pessoal intenso (~400 ditados/mês) isso dá **menos de US$ 0,50 por mês**. Veja os limites e o plano da sua conta em [console.groq.com/settings/limits](https://console.groq.com/settings/limits).

## Problemas comuns

| A barra mostra | O que fazer |
|---|---|
| **Chave Groq: veja Configurações** | Ainda não há chave. Cole em Configurações → Transcrição. |
| **Chave Groq inválida** | A chave foi apagada, digitada errada ou expirou. Crie outra em console.groq.com/keys e salve de novo. |
| **Limite do Groq: aguarde 1 min** | Você atingiu o limite de pedidos por minuto/dia do seu plano Groq. Espere um pouco ou veja seus limites no console. |
| **Sem conexão com o Groq** | Sem internet ou o Groq está fora. Tente de novo em instantes. |
| **Nenhuma fala detectada** | O microfone não captou áudio. Confira o microfone padrão do Windows. |
| Erra nomes (marcas, pessoas, siglas) | Adicione em Configurações → Transcrição → **Vocabulário pessoal**. Para erros que se repetem sempre igual, crie uma regra em `%APPDATA%\FALAI\replacements.txt` (ex.: `super base => Supabase`). |
| `Ctrl+Shift` conflita com outro app | Troque em Configurações → Atalho. |

## Privacidade

- **O áudio do ditado é enviado ao Groq** para transcrição, e o texto, para revisão (pontuação e termos). Veja a [política de privacidade do Groq](https://groq.com/privacy-policy).
- O histórico de ditados fica **só no seu PC**, criptografado (`%APPDATA%\FALAI\`).
- O FALAI não tem servidor próprio no modo local. A única outra conexão é a checagem de atualização no GitHub (para desligar: `"updates_enabled": false` em `%APPDATA%\FALAI\config.json`).

## Rodando do código (modo local)

```bash
python -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env   # preencha GROQ_API_KEY
python main.py
```

Hotkey padrão: `Ctrl+Shift` (push-to-talk). Configurações ficam em `%APPDATA%\FALAI\`.

## Precisão

- **Vocabulário pessoal** (Configurações → Transcrição): nomes, marcas e termos que você fala. Vai para o Whisper e para o revisor.
- **`%APPDATA%\FALAI\replacements.txt`**: regras fixas `errado => certo` (ou `re: <regex> => certo`), aplicadas sem LLM.
- **Contexto no revisor**: os ditados dos últimos 15 min vão ao revisor como referência (`dictation_context`). Não vão ao Whisper: nos testes ele passou a copiar o texto anterior.
- **Diagnóstico** (opcional): `save_debug_audio: true` guarda os últimos 50 áudios + textos em `%APPDATA%\FALAI\debug_audio\` para medir acurácia na sua voz. Nada sai do seu PC.
- `python scripts/mine_dictation_history.py` sugere regras e termos a partir do seu histórico local.

## Estrutura

| Pasta | O quê |
|---|---|
| `main.py`, `src/ui/` | App desktop (PySide6): tray, barra flutuante, janelas |
| `src/audio/` | Captura, corte de silêncio, transcrição |
| `src/utils/` | Revisor LLM, memória de ditado, hotkeys, clipboard, histórico |
| `src/security/` | Armazenamento local criptografado (DPAPI) |
| `src/backend/` | Cliente do modo nuvem opcional (sessão, outbox offline) |
| `supabase/functions/` | Edge Functions (Deno) |
| `database/`, `supabase/migrations/` | Schema e RLS do Postgres |

## Testes

```bash
python -m pytest -q tests
```

## Licença

[AGPL-3.0](LICENSE). Use, modifique e redistribua à vontade; se oferecer o FALAI (ou derivado) como serviço em rede, publique o código-fonte das suas modificações.
