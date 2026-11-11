---
name: connection-and-security
description: Diagnose and secure the ChatGPT-to-Windows MCP connection over ngrok.
---

# Connection And Security

The MCP endpoint is `/mcp` behind an authenticated HTTPS tunnel. Verify the target laptop using `who_am_i` and inspect server health without treating an HTTP 200 alone as authorization. Use bearer credentials stored only in the local environment and ChatGPT connection settings; never include them in code, logs, URLs, or archives. Rotate a credential if it was posted in chat. Bind the local server to `127.0.0.1`, use a trusted tunnel, and never expose an unauthenticated command endpoint. Ask before changing firewall rules or tunnel identity.
