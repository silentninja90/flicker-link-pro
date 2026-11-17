# Stripe setup for Flicker Link Pro

Use Stripe test mode on the staging relay with its own Neon database and USD
price. A Stripe live key is rejected on the known staging hostname.
The production relay leaves billing disabled with a sandbox key. Use the
production service and a live price, key, and webhook only for the live rollout.
The test relay webhook URL is
`https://flicker-link-pro-2-staging.onrender.com/billing/webhook`.

1. Create one recurring Price for **US$5 per month** in Stripe. Use a flat
   per-unit price with no trial. Enable the Stripe customer portal with payment
   method updates and cancellation. Enable Stripe's setting to limit customers
   to one subscription and keep plan switching off for this single-plan setup.
2. Create a Stripe webhook using snapshot events at the relay's HTTPS URL
   followed by `/billing/webhook`. Subscribe to
   `checkout.session.completed`, `customer.subscription.created`,
   `customer.subscription.updated`, `customer.subscription.deleted`,
   `customer.subscription.paused`, `customer.subscription.resumed`,
   `invoice.paid`, and `invoice.payment_failed`.
3. Verify that Render's test relay uses the Neon branch `staging-oauth-20261111`.
   Save `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PRICE_ID`, and
   `FLICKER_FREE_CALL_ALLOWANCE=15000` together in that service's environment.
   Keep all Stripe values in test mode. Test billing can be validated with
   `FLICKER_PURGE_REVOKED_DEVICES` unset.
4. Sign in to the website, connect a staging computer, and open its account
   page and select Continue to Stripe. On Stripe Checkout, confirm the US$5
   monthly charge and cancellation notice appears by Subscribe. First close
   Checkout without subscribing and confirm no payment or unlimited access.
   Then reopen Checkout and subscribe using a Stripe test card.
   Confirm activation after a signed event and that only the paying account
   receives unlimited calls. Exercise cancellation, expiry, and failed
   renewal. With cancellation at period end, a paid subscription stays active
   through the period. A subscription that is no longer active loses
   unlimited access and falls back to the account's current free allowance.
5. Publish accurate support, privacy, and subscription terms before enabling
   live billing. The relay stores a Stripe customer reference and paid-through
   timestamp in Neon. Stripe hosts the card and billing management screens.

The Checkout success page only shows payment confirmation is pending. It
cannot change entitlements. Verified Stripe events trigger a fresh read of
the current subscription so retries and events arriving out of order use the
same current state.
