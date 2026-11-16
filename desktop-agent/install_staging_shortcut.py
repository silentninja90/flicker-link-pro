"""Install staged Flicker Link Pro 2 agent ONLY into its own separate folder.

Never touches the existing FlickerLinkProTool/ngrok application.
Default mode is dry-run. Explicit --apply creates a local backup first.
"""
import argparse
from datetime import datetime
import os
from pathlib import Path
import shutil

SOURCE = Path(__file__).resolve().parent
DEST = Path(os.environ["LOCALAPPDATA"]).resolve() / "FlickerLinkPro2"
EXPECTED_SHORTCUT_TARGET = DEST / "Start-FlickerLinkPro2.cmd"
SERVER = "https://flicker-link-pro-2-staging.onrender.com"

START = """@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
title Flicker Link Pro 2 - Staging Desktop Agent
if not exist "%~dp0.venv\\Scripts\\python.exe" (
  echo Missing Python environment for Flicker Link Pro 2.
  pause
  exit /b 1
)
"%~dp0.venv\\Scripts\\python.exe" "%~dp0flicker_relay_agent.py" --profile staging
set "FLP_EXIT=%ERRORLEVEL%"
echo.
if not "%FLP_EXIT%"=="0" echo [ERROR] Flicker Link Pro 2 ended with a problem.
echo Flicker Link Pro 2 has stopped. Review any messages above.
echo Press any key to close this window.
pause >nul
exit /b %FLP_EXIT%
"""

SIGNOUT = """@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
title Flicker Link Pro 2 - Staging Sign Out
if not exist "%~dp0.venv\\Scripts\\python.exe" (
  echo Missing Python environment.
  pause
  exit /b 1
)
"%~dp0.venv\\Scripts\\python.exe" "%~dp0flicker_relay_agent.py" --profile staging --logout
if errorlevel 1 (
  echo Staging sign-out failed. Saved credential was retained.
  pause
)
"""

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Make backed-up changes")
    args = parser.parse_args()
    if DEST.name != "FlickerLinkPro2" or not EXPECTED_SHORTCUT_TARGET.is_file():
        raise RuntimeError("Flicker Link Pro 2 launcher not found; refusing install")
    if not (DEST / ".venv" / "Scripts" / "python.exe").exists():
        raise RuntimeError("Flicker Link Pro 2 Python environment missing")
    additions = ["credential_store.py", "sensitive_controls.py"]
    originals = ["flicker_relay_agent.py", "Start-FlickerLinkPro2.cmd", "Sign-Out.cmd"]
    for f in ("flicker_relay_agent.py", *additions):
        if not (SOURCE / f).is_file():
            raise RuntimeError("Source file missing: " + f)
    for f in originals:
        if not (DEST / f).is_file():
            raise RuntimeError("Expected Flicker Link Pro 2 original missing: " + f)
    print("TARGET: FlickerLinkPro2 (staging only)")
    print("STAGING_SERVER:", SERVER)
    print("FILES:", ", ".join(originals + additions))
    print("NGROK_PROJECT: untouched")
    if not args.apply:
        print("DRY_RUN: No files changed")
        return
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = DEST / ("backup-before-staging-" + stamp)
    backup_dir.mkdir(parents=False, exist_ok=False)
    for f in originals:
        shutil.copy2(DEST / f, backup_dir / f)
    for f in additions:
        existing_file = DEST / f
        if existing_file.exists():
            shutil.copy2(existing_file, backup_dir / f)
    shutil.copy2(SOURCE / "flicker_relay_agent.py", DEST / "flicker_relay_agent.py")
    for f in additions:
        shutil.copy2(SOURCE / f, DEST / f)
    (DEST / "Start-FlickerLinkPro2.cmd").write_text(START, encoding="utf-8")
    (DEST / "Sign-Out.cmd").write_text(SIGNOUT, encoding="utf-8")
    print("INSTALLED: Staging agent and independent launcher")
    print("BACKUP_FOLDER:", backup_dir.name)
    print("PRESERVED: config.json and existing ngrok application")
    print("CREDENTIAL_TARGET: FlickerLinkPro2/StagingDevicePairing")

if __name__ == "__main__":
    main()
