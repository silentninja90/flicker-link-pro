---
name: connection-and-security
description: Pair and secure the Windows computer connection to the Flicker Link Pro cloud relay.
---

# Connection and Security

Flicker Link Pro uses an authenticated HTTPS relay at `https://flicker-link-pro.onrender.com/mcp`; the Windows app maintains the connection to that relay. Sign in to the website, pair one computer to the account, then start the Windows app and use `who_am_i` to confirm the returned computer name. A successful website response alone does not prove that a desktop agent is paired or online.

Pairing credentials stay in Windows Credential Manager. Never paste pairing tokens, access tokens, API keys, database connection strings, or passwords into chat, source code, logs, URLs, or ZIP files. Revoke a pairing from the account's paired-computer page or use the app's sign-out shortcut. The app's first sensitive-action warning authorizes the tool set for that pairing until the app stops or the pairing is revoked; ChatGPT may separately request confirmation for irreversible actions. Use Flicker Link Pro only on computers and data you are authorized to access.
