"""Store Flicker Link Pro device pairing in the current user's Windows Credential Manager.

No credential is written to a JSON file or Windows shortcut. Credentials persist across
reboots and app relaunches until logout, uninstall cleanup, or account revocation.
"""
from __future__ import annotations
import ctypes
from ctypes import wintypes
import json
import os

TARGET = "FlickerLinkPro2/DevicePairing"
CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2
ERROR_NOT_FOUND = 1168

class CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]

PCREDENTIAL = ctypes.POINTER(CREDENTIALW)

def _api():
    if os.name != "nt":
        raise RuntimeError("Windows Credential Manager requires Windows")
    api = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
    api.CredWriteW.argtypes = [PCREDENTIAL, wintypes.DWORD]
    api.CredWriteW.restype = wintypes.BOOL
    api.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                              ctypes.POINTER(PCREDENTIAL)]
    api.CredReadW.restype = wintypes.BOOL
    api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    api.CredDeleteW.restype = wintypes.BOOL
    api.CredFree.argtypes = [ctypes.c_void_p]
    api.CredFree.restype = None
    return api

def save_credential(server: str, token: str, target: str = TARGET):
    if not server.startswith("https://") or not token or any(c in server for c in "\r\n"):
        raise ValueError("A secure HTTPS server and nonempty credential are required")
    raw = json.dumps({"server": server.rstrip("/"), "token": token},
                     separators=(",", ":")).encode("utf-16-le")
    if len(raw) > 2560:
        raise ValueError("Device credential exceeds Windows Credential Manager size limit")
    buffer = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
    credential = CREDENTIALW()
    credential.Type = CRED_TYPE_GENERIC
    credential.TargetName = target
    credential.CredentialBlobSize = len(raw)
    credential.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
    credential.Persist = CRED_PERSIST_LOCAL_MACHINE
    credential.UserName = "FlickerLinkPro"
    if not _api().CredWriteW(ctypes.byref(credential), 0):
        raise ctypes.WinError(ctypes.get_last_error())

def load_credential(target: str = TARGET):
    api = _api()
    result = PCREDENTIAL()
    if not api.CredReadW(target, CRED_TYPE_GENERIC, 0, ctypes.byref(result)):
        err = ctypes.get_last_error()
        if err == ERROR_NOT_FOUND:
            return None
        raise ctypes.WinError(err)
    try:
        item = result.contents
        raw = ctypes.string_at(item.CredentialBlob, item.CredentialBlobSize)
        data = json.loads(raw.decode("utf-16-le"))
        return data["server"], data["token"]
    finally:
        api.CredFree(ctypes.cast(result, ctypes.c_void_p))

def delete_credential(target: str = TARGET):
    if not _api().CredDeleteW(target, CRED_TYPE_GENERIC, 0):
        err = ctypes.get_last_error()
        if err != ERROR_NOT_FOUND:
            raise ctypes.WinError(err)
