# Flicker Link Pro Privacy Policy

*Draft for review*

Eric Williams operates Flicker Link Pro. This policy covers the Flicker Link Pro website, ChatGPT plugin, cloud relay, and Windows app. For privacy questions or requests, email flickerlinkpro@gmail.com.

## What we use and why

| Information | How we use it |
| --- | --- |
| Google account identifier and verified email address | We verify sign-in, associate the account with its paired computer, display the signed-in email address, and pass the email address to Stripe when creating a billing profile. |
| Sign-in cookies | The Google sign-in cookie secures the sign-in exchange and expires after 10 minutes. The website session cookie keeps you signed in for up to 12 hours. Signing out clears the website session cookie. |
| Device and pairing information | We store the device identifier, device name, pairing times, last connection time, revocation time, and a cryptographic digest of the pairing token. We use these records to connect the account to the correct computer, show its connection status, and enforce revocation. The Windows app stores the pairing token in Windows Credential Manager. |
| Tool requests and results | The relay forwards requests to your paired computer and returns results to ChatGPT. Depending on the action, those requests or results can include file contents, paths, screenshots, command output, or system information. The Windows app can also save a tool result locally when you ask it to. |
| Usage and subscription information | We maintain account-level call counts, the start of the usage period, a Stripe customer identifier, and the date through which paid access applies. We use this information to apply usage limits and recognize active memberships. Stripe handles card entry, billing, and payment processing on the Flicker Link Pro website. |
| Connection and service logs | Hosting logs can include IP addresses, request times, routes, status codes, and operational errors. We use them to run, secure, and troubleshoot the service. |
| Support messages | We use the information you send to answer questions, troubleshoot problems, and handle requests about your account or data. |

## Who receives information

- Google provides sign-in.
- Render hosts the website and relay. Neon hosts the database containing device, usage, and billing reference records.
- OpenAI processes tool requests and results when you use Flicker Link Pro in ChatGPT. Your ChatGPT conversation and account data are subject to OpenAI's policies and settings.
- Stripe handles website checkout and billing. Stripe receives the information needed to process your subscription and applies its own privacy practices.
- When you direct a supported tool to send information to an external destination, that destination receives the information needed for the requested action.

## Retention and controls

The relay carries tool requests and results between ChatGPT and the Windows app. The account database stores device records, usage counters, and billing references. A tool result you save on the computer remains under your control there. ChatGPT conversations and Stripe transaction records follow the applicable providers' retention practices.

Revoked device records become eligible for deletion after 30 days. The relay checks when it starts and hourly while running, so cleanup resumes when the service next starts after an outage. The Neon project's point-in-time recovery window is six hours. Render makes dashboard logs available for 7 to 30 days, depending on the workspace plan.

Usage counters are kept while your account is active to apply the free allowance and paid access. After account closure, they are removed when no longer needed for security, billing disputes, or legal obligations. Billing records are retained as needed for tax, accounting, security, and dispute obligations. Support messages are kept for 90 days after the issue is resolved, unless needed longer to handle a dispute or legal obligation.

You can temporarily disconnect the computer by stopping the Windows app. To revoke the pairing, use **Flicker Link Pro - Sign Out** on that computer or revoke the computer from **Paired Computers** on the website. Revocation blocks further access through that pairing. You can manage or cancel a paid membership from **Manage billing** on the website.

To request access to, correction of, or deletion of your information, contact flickerlinkpro@gmail.com. We may ask for information needed to verify the request. Your rights depend on the laws that apply where you live. Records needed for billing, security, or legal obligations may remain after an account or pairing is no longer active.
