# Flicker Link Pro

Remote computer control for ChatGPT via Model Context Protocol (MCP) and secure WebSockets.

## Repository Architecture

```text
flicker-link-pro/
├── cloud-relay/        # Central Web portal & OAuth 2.0 MCP relay (Deploy to Render / Railway)
├── desktop-agent/      # Local agent that executes the 66 tools on your laptop
└── chatgpt-plugin/     # ChatGPT plugin bundle (plugin.json, mcp.json, skills, assets)
```

## Quick Start

### 1. Deploy Cloud Relay (`cloud-relay/`)
- Deploy `cloud-relay/` to [Render.com](https://render.com) (Web Service, Python 3).
- Build Command: `pip install -r requirements.txt`
- Start Command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- Set Environment Variable: `BASE_URL=https://your-app.onrender.com`

### 2. Run Desktop Agent (`desktop-agent/`)
- On your laptop, navigate to `desktop-agent/`
- Install dependencies: `pip install -r requirements.txt`
- Visit your Cloud Relay URL (`https://your-app.onrender.com`), log in with your email, and copy your device pairing command:
  ```powershell
  python flicker_relay_agent.py --server wss://your-app.onrender.com --token flk_xxxxxxxx
  ```

### 3. Add to ChatGPT
- In `chatgpt-plugin/mcp.json`, replace `YOUR_DOMAIN` with your deployed cloud domain (`your-app.onrender.com`).
- Add the custom MCP server in ChatGPT Settings using `https://your-app.onrender.com/mcp`.
- Complete the one-click OAuth login to link your ChatGPT account to your laptop.
