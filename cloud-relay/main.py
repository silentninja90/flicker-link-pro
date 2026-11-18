"""Flicker Link Pro cloud relay: Google OIDC login and PKCE-protected MCP OAuth.

Google confirms identity. This server issues audience-bound OAuth tokens for ChatGPT.
Device pairing is available only in a Google-authenticated browser session.
"""
import asyncio
import base64
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timezone
import hashlib
import html
import json
import logging
import os
from functools import lru_cache
import pathlib
import re
import secrets
import time
import uuid
from urllib.parse import urlencode, urlsplit

import httpx
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
import jwt
from jwt import PyJWKClient
from jwt.exceptions import PyJWTError
from device_registry import DeviceRegistry
from site_theme import page_shell

BASE_URL = os.getenv("BASE_URL", "https://flicker-link-pro.onrender.com").rstrip("/")
RESOURCE = BASE_URL + "/mcp"
SERVER_NAME = (
    "flicker-link-pro-staging"
    if urlsplit(BASE_URL).hostname == "flicker-link-pro-2-staging.onrender.com"
    else "flicker-link-pro"
)
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
STAGING_OWNER_SUBJECTS = frozenset(
    subject.strip()
    for subject in os.getenv("FLICKER_STAGING_OWNER_SUBJECTS", "").split(",")
    if subject.strip()
) if SERVER_NAME == "flicker-link-pro-staging" else frozenset()
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
SECRET = os.getenv("FLICKER_SECRET", "")
OPENAI_APPS_CHALLENGE = os.getenv("OPENAI_APPS_CHALLENGE", "")
PURGE_REVOKED = os.getenv("FLICKER_PURGE_REVOKED_DEVICES", "") == "1"
SCOPES = "laptop:control"
CATALOG = json.loads((pathlib.Path(__file__).parent / "tool_catalog.json").read_text(encoding="utf-8"))
TOOL_SECURITY_SCHEMES = [{"type": "oauth2", "scopes": [SCOPES]}]
for tool in CATALOG:
    tool["securitySchemes"] = TOOL_SECURITY_SCHEMES
    tool.setdefault("_meta", {})["securitySchemes"] = TOOL_SECURITY_SCHEMES
CATALOG_NAMES = {entry["name"] for entry in CATALOG}
FREE_CALL_ALLOWANCE = int(os.getenv("FLICKER_FREE_CALL_ALLOWANCE", "0"))
if FREE_CALL_ALLOWANCE < 0:
    raise ValueError("FLICKER_FREE_CALL_ALLOWANCE must be zero or positive")
if FREE_CALL_ALLOWANCE and not os.getenv("DATABASE_URL", "").strip():
    raise ValueError("A PostgreSQL DATABASE_URL is required to enable tool call allowances")
STRIPE_KEY = os.getenv("STRIPE_SECRET_KEY", "").strip()
STRIPE_PUBLISHABLE_KEY = os.getenv("STRIPE_PUBLISHABLE_KEY", "").strip()
STRIPE_WEBHOOK = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()
STRIPE_PRICE = os.getenv("STRIPE_PRICE_ID", "").strip()
BILLING = None
stripe_settings = (STRIPE_KEY, STRIPE_WEBHOOK, STRIPE_PRICE)
stripe_test_key = STRIPE_KEY.startswith(("sk_test_", "rk_test_"))
if STRIPE_KEY and stripe_test_key and not SERVER_NAME.endswith("-staging"):
    logging.getLogger("flicker-link-pro").warning("Stripe sandbox billing is disabled on the production relay")
elif all(stripe_settings):
    if not FREE_CALL_ALLOWANCE or not (
        STRIPE_KEY.startswith(("sk_test_", "rk_test_", "sk_live_", "rk_live_"))
        and STRIPE_WEBHOOK.startswith("whsec_") and STRIPE_PRICE.startswith("price_")
    ):
        raise ValueError("Billing requires the Stripe configuration and an enabled free allowance")
    if SERVER_NAME.endswith("-staging") and not stripe_test_key:
        raise ValueError("Staging billing requires a Stripe test key")
    from stripe_billing import BillingAccountError, RECURRING_BILLING_NOTICE, StripeBilling

    BILLING = StripeBilling(STRIPE_KEY, STRIPE_WEBHOOK, STRIPE_PRICE, BASE_URL)
elif any(stripe_settings):
    logging.getLogger("flicker-link-pro").warning("Stripe billing is disabled until all Stripe settings are configured")
CHECKOUT_AVAILABLE = BILLING is not None and STRIPE_PUBLISHABLE_KEY.startswith(
    "pk_test_" if stripe_test_key else "pk_live_"
)
UNMETERED_TOOLS = {"list_devices", "get_usage_stats"}
ACTIVE_SOCKETS = {}
ACTIVE_DEVICE_IDS = {}
DEVICE_HEARTBEAT_INTERVAL = 120
PENDING_CALLS = {}
REDEEMED_CODES = {}  # one-time authorization code ID -> JWT expiration timestamp
# Authorization codes are invalidated on every process restart.
PROCESS_CODE_KEY = secrets.token_urlsafe(48)

async def purge_revoked_devices():
    while True:
        try:
            await asyncio.to_thread(lambda: device_registry().purge_revoked())
        except Exception as exc:
            logging.getLogger("flicker-link-pro").warning(
                "Revoked device cleanup failed: %s", type(exc).__name__)
        await asyncio.sleep(3600)


@asynccontextmanager
async def lifespan(_app):
    cleanup = (
        asyncio.create_task(purge_revoked_devices())
        if PURGE_REVOKED and os.getenv("DATABASE_URL", "").strip() else None
    )
    try:
        yield
    finally:
        if cleanup is not None:
            cleanup.cancel()
            with suppress(asyncio.CancelledError):
                await cleanup


app = FastAPI(title="Flicker Link Pro Cloud Relay", version="2.2.0", lifespan=lifespan)
app.mount("/assets", StaticFiles(directory=pathlib.Path(__file__).parent / "assets"), name="assets")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(
        (pathlib.Path(__file__).parent / "assets" / "Flicker-Link-Pro-Stripe-Icon.png").read_bytes(),
        media_type="image/png", headers={"Cache-Control": "public, max-age=86400"},
    )


@app.get("/robots.txt", include_in_schema=False)
async def robots_txt():
    return PlainTextResponse(
        "User-agent: *\nAllow: /\nDisallow: /devices\nDisallow: /oauth/\nDisallow: /auth/\n"
        "Sitemap: " + BASE_URL + "/sitemap.xml\n",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@app.get("/sitemap.xml", include_in_schema=False)
async def sitemap_xml():
    pages = ("/", "/setup", "/device-access", "/support", "/privacy", "/terms")
    items = "".join(f"<url><loc>{html.escape(BASE_URL + path)}</loc></url>" for path in pages)
    return Response(
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?><urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">"
        + items + "</urlset>", media_type="application/xml",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@app.exception_handler(StarletteHTTPException)
@app.exception_handler(HTTPException)
async def browser_http_error(request: Request, exc: HTTPException):
    accepts_html = "text/html" in request.headers.get("accept", "")
    if not accepts_html or request.url.path in ("/mcp", "/oauth/token", "/billing/webhook"):
        detail = exc.detail if isinstance(exc.detail, str) else "Request failed"
        return JSONResponse({"detail": detail}, status_code=exc.status_code, headers=exc.headers)
    if exc.status_code == 404:
        title, message = "We couldn’t find that page", "The link may have moved or the address may be incorrect."
    elif exc.status_code >= 500:
        title, message = "This page is temporarily unavailable", "Please try again in a moment. If the issue continues, contact support."
    else:
        title, message = "We couldn’t complete that step", str(exc.detail)
    content = (
        '<section class="error-card"><span class="error-mark">Flicker Link Pro</span>'
        f'<h1>{html.escape(title)}</h1><p>{html.escape(message)}</p>'
        '<div class="actions"><a class="button" href="/setup">Setup</a>'
        '<a class="button secondary" href="/support">Get support</a></div></section>'
    )
    return HTMLResponse(page_shell(title, content, reading=True), status_code=exc.status_code, headers=exc.headers)


@app.exception_handler(Exception)
async def browser_server_error(request: Request, _exc: Exception):
    accepts_html = "text/html" in request.headers.get("accept", "")
    if not accepts_html or request.url.path in ("/mcp", "/oauth/token", "/billing/webhook"):
        return JSONResponse({"detail": "Request failed"}, status_code=500)
    content = (
        '<section class="error-card\"><span class="error-mark">Flicker Link Pro</span>'
        '<h1>This page is temporarily unavailable</h1>'
        '<p>Please try again in a moment. If the issue continues, contact support.</p>'
        '<div class="actions"><a class="button" href=\"/setup\">Setup</a>'
        '<a class="button secondary" href=\"/support\">Get support</a></div></section>'
    )
    return HTMLResponse(page_shell("Service unavailable", content, reading=True), status_code=500)


def account_usage(owner, *, consume=False):
    try:
        is_owner = owner in STAGING_OWNER_SUBJECTS
        usage = device_registry().usage(owner, FREE_CALL_ALLOWANCE, consume=consume and not is_owner)
        if is_owner:
            return {**(usage or {"has_billing": False}), "unlimited": True, "allowed": True, "owner": True}
        return usage
    except Exception:
        raise HTTPException(503, "Account usage is temporarily unavailable") from None


def reset_date(usage):
    return datetime.fromtimestamp(usage["resets_at"], timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


@app.get("/.well-known/openai-apps-challenge", include_in_schema=False)
async def openai_apps_challenge():
    """Serve the exact temporary token supplied during publisher verification."""
    if not OPENAI_APPS_CHALLENGE:
        raise HTTPException(404, "Domain verification challenge is not configured")
    return PlainTextResponse(OPENAI_APPS_CHALLENGE, headers={"Cache-Control": "no-store"})

@lru_cache(maxsize=4)
def _postgres_registry_cached(database_url: str, secret: str):
    from postgres_registry import PostgresDeviceRegistry
    return PostgresDeviceRegistry(database_url, secret, meter_usage=bool(FREE_CALL_ALLOWANCE))


def device_registry():
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if database_url:
        try:
            return _postgres_registry_cached(database_url, server_secret())
        except (OSError, ValueError) as exc:
            raise HTTPException(503, "Durable PostgreSQL storage is unavailable") from exc
        except Exception as exc:
            # psycopg2 errors may include the DSN: never expose their details.
            if isinstance(exc, HTTPException):
                raise
            raise HTTPException(503, "Durable PostgreSQL storage is unavailable") from exc
    db_path = os.environ.get("FLICKER_DB_PATH", "").strip()
    if not db_path or not pathlib.Path(db_path).is_absolute():
        raise HTTPException(503, "A persistent FLICKER_DB_PATH is required for device pairing")
    if os.environ.get("RENDER"):
        mount = pathlib.Path(os.environ.get("FLICKER_DISK_MOUNT", "/var/data")).resolve()
        database = pathlib.Path(db_path).resolve()
        if mount not in database.parents or not os.path.ismount(str(mount)):
            raise HTTPException(503, "Device pairing requires a mounted persistent Render disk")
    try:
        return DeviceRegistry(db_path, server_secret())
    except (OSError, ValueError) as exc:
        raise HTTPException(503, "Durable device storage is unavailable") from exc

async def disconnect_device(owner_sub, device_id):
    if ACTIVE_DEVICE_IDS.get(owner_sub) != device_id:
        return
    ws = ACTIVE_SOCKETS.get(owner_sub)
    if ws is not None:
        try:
            await ws.close(code=1008)
        except RuntimeError:
            pass

def server_secret():
    if not SECRET or SECRET == "flicker-link-pro-secret-key-change-me" or len(SECRET) < 24:
        raise HTTPException(503, "FLICKER_SECRET must be configured securely in Render")
    return SECRET

def sign(kind, sub, aud, ttl, **extra):
    now = int(time.time())
    claims = {"iss": BASE_URL, "aud": aud, "sub": sub, "kind": kind,
              "iat": now, "exp": now + ttl, "jti": secrets.token_urlsafe(16)}
    claims.update(extra)
    return jwt.encode(claims, PROCESS_CODE_KEY if kind == "auth_code" else server_secret(), algorithm="HS256")

def verify(token, kind, aud):
    try:
        claims = jwt.decode(token, PROCESS_CODE_KEY if kind == "auth_code" else server_secret(), algorithms=["HS256"],
                            issuer=BASE_URL, audience=aud)
        if claims.get("kind") != kind:
            raise ValueError("Wrong token type")
        return claims
    except (PyJWTError, ValueError, TypeError):
        raise HTTPException(401, "Invalid or expired credential")

def safe_next(value):
    return value if value.startswith("/") and not value.startswith("//") and "\\" not in value and len(value) <= 5000 else "/devices"

def session(request):
    raw = request.cookies.get("flp_session", "")
    if not raw:
        return None
    try:
        return verify(raw, "session", BASE_URL + "/session")
    except HTTPException:
        return None

def digest(value):
    return base64.urlsafe_b64encode(hashlib.sha256(value.encode()).digest()).rstrip(b"=").decode()

def check_origin(request):
    if request.headers.get("origin", "") != BASE_URL:
        raise HTTPException(403, "Invalid request origin")

def validate_redirect(uri):
    try:
        parsed = urlsplit(uri)
        return bool(
            (parsed.scheme == "https" or
             (parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1")))
            and parsed.netloc and not parsed.username and not parsed.password
            and not parsed.fragment and len(uri) < 700
        )
    except ValueError:
        return False

def oauth_client(client_id):
    client = verify(client_id, "client", BASE_URL + "/clients")
    if not client.get("redirect_uris"):
        raise HTTPException(400, "Invalid client")
    return client

def auth_request(params):
    client_id = params.get("client_id", "")
    client = oauth_client(client_id)
    redirect_uri = params.get("redirect_uri", "")
    if redirect_uri not in client["redirect_uris"]:
        raise HTTPException(400, "Unregistered redirect URI")
    if params.get("response_type") != "code":
        raise HTTPException(400, "Only authorization code flow is supported")
    if params.get("code_challenge_method") != "S256":
        raise HTTPException(400, "PKCE S256 is required")
    challenge = params.get("code_challenge", "")
    if len(challenge) != 43 or any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for c in challenge):
        raise HTTPException(400, "Invalid PKCE challenge")
    if params.get("resource") != RESOURCE:
        raise HTTPException(400, "Invalid MCP resource")
    if set(params.get("scope", SCOPES).split()) != {SCOPES}:
        raise HTTPException(400, "Unsupported scope")
    if not params.get("state") or len(params["state"]) > 1024:
        raise HTTPException(400, "Missing OAuth state")
    return {"client_id": client_id, "redirect_uri": redirect_uri,
            "challenge": challenge, "resource": RESOURCE, "scope": SCOPES,
            "state": params["state"], "client_name": client.get("client_name", "MCP client")}

def unauthorized():
    return JSONResponse({"error": "unauthorized"}, 401, headers={
        "WWW-Authenticate": 'Bearer resource_metadata="' + BASE_URL + '/.well-known/oauth-protected-resource", scope="' + SCOPES + '"'})

@app.get("/.well-known/oauth-protected-resource")
@app.get("/.well-known/oauth-protected-resource/mcp")
async def resource_metadata():
    return {"resource": RESOURCE, "authorization_servers": [BASE_URL],
            "scopes_supported": [SCOPES], "bearer_methods_supported": ["header"]}

@app.get("/.well-known/oauth-authorization-server")
async def authorization_metadata():
    return {"issuer": BASE_URL, "authorization_endpoint": BASE_URL + "/oauth/authorize",
            "token_endpoint": BASE_URL + "/oauth/token",
            "registration_endpoint": BASE_URL + "/oauth/register",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code"],
            "token_endpoint_auth_methods_supported": ["none"],
            "code_challenge_methods_supported": ["S256"],
            "scopes_supported": [SCOPES],
            "service_documentation": BASE_URL + "/"}

@app.post("/oauth/register")
async def register(request: Request):
    data = await request.json()
    redirect_uris = data.get("redirect_uris")
    if (not isinstance(redirect_uris, list) or not 1 <= len(redirect_uris) <= 5 or
        not all(isinstance(u, str) and validate_redirect(u) for u in redirect_uris) or
        len(set(redirect_uris)) != len(redirect_uris) or
        data.get("token_endpoint_auth_method", "none") != "none"):
        raise HTTPException(400, "Invalid public-client registration")
    name = str(data.get("client_name", "MCP client"))[:100]
    client_id = sign("client", "registered-client", BASE_URL + "/clients",
                     365 * 86400, redirect_uris=redirect_uris, client_name=name)
    return JSONResponse({"client_id": client_id, "client_name": name,
                         "redirect_uris": redirect_uris,
                         "token_endpoint_auth_method": "none",
                         "grant_types": ["authorization_code"],
                         "response_types": ["code"]}, status_code=201)

class GoogleCallbackAccessLogFilter(logging.Filter):
    """Remove one-time OAuth authorization codes from Uvicorn access logs."""
    def filter(self, record):
        if isinstance(record.args, tuple):
            record.args = tuple(
                re.sub(r"(/auth/google/callback)\?[^\s\"']+", r"\1?[redacted]", value)
                if isinstance(value, str) else value
                for value in record.args
            )
        return True


logging.getLogger("uvicorn.access").addFilter(GoogleCallbackAccessLogFilter())


def google_token_error_category(response) -> str:
    """Return only documented coarse Google error codes; never error_description."""
    try:
        result = response.json()
    except (ValueError, TypeError):
        return "unknown"
    code = result.get("error") if isinstance(result, dict) else None
    safe_codes = {"invalid_client", "invalid_grant", "invalid_request",
                  "unauthorized_client", "access_denied"}
    return code if isinstance(code, str) and code in safe_codes else "unknown"


@app.get("/auth/google/start")
async def google_start(next: str = "/devices"):
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise HTTPException(503, "Google OAuth credentials are not configured")
    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(48)
    flow = sign("google_flow", "login", BASE_URL + "/google", 600,
                state=state, nonce=nonce, verifier=verifier, next=safe_next(next))
    params = {"client_id": GOOGLE_CLIENT_ID, "redirect_uri": BASE_URL + "/auth/google/callback",
              "response_type": "code", "scope": "openid email profile",
              "state": state, "nonce": nonce, "code_challenge": digest(verifier),
              "code_challenge_method": "S256"}
    reply = RedirectResponse("https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params))
    reply.set_cookie("flp_google_flow", flow, httponly=True, secure=True, samesite="lax", max_age=600, path="/")
    return reply

@app.get("/auth/google/callback")
async def google_callback(request: Request, state: str = "", code: str = ""):
    flow = verify(request.cookies.get("flp_google_flow", ""), "google_flow", BASE_URL + "/google")
    if not code or not secrets.compare_digest(state, flow["state"]):
        raise HTTPException(400, "Google sign-in state mismatch")
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post("https://oauth2.googleapis.com/token", data={
            "client_id": GOOGLE_CLIENT_ID, "client_secret": GOOGLE_CLIENT_SECRET,
            "code": code, "code_verifier": flow["verifier"],
            "grant_type": "authorization_code",
            "redirect_uri": BASE_URL + "/auth/google/callback"})
        if resp.status_code != 200:
            logging.getLogger("flicker-link-pro").warning(
                "Google token exchange rejected: HTTP %s, category=%s",
                resp.status_code, google_token_error_category(resp))
            raise HTTPException(400, "Google token exchange failed")
        tokens = resp.json()
    try:
        def check_google_signature():
            # Fetches Google's public JWKS and validates issuer, audience, expiry and signature.
            key = PyJWKClient("https://www.googleapis.com/oauth2/v3/certs").get_signing_key_from_jwt(tokens["id_token"]).key
            return jwt.decode(
                tokens["id_token"], key, algorithms=["RS256"],
                audience=GOOGLE_CLIENT_ID,
                issuer=["https://accounts.google.com", "accounts.google.com"],
                options={"require": ["iss", "sub", "aud", "exp", "iat"]})
        identity = await asyncio.to_thread(check_google_signature)
        if not identity.get("email_verified") or identity.get("nonce") != flow["nonce"]:
            raise ValueError("Invalid Google account proof")
    except Exception:
        raise HTTPException(401, "Unable to verify Google identity")
    user = sign("session", identity["sub"], BASE_URL + "/session", 12 * 3600,
                email=identity.get("email", ""), csrf=secrets.token_urlsafe(24))
    response = RedirectResponse(safe_next(flow["next"]))
    response.set_cookie("flp_session", user, secure=True, httponly=True,
                        samesite="lax", max_age=12 * 3600, path="/")
    response.delete_cookie("flp_google_flow", path="/")
    return response

@app.get("/healthz")
async def healthz():
    """DB readiness probe for staging; never expose connection details."""
    try:
        device_registry().list_owned("__flicker_health_check__")
    except Exception as exc:
        # Log the exception CLASS only. PostgreSQL exceptions can embed credentials.
        kind = type(exc).__name__
        if isinstance(exc, HTTPException):
            kind = "postgres_storage_unavailable" if os.getenv("DATABASE_URL") else "database_url_missing"
        logging.getLogger("flicker-link-pro").warning("Database health check failed: %s", kind)
        raise HTTPException(503, "Database unavailable") from None
    return {"status": "ok", "database": "ready"}


@app.get("/")
async def home(request: Request):
    user = session(request)
    if user:
        return RedirectResponse("/devices")
    content = '''
<section class="hero" aria-labelledby="hero-title">
  <div class="hero-copy"><span class="eyebrow">Your computer, connected to ChatGPT</span>
    <h1 id="hero-title">Connect ChatGPT to your Windows PC</h1>
    <p>Pair your Windows computer with Flicker Link Pro to work with files and apps from ChatGPT. You stay in control of the computer and can disconnect it from your account.</p>
    <div class="actions"><a class="button" href="/setup">Set up my PC</a><a class="button secondary" href="#how-it-works">See how it works</a></div>
    <p class="support-note">Already paired? <a href="/auth/google/start?next=%2Fdevices">Sign in to manage your computer</a>.</p>
  </div>
  <figure class="preview-wrap product-shot">
    <img src="/assets/paired-computers-preview.png" alt="Flicker Link Pro Paired Computers page showing a connected computer, revoked pairings, and the option to pair a Windows computer.">
    <figcaption class="preview-caption">Paired Computers on Flicker Link Pro, captured from the staging account.</figcaption>
  </figure>
</section>
<section class="section" id="how-it-works" aria-labelledby="how-title"><div class="section-intro"><span class="eyebrow">A simple setup</span><h2 id="how-title">How connection works</h2><p>Sign in with the account you want to use for this paired computer.</p></div>
  <div class="grid">
    <article class="panel"><span class="step-number">1</span><h3>Sign in</h3><p>Use Google to open your Flicker Link Pro account and start a pairing request.</p></article>
    <article class="panel"><span class="step-number">2</span><h3>Pair your Windows PC</h3><p>Open the Flicker Link Pro companion on Windows, enter the pairing token. The Windows app asks for approval when you first request a sensitive action.</p></article>
    <article class="panel"><span class="step-number">3</span><h3>Use it in ChatGPT</h3><p>Connect the Flicker Link Pro plugin in ChatGPT. Your paired computer must be running and online.</p></article>
  </div><div class="actions"><a class="button" href="/setup">View setup steps</a></div>
</section>
<section class="section" aria-labelledby="capabilities-title"><div class="section-intro"><span class="eyebrow">What you can do</span><h2 id="capabilities-title">Use your computer from a chat</h2><p>Flicker Link Pro offers tools for common computer work. Available actions depend on Windows, your installed software, and the permissions you grant.</p></div>
  <div class="grid">
    <article class="panel"><div class="panel-icon" aria-hidden="true">⌕</div><h3>Find and work with files</h3><p>Search folders, inspect documents, and create or organize files you choose.</p></article>
    <article class="panel"><div class="panel-icon" aria-hidden="true">▣</div><h3>Check your PC</h3><p>Review system resources, drives, network details, windows, and running processes.</p></article>
    <article class="panel"><div class="panel-icon" aria-hidden="true">⌘</div><h3>Work with apps</h3><p>Run commands or interact with desktop apps when the companion and required tools are available.</p></article>
  </div>
</section>
<section class="section" aria-labelledby="access-title"><div class="access-panel"><div><span class="eyebrow">Your access, your choice</span><h2 id="access-title">Understand computer access</h2><p>Flicker Link Pro routes your requested actions through your paired Windows companion.</p></div>
  <ul><li>The companion must be running and connected for computer actions to work.</li><li>Depending on the tool, requests can access files, apps, desktop controls, commands, and system information available to your Windows account.</li><li>The companion asks before granting its full sensitive-tool access. ChatGPT may also request confirmation for individual actions.</li><li>Stop the companion to disconnect temporarily, or sign out/revoke the computer to remove its pairing.</li></ul>
</div><p style="margin-top:16px"><a href="/device-access">Review device access</a> · <a href="/support">Get help with setup</a></p></section>
<section class="section" aria-labelledby="faq-title"><div class="section-intro"><span class="eyebrow">Common questions</span><h2 id="faq-title">Before you connect</h2></div>
  <div class="faq"><details><summary>What do I need?</summary><p>A Windows computer with the Flicker Link Pro companion, a Google account, and access to Flicker Link Pro in ChatGPT.</p></details>
  <details><summary>Does my computer need to stay online?</summary><p>Yes. It must be powered on, connected to the internet, and running the companion while you use computer tools.</p></details>
  <details><summary>How do I disconnect?</summary><p>Stop the companion to pause the connection. To revoke pairing, use the sign-out option on Windows or revoke the computer from your account’s Paired Computers page.</p></details>
  <details><summary>Where can I get help?</summary><p>Visit <a href="/support">Flicker Link Pro Support</a>. Never send your password or pairing token in a support message.</p></details></div>
</section>
<section class="section" aria-labelledby="final-cta"><div class="section-intro"><span class="eyebrow">Ready when you are</span><h2 id="final-cta">Connect your Windows PC</h2><p>Sign in to create a pairing token and manage your computer.</p><a class="button" href="/setup">Set up my PC</a></div></section>
'''
    return HTMLResponse(page_shell("Connect ChatGPT to your Windows PC", content))


@app.get("/setup")
async def setup(request: Request):
    signed_in = bool(session(request))
    content = '''<span class="eyebrow">Setup guide</span><h1>Connect your Windows PC</h1>
<p>Keep the browser open while you complete pairing on the Windows computer you want to connect.</p>
<div class="steps"><div class="step"><span class="step-number">1</span><strong>Sign in</strong><p>Use the Google account you want linked to this PC.</p></div>
<div class="step"><span class="step-number">2</span><strong>Create a pairing token</strong><p>From Paired Computers, start pairing and choose a name for your PC.</p></div>
<div class="step"><span class="step-number">3</span><strong>Finish on Windows</strong><p>Open Flicker Link Pro, and paste the token. Approve sensitive access on Windows when you first need it.</p></div></div>
<div class="panel"><h2>Before you begin</h2><ul><li>A Windows PC with the Flicker Link Pro companion installed.</li><li>A Google account for your Flicker Link Pro account.</li><li>Access to Flicker Link Pro in ChatGPT.</li></ul><p>Need the Windows app or access in ChatGPT? <a href="/support">Contact support about availability</a>.</p><p>Review <a href="/device-access">what computer access means</a> before pairing.</p></div>
<div class="alert"><strong>Continue on your Windows PC</strong><p>The companion must be installed and running to finish pairing. Keep your token private; it grants access to the computer.</p></div>
<div class="actions"><a class="button" href="/auth/google/start?next=%2Fdevices">Continue with Google</a><a class="button secondary" href="/support">Get setup help</a></div>
<p>After pairing, return to Paired Computers and refresh to check the connection. You can rename or revoke the computer there.</p>'''
    if signed_in:
        content = content.replace('href="/auth/google/start?next=%2Fdevices">Continue with Google',
                                  'href="/devices">Open Paired Computers')
    return HTMLResponse(page_shell("Setup", content, signed_in=signed_in, reading=True, active="setup"),
                        headers={"Cache-Control": "no-store"})


@app.get("/support")
async def support():
    content = '''<span class="eyebrow">Flicker Link Pro help</span><h1>Get support</h1>
<p>Start with the steps below. If you still need help, email <a href="mailto:flickerlinkpro@gmail.com">flickerlinkpro@gmail.com</a>.</p>
<div class="grid support-grid">
<article class="panel" id="signin"><h2>Sign-in trouble</h2><p>Check that your browser can open Google sign-in and that you return to the same Flicker Link Pro account you used to pair your computer.</p><a href="/auth/google/start?next=%2Fdevices">Try signing in</a></article>
<article class="panel" id="pairing"><h2>Pairing or expired token</h2><p>Sign in, create a fresh pairing token on Paired Computers, then enter it in the Windows companion. Treat the token like a password.</p><a href="/setup">See setup steps</a></article>
<article class="panel" id="offline"><h2>Computer shows offline</h2><p>Open Flicker Link Pro on Windows, check that the PC has internet access, and refresh Paired Computers.</p><a href="/devices">Check computer status</a></article>
<article class="panel" id="disconnect"><h2>Disconnect or remove a PC</h2><p>Stop the companion to pause its connection. Sign out on Windows or revoke the computer from your account to end its pairing.</p><a href="/devices">Manage paired computers</a></article>
</div><section class="section"><h2>Contact support</h2><p>Include the error message, Windows version, and what step you were on. Do not include passwords, pairing tokens, private keys, or file contents.</p><a class="button" href="mailto:flickerlinkpro@gmail.com">Email support</a></section>'''
    return HTMLResponse(page_shell("Support", content, reading=True, active="support"))


@app.get("/device-access")
async def device_access():
    content = """<article class="prose"><h1>Device access</h1>
<p>Pair one Windows computer you own or are authorized to use. Computer actions work while the Flicker Link Pro companion is running and connected.</p>
<h2>What the tools can access</h2>
<p>Depending on the action you request, tools can read or change files, capture the screen, interact with desktop apps, run commands, or return system data available to your Windows account. Requests and results pass through the relay between ChatGPT and your computer.</p>
<h2>When Windows asks for approval</h2>
<p>The companion asks when you first request a sensitive action. If you grant full access, that approval stays saved across app restarts. It clears when you sign out of the Windows app or revoke the pairing. ChatGPT can ask for a separate confirmation.</p>
<h2>How to disconnect</h2>
<p>Close the Windows companion to pause access. To remove the pairing, use the Windows sign-out shortcut or select Disconnect PC in Paired Computers. You will need a new pairing token to reconnect after that.</p>
<div class="actions"><a class="button" href="/setup">View setup steps</a><a class="button secondary" href="/privacy">Read the privacy policy</a></div></article>"""
    return HTMLResponse(page_shell("Device access", content, reading=True))


@app.get("/privacy")
async def privacy():
    content = '''<article class="prose"><span class="eyebrow">Your information</span><h1>Privacy Policy</h1>
<p><strong>Last updated: November 17, 2026</strong></p>
<p>Eric Williams operates Flicker Link Pro. This policy covers the Flicker Link Pro website, ChatGPT plugin, cloud relay, and Windows app. For privacy questions or requests, email <a href="mailto:flickerlinkpro@gmail.com">flickerlinkpro@gmail.com</a>.</p>
<h2>Information we use</h2>
<ul>
<li><strong>Google account identifier and verified email:</strong> sign-in, account pairing, showing the signed-in email, and creating a Stripe billing profile.</li>
<li><strong>Sign-in cookies:</strong> the sign-in exchange cookie expires after 10 minutes; the website session cookie lasts up to 12 hours. Signing out clears the website session.</li>
<li><strong>Device and pairing details:</strong> device identifier and name, pairing and connection times, revocation time, and a cryptographic digest of the pairing token. The Windows app stores the token in Windows Credential Manager.</li>
<li><strong>Tool requests and results:</strong> the relay passes requests to your paired computer and results to ChatGPT. Depending on the tool, these can include file contents, paths, screenshots, command output, and system information. The Windows app can save a result locally when you ask it to.</li>
<li><strong>Usage and subscription details:</strong> account-level call counts and period start, a Stripe customer identifier, and the date through which paid access applies. These enforce call limits and recognize paid access.</li>
<li><strong>Service logs:</strong> Render logs can include IP addresses, request times, routes, status codes, and operational errors, used to operate, secure, and troubleshoot the service.</li>
<li><strong>Support messages:</strong> information you send to answer support and privacy requests.</li>
</ul>
<h2>Who receives information</h2>
<ul><li>Google provides sign-in.</li><li>Render hosts the website and relay; Neon hosts account, device, usage, and billing-reference data.</li><li>OpenAI processes tool requests and results when you use Flicker Link Pro in ChatGPT. OpenAI's own policies and settings govern your ChatGPT account and conversations.</li><li>Stripe processes website checkout and billing under its own privacy practices.</li><li>A destination you select for a supported transfer tool receives information needed for that action.</li></ul>
<h2>Retention and your choices</h2>
<p>Revoked device records become eligible for deletion after 30 days. The service checks at startup and hourly while running; if it is stopped or unavailable, cleanup runs after it starts again. Neon currently reports a six-hour point-in-time recovery window. Render log availability is 7 to 30 days depending on the workspace plan. Provider retention settings may change.</p>
<p>Usage counters are kept while your account is active to apply the free allowance and paid access. After account closure, they are removed when no longer needed for security, billing disputes, or legal obligations. Billing records are retained as needed for tax, accounting, security, and dispute obligations. Support messages are kept for 90 days after the issue is resolved, unless needed longer to handle a dispute or legal obligation.</p>
<p>Stop the Windows app to disconnect temporarily. Use <strong>Flicker Link Pro - Sign Out</strong> on the computer or revoke it from <strong>Paired Computers</strong> to revoke its pairing. Manage or cancel a paid membership from <strong>Manage billing</strong> on the website.</p>
<p>To request access to, correction of, or deletion of your information, email <a href="mailto:flickerlinkpro@gmail.com">flickerlinkpro@gmail.com</a>. We may ask for information needed to verify the request. Applicable rights depend on where you live. Some records may remain when needed for billing, security, or legal obligations.</p>
<p><a href="/terms">Terms of Service</a> · <a href="/support">Support</a></p></article>'''
    return HTMLResponse(page_shell("Privacy Policy", content, reading=True))


@app.get("/terms")
async def terms():
    content = '''<article class="prose"><span class="eyebrow">Terms of service</span><h1>Terms of Service</h1>
<p><strong>Last updated: November 17, 2026</strong></p>
<p>These terms cover the Flicker Link Pro website, ChatGPT plugin, cloud relay, and Windows app operated by Eric Williams. Contact <a href="mailto:flickerlinkpro@gmail.com">flickerlinkpro@gmail.com</a> for support or billing questions.</p>
<h2>Your account and computer</h2>
<p>Use Flicker Link Pro only with a computer you own or are authorized to control. Keep your sign-in and pairing token private. You are responsible for permission to access the files, software, and services involved in each request.</p>
<p>Flicker Link Pro lets you request actions on a paired Windows computer. Review the action and its target before approving it. Some actions can change or delete files, stop processes, or transfer information. Keep backups of information you need.</p>
<p>Stop the Windows app to disconnect temporarily. To remove the pairing, use <strong>Flicker Link Pro - Sign Out</strong> or revoke the computer from <strong>Paired Computers</strong> on the website.</p>
<h2>Acceptable use</h2>
<p>Use the service lawfully. Access only computers, accounts, and data you have permission to use. Do not use it to access another person's computer or information without authorization, secretly monitor someone, distribute malicious software, bypass access controls, or interfere with another service.</p>
<h2>Usage and optional membership</h2>
<p>The free plan includes 15,000 metered tool calls per 30-day period. The first period starts when the computer first connects. Your account page shows usage and the next reset date.</p>
<p>The Flicker Link Pro website offers an optional unlimited membership for <strong>US$5 per month</strong>. Stripe Checkout shows the price and recurring charge before payment. By confirming the subscription in checkout, you authorize the recurring monthly charge until you cancel.</p>
<p>To cancel, select <strong>Manage billing</strong> on the website. Cancellation at the end of the billing period stops the next renewal; paid access continues through the date shown in the billing portal. Contact <a href="mailto:flickerlinkpro@gmail.com">flickerlinkpro@gmail.com</a> about incorrect charges or a refund request. Applicable consumer rights continue to apply.</p>
<h2>Availability</h2>
<p>Remote actions depend on the Windows app, your computer, network access, and services such as ChatGPT, Google sign-in, and Stripe. Some tools also require software or permissions on your computer. Availability may change during maintenance, outages, or updates.</p>
<p>See the <a href="/privacy">Privacy Policy</a> for details about information Flicker Link Pro uses. <a href="/support">Support</a></p></article>'''
    return HTMLResponse(page_shell("Terms of Service", content, reading=True))


async def billing_form(request):
    if BILLING is None:
        raise HTTPException(404)
    check_origin(request)
    user = session(request)
    if not user:
        raise HTTPException(401, "Sign in first")
    form = await request.form()
    if not secrets.compare_digest(str(form.get("csrf", "")), user["csrf"]):
        raise HTTPException(403, "Invalid CSRF token")
    return user


async def billing_call(operation, *args):
    try:
        return await asyncio.to_thread(lambda: operation(device_registry(), *args))
    except BillingAccountError as exc:
        raise HTTPException(400, str(exc)) from None
    except Exception as exc:
        logging.getLogger("flicker-link-pro").warning("Billing request failed: %s", type(exc).__name__)
        raise HTTPException(503, "Billing is temporarily unavailable") from None


@app.post("/billing/checkout")
async def stripe_checkout(request: Request):
    user = await billing_form(request)
    if user["sub"] in STAGING_OWNER_SUBJECTS:
        raise HTTPException(409, "This account already has unlimited owner access.")
    if not CHECKOUT_AVAILABLE:
        raise HTTPException(503, "Checkout is temporarily unavailable")
    result = await billing_call(BILLING.checkout, user["sub"], user.get("email"))
    return JSONResponse(result, headers={"Cache-Control": "no-store"})


@app.post("/billing/portal")
async def stripe_portal(request: Request):
    user = await billing_form(request)
    url = await billing_call(BILLING.portal, user["sub"])
    return RedirectResponse(url, status_code=303)


@app.post("/billing/webhook", include_in_schema=False)
async def stripe_webhook(request: Request):
    if BILLING is None:
        raise HTTPException(404)
    payload = bytearray()
    async for chunk in request.stream():
        if len(payload) + len(chunk) > 512 * 1024:
            raise HTTPException(413, "Webhook payload too large")
        payload.extend(chunk)
    from stripe import SignatureVerificationError

    try:
        customer = BILLING.webhook_customer(bytes(payload), request.headers.get("stripe-signature"))
    except (SignatureVerificationError, ValueError, KeyError):
        raise HTTPException(400, "Invalid Stripe event") from None
    if customer:
        await billing_call(BILLING.refresh, customer)
    return Response(status_code=204)


@app.get("/devices")
async def devices(request: Request):
    user = session(request)
    if not user:
        return RedirectResponse("/auth/google/start?next=%2Fdevices")
    registry = device_registry()
    email = html.escape(user.get("email", ""), quote=True)
    csrf = html.escape(user["csrf"], quote=True)
    items = registry.list_owned(user["sub"])
    connected_device = (
        ACTIVE_DEVICE_IDS.get(user["sub"]) if user["sub"] in ACTIVE_SOCKETS else None
    )
    device_forms = []
    revoked_forms = []
    for item in items:
        name = html.escape(item["label"], quote=True)
        identity = html.escape(item["id"], quote=True)
        if item["revoked_at"] is not None:
            status, status_class = "Revoked", "revoked"
        elif item["id"] == connected_device:
            status, status_class = "Connected", "connected"
        else:
            status, status_class = (("Offline · open the Windows app", "offline")
                                    if item["last_seen_at"] is not None else ("Waiting for your PC", "waiting"))
        seen_at = item["last_seen_at"]
        last_seen = (datetime.fromtimestamp(seen_at, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
                     if seen_at is not None else "Not yet connected")
        actions = "" if item["revoked_at"] is not None else (
            '<div class="device-actions"><form class="inline-form" action="/devices/rename" method="post">'
            '<input type="hidden" name="csrf" value="' + csrf + '">'
            '<input type="hidden" name="device_id" value="' + identity + '">'
            '<label>Computer name <input name="label" maxlength="80" required value="' + name + '"></label>'
            '<button class="secondary" type="submit">Save name</button></form>'
            '<form action="/devices/revoke" method="post" data-confirm="Revoke ' + name + '? This disconnects the computer and it must be paired again before use.">'
            '<input type="hidden" name="csrf" value="' + csrf + '">'
            '<input type="hidden" name="device_id" value="' + identity + '">'
            '<button class="danger" type="submit">Disconnect PC</button></form></div>')
        cards = revoked_forms if item["revoked_at"] is not None else device_forms
        cards.append(
            '<article class="device-card"><div class="device-card-head"><div><h3>' + name + '</h3>'
            '<span class="status ' + status_class + '">' + status + '</span></div>'
            '<p>Last connected: ' + last_seen + '</p></div>' + actions + '</article>')
    checkout_head = ""
    output = '<span class="eyebrow">Your account</span><h1>Paired Computers</h1>'
    output += '<div class="account-bar"><span>Signed in as <strong>' + email + '</strong></span>'
    output += '<a class="button secondary" href="/devices">Refresh status</a></div>'
    if SERVER_NAME == "flicker-link-pro-staging":
        subject = html.escape(user["sub"])
        output += ('<details class="panel"><summary>Staging account details</summary>'
                   f'<p>Account ID for owner access testing: <code>{subject}</code></p></details>')
    account_header = output
    output = ""
    if FREE_CALL_ALLOWANCE:
        usage = await asyncio.to_thread(account_usage, user["sub"])
        if usage is None:
            output += '<section class="usage-card"><h2>Tool usage</h2><p>Your first 30-day usage period starts when your computer connects.</p></section>'
        elif usage.get("owner"):
            output += '<section class="usage-card"><h2>Tool usage</h2><p class="usage-value">Owner · Unlimited</p><p>Your owner access is free.</p></section>'
        elif usage["unlimited"]:
            output += '<section class="usage-card"><h2>Tool usage</h2><p class="usage-value">Unlimited tool calls</p><p>Your membership is active.</p></section>'
        else:
            percent = min(100, round(100 * usage["used"] / max(usage["allowance"], 1)))
            output += (f'<section class="usage-card"><h2>Tool usage</h2><p class="usage-value">{usage["used"]:,} <span style="font-size:16px;color:var(--muted);font-weight:400">of {usage["allowance"]:,} calls</span></p>'
                       f'<div class="meter" role="meter" aria-label="Tool calls used" aria-valuemin="0" aria-valuemax="{usage["allowance"]}" aria-valuenow="{usage["used"]}"><span style="width:{percent}%"></span></div>'
                       f'<p>Resets {html.escape(reset_date(usage))}.</p></section>')
        if BILLING is not None and usage is not None:
            if request.query_params.get("billing") == "complete" and not usage["unlimited"]:
                output += '<div class="alert" role="status"><strong>Payment confirmation in progress</strong><p>Refresh this page in a moment to check your plan.</p></div>'
            if CHECKOUT_AVAILABLE and not usage["unlimited"]:
                checkout_head = '<script defer src="https://js.stripe.com/dahlia/stripe.js"></script>'
                checkout_key = html.escape(STRIPE_PUBLISHABLE_KEY, quote=True)
                output += ('<section class="usage-card"><h2>Unlimited membership</h2>'
                           f'<p>{RECURRING_BILLING_NOTICE}</p>'
                           '<form id="start-checkout" action="/billing/checkout" method="post" '
                           f'data-stripe-key="{checkout_key}">'
                           f'<input type="hidden" name="csrf" value="{csrf}">'
                           '<button type="submit">Open checkout</button></form>'
                           '<p id="checkout-status" role="status"></p>'
                           '<div id="checkout-form"></div></section>' + EMBEDDED_CHECKOUT_SCRIPT)
            if usage["has_billing"]:
                output += ('<form class="usage-card" action="/billing/portal" method="post">'
                           f'<input type="hidden" name="csrf" value="{csrf}">'
                           '<button class="secondary" type="submit">Manage billing or cancel</button></form>')
    billing_section = output
    output = account_header
    output += '<section class="section" aria-labelledby="computers-heading"><div class="section-intro"><h2 id="computers-heading">Your computer</h2>'
    output += '<p>Open Flicker Link Pro on Windows, then refresh this page to check its connection.</p></div>'
    if device_forms:
        output += '<div class="card-list">' + ''.join(device_forms) + '</div>'
    else:
        output += '<div class="empty"><h3>No computer paired yet</h3><p>Create a pairing token, then enter it in the Windows companion.</p></div>'
    output += ('<section class="panel" style="margin-top:20px"><h3>Pair a Windows computer</h3>'
               '<form class="inline-form" action="/devices/pair" method="post">'
               '<input type="hidden" name="csrf" value="' + csrf + '">'
               '<label>Computer name <input name="label" maxlength="80" value="Windows computer" required></label> '
               '<button type="submit">Create pairing token</button></form></section>'
               '<p style="margin-top:18px"><a href="/support">Get connection help</a></p>')
    if revoked_forms:
        output += ('<details class="panel"><summary>Previously paired computers</summary>'
                   '<div class="card-list">' + ''.join(revoked_forms) + '</div></details>')
    output += '</section>' + billing_section
    content = output + '''<script>
document.querySelectorAll('form[data-confirm]').forEach((form)=>form.addEventListener('submit',(event)=>{
  if(!window.confirm(form.dataset.confirm)) event.preventDefault();
}));
</script>'''
    return HTMLResponse(page_shell("Paired Computers", content, signed_in=True) .replace(
        '</head>', checkout_head + '</head>'), headers={"Cache-Control": "no-store"})


EMBEDDED_CHECKOUT_SCRIPT = """
<script>
(() => {
    const start = document.querySelector('#start-checkout');
    const button = start.querySelector('button');
    const status = document.querySelector('#checkout-status');
    const appearance = {
        theme: 'night',
        labels: 'floating',
        inputs: 'spaced',
        variables: {
            borderRadius: '4px',
            colorBackground: '#ffffff',
            colorDanger: '#df1b41',
            colorPrimary: '#0570de',
            colorSuccess: '#00c853',
            colorText: '#30313d',
            fontFamily: 'default',
            fontSizeBase: '16px',
            spacingUnit: '4px'
        }
    };

    start.addEventListener('submit', async (event) => {
        event.preventDefault();
        if (button.disabled) return;
        button.disabled = true;
        status.textContent = 'Loading checkout…';
        let failureMessage = 'Checkout could not load. Please try again.';
        let paymentForm;
        try {
            const stripe = Stripe(start.dataset.stripeKey);
            const response = await fetch(start.action, {method: 'POST', body: new FormData(start)});
            const result = await response.json();
            if (!response.ok) {
                if (typeof result.detail === 'string') failureMessage = result.detail;
                throw new Error();
            }
            if (result.portal_url) {
                window.location.assign(result.portal_url);
                return;
            }
            if (!result.client_secret) throw new Error();
            const checkout = stripe.initCheckoutFormSdk({clientSecret: result.client_secret, appearance});
            paymentForm = checkout.createForm({layout: 'expanded'});
            paymentForm.mount('#checkout-form');
            const loaded = await checkout.loadActions();
            if (loaded.type !== 'success') throw new Error();
            paymentForm.on('confirm', async (confirmEvent) => {
                status.textContent = '';
                try {
                    await loaded.actions.confirm({formConfirmEvent: confirmEvent});
                } catch {
                    status.textContent = 'Payment could not be confirmed. Please try again.';
                }
            });
            start.hidden = true;
            status.textContent = '';
        } catch {
            paymentForm?.destroy?.();
            document.querySelector('#checkout-form').replaceChildren();
            status.textContent = failureMessage;
            button.disabled = false;
        }
    });
})();
</script>
"""

@app.get("/devices/pair/status/{device_id}")
async def pairing_status(request: Request, device_id: str):
    user = session(request)
    if not user:
        raise HTTPException(401, "Sign in first")
    owner = user["sub"]
    items = await asyncio.to_thread(lambda: device_registry().list_owned(owner))
    if not any(item["id"] == device_id and item["revoked_at"] is None for item in items):
        raise HTTPException(404, "Pairing unavailable")
    connected = owner in ACTIVE_SOCKETS and ACTIVE_DEVICE_IDS.get(owner) == device_id
    return JSONResponse({"connected": connected}, headers={"Cache-Control": "no-store"})


@app.post("/devices/pair")
async def pair(request: Request):
    check_origin(request)
    user = session(request)
    if not user:
        raise HTTPException(401, "Sign in first")
    form = await request.form()
    if not secrets.compare_digest(str(form.get("csrf", "")), user["csrf"]):
        raise HTTPException(403, "Invalid CSRF token")
    try:
        created = device_registry().issue(user["sub"], str(form.get("label", "Windows computer")))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    content = (
        '<span class="eyebrow">Device pairing</span><h1>Finish on your Windows PC</h1>'
        '<p>Open Flicker Link Pro on Windows, paste this token into the companion, then press Enter. '
        'This token grants access to your computer. Do not share it or include it in a support request.</p>'
        '<label for="pair-code">Device pairing token</label>'
        '<input class="token" id="pair-code" readonly value="' + html.escape(created["token"], quote=True) + '">'
        '<button class="secondary" id="copy-pair-code" type="button" hidden>Copy pairing token</button>'
        '<p id="copy-result" role="status"></p>'
        '<script src="/assets/pairing.js" defer></script>'
        '<p>Keep this token private.</p>'
        '<div class="panel"><strong>Connection status</strong>'
        '<p id="pairing-status" role="status" data-device-id="' + html.escape(created["id"], quote=True) + '">'
        'Waiting for your Windows companion to connect.</p></div>'
        '<div class="actions"><a class="button" href="/devices">Back to Paired Computers</a>'
        '<a class="button secondary" href="/support">Get help</a></div>'
    )
    return HTMLResponse(page_shell("Device pairing", content, signed_in=True, reading=True),
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})

@app.post("/devices/rename")
async def rename_device(request: Request):
    check_origin(request)
    user = session(request)
    if not user:
        raise HTTPException(401, "Sign in first")
    form = await request.form()
    if not secrets.compare_digest(str(form.get("csrf", "")), user["csrf"]):
        raise HTTPException(403, "Invalid CSRF token")
    label = str(form.get("label", "")).strip()
    if not label or len(label) > 80 or not label.isprintable():
        raise HTTPException(400, "Enter a computer name between 1 and 80 characters")
    device_id = str(form.get("device_id", ""))
    if not await asyncio.to_thread(lambda: device_registry().rename_owned(user["sub"], device_id, label)):
        raise HTTPException(404, "Device not found or already revoked")
    return RedirectResponse("/devices", status_code=303)


@app.post("/devices/revoke")
async def revoke_device(request: Request):
    check_origin(request)
    user = session(request)
    if not user:
        raise HTTPException(401, "Sign in first")
    form = await request.form()
    if not secrets.compare_digest(str(form.get("csrf", "")), user["csrf"]):
        raise HTTPException(403, "Invalid CSRF token")
    device_id = str(form.get("device_id", ""))
    if not device_registry().revoke_owned(user["sub"], device_id):
        raise HTTPException(404, "Device not found or already revoked")
    await disconnect_device(user["sub"], device_id)
    return RedirectResponse("/devices", status_code=303)

@app.post("/devices/revoke-current")
async def revoke_current(request: Request):
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(401, "Missing device authorization")
    token = header[7:]
    registry = device_registry()
    device = registry.authenticate(token)
    if device is None:
        raise HTTPException(401, "Device authorization revoked or invalid")
    registry.revoke_credential(token)
    await disconnect_device(device["sub"], device["id"])
    return Response(status_code=204, headers={"Cache-Control": "no-store"})

@app.get("/devices/current")
async def current_device(request: Request):
    """Read-only pairing check so the desktop can distinguish revocation from outages."""
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(401, "Missing device authorization")
    device = device_registry().authenticate(header[7:])
    if device is None:
        raise HTTPException(401, "Device authorization revoked or invalid")
    return JSONResponse(
        {"id": device["id"], "label": device["label"]},
        headers={"Cache-Control": "no-store"},
    )

@app.get("/auth/logout")
async def logout():
    r = RedirectResponse("/")
    r.delete_cookie("flp_session", path="/")
    return r

@app.get("/oauth/authorize")
async def authorize(request: Request):
    data = auth_request(dict(request.query_params))
    user = session(request)
    if not user:
        target = str(request.url.path) + "?" + str(request.url.query)
        return RedirectResponse("/auth/google/start?" + urlencode({"next": target}))
    consent = sign("consent", user["sub"], BASE_URL + "/consent", 600,
                   client_hash=digest(data["client_id"]), redirect_uri=data["redirect_uri"],
                   challenge=data["challenge"], resource=data["resource"],
                   state=data["state"], scope=data["scope"])
    client_name = html.escape(data["client_name"], quote=True)
    target_host = html.escape(urlsplit(data["redirect_uri"]).netloc, quote=True)
    content = ('<span class="eyebrow">Secure connection</span><h1>Connect Flicker Link Pro</h1>'
        '<p><strong>' + client_name + '</strong> is requesting access to the Flicker Link Pro tools for your paired computer.</p>'
        '<section class="panel"><h2>What this allows</h2><p>ChatGPT can send your requested actions to your paired Windows companion while it is connected. Depending on the tool, actions may read or change files, use apps, run commands, or access system information.</p>'
        '<p>Only continue if you started this connection in ChatGPT.</p><p>Redirect destination: <strong>' + target_host + '</strong></p></section>'
        '<form class="actions" method="post" action="/oauth/approve"><input type="hidden" name="consent" value="' +
        html.escape(consent, quote=True) + '"><input type="hidden" name="csrf" value="' +
        html.escape(user["csrf"], quote=True) + '">'
        '<button type="submit" name="decision" value="allow">Allow computer access</button> '
        '<button class="secondary" type="submit" name="decision" value="deny">Deny</button></form>'
        '<p><a href="/support">Review connection help</a></p>')
    return HTMLResponse(page_shell("Connect Flicker Link Pro", content, signed_in=True, reading=True))

def oauth_callback(redirect_uri, params):
    separator = "&" if urlsplit(redirect_uri).query else "?"
    # A form submission must become a GET at the registered client callback.
    return RedirectResponse(redirect_uri + separator + urlencode(params), status_code=303)


@app.post("/oauth/approve")
async def approve(request: Request):
    check_origin(request)
    user = session(request)
    if not user:
        raise HTTPException(401, "Sign in first")
    form = await request.form()
    if not secrets.compare_digest(str(form.get("csrf", "")), user["csrf"]):
        raise HTTPException(403, "Invalid CSRF token")
    approved = verify(str(form.get("consent", "")), "consent", BASE_URL + "/consent")
    if approved["sub"] != user["sub"]:
        raise HTTPException(403, "Account does not match approval")
    redirect_uri = approved["redirect_uri"]
    if form.get("decision") != "allow":
        return oauth_callback(redirect_uri, {"error": "access_denied", "state": approved["state"]})
    code = sign("auth_code", user["sub"], BASE_URL + "/authcode", 90,
                client_hash=approved["client_hash"], redirect_uri=redirect_uri,
                challenge=approved["challenge"], resource=RESOURCE, scope=SCOPES)
    return oauth_callback(redirect_uri, {"code": code, "state": approved["state"]})

def consume_auth_code(jti: str, expires_at: int) -> None:
    """Single use, bounded memory. Never clear live redemptions under load."""
    if jti in REDEEMED_CODES:
        raise HTTPException(400, "Authorization code has already been used")
    if len(REDEEMED_CODES) >= 10000:
        now = int(time.time())
        for used_id, expiry in list(REDEEMED_CODES.items()):
            if expiry <= now:
                del REDEEMED_CODES[used_id]
        if len(REDEEMED_CODES) >= 10000:
            raise HTTPException(503, "Authorization server temporarily busy")
    REDEEMED_CODES[jti] = int(expires_at)


@app.post("/oauth/token")
async def token_endpoint(request: Request):
    form = await request.form()
    grant = str(form.get("grant_type", ""))
    client_id = str(form.get("client_id", ""))
    oauth_client(client_id)
    if form.get("resource") != RESOURCE:
        raise HTTPException(400, "Invalid resource indicator")
    if grant == "authorization_code":
        code = verify(str(form.get("code", "")), "auth_code", BASE_URL + "/authcode")
        verifier = str(form.get("code_verifier", ""))
        if (len(verifier) < 43 or len(verifier) > 128 or
            not secrets.compare_digest(digest(verifier), code["challenge"]) or
            code["client_hash"] != digest(client_id) or
            code["redirect_uri"] != str(form.get("redirect_uri", "")) or
            code["resource"] != RESOURCE):
            raise HTTPException(400, "Invalid authorization code or PKCE proof")
        consume_auth_code(code["jti"], code["exp"])
        sub = code["sub"]
    else:
        raise HTTPException(400, "Unsupported grant type")
    access = sign("access", sub, RESOURCE, 3600, scope=SCOPES)
    return {"access_token": access,
            "token_type": "Bearer", "expires_in": 3600, "scope": SCOPES}

@app.websocket("/ws/device")
async def device_websocket(websocket: WebSocket):
    header = websocket.headers.get("authorization", "")
    if not header.startswith("Bearer "):
        await websocket.close(code=1008)
        return
    try:
        registry = device_registry()
        device = await asyncio.to_thread(registry.authenticate, header[7:])
        if device is None:
            await websocket.close(code=1008)
            return
        await asyncio.to_thread(registry.touch, device["id"])
    except Exception:
        await websocket.close(code=1013)
        return
    sub = device["sub"]
    if sub in ACTIVE_SOCKETS:
        try:
            await ACTIVE_SOCKETS[sub].close(code=1000)
        except Exception:
            pass
    await websocket.accept()
    ACTIVE_SOCKETS[sub] = websocket
    ACTIVE_DEVICE_IDS[sub] = device["id"]
    presence_id = None
    presence_confirmed = False
    try:
        while True:
            try:
                payload = await asyncio.wait_for(websocket.receive_text(), timeout=DEVICE_HEARTBEAT_INTERVAL)
            except asyncio.TimeoutError:
                # A JSON-RPC ping checks the agent itself and elicits an
                # application message from current Windows installers.
                presence_id = "presence-" + uuid.uuid4().hex
                await websocket.send_json({"jsonrpc": "2.0", "id": presence_id, "method": "ping"})
                continue
            message = json.loads(payload)
            if not isinstance(message, dict):
                continue
            call_id = message.get("id")
            if presence_id is not None and call_id == presence_id:
                presence_id = None
                if not presence_confirmed and message.get("result") == {}:
                    logging.getLogger("uvicorn.error").info("Device connection heartbeat confirmed")
                    presence_confirmed = True
                continue
            pending = PENDING_CALLS.get(call_id)
            if pending and pending[0] == sub and not pending[1].done():
                pending[1].set_result(message.get("result"))
    except (WebSocketDisconnect, ValueError, json.JSONDecodeError):
        pass
    finally:
        if ACTIVE_SOCKETS.get(sub) is websocket:
            ACTIVE_SOCKETS.pop(sub, None)
            ACTIVE_DEVICE_IDS.pop(sub, None)

@app.post("/mcp")
async def mcp(request: Request):
    authorization = request.headers.get("authorization", "")
    if not authorization.startswith("Bearer "):
        return unauthorized()
    try:
        account = verify(authorization[7:], "access", RESOURCE)
        if SCOPES not in account.get("scope", "").split():
            return unauthorized()
    except HTTPException:
        return unauthorized()
    body = await request.body()
    if len(body) > 1024 * 1024:
        raise HTTPException(413, "MCP request too large")
    try:
        data = json.loads(body)
        if not isinstance(data, dict) or data.get("jsonrpc") != "2.0":
            raise ValueError()
    except (ValueError, TypeError):
        raise HTTPException(400, "Invalid JSON-RPC request")
    method = data.get("method")
    req_id = data.get("id")
    if method == "notifications/initialized":
        return Response(status_code=202)
    if method == "initialize":
        versions = ("2025-11-25", "2025-06-18", "2025-03-26")
        desired = data.get("params", {}).get("protocolVersion")
        version = desired if desired in versions else "2025-03-26"
        return {"jsonrpc": "2.0", "id": req_id, "result": {
            "protocolVersion": version, "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": "2.2.0"}}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}
    owner = account["sub"]
    ws = ACTIVE_SOCKETS.get(owner)
    active_id = ACTIVE_DEVICE_IDS.get(owner)
    params = data.get("params")
    tool_name = params.get("name") if isinstance(params, dict) else None
    if method == "tools/call" and isinstance(params, dict) and params.get("name") == "list_devices":
        devices = [
            {"id": device["id"], "label": device["label"],
             "online": ws is not None and device["id"] == active_id,
             "last_seen_at": device["last_seen_at"]}
            for device in await asyncio.to_thread(lambda: device_registry().list_owned(owner))
            if device["revoked_at"] is None
        ]
        return {"jsonrpc": "2.0", "id": req_id, "result": {
            "content": [{"type": "text", "text": json.dumps({"devices": devices})}],
            "structuredContent": {"devices": devices},
        }}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": CATALOG}}
    if method not in ("tools/list", "tools/call"):
        return {"jsonrpc": "2.0", "id": req_id,
                "error": {"code": -32601, "message": "Method not found"}}
    if ws is None or not active_id or not await asyncio.to_thread(
        lambda: device_registry().is_active(active_id)
    ):
        return {"jsonrpc": "2.0", "id": req_id,
                "error": {"code": -32000, "message": "Desktop agent offline. Sign in and pair it at /devices."}}
    if not isinstance(tool_name, str) or tool_name not in CATALOG_NAMES:
        return {"jsonrpc": "2.0", "id": req_id,
                "error": {"code": -32602, "message": "Unknown tool"}}
    call_id = uuid.uuid4().hex
    if len(PENDING_CALLS) >= 100:
        return {"jsonrpc": "2.0", "id": req_id,
                "error": {"code": -32000, "message": "Relay is busy"}}
    future = asyncio.get_running_loop().create_future()
    PENDING_CALLS[call_id] = (account["sub"], future)
    try:
        if FREE_CALL_ALLOWANCE and tool_name not in UNMETERED_TOOLS:
            usage = await asyncio.to_thread(account_usage, owner, consume=True)
            if usage is None:
                raise HTTPException(503, "Account usage is temporarily unavailable")
            if not usage["allowed"]:
                message = f"Your free tool call allowance is used up. It resets {reset_date(usage)}."
                return {"jsonrpc": "2.0", "id": req_id, "result": {
                    "isError": True,
                    "content": [{"type": "text", "text": message}],
                }}
        if ACTIVE_SOCKETS.get(owner) is not ws or ACTIVE_DEVICE_IDS.get(owner) != active_id:
            return {"jsonrpc": "2.0", "id": req_id,
                    "error": {"code": -32000, "message": "Desktop agent connection changed. Try again."}}
        forwarded = dict(data)
        forwarded["id"] = call_id
        # Leave five seconds of margin before the MCP request's 45-second wait
        # expires, so queued desktop prompts cannot execute stale calls.
        forwarded["_flicker_deadline_unix"] = time.time() + 40.0
        await ws.send_text(json.dumps(forwarded))
        result = await asyncio.wait_for(future, timeout=45.0)
        if (isinstance(params, dict) and params.get("name") == "who_am_i"
                and isinstance(result, dict) and isinstance(result.get("structuredContent"), dict)
                and not result.get("isError")):
            devices = await asyncio.to_thread(lambda: device_registry().list_owned(owner))
            label = next((d["label"] for d in devices
                          if d["id"] == active_id and d["revoked_at"] is None), None)
            if label is not None:
                identity = {**result["structuredContent"], "device_name": label}
                result = {**result, "structuredContent": identity,
                          "content": [{"type": "text", "text": json.dumps(identity)}]}
        return {"jsonrpc": "2.0", "id": req_id, "result": result}
    except (asyncio.TimeoutError, WebSocketDisconnect, RuntimeError):
        return {"jsonrpc": "2.0", "id": req_id,
                "error": {"code": -32000, "message": "Desktop agent did not respond"}}
    finally:
        PENDING_CALLS.pop(call_id, None)
