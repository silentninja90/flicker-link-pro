# Flicker Link Pro 2 — Render Free + Neon PostgreSQL

This is the selected development architecture. Render hosts the FastAPI relay.
Neon provides a durable, external PostgreSQL registry for laptop device credentials.
Google OAuth verifies account ownership. ChatGPT OAuth and Windows agent credentials
remain separate.

## Connect Neon without sharing passwords in ChatGPT

1. Connect the Neon integration in ChatGPT, or sign in at https://console.neon.tech.
2. Create a Neon Free project named Flicker Link Pro 2 (no paid upgrade).
   Prefer a database region close to the Render service's Oregon region.
3. Use the project's PRIMARY branch and its pooled Postgres connection string.
   The value starts with postgresql:// and includes a database password.
4. In Render service srv-dbpun2d6e07s73bj18tg > Environment, add:
   DATABASE_URL = the pooled Neon Postgres connection string.
   Paste it DIRECTLY in Render with the value hidden; do not paste it in chat,
   add it to Git, send screenshots of it, or put it in URLs.
5. Preserve these existing Render keys and their private values:
   GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, FLICKER_SECRET, BASE_URL.
   Never reset FLICKER_SECRET casually: it authenticates existing devices.
6. Render Free needs NO persistent disk when DATABASE_URL is configured.
   If DATABASE_URL is missing, the current new relay fails closed with HTTP 503
   instead of pretending to save data on Render's ephemeral filesystem.

## Implementation

cloud-relay/postgres_registry.py uses psycopg2, transactional SQL,
parameter binding, owner-scoped revocation, HMAC-SHA256 credential digests,
and a 10-active-device limit per Google subject. It forces TLS verify-full
with the certifi CA bundle even if the URI requested weaker sslmode.

cloud-relay/main.py chooses PostgreSQL whenever DATABASE_URL exists; the
original SQLite implementation remains available for local tests or a
future paid Render disk. The database schema is created on first use.

Google OAuth and MCP retain the same cloud URL:
https://flicker-link-pro.onrender.com

## Test and deployment gates

Local tests use SQLite as a SQL-compatible fake for PostgreSQL. This validates
the adapter methods but is NOT a real Neon connectivity or PostgreSQL server
integration test. The actual Neon database must be created and connected
before deployment. Once connected, test schema initialization, token persistence
across Render restart, revocation across app restart, Google sign-in,
the Windows credential vault, and ChatGPT's 66 MCP tools.

Do not push/merge to GitHub main, change the deployed Render service,
or update the installed desktop agent/plugin until the staging tests
and security review have been completed. The current branch is a WIP.

## Operational concerns

- Neon Free is capacity-limited and can sleep when idle. Expect cold starts.
- Choose a pooled connection string for Render's request-driven FastAPI app.
- Backups and plan limits must be monitored; Free does not guarantee
  uninterrupted availability.
- Device secrets are stored only in Windows Credential Manager locally and
  HMAC digests in Neon. Logout first revokes the server credential.
- Deleting a Windows shortcut does not erase application credentials.
  A real uninstaller must perform the supported --uninstall/logout operation.
