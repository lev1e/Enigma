# Research: chat UI with a side preview panel (S11A)

Method: written from working knowledge of the products and projects; no live page fetch in this session (context budget), so behaviours and licences below are NOT re-verified against current releases. Reference code was never copied; only structure and behaviour were used.

| Product | Layout | Panel open / close | Tabs | Responsive | Keyboard | Adopt / reject for Anonymizer |
|---|---|---|---|---|---|---|
| Claude.ai Artifacts | Chat column left, artifact panel right (split) | Opens when an artifact is produced or its card is clicked; close button | Preview / Code; version switcher | Narrow: panel replaces chat as full view with back | Esc closes in overlay | Adopt: split view, click a file card to open, version switcher, "new version" jump. Reject: running code in an iframe (we never execute file content) |
| ChatGPT Canvas | Chat narrows, document pane right | Opens on request or on long text/code | Doc view, version arrows, inline edit toolbar | Full-screen on phone | Standard | Adopt: panel follows the latest AI edit. Reject: inline edit in panel (edits stay as new file versions) |
| DeepSeek chat | Single column, file chips above composer, optional artifact-like preview | Opens per message | Preview / Code on HTML | Sheet on mobile | Standard | Adopt: attached files as labels, composer at bottom. Reject: HTML live preview (security) |
| Open WebUI | Chat plus "Artifacts" pane right, file preview modal | Pane toggles per message; modal for files | Preview / source; PDF viewer | Overlay on small screens | Esc closes modal | Adopt: pane toggle in header, text/table/pdf viewers by type. Reject: remote CDNs, sandboxed iframes with scripts |
| LibreChat | Chat with side panel for Artifacts and file lists | Toggle button; panel remembers state | Preview / code / versions | Collapses under 768 px | Esc | Adopt: remembered open state, versions as list. Reject: code artifacts |
| LobeChat | Chat with right "portal" for Artifacts and files | Opens by click on artifact, close button | Preview / code | Drawer on mobile | Esc | Adopt: portal as a replaceable column, drawer on narrow. Reject: plugins and sandboxes |

Licences and sources (from memory, verify before relying): Open WebUI (https://github.com/open-webui/open-webui, BSD-3-Clause-based custom licence with branding clause), LibreChat (https://github.com/danny-avila/LibreChat, MIT), LobeChat (https://github.com/lobehub/lobe-chat, Apache-2.0 / LobeHub licence), assistant-ui (https://github.com/assistant-ui/assistant-ui, MIT), Chatbot UI (https://github.com/mckaywrigley/chatbot-ui, MIT). Claude.ai, ChatGPT and DeepSeek are closed products: only observable behaviour was used.

Decisions for this product (offline, privacy-first): content is rendered as data via textContent, never as markup; HTML/SVG shown as source; default tab is the anonymized version (what the AI sees); original is a separate tab marked "local only"; placeholders get chips; size limits fail closed; panel state kept in app prefs, not localStorage.
