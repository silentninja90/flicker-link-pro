# Sticky sensitive-controls consent for Flicker Link Pro

**Status:** Approved for staging implementation
**Date:** 2026-11-15

## Intent

Make Flicker Link Pro usable for one person's own Windows computer through the Render and Neon staging setup. Keep file access unrestricted across the files that Windows already lets the signed-in user access. Ask once, on the first sensitive action, before enabling the broad controls for that device pairing. After approval, do not ask again until the user signs out, removes the pairing, or the server revokes that device. A temporary network outage or agent restart does not clear the approval.

## Current behavior

- Google sign-in identifies the owner; a paired desktop agent stores its device credential in Windows Credential Manager. Neon stores only a keyed digest of the device credential and pairing metadata.
- The Cloud MCP service forwards tool calls to the paired Windows agent. The local dispatcher performs file, command, process, database, network-transfer, Docker, and desktop actions.
- The local dispatcher currently has no persistent per-pairing consent decision. The pairing page shows a device credential and command for the user to enter.
- The registry allows up to ten active pairings per Google account, while the relay routes calls through one live socket per account.
- Staging uses a separate Render service and Neon branch. Production remains out of scope for this change.

## Goals

1. Enforce one active computer pairing per Google account. Pairing another computer is blocked until the owner explicitly removes or revokes the existing one; never silently replace it.
2. On the first sensitive tool call, show one clear local Windows warning before executing it.
3. If approved, allow all listed sensitive tools for that pairing without further confirmation prompts.
4. Persist approval locally, bound to the current server and pairing credential, and clear it on sign-out, unpair, credential replacement, or confirmed server revocation.
5. Preserve the approval across temporary network loss and application restarts.
6. If the local user cannot see or answer the warning, fail closed: do not execute the requested action.
7. Keep the existing Google account ownership, TLS, device revocation, and separate staging/production configurations.

## Non-goals

- No file path restrictions: file operations remain available across all paths accessible to the Windows user after the one-time approval.
- No per-call approvals after the user approves the pairing.
- No automatic revocation of existing pairings during migration.
- No production deployment, public plugin submission, or broad tool-set expansion as part of this consent change.

## Sensitive action boundary

The one-time warning must plainly say that approval enables the paired computer to be controlled through ChatGPT until that pairing is removed. It must call out unrestricted user-accessible file reading and changes, command and WSL execution, process and Docker control, database execution, HTTPS transfers, screenshots, and keyboard/mouse/window interaction.

The local tool dispatcher owns one explicit classification list. Any tool that reads or changes private files, executes a command, affects processes or containers, executes SQL, transfers data, captures the screen, or sends desktop input is gated. Basic identity, pairing status, and system-health diagnostics may remain ungated. New tools default to gated until deliberately classified.

## Consent flow

1. A non-sensitive call works as it does today.
2. Before the first gated tool executes, the Windows agent checks the consent state for the active server and pairing.
3. If undecided, show a native local approval prompt explaining the full access above and that the choice remains in force until sign-out or unpair. The prompt offers **Approve for this pairing** and **Deny**.
4. On approval, persist `allowed` locally, then execute that first requested action once. Future gated calls execute without another prompt.
5. On denial, persist `denied` for the pairing and reject the request. Do not prompt again; the owner can sign out/unpair and pair again to make a new choice.
6. If no interactive local desktop is available, the prompt is dismissed, or the approval wait expires, reject the current call without running it. Do not persist approval. The user may retry when at the computer.
7. A pairing replacement, local app sign-out/uninstall, dashboard revocation, or confirmed invalid/revoked pairing clears consent. Signing out of Google in the browser only ends the website session; it does not unlink the desktop agent or clear its consent. A transient disconnect or reconnect does not.

## Sign-out, revocation, and in-flight calls

- Local app sign-out or uninstall clears the pairing and its consent only after the server confirms revocation (`204`), or reports the credential is already invalid (`401`). If the server cannot be reached, keep both and report that sign-out did not finish.
- A dashboard revocation closes that device's WebSocket. The desktop checks a read-only pairing-status endpoint before clearing local credentials; only an explicit unauthorized response confirms revocation. Temporary transport loss, timeout, or service-unavailable responses preserve consent.
- Once local sign-out or revocation begins, reject new tool calls and discard calls that have not started. An operation already executing may finish or time out; it cannot always be rolled back safely. Do not kill arbitrary processes as a side effect of clearing consent.
- The relay attaches an expiration time to each forwarded call, and the desktop drops expired calls before prompting and again immediately before dispatch. A closed device connection during the prompt also cancels the waiting call.
- Signing out of Google in the browser does not affect a paired computer. The website session and desktop pairing are separate credentials.

## Storage and enforcement

- Store the decision in Windows Credential Manager, separate from the server's database. Bind it to the normalized relay URL and a one-way fingerprint of the current device credential so it cannot carry over to a different pairing.
- Do not store the raw pairing token in the consent record, send consent status to the cloud, or include it in ordinary logs.
- Check consent in the shared local execution path before any gated tool reaches its implementation. Do not rely only on the ChatGPT server or tool descriptions to enforce it.
- Record only the consent decision, timestamp, relay profile, and pairing fingerprint in a local audit event; do not log file contents, commands, SQL, or transfer URLs.
- Clear consent only after a successful local credential deletion or confirmed server revocation. If revocation is unreachable, retain the pairing and report that sign-out did not complete.

## One-computer pairing policy

- Both SQLite and Neon registry implementations enforce one non-revoked pairing per account under a transaction/lock.
- If an account already has an active pairing, `/devices/pair` explains that the current computer must be removed first. The service does not return a second token or revoke the first computer automatically.
- Existing staging rows are preserved. Before enabling the limit on staging, inspect duplicate ownership using a privacy-preserving aggregate; do not revoke any record automatically.

## Alternatives considered

1. **Local first-use gate (chosen):** the paired Windows agent prompts at the actual first sensitive action and persists the answer locally. This keeps approval next to the computer being controlled and makes local execution impossible until approved.
2. **Cloud pairing-page approval:** ask during Google-authenticated pairing and store the approval in Neon. This is simpler for a headless install, but it records only account consent and gives less assurance that the person at the computer saw the warning.
3. **Prompt for every sensitive call:** gives the strongest per-action review but conflicts with the requested one-time approval and makes regular use cumbersome.

## Release and migration constraints

- Implement and validate on the staging branch and staging Render/Neon resources only.
- Keep current staging credentials intact. When enforcing the one-pairing limit, existing users with more than one active pairing must explicitly revoke extras.
- The public-facing package still needs a non-placeholder endpoint, a reviewed first-run installer/pairing experience, and publication details. This design does not make the plugin ready for public release by itself.

## Acceptance criteria

- A second active pairing for one account is refused with a clear revoke-first message; the existing pairing stays active.
- The first gated call cannot execute before a local decision.
- Approval enables later gated calls without additional prompts, including after agent restart and a temporary network interruption.
- Denial blocks gated calls without repeated prompts.
- Sign-out, unpair, token replacement, and confirmed revocation remove the saved consent; a new pairing starts undecided.
- If the local prompt cannot be shown or answered, the tool call is rejected and no action runs.
- Full Windows-user file access remains available after approval, with no root/path allowlist added.
- Staging remains isolated from production.
