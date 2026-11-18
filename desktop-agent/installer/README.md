# Flicker Link Pro Windows installer

This per-user installer uses the production Render relay, installs without
administrator rights, includes the complete 66-tool catalog, and creates a
desktop shortcut plus a separate sign-out shortcut. The desktop app asks on
the first sensitive tool call. Approval remains saved across app restarts and
clears when the user signs out on Windows or revokes the pairing.

The app stores the pairing credential in Windows Credential Manager. The
installer contains only the public relay address, not an account token or
server secret. The one-computer-per-account rule is enforced by the relay.

## Build a signed release

Use a clean 64-bit Python environment, install the Windows app requirements,
PyInstaller 6, and Inno Setup 6. A trusted code-signing certificate for the
publisher Eric Williams must be available to SignTool in the current Windows
user's certificate store. The build signs the Windows app, installer, and
uninstaller, then stops if Windows does not report a valid signature from the
expected publisher.

```powershell
python -m pip install -r desktop-agent/requirements.txt "pyinstaller>=6.20,<7"
desktop-agent/installer/build.ps1 `
  -Python (Get-Command python).Source `
  -InnoCompiler 'C:\Path\To\ISCC.exe' `
  -OutputDirectory 'C:\Path\To\Artifacts'
```

The default signing command uses the signing certificate installed for Eric
Williams. If a managed signing provider requires a different command, pass it
through `-SignToolCommand`; do not put certificate passwords or private keys in
the command, repository, or installer.

Do not distribute an installer until it has a valid signature, its SHA-256 hash
has been recorded, and a clean Windows installation has been reviewed.
