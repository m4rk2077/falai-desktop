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

## Instalar (Windows 10/11)

1. Baixe o **`FALAI-Setup-1.5.6.exe`** em [Releases](https://github.com/m4rk2077/falai-desktop/releases/latest) e instale (não precisa de admin).
2. Crie uma chave **grátis** em [console.groq.com/keys](https://console.groq.com/keys).
3. Abra o FALAI, cole a chave no primeiro passo (ou em **Configurações → Transcrição**).
4. Segure `Ctrl+Shift`, fale, solte.

> O instalador ainda não é assinado digitalmente: o Windows SmartScreen pode avisar. Clique em **Mais informações → Executar assim mesmo**, ou compile você mesmo (abaixo).

O custo é o do seu uso no Groq — em uso pessoal intenso, centavos de dólar por mês.

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
