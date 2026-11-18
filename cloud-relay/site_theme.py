"""Shared public and account-page presentation for Flicker Link Pro."""

import html
import os


BASE_URL = html.escape(os.getenv("BASE_URL", "https://flicker-link-pro.onrender.com").rstrip("/"), quote=True)


def page_shell(title, content, *, signed_in=False, reading=False, active=""):
    title = html.escape(title)
    description = html.escape(
        f"{title} for Flicker Link Pro. Connect your Windows PC, manage pairing, and find setup support.",
        quote=True,
    )
    cls = "main reading" if reading else "main"
    setup_href = "/setup"
    home_href = "/devices" if signed_in else "/"
    sign_link = '<a href="/auth/logout">Sign out</a>' if signed_in else '<a class="button" href="/auth/google/start?next=%2Fdevices">Sign in</a>'
    mobile_sign_link = '<a href="/auth/logout">Sign out</a>' if signed_in else '<a href="/auth/google/start?next=%2Fdevices">Sign in</a>'
    menu = (
        '<nav class="nav desktop-nav" aria-label="Main navigation">'
        + f'<a href="{setup_href}"' + (' aria-current="page"' if active == "setup" else '') + '>Setup</a>'
        + f'<a href="/support"' + (' aria-current="page"' if active == "support" else '') + '>Support</a>'
        + sign_link + '</nav>'
        + '<details class="mobile-nav"><summary aria-label="Open navigation menu">Menu</summary>'
        + '<nav class="mobile-menu" aria-label="Mobile navigation">'
        + f'<a href="{setup_href}">Setup</a><a href="/support">Support</a>'
        + mobile_sign_link + '</nav></details>'
    )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<title>{title} | Flicker Link Pro</title>'
        f'<meta name="description" content="{description}">'
        f'<meta property="og:title" content="{title} | Flicker Link Pro">'
        '<meta property="og:description" content="Connect ChatGPT to your paired Windows PC with Flicker Link Pro.">'
        '<meta property="og:type" content="website">'
        f'<meta property="og:image" content="{BASE_URL}/assets/Flicker-Link-Pro-Stripe-Logo.png">'
        '<meta name="twitter:card" content="summary">'
        '<meta name="theme-color" content="#0D1023">'
        '<link rel="icon" type="image/png" href="/assets/Flicker-Link-Pro-Stripe-Icon.png">'
        '<link rel="stylesheet" href="/assets/site.css"></head><body><a class="skip" href="#main">Skip to content</a>'
        '<div class="shell"><header class="site-header"><div class="header-inner">'
        f'<a class="brand{" compact" if signed_in else ""}" href="{home_href}" aria-label="Flicker Link Pro home">'
        + ('<img src="/assets/Flicker-Link-Pro-Stripe-Icon.png" alt=""><span>Flicker Link Pro</span>' if signed_in else '<img src="/assets/Flicker-Link-Pro-Stripe-Logo.png" alt="Flicker Link Pro">')
        + '</a>' + menu + '</div></header>'
        f'<main id="main" class="{cls}">{content}</main>'
        '<footer class="site-footer"><div class="footer-inner"><span>Flicker Link Pro</span>'
        '<nav class="footer-links" aria-label="Footer navigation">'
        '<a href="/setup">Setup</a><a href="/support">Support</a>'
        '<a href="/privacy">Privacy</a><a href="/terms">Terms</a>'
        '</nav></div></footer></div></body></html>'
    )
