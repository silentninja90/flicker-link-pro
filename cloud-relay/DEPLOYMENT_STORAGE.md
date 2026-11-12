# Flicker Link Pro — durable device pairing deployment

The development relay stores revocable Windows device credentials in SQLite.
**Do not deploy this SQLite version on a Render Free web service.**
Render Free has an ephemeral filesystem, which would discard device records
after restarts and spin-downs. The server refuses pairing if the disk is missing.

## SQLite on a paid Render web service

1. Upgrade the web service to a disk-compatible plan (may incur charges).
2. Attach a persistent Render disk mounted at /var/data.
3. Set the following environment variables without exposing secret values:
   - FLICKER_DB_PATH=/var/data/flicker-pairings.sqlite3
   - FLICKER_DISK_MOUNT=/var/data
   - BASE_URL=https://flicker-link-pro.onrender.com
   - FLICKER_SECRET — preserve your existing strong secret
   - GOOGLE_CLIENT_ID — existing Google OAuth client ID
   - GOOGLE_CLIENT_SECRET — rotated Google client secret
4. Use one web service instance; back up and monitor the database.
5. Deploy, verify metadata, Google login, device pairing, revocation and tool catalog.
6. Install the updated desktop agent and credential_store.py, pair once, restart
   and verify automatic reconnection without signing in again.

Rotating FLICKER_SECRET invalidates existing device credentials.

## Alternative: external durable database and free Render web service

Move the device registry to a managed database such as Postgres. This branch
currently implements SQLite only. Do not set FLICKER_DB_PATH to a Postgres URL.
A Free Render Postgres instance expires after 30 days, so it is not durable
enough for the product requirement. Implement and test a Postgres adapter
before deploying if an external provider is chosen.

## Logout, uninstall and privacy

- The Windows agent saves its device credential to Windows Credential Manager.
- The --logout operation calls authenticated /devices/revoke-current first,
  then erases the saved credential. The --uninstall option does the same.
- On network failure logout reports failure and keeps the credential so remote
  revocation can be retried. Users may revoke from the Google-authenticated
  /devices website.
- Deleting a Windows shortcut alone does not uninstall the app or remove
  credentials. A future real installer/uninstaller must call --uninstall.
- Device secrets are long-lived but revocable. Keep them out of screenshots,
  support tickets, command logs, Git and URLs.

## Release gate

This remains a development branch. Do not merge/push to main, update the
private ChatGPT plugin, or deploy over Render production until:
- durable storage is provisioned,
- a release security review is complete,
- browser Google OAuth and WebSocket execution are tested,
- the updated Windows agent is installed and safely re-paired.
