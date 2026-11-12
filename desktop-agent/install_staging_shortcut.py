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
if errorlevel 1 (
  echo.
  echo Staging connection failed.
  pause
)
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
    additions = ["credential_store.py"]
    originals = ["flicker_relay_agent.py", "Start-FlickerLinkPro2.cmd", "Sign-Out.cmd"]
    if not (SOURCE / "flicker_relay_agent.py").is_file():
        raise RuntimeError("Source agent missing")
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
    existing_store = DEST / "credential_store.py"
    if existing_store.exists():
        shutil.copy2(existing_store, backup_dir / "credential_store.py")
    shutil.copy2(SOURCE / "flicker_relay_agent.py", DEST / "flicker_relay_agent.py")
    shutil.copy2(SOURCE / "credential_store.py", DEST / "credential_store.py")
    (DEST / "Start-FlickerLinkPro2.cmd").write_text(START, encoding="utf-8")
    (DEST / "Sign-Out.cmd").write_text(SIGNOUT, encoding="utf-8")
    print("INSTALLED: Staging agent and independent launcher")
    print("BACKUP_FOLDER:", backup_dir.name)
    print("PRESERVED: config.json and existing ngrok application")
    print("CREDENTIAL_TARGET: FlickerLinkPro2/StagingDevicePairing")

if __name__ == "__main__":
    main()
