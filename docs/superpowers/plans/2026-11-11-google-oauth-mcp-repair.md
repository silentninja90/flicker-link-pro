# Flicker Link Pro Google OAuth & MCP Relay Repair — Implementation Plan

> For agentic workers: use superpowers:executing-plans with TDD and verification.

**Goal:** Ship Google-authenticated laptop pairing and OAuth-protected MCP discovery/execution for the 66-tool Windows agent.

**Architecture:** Google verifies user identity through OIDC. A FastAPI Render relay issues separate OAuth 2.1-style tokens, validates PKCE and resource audience, and routes tool calls to a separately paired Windows WebSocket agent. The original Render deployment stays live until isolated tests pass.

**Tech stack:** FastAPI, python-jose, google-auth, HTTPX, WebSockets, Render, Python desktop agent.

**Spec:** Existing project and user-approved Google-only initial release; later GitHub/email-password sign-in; final brand Flicker Link Pro.

## Global Constraints
- Never expose Google Client Secret, device tokens, or access tokens in source, logs, or chat.
- Do not disable authentication to make MCP discovery work.
- Keep the GitHub main branch, Render deployment, and existing installed desktop agent unchanged until coordinated release.
- MCP catalog must include exactly 66 unique existing names.
- Only Google-authenticated account subjects may pair devices or consent to ChatGPT access.
- Tool execution requires audience- and scope-bound access tokens.
- Device pairing must be revocable before production release.
- First Google login and device pairing happen once. Later launches/reboots automatically load the pairing from Windows Credential Manager.
- Local logout and uninstall must erase the pairing. Deleting a shortcut alone cannot erase Windows credentials.
- Device credentials are high-entropy, opaque, revocable, and remain paired until user logout/revocation; there is no 30-day expiry. The server stores only a keyed digest, and the Windows app stores its key in Credential Manager.
- This long-lived key avoids repeated login but would be reusable if stolen until revoked; users must be able to revoke it through the authenticated dashboard.
- Selected path: Render Free + Neon PostgreSQL using DATABASE_URL; Neon connection and end-to-end live tests still need to be completed. SQLite remains an optional fallback but requires a persistent disk and must never use Render Free's ephemeral filesystem.

## Review Focus
- An attacker reuses an authorization code after a Render restart.
- A leaked device credential cannot be revoked without rotating all credentials.
- A malicious OAuth client registers a misleading redirect URI.
- An MCP request with wrong audience or invalid scope is rejected.
- A browser auth request includes an invalid state, nonce, or CSRF token.

### Task 1: Google identity and authenticated pairing
**Files:** cloud-relay/main.py; cloud-relay/requirements.txt; cloud-relay/test_relay.py.
- [ ] Write failing test for Google callback state/nonce failures, pairing CSRF, and identity subject.
- [ ] Run test and confirm expected failure.
- [ ] Implement session and device pairing.
- [ ] Run tests and confirm pass.
- [ ] Review token lifetime, revocation, and account sign-out.

### Task 2: MCP OAuth, PKCE, and tool catalog
**Files:** cloud-relay/main.py; cloud-relay/tool_catalog.json; cloud-relay/test_relay.py.
- [ ] Write failing tests for OAuth discovery, DCR, PKCE, replay, audience, and exactly 66 tools while offline.
- [ ] Run test and confirm expected failure.
- [ ] Implement minimum valid OAuth endpoints.
- [ ] Run tests and confirm pass.
- [ ] Check against current MCP authorization specification.

### Task 3: Desktop agent and reconnect
**Files:** desktop-agent/flicker_relay_agent.py and installed agent only at release time.
- [ ] Write test for header-based WebSocket auth and tool dispatch.
- [ ] Run test and confirm expected failure.
- [ ] Implement header-based token exchange.
- [ ] Run tests and confirm pass.
- [ ] Back up installed agent and coordinate restart/re-pair after server deploy.

### Task 4: Release and plugin
**Files:** chatgpt-plugin/mcp.json and owned plugin package; Render deployment.
- [ ] Peer security review and address important findings.
- [ ] Full local runtime tests and one authenticated end-to-end tool call on a test device.
- [ ] Confirm Render secrets exist without reading or logging them.
- [ ] Obtain explicit authorization before updating shared GitHub main / Render production.
- [ ] Deploy, verify OAuth endpoints and 66-tool discovery, then update plugin manifest.
- [ ] Pair laptop using Google and verify an authorized low-risk command.
