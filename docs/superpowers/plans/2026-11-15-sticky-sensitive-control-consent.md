# Sticky Sensitive-Control Consent Implementation Plan

> **For agentic workers:** Use the native execution workflow after the user reviews this plan. Steps use checkbox syntax for tracking.

**Goal:** Enforce one paired Windows computer per account and add a first-use local approval gate whose decision persists for that device pairing.

**Architecture:** The Render relay and both pairing registries will enforce a single active pairing per account without silently revoking existing records. The Windows relay agent will check a shared sensitive-tool classification before dispatch, show a local warning on the first sensitive call, and store allow/deny in Windows Credential Manager bound to the server and pairing fingerprint.

**Tech Stack:** Python 3.12, FastAPI, SQLite and PostgreSQL registries, Windows Credential Manager, Windows local dialog, WebSockets.

**Spec:** `docs/superpowers/specs/2026-11-15-sticky-sensitive-control-consent-design.md`

## Global Constraints

- Preserve unrestricted access to files accessible to the signed-in Windows user after approval; add no path allowlist.
- Allow at most one active pairing per Google account; never replace or revoke the existing device automatically.
- Show the warning at the first sensitive tool request; approval or denial is sticky for the pairing.
- Temporary network failures and application restarts do not clear consent.
- Local sign-out, unpair, token replacement, and confirmed server revocation clear consent.
- If the local warning cannot be shown or answered, fail closed and do not execute the action.
- Keep all changes on the staging branch and staging Render/Neon resources; production remains untouched.
- Do not add or run automated tests unless the user asks for them.

## Review Focus

- An account with existing multiple active rows must keep them; no migration may choose or revoke a computer automatically.
- A second concurrent pairing request must not create a second active device.
- A new, changed, or staging credential must not inherit an old approval.
- A transient WebSocket close, timeout, or Render outage must preserve both the pairing and consent.
- A denied or unavailable local prompt must never dispatch the requested tool.

---

### Task 1: Enforce one active pairing per account

**Files:**
- Modify: `cloud-relay/postgres_registry.py`
- Modify: `cloud-relay/device_registry.py`
- Modify: `cloud-relay/main.py`
- Modify: `cloud-relay/NEON_SETUP.md`

**Implementation:**

1. Change the active device limit in both registry implementations to one.
2. Keep PostgreSQL account-scoped advisory locking. Use a SQLite immediate write transaction around count and insert so concurrent pairing requests cannot both pass the one-device check.
3. Return a clear error instructing the owner to revoke the current computer before pairing a replacement.
4. Preserve current rows and the existing revoke flow. Do not add automatic deletion or a data migration.
5. Before staging rollout, use an aggregate-only Neon query to count accounts with multiple active pairings. If any exist, retain them and have the owner explicitly revoke extras before reporting that strict one-device coverage is complete.

**Verification:**
- Review both implementations for matching limit and transaction behavior.
- Review the pair route to confirm no token is issued when an active pairing exists.
- Check `git diff --check`.

### Task 2: Add pairing-bound consent storage and the local warning

**Files:**
- Modify: `desktop-agent/credential_store.py`
- Create: `desktop-agent/sensitive_controls.py`

**Interfaces:**
- `sensitive_controls.is_sensitive_tool(name: str) -> bool`
- `sensitive_controls.authorize_sensitive_tool(name: str, server: str, token: str, target: str) -> bool`
- Credential storage adds functions to read, write, and delete `allowed`/`denied` consent under a separate Windows Credential Manager target.

**Implementation:**

1. Classify as sensitive tools that access user files, execute commands, control processes or Docker, run SQL, transfer data over HTTPS, capture the screen, or send desktop input. Keep only identity, pairing status, basic configuration, and system-health reads ungated. Make unclassified tools sensitive by default.
2. Bind stored consent to the normalized relay URL and a SHA-256 fingerprint of the current device token; never store the raw token in the consent record.
3. Display one local Windows warning with a safe default of Deny. State that approval enables the full sensitive tool set for this pairing, including unrestricted file access, until sign-out or unpair.
4. Persist `allowed` on approval and `denied` on denial. A denial blocks sensitive calls without repeating the warning; a new pairing resets the decision.
5. If no interactive desktop or a usable prompt is unavailable, deny the current call without persisting a decision.

**Verification:**
- Review classification against all names in `desktop-agent/tool_catalog.json`; new names must be gated by default.
- Review stored consent payloads to ensure they include no raw pairing token.
- Check `git diff --check`.

### Task 3: Gate relayed calls and clear consent with pairing lifecycle

**Files:**
- Modify: `desktop-agent/flicker_relay_agent.py`
- Modify: `cloud-relay/main.py`
- Modify: `desktop-agent/STAGING_ONLY.md`

**Implementation:**

1. Before calling the local tool dispatcher for a sensitive `tools/call`, obtain the local decision. Execute only when it is `allowed`; return a clear tool error for `denied` or unavailable prompts.
2. Run the prompt in the existing worker-thread path so the WebSocket event loop remains responsive. Ensure a timed-out or dismissed prompt does not execute later after the cloud call has expired.
3. When a new server/token pair differs from the saved pair, remove the consent record before saving the new credential.
4. On local logout/uninstall, clear consent only after remote revoke succeeds or returns already-invalid. If the network fails, retain both pairing and consent.
5. On confirmed remote revocation (invalid WebSocket authentication), clear the local pairing and consent. Preserve them through transient connection loss and service errors.
6. Document that Google website sign-out only ends the website session; local app sign-out or device removal revokes the pairing.
7. Add a read-only pairing-status endpoint so the desktop clears local credentials only after explicit invalidation, not after a service-side handshake failure. Attach an expiry to relayed calls and recheck it immediately before local dispatch; discard calls if revocation closes the connection during the warning.

**Verification:**
- Review each pairing, logout, retry, and WebSocket reconnect branch against the consent lifecycle.
- Confirm `tools/list` and non-sensitive diagnostics do not show the warning.
- Check `git diff --check`.

### Task 4: Final source review

**Files:**
- Review all modified files; do not change production resources.

**Verification:**
- Check Python syntax for changed modules without running automated tests.
- Validate that the current Render staging branch's cloud changes are limited to the one-pairing policy and leave secrets/configuration unchanged.
- Inspect the final diff and report any staging-only deployment or existing-duplicate prerequisite separately.
