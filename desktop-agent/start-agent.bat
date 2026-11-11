@echo off
setlocal
title FLICKER LINK PRO - DESKTOP RELAY

set /p SERVER="Enter your Cloud Relay URL (e.g. wss://your-app.onrender.com): "
set /p TOKEN="Enter your Device Token from the web dashboard: "

echo.
echo Starting Flicker Link Pro Relay Agent...
python flicker_relay_agent.py --server %SERVER% --token %TOKEN%
pause
