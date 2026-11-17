"""Website-only Stripe Checkout, billing portal, and paid access reconciliation."""

from hashlib import sha256

import stripe


EVENT_TYPES = {
    "checkout.session.completed",
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
    "customer.subscription.paused",
    "customer.subscription.resumed",
    "invoice.paid",
    "invoice.payment_failed",
}

RECURRING_BILLING_NOTICE = (
    "By subscribing, you authorize Flicker Link Pro to charge US$5 today and "
    "every month until you cancel. Cancel from Manage billing on your Flicker Link Pro account page."
)


class BillingAccountError(Exception):
    """An account condition safe to show to the signed-in customer."""


class StripeBilling:
    def __init__(self, key, webhook_secret, price_id, base_url):
        self.client = stripe.StripeClient(
            key, stripe_version="2025-03-31.basil",
            http_client=stripe.HTTPXClient(timeout=8, allow_sync_methods=True),
            max_network_retries=1,
        )
        self.live = key.startswith(("sk_live_", "rk_live_"))
        self.webhook_secret = webhook_secret
        self.price_id = price_id
        self.return_url = base_url + "/devices"

    def webhook_customer(self, body, signature):
        if not signature:
            raise ValueError("Missing Stripe signature")
        event = self.client.construct_event(body, signature, self.webhook_secret)
        if event["livemode"] != self.live:
            raise ValueError("Wrong Stripe mode")
        if event["type"] in EVENT_TYPES:
            customer = event["data"]["object"].get("customer")
            if isinstance(customer, str) and customer.startswith("cus_"):
                return customer
        return None

    @staticmethod
    def _lock(cur, owner):
        cur.execute("SELECT pg_advisory_xact_lock(697551, hashtext(%s))", (owner,))

    def _subscriptions(self, customer):
        return self.client.v1.subscriptions.list(params={
            "customer": customer, "status": "all", "limit": 100,
            "expand": ["data.latest_invoice"],
        }).auto_paging_iter()

    def checkout(self, registry, owner, email):
        with registry.billing_transaction() as cur:
            self._lock(cur, owner)
            cur.execute("SELECT 1 FROM account_usage WHERE owner_sub=%s", (owner,))
            if cur.fetchone() is None:
                raise BillingAccountError("Connect your computer before subscribing.")
            cur.execute("SELECT customer_id FROM stripe_billing WHERE owner_sub=%s", (owner,))
            row = cur.fetchone()
            if row:
                customer = row[0]
            else:
                account_key = sha256((self.return_url + ":" + owner).encode()).hexdigest()
                result = self.client.v1.customers.create(
                    params={"email": email} if email else {},
                    options={"idempotency_key": "flicker-customer-" + account_key},
                )
                customer = result.id
                cur.execute("INSERT INTO stripe_billing (owner_sub, customer_id) VALUES (%s, %s)",
                            (owner, customer))
        with registry.billing_transaction() as cur:
            self._lock(cur, owner)
            if any(sub["status"] not in {"canceled", "incomplete_expired"}
                   for sub in self._subscriptions(customer)):
                return self._portal(customer)
            price = self.client.v1.prices.retrieve(self.price_id)
            recurring = price.get("recurring") or {}
            if (not price.get("active") or price.get("livemode") != self.live
                    or price.get("currency") != "usd" or price.get("unit_amount") != 500
                    or recurring.get("interval") != "month" or recurring.get("interval_count") != 1
                    or recurring.get("usage_type") != "licensed"):
                raise RuntimeError("Stripe price must be an active US$5 monthly price")
            checkout = self.client.v1.checkout.sessions
            for existing in checkout.list(params={
                "customer": customer, "status": "open", "limit": 100,
            }).auto_paging_iter():
                if existing["mode"] != "subscription":
                    continue
                if existing.get("metadata", {}).get("flicker_consent") == self.price_id and existing.get("url"):
                    return existing["url"]
                checkout.expire(existing["id"])
            created = checkout.create(params={
                "mode": "subscription", "customer": customer,
                "line_items": [{"price": self.price_id, "quantity": 1}],
                "payment_method_types": ["card"],
                "adaptive_pricing": {"enabled": False},
                "custom_text": {"submit": {"message": RECURRING_BILLING_NOTICE}},
                "metadata": {"flicker_consent": self.price_id},
                "success_url": self.return_url + "?billing=complete",
                "cancel_url": self.return_url,
            })
            return created["url"]

    def _portal(self, customer):
        result = self.client.v1.billing_portal.sessions.create(params={
            "customer": customer, "return_url": self.return_url,
        })
        return result["url"]

    def portal(self, registry, owner):
        with registry.billing_transaction() as cur:
            cur.execute("SELECT customer_id FROM stripe_billing WHERE owner_sub=%s", (owner,))
            row = cur.fetchone()
        if row is None:
            raise BillingAccountError("There is no billing profile for this account.")
        return self._portal(row[0])

    def refresh(self, registry, customer):
        with registry.billing_transaction() as cur:
            cur.execute("SELECT owner_sub FROM stripe_billing WHERE customer_id=%s", (customer,))
            row = cur.fetchone()
            if row is None:
                return
            self._lock(cur, row[0])
            # Fetch current state inside the lock so a delayed or repeated event
            # cannot replace a newer payment or cancellation with stale data.
            paid_periods = []
            for subscription in self._subscriptions(customer):
                invoice = subscription.get("latest_invoice")
                if subscription["status"] != "active" or not invoice or invoice["status"] != "paid":
                    continue
                for item in subscription["items"]["data"]:
                    if item["price"]["id"] == self.price_id:
                        paid_periods.append(item["current_period_end"])
            cur.execute("UPDATE stripe_billing SET paid_through=%s WHERE customer_id=%s",
                        (max(paid_periods, default=None), customer))
