# W13a: inline AI chat in the file-chat view
- New shared module anonymizer/web/ai-chat.js (AIChat.mount) used by index.html (inline, list in feed, composer in the sticky dock) and by /ai (ai.html). Route /ai-chat.js in webapp.py (auth required, CSP unchanged).
- Backend unchanged: same /api/ai/* endpoints (guard, label-form only, SSE, attachments, export).
- "ИИ-чат" button focuses the inline composer (falls back to /ai link without an open chat).
- #stage-chat made more prominent; it already shows job.stage.
- Tests: tests/test_ws_w13a.py (6). Leak e2e: e2e 88 req, leaks=0; w12b 32 req, leaks=0. No new send path.
- Unverified (no browser): visual layout, dark theme, sticky dock height with both composers, mobile width, SSE feel.
