# Flicker Link Pro Stripe Checkout

## Values to Replace

The Checkout code uses the existing subscription mode and the configured
monthly Price ID. There are no placeholder values in the source files.

| Render environment variable | What to set |
| --- | --- |
| STRIPE_PUBLISHABLE_KEY | Add the publishable key for this Stripe environment. Use the sandbox key on staging and the live key on production. |
| STRIPE_SECRET_KEY | Use the restricted server key for the same Stripe environment as the publishable key. |
| STRIPE_WEBHOOK_SECRET | Use the signing secret from this environment's Stripe webhook destination. |
| STRIPE_PRICE_ID | Use the active US$5 monthly Price ID for this environment. The production Price ID is price_1UciWuL2BFW1VnMqeIFzwOJt. |
| FLICKER_FREE_CALL_ALLOWANCE | Set to 15000 on the existing Neon-backed relay. |

On each Render service, check the service's **Environment** page and the
groups linked there. Service-level variables take precedence. Keep the secret
key and webhook signing secret in Render. The publishable key is the only
configured Stripe API key the page sends to the browser.

## Configured Parameters

The existing Checkout Session call in [stripe_billing.py](cloud-relay/stripe_billing.py)
uses these Checkout Studio settings.

| Parameter | Value |
| --- | --- |
| ui_mode | form |
| billing_address_collection | auto |
| phone_number_collection.enabled | false |
| automatic_tax.enabled | false |
| payment_method_collection | always |
| submit_type | auto |
| saved_payment_method_options.payment_method_save | enabled |
| integration_identifier | custom_embedded_web_0001 |

The call also uses subscription mode, one unit of the configured price, the
account's Stripe Customer, and a return URL for the existing account page.
The [account page](cloud-relay/main.py) contains the configured appearance and
mounts the expanded form using Stripe.js Dahlia.

## Setup and next steps

1. Use the updated [Python dependencies](cloud-relay/requirements.txt). The
   Checkout Session requests use the 2026-03-25.dahlia Stripe API.
2. Configure and deploy to the staging service first. Sign in with a paired
   test account, open Checkout, and verify the US$5 monthly renewal notice.
   Use 4242 4242 4242 4242 with a future expiration and any three-digit CVC
   for a successful sandbox payment. Use 4000 0025 0000 3155 to exercise 3D
   Secure. Use Stripe test cards only in the sandbox.
3. After paying, confirm the account page shows unlimited membership after
   the signed webhook is delivered. Confirm Manage billing opens the portal
   for that customer. Exercise cancellation and confirm access continues
   through the paid period.
4. For production, verify the live webhook destination points to
   https://flicker-link-pro.onrender.com/billing/webhook. Use the existing
   snapshot events for Checkout completion, subscription creation, updates,
   deletion, pausing and resuming, and invoice payment success and failure.
   Check that the service loads the live Stripe settings after deployment.
   Open the form to verify the price and renewal notice before accepting
   customer payments.
5. For future product changes, update the corresponding Stripe price and the
   server-side price validation together. Use Stripe's customer and
   subscription records to track subscriptions. The signed webhook remains
   responsible for refreshing the paid-through date in Neon.

The signed-in account page submits its existing CSRF token to
POST /billing/checkout. The route returns a Checkout Session client secret
to mount the Stripe form, or a portal URL for a subscriber who already
has a membership. Stripe returns the customer to /devices after payment.
The browser return only shows status. The webhook updates access.

This checklist is the only new file. The integration uses the existing
billing module, account page, and routes.

[Stripe embedded form guide](https://docs.stripe.com/checkout/form/quickstart) ·
[Stripe testing](https://docs.stripe.com/testing) ·
[Stripe Support](https://support.stripe.com) ·
[Stripe MCP](https://docs.stripe.com/mcp)
