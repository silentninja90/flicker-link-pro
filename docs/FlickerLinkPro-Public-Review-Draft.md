# Flicker Link Pro public review draft

## Listing

- Display name: Flicker Link Pro
- Intended publisher: Eric Williams, individual verification pending
- Subtitle: Connect to your Windows PC
- Description: Pair one Windows computer to your account and use 66 tools for
  computer health, files, desktop actions, commands, processes, Docker,
  databases, backups, and transfers. The paired Windows app asks for full access
  on the first high-risk tool call. Approval lasts until the agent stops or the
  pairing is revoked.
- Product website: https://flicker-link-pro.onrender.com/
- Support: https://flicker-link-pro.onrender.com/support
- Privacy: draft now states 30-day revoked-device cleanup eligibility, active
  account usage-counter retention, billing record retention for tax/accounting/
  security/disputes, and support messages for 90 days after issue resolution.
  Public `/privacy` and `/terms` routes are being prepared in the isolated
  production checkout; verify them after deployment.
- Icon: original `chatgpt-plugin/assets/flicker-link.png`.
- Countries: all available countries.
- Commerce: the standalone Flicker Link Pro website offers a US$5 monthly
  membership. For public review, disclose the existing paid entitlement. Keep
  subscription offers and transactional links out of the plugin and its usage
  limit messages.

The product display name is **Flicker Link Pro**. The public directory displays
the publisher identity verified on the OpenAI Platform. The intended individual
publisher and website operator is **Eric Williams**.

## Proposed reviewer cases

Use a dedicated test account, a dedicated Windows computer, and disposable
sample data. These cases are drafts and must be run on the exact release build.

| Case | Prompt or setup | Expected result |
| --- | --- | --- |
| Positive | Identify my paired Windows computer. | `who_am_i` returns the test computer identity. |
| Positive | Check CPU, memory, and disk use on the test computer. | `system_resources` returns health data. |
| Positive | Check whether `C:\Windows` exists. | `path_info` reports directory metadata without a Windows approval. |
| Positive | Create a text file in the disposable test folder. | On a fresh session, Windows asks once for full access before creating the file. |
| Positive | Show the currently running containers on a test machine with Docker Desktop. | `docker_containers` returns the CLI result or a clear missing-CLI message. |
| Negative | Deny full access on the first request to read a test file. | The sensitive request is blocked. |
| Negative | On a fresh session, decline full access when asked to delete a test file. | No file is deleted. |
| Negative | Stop the agent and request a computer identity. | The connector reports that the computer is offline. |

## Release evidence still needed

- A local submission draft ZIP was assembled at
  `artifacts/FlickerLinkPro-2.2.0-submission-draft.zip`. It includes the
  production MCP configuration, icon, nine skills, and five positive/three
  negative review cases. The public privacy and terms routes are not deployed,
  and the required demo recording URL is absent, so this ZIP is not ready to
  submit.
- Review the release catalog's explicit Boolean annotations for all 66 tools.
  They are now present in the unreleased production branch. Confirm the
  annotations and descriptions against behavior and verify that irreversible
  actions still receive the client-required human confirmation. The schema
  review found that `shutdown` currently terminates a managed process session,
  not Windows; the remaining audit and UI-event tools expose limited local
  metadata rather than cloud-wide records. Decide whether those behaviors meet
  the intended listing before submission. Disclose the Windows agent dependency
  and broad system access to reviewers.
- Complete the exact domain-verification challenge on the Render production
  MCP hostname and verify the stable production URL.
- Verify Eric Williams as the individual publisher on the OpenAI Platform.
- Review the [privacy policy draft](FlickerLinkPro-Privacy-Policy.md) and
  [terms draft](FlickerLinkPro-Terms-of-Service.md). Production was configured
  to clean up revoked devices starting after 30 days. The check runs at startup
  and hourly while the service is running. Neon reports six hours of restore
  history and no snapshots. The operator approved keeping usage counters while
  accounts are active, billing records as needed for tax/accounting/security/
  disputes, and support messages for 90 days after issue resolution. Review
  exports or separate backups against these same choices.
  The live Stripe customer portal is active and defaults to cancellation at
  the end of the billing period. Verify that a signed-in customer can open
  **Manage billing** from the website and confirm any refund policy before
  posting the terms.
  Verify all four listing URLs in a signed-out browser after deployment.
- Record an actual demo with reviewer access and complete the five positive and
  three negative tests in the publication portal.
- The consumer-only Windows installer source is in
  `desktop-agent/installer`. It is locked to the production Render host, signs
  the app, setup, and uninstaller, and checks for a valid Eric Williams
  signature. A trusted signing certificate is not available in this workspace,
  so the production installer has not been built. The existing preview is
  unsigned. After signing, verify install, first sensitive-action approval,
  restart reset, sign-out, and uninstall on a clean Windows computer.
- The package metadata has no reviewer demo recording URL. Record a short
  reviewer-accessible walkthrough only after running the five positive and
  three negative cases on the exact submitted server and Windows build.
- Build and validate the public ZIP, connect the production MCP server, resolve
  the package and tool scans, and have the publisher complete the attestations
  for review.

[OpenAI plugin guidelines](https://developers.openai.com/plugins/plugin-guidelines)
and [submission instructions](https://developers.openai.com/plugins/deploy/submission)
describe the public review requirements.
