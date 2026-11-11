import os
import uuid
import json
import asyncio
from typing import Dict
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, Form, Query, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from jose import jwt

APP_SECRET = os.getenv("FLICKER_SECRET", "flicker-link-pro-secret-key-change-me")
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")

app = FastAPI(title="Flicker Link Pro Cloud Relay")

# In-memory stores
DEVICES: Dict[str, dict] = {}             # device_token -> {"user_id": ..., "name": ...}
ACTIVE_SOCKETS: Dict[str, WebSocket] = {} # user_id -> WebSocket
PENDING_AUTH_CODES: Dict[str, str] = {}   # auth_code -> user_id
PENDING_CALLS: Dict[str, asyncio.Future] = {}

def create_user_token(user_id: str) -> str:
    return jwt.encode({"sub": user_id}, APP_SECRET, algorithm="HS256")

def decode_user_token(token: str) -> str:
    payload = jwt.decode(token, APP_SECRET, algorithms=["HS256"])
    return payload["sub"]

@app.get("/", response_class=HTMLResponse)
async def home():
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
      <title>Flicker Link Pro</title>
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background: #0f172a; color: #f8fafc; display: flex; justify-content: center; align-items: center; min-height: 100vh; margin: 0; }}
        .card {{ background: #1e293b; padding: 32px; border-radius: 12px; max-width: 440px; width: 100%; box-shadow: 0 10px 25px rgba(0,0,0,0.5); }}
        h2 {{ margin-top: 0; color: #38bdf8; font-size: 24px; }}
        p {{ color: #94a3b8; line-height: 1.5; }}
        input, button {{ width: 100%; padding: 12px; margin: 8px 0; border-radius: 6px; box-sizing: border-box; font-size: 15px; }}
        input {{ background: #334155; border: 1px solid #475569; color: white; }}
        button {{ background: #0284c7; border: none; color: white; font-weight: 600; cursor: pointer; }}
        button:hover {{ background: #0369a1; }}
      </style>
    </head>
    <body>
      <div class="card">
        <h2>Flicker Link Pro</h2>
        <p>Sign in to pair your computer and connect ChatGPT remote control:</p>
        <form action="/login" method="post">
          <input type="email" name="email" placeholder="name@example.com" required />
          <button type="submit">Sign In / Register</button>
        </form>
      </div>
    </body>
    </html>
    """

@app.post("/login", response_class=HTMLResponse)
async def login(email: str = Form(...)):
    user_id = email.strip().lower()
    device_token = f"flk_{uuid.uuid4().hex[:16]}"
    DEVICES[device_token] = {"user_id": user_id, "name": "Primary Computer"}
    ws_url = BASE_URL.replace("https://", "wss://").replace("http://", "ws://")
    
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
      <title>Flicker Link Pro - Connected</title>
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background: #0f172a; color: #f8fafc; padding: 40px 20px; }}
        .box {{ max-width: 600px; margin: 0 auto; background: #1e293b; padding: 32px; border-radius: 12px; }}
        h2 {{ color: #38bdf8; }}
        code {{ background: #0f172a; color: #38bdf8; padding: 12px; display: block; border-radius: 6px; word-break: break-all; margin: 10px 0; font-family: monospace; font-size: 14px; border: 1px solid #334155; }}
        .badge {{ background: #059669; color: white; padding: 4px 10px; border-radius: 20px; font-size: 12px; font-weight: 600; display: inline-block; }}
        a {{ color: #38bdf8; text-decoration: none; }}
      </style>
    </head>
    <body>
      <div class="box">
        <span class="badge">Account Active</span>
        <h2>Welcome, {user_id}</h2>
        <p><strong>Step 1: Start the Desktop Agent on your Laptop</strong></p>
        <p style="color:#94a3b8;">Run this command in your desktop agent folder:</p>
        <code>python flicker_relay_agent.py --server {ws_url} --token {device_token}</code>
        <p><strong>Step 2: Connect ChatGPT</strong></p>
        <p style="color:#94a3b8;">In ChatGPT Settings &gt; Apps / Connectors, add your MCP endpoint:</p>
        <code>{BASE_URL}/mcp</code>
        <p style="margin-top:24px;"><a href="/">&larr; Log out / New Device</a></p>
      </div>
    </body>
    </html>
    """

@app.get("/oauth/authorize")
async def oauth_authorize(redirect_uri: str, state: str, client_id: str = ""):
    code = f"code_{uuid.uuid4().hex[:16]}"
    return HTMLResponse(f"""
    <!DOCTYPE html>
    <html>
    <head>
      <title>Authorize ChatGPT</title>
      <style>
        body {{ font-family: sans-serif; background: #0f172a; color: white; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }}
        .card {{ background: #1e293b; padding: 32px; border-radius: 10px; max-width: 400px; text-align: center; }}
        button, input {{ width: 100%; padding: 10px; margin: 8px 0; border-radius: 6px; box-sizing: border-box; }}
        input {{ background: #334155; border: 1px solid #475569; color: white; }}
        button {{ background: #10a37f; color: white; border: none; font-weight: bold; cursor: pointer; }}
      </style>
    </head>
    <body>
      <div class="card">
        <h3>Connect Flicker Link Pro to ChatGPT</h3>
        <p style="color:#94a3b8;font-size:14px;">Enter your registered account email to authorize remote laptop commands:</p>
        <form action="/oauth/approve" method="post">
          <input type="hidden" name="redirect_uri" value="{redirect_uri}" />
          <input type="hidden" name="state" value="{state}" />
          <input type="hidden" name="code" value="{code}" />
          <input type="email" name="email" placeholder="Your account email" required />
          <button type="submit">Authorize Connection</button>
        </form>
      </div>
    </body>
    </html>
    """)

@app.post("/oauth/approve")
async def oauth_approve(redirect_uri: str = Form(...), state: str = Form(...), code: str = Form(...), email: str = Form(...)):
    user_id = email.strip().lower()
    PENDING_AUTH_CODES[code] = user_id
    return RedirectResponse(f"{redirect_uri}?code={code}&state={state}", status_code=302)

@app.post("/oauth/token")
async def oauth_token(request: Request):
    form = await request.form()
    code = form.get("code")
    if not code or code not in PENDING_AUTH_CODES:
        raise HTTPException(status_code=400, detail="Invalid or expired authorization code")
    user_id = PENDING_AUTH_CODES.pop(code)
    token = create_user_token(user_id)
    return JSONResponse({
        "access_token": token,
        "token_type": "bearer",
        "expires_in": 2592000
    })

@app.websocket("/ws/device")
async def device_websocket(websocket: WebSocket, token: str = Query(...)):
    if token not in DEVICES:
        await websocket.close(code=1008)
        return
    user_id = DEVICES[token]["user_id"]
    await websocket.accept()
    ACTIVE_SOCKETS[user_id] = websocket
    try:
        while True:
            msg = await websocket.receive_text()
            data = json.loads(msg)
            req_id = data.get("id")
            if req_id and req_id in PENDING_CALLS:
                PENDING_CALLS[req_id].set_result(data.get("result"))
    except WebSocketDisconnect:
        ACTIVE_SOCKETS.pop(user_id, None)

@app.post("/mcp")
async def mcp_endpoint(request: Request):
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    token = auth_header[7:].strip()
    try:
        user_id = decode_user_token(token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid Token")

    payload = await request.json()
    method = payload.get("method")
    req_id = payload.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "flicker-link-pro", "version": "2.0.0"}
            }
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    ws = ACTIVE_SOCKETS.get(user_id)
    if not ws:
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": []}}
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32000, "message": "Your computer is currently offline. Start flicker_relay_agent.py on your machine."}
        }

    fut = asyncio.get_event_loop().create_future()
    PENDING_CALLS[req_id] = fut
    await ws.send_text(json.dumps(payload))
    try:
        result = await asyncio.wait_for(fut, timeout=65.0)
        return {"jsonrpc": "2.0", "id": req_id, "result": result}
    except asyncio.TimeoutError:
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32000, "message": "Command timed out on laptop."}}
    finally:
        PENDING_CALLS.pop(req_id, None)
