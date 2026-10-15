# P1 report: providers, model picker, original-data path, policy hook

Owner decision applied: no restrictions on anonymized vs original for any provider. A read-only policy hook exists for later tightening.

## What was done
- Provider layer (`keystore.py`, `chat_api.py`, `llm.py`): user-defined providers (name, kind incl. custom OpenAI-compatible, base URL, optional key, model list, `internal` flag). Public info carries `badge` "внутренняя"/"внешняя". Settings page (`ai.html`) manages many providers (add, edit, delete).
- Model picker (`ai-chat.js`): compact select in the composer footer (the only new always-visible element, hidden if no provider), choice stored per chat (`/api/ai/chats/<id>/choice`), switchable mid-conversation.
- Source choice: in the "+" menu each ticked file has "Версия: Обезличенный/Исходный". Originals path (`chat_pipeline.prepare_originals`, `ai_chat._with_chat_files`): no personal-data guard, no placeholders, reply shown as is; recognised secrets are masked ("[секрет удалён]") and the final request is re-scanned (fail closed). Quiet one-line notice with provider and badge, Enter confirms (confirmation bound to text, provider, model, files). Original-mode messages are marked and never reused in anonymized history. File editing is not done in originals mode.
- Policy (`policy.py`): optional `policy.json` (env `ANONYMIZER_POLICY` or OS location), read on every request, never written. Absent = nothing enforced. Keys: provider tier, `allow_originals_to_external`, `allowed_hosts`. Unreadable file fails safe for originals.
- Guard fix: `guard.secrets_left` ignores our own mask text.
- Docs: SECURITY.md and README AI-chat sections updated.

## Tests
`tests/test_ws_p1.py` (11): provider CRUD/badge/models, per-chat choice, anonymized path unchanged, originals confirm + secret masking + no placeholders, external allowed without policy, history isolation, no text in logs, policy absent/tier/hosts/broken. Existing llm keystore/pipeline/settings/e2e/adapters, s10a, s13a, chat_ux_page: 92 OK.

## UI check (Browser pane, synthetic data, fake provider)
1440 light and 390 dark: picker, source toggle, notice, Enter confirm, orig-marked messages, no horizontal scroll, 44px targets.

## Limits
- Detector does not recognise a bare `sk-proj-...` key without a "password/token:" label; such a key in an original would go out.
- Only a fake provider was tested; no real Tedorra/Qwen/GPT/Claude/Gemini, no real keychain.
- The "internal" flag is a label; the policy file is not protected from a user who can write it.
