# Flicker Link Pro 2 — staging desktop shortcut (separate from ngrok)

This staged installation is ONLY at:
%LOCALAPPDATA%\FlickerLinkPro2

Its shortcut is:
%USERPROFILE%\OneDrive\Desktop\Flicker Link Pro 2.lnk

The user's existing working ngrok installation is separate:
%LOCALAPPDATA%\FlickerLinkProTool
No files, shortcuts, processes, or credentials in that folder are changed
by this staging installer. The production Render service remains unchanged.

The desktop shortcut launches Start-FlickerLinkPro2.cmd, which runs:
flicker_relay_agent.py --profile staging

The staging profile connects only to:
https://flicker-link-pro-2-staging.onrender.com

The staging device token persists in Windows Credential Manager under
FlickerLinkPro2/StagingDevicePairing.
The default profile has a different credential target. Staging sign-out
revokes and deletes only the staging pairing.

The prior FLP2 agent, shortcut launcher and signout script are backed
up under backup-before-staging-<timestamp> folders within FlickerLinkPro2.
Existing FLP2 config.json is preserved but NOT read by the staging agent.

Pairing instructions:
1. Launch the "Flicker Link Pro 2" shortcut on the Windows desktop.
2. Sign in with Google in the browser that the launcher opens.
3. On Paired Computers, select "Pair a new computer" if no credential
   from a previous pairing remains available.
4. Copy ONLY the token starting with flk2_ shown after "--token".
5. Paste directly into the hidden-input prompt in the Windows console.
   Never paste the token into a chat, screenshot, or issue tracker.
6. The console should print "[CONNECTED] Saved pairing accepted".
7. Relaunching should reuse the credential without a new sign-in.
8. Revoke unused authorizations from the staging web dashboard.

The WebSocket uses a direct (no system proxy) WSS connection for staging
only, because a direct handshake was verified and the default proxy path
timed out on this Windows machine. Other profiles are unchanged.

To restore the prior FLP2 launcher and agent, copy files from one
backup-before-staging folder back into FlickerLinkPro2. Do not copy
anything into FlickerLinkProTool.

Verification status:
- Staging web /healthz HTTP 200 and Google login dashboard: verified.
- Staging WebSocket invalid credential denied: verified.
- 66 tool catalog: verified.
- Staging source tests and credential isolation: verified.
- Actual valid token connection and full MCP command delivery:
  PENDING user entering staging credential into FLP2 shortcut window.
