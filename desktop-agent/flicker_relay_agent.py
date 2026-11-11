"""Flicker Link Pro - Desktop Relay Agent
Connects your laptop outbound to your Flicker Link Pro cloud relay via WebSockets.
Executes all 66 tools locally using flicker_server.py handlers.
"""
from __future__ import annotations
import argparse
import asyncio
import json
import sys
import os
import pathlib
import websockets

# Import local tool dispatch and catalog
from flicker_server import handle, CATALOG

async def run_relay(server_url: str, token: str):
    ws_endpoint = f"{server_url}/ws/device?token={token}"
    print("=" * 60)
    print(" FLICKER LINK PRO - DESKTOP RELAY AGENT")
    print("=" * 60)
    print(f"Connecting to Cloud Relay: {ws_endpoint}")
    print(f"Loaded {len(CATALOG)} MCP tools.")
    
    while True:
        try:
            async with websockets.connect(ws_endpoint, max_size=15 * 1024 * 1024, ping_interval=20, ping_timeout=20) as ws:
                print("\n[CONNECTED] Laptop is securely linked to your Flicker Link Pro account.")
                print("Ready to receive remote commands from ChatGPT mobile and web.\n")
                
                while True:
                    msg = await ws.recv()
                    req = json.loads(msg)
                    method = req.get("method")
                    req_id = req.get("id")
                    
                    if method == "tools/list":
                        response = {"tools": CATALOG}
                    else:
                        mcp_resp = handle(req)
                        response = mcp_resp.get("result") if mcp_resp else {}
                        if mcp_resp and "error" in mcp_resp:
                            response = {"isError": True, "error": mcp_resp["error"]}
                    
                    await ws.send(json.dumps({
                        "id": req_id,
                        "result": response
                    }))
                    
        except (websockets.exceptions.ConnectionClosed, ConnectionRefusedError, OSError) as e:
            print(f"[DISCONNECTED] Connection lost ({e}). Reconnecting in 5s...")
            await asyncio.sleep(5)
        except Exception as e:
            print(f"[ERROR] Error processing request: {e}")
            await asyncio.sleep(2)

def main():
    parser = argparse.ArgumentParser(description="Flicker Link Pro Desktop Relay Agent")
    parser.add_argument("--server", required=True, help="Relay server URL (e.g., wss://flickerlinkpro.onrender.com)")
    parser.add_argument("--token", required=True, help="Device pairing token from your dashboard")
    args = parser.parse_args()

    # Clean server URL to WebSocket format
    server_url = args.server.rstrip("/")
    if server_url.startswith("https://"):
        server_url = "wss://" + server_url[8:]
    elif server_url.startswith("http://"):
        server_url = "ws://" + server_url[7:]

    try:
        asyncio.run(run_relay(server_url, args.token))
    except KeyboardInterrupt:
        print("\nAgent stopped by user.")

if __name__ == "__main__":
    main()
