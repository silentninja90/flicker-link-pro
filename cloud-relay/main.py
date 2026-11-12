"""Flicker Link Pro cloud relay: Google OIDC login and PKCE-protected MCP OAuth.

Google confirms identity. This server issues audience-bound OAuth tokens for ChatGPT.
Device pairing is available only in a Google-authenticated browser session.
"""
import asyncio
import base64
import hashlib
import html
import json
import os
import pathlib
import secrets
import time
import uuid
from urllib.parse import urlencode, urlsplit

import httpx
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
import jwt
from jwt import PyJWKClient
from jwt.exceptions import PyJWTError
from device_registry import DeviceRegistry

BASE_URL = os.getenv("BASE_URL", "https://flicker-link-pro.onrender.com").rstrip("/")
RESOURCE = BASE_URL + "/mcp"
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "")
SECRET = os.getenv("FLICKER_SECRET", "")
SCOPES = "laptop:control"
CATALOG = json.loads((pathlib.Path(__file__).parent / "tool_catalog.json").read_text(encoding="utf-8"))
ACTIVE_SOCKETS = {}
ACTIVE_DEVICE_IDS = {}
PENDING_CALLS = {}
REDEEMED_CODES = set()
# Authorization codes are invalidated on every process restart.
PROCESS_CODE_KEY = secrets.token_urlsafe(48)
app = FastAPI(title="Flicker Link Pro Cloud Relay", version="2.2.0")

def device_registry():
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

@app.get("/")
async def home(request: Request):
    user = session(request)
    if user:
        return RedirectResponse("/devices")
    return HTMLResponse('<html><body style="font:18px sans-serif;max-width:580px;margin:70px auto"><h2>Flicker Link Pro</h2><p>Sign in with Google to pair your computer securely.</p><a href="/auth/google/start">Continue with Google</a></body></html>')

@app.get("/devices")
async def devices(request: Request):
    user = session(request)
    if not user:
        return RedirectResponse("/auth/google/start?next=%2Fdevices")
    registry = device_registry()
    email = html.escape(user.get("email", ""), quote=True)
    csrf = html.escape(user["csrf"], quote=True)
    items = registry.list_owned(user["sub"])
    device_forms = []
    for item in items:
        name = html.escape(item["label"], quote=True)
        identity = html.escape(item["id"], quote=True)
        status = "Revoked" if item["revoked_at"] is not None else "Paired"
        actions = "" if item["revoked_at"] is not None else (
            '<form action="/devices/revoke" method="post">'
            '<input type="hidden" name="csrf" value="' + csrf + '">'
            '<input type="hidden" name="device_id" value="' + identity + '">'
            '<button type="submit">Revoke this computer</button></form>')
        device_forms.append('<li><strong>' + name + '</strong> - ' + status + actions + '</li>')
    output = '<html><body style="font:18px sans-serif;max-width:780px;margin:55px auto">'
    output += '<h2>Flicker Link Pro - Paired Computers</h2><p>Signed in as ' + email + '</p>'
    output += '<ul>' + ''.join(device_forms) + '</ul>'
    output += '<p>Devices stay paired until you revoke them or log out from the desktop app.</p>'
    output += ('<form action="/devices/pair" method="post">'
               '<input type="hidden" name="csrf" value="' + csrf + '">'
               '<label>Computer name <input name="label" maxlength="80" value="Windows computer"></label> '
               '<button type="submit">Pair a new computer</button></form>'
               '<p><a href="/auth/logout">Sign out of website</a></p></body></html>')
    return HTMLResponse(output, headers={"Cache-Control": "no-store"})

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
    command = "python flicker_relay_agent.py --server " + BASE_URL + " --token " + created["token"]
    return HTMLResponse(
        '<html><body style="font:16px sans-serif;max-width:900px;margin:50px auto">'
        '<h2>One-time device pairing credential</h2>'
        '<p>Run this on your computer once. The app then saves the pairing in Windows Credential Manager.'
        ' Treat this credential like a password and do not share it.</p>'
        '<pre style="white-space:pre-wrap;overflow-wrap:anywhere;background:#eee;padding:15px">'
        + html.escape(command) +
        '</pre><p><a href="/devices">Back to paired computers</a></p></body></html>',
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"})

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
    return HTMLResponse('<html><body style="font:17px sans-serif;max-width:650px;margin:60px auto">'
        '<h2>Authorize Flicker Link Pro</h2><p>' + client_name + ' requests remote computer control.'
        '</p><p>Redirect destination: <strong>' + target_host + '</strong></p>'
        '<p>Only approve if you initiated this connection in ChatGPT.</p>'
        '<form method="post" action="/oauth/approve"><input type="hidden" name="consent" value="' +
        html.escape(consent, quote=True) + '"><input type="hidden" name="csrf" value="' +
        html.escape(user["csrf"], quote=True) + '">'
        '<button type="submit" name="decision" value="allow">Allow laptop control</button> '
        '<button type="submit" name="decision" value="deny">Deny</button></form></body></html>')

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
        return RedirectResponse(redirect_uri + "?" + urlencode({"error": "access_denied", "state": approved["state"]}))
    code = sign("auth_code", user["sub"], BASE_URL + "/authcode", 90,
                client_hash=approved["client_hash"], redirect_uri=redirect_uri,
                challenge=approved["challenge"], resource=RESOURCE, scope=SCOPES)
    return RedirectResponse(redirect_uri + "?" + urlencode({"code": code, "state": approved["state"]}))

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
        if code["jti"] in REDEEMED_CODES:
            raise HTTPException(400, "Authorization code has already been used")
        REDEEMED_CODES.add(code["jti"])
        if len(REDEEMED_CODES) > 10000:
            REDEEMED_CODES.clear()
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
        device = registry.authenticate(header[7:])
        if device is None:
            await websocket.close(code=1008)
            return
    except HTTPException:
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
    registry.touch(device["id"])
    try:
        while True:
            message = json.loads(await websocket.receive_text())
            call_id = message.get("id")
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
            "serverInfo": {"name": "flicker-link-pro", "version": "2.2.0"}}}
    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}
    ws = ACTIVE_SOCKETS.get(account["sub"])
    active_id = ACTIVE_DEVICE_IDS.get(account["sub"])
    if ws is not None and (not active_id or not device_registry().is_active(active_id)):
        ws = None
    if method == "tools/list" and ws is None:
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": CATALOG}}
    if method not in ("tools/list", "tools/call"):
        return {"jsonrpc": "2.0", "id": req_id,
                "error": {"code": -32601, "message": "Method not found"}}
    if ws is None:
        return {"jsonrpc": "2.0", "id": req_id,
                "error": {"code": -32000, "message": "Desktop agent offline. Sign in and pair it at /devices."}}
    call_id = uuid.uuid4().hex
    if len(PENDING_CALLS) >= 100:
        return {"jsonrpc": "2.0", "id": req_id,
                "error": {"code": -32000, "message": "Relay is busy"}}
    future = asyncio.get_running_loop().create_future()
    PENDING_CALLS[call_id] = (account["sub"], future)
    try:
        forwarded = dict(data)
        forwarded["id"] = call_id
        await ws.send_text(json.dumps(forwarded))
        result = await asyncio.wait_for(future, timeout=45.0)
        return {"jsonrpc": "2.0", "id": req_id, "result": result}
    except (asyncio.TimeoutError, WebSocketDisconnect, RuntimeError):
        return {"jsonrpc": "2.0", "id": req_id,
                "error": {"code": -32000, "message": "Desktop agent did not respond"}}
    finally:
        PENDING_CALLS.pop(call_id, None)
