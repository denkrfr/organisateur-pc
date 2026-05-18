"""Stockage chiffre des cles API utilisateur via Windows DPAPI.

DPAPI = Data Protection API de Windows. Chiffre des bytes avec une cle
derivee du mot de passe Windows de l'utilisateur. Resultat :
  - Stocke en local seulement
  - Seul cet utilisateur Windows peut dechiffrer
  - Un autre compte Windows (meme admin) ne peut PAS lire la cle
  - Si l'user perd son mot de passe Windows et reset, les cles sont perdues

Equivalent du Android Keystore cote PC (sans Hardware Security Module mais
suffisant pour usage perso). 0 dependance externe : ctypes + crypt32.dll
(Win10/11 default).

Fichier : ~/.organisateur-pc/api_keys.bin (binaire chiffre)
Provider selectionne : ~/.organisateur-pc/api_provider.txt (clair, juste l'id)
"""

from __future__ import annotations
import base64
import ctypes
import json
import os
from ctypes import wintypes
from pathlib import Path
from typing import Literal, Optional


ProviderId = Literal["gemini", "gemini-paid", "openai"]
VALID_PROVIDERS: set[str] = {"gemini", "gemini-paid", "openai"}


def _data_dir() -> Path:
    d = Path.home() / ".organisateur-pc"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _keys_file() -> Path:
    return _data_dir() / "api_keys.bin"


def _provider_file() -> Path:
    return _data_dir() / "api_provider.txt"


# ---------------------------------------------------------------------------
# DPAPI low-level via ctypes
# ---------------------------------------------------------------------------
class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _to_blob(data: bytes) -> _DATA_BLOB:
    buf = ctypes.create_string_buffer(data, len(data))
    blob = _DATA_BLOB()
    blob.cbData = len(data)
    blob.pbData = ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte))
    # Keep a ref on buf so it doesn't get GC'ed before use
    blob._buf_ref = buf  # type: ignore[attr-defined]
    return blob


def _from_blob(blob: _DATA_BLOB) -> bytes:
    return ctypes.string_at(blob.pbData, blob.cbData)


def _crypt32():
    try:
        return ctypes.windll.crypt32
    except (AttributeError, OSError) as e:
        raise RuntimeError(f"DPAPI indisponible (non-Windows ?) : {e}")


def _kernel32():
    return ctypes.windll.kernel32


def dpapi_encrypt(plaintext: bytes) -> bytes:
    """Chiffre des bytes avec la cle DPAPI de l'utilisateur courant."""
    in_blob = _to_blob(plaintext)
    out_blob = _DATA_BLOB()
    crypt32 = _crypt32()
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DATA_BLOB), wintypes.LPCWSTR,
        ctypes.POINTER(_DATA_BLOB), ctypes.c_void_p,
        ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(_DATA_BLOB),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    if not crypt32.CryptProtectData(
        ctypes.byref(in_blob), "organisateur-pc",
        None, None, None, 0, ctypes.byref(out_blob),
    ):
        raise RuntimeError("DPAPI CryptProtectData echec")
    try:
        return _from_blob(out_blob)
    finally:
        _kernel32().LocalFree(out_blob.pbData)


def dpapi_decrypt(ciphertext: bytes) -> bytes:
    """Dechiffre des bytes chiffres par dpapi_encrypt sous le meme user."""
    in_blob = _to_blob(ciphertext)
    out_blob = _DATA_BLOB()
    crypt32 = _crypt32()
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DATA_BLOB), ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(_DATA_BLOB), ctypes.c_void_p,
        ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(_DATA_BLOB),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    if not crypt32.CryptUnprotectData(
        ctypes.byref(in_blob), None,
        None, None, None, 0, ctypes.byref(out_blob),
    ):
        raise RuntimeError("DPAPI CryptUnprotectData echec (cle corrompue ?)")
    try:
        return _from_blob(out_blob)
    finally:
        _kernel32().LocalFree(out_blob.pbData)


# ---------------------------------------------------------------------------
# Store : JSON serialise + chiffre DPAPI
# ---------------------------------------------------------------------------
def _load_all_keys() -> dict[str, str]:
    """Retourne {provider_id: api_key} dechiffres. Vide si rien sauve."""
    f = _keys_file()
    if not f.exists():
        return {}
    try:
        ciphertext = f.read_bytes()
        plaintext = dpapi_decrypt(ciphertext)
        data = json.loads(plaintext.decode("utf-8"))
        if not isinstance(data, dict):
            return {}
        # Sanity : ne garder que les providers valides
        return {k: v for k, v in data.items() if k in VALID_PROVIDERS and isinstance(v, str)}
    except Exception:  # noqa: BLE001 — fichier corrompu / DPAPI fail
        return {}


def _save_all_keys(keys: dict[str, str]) -> None:
    """Chiffre + sauve atomiquement."""
    plaintext = json.dumps(keys, ensure_ascii=False).encode("utf-8")
    ciphertext = dpapi_encrypt(plaintext)
    f = _keys_file()
    tmp = f.with_suffix(f.suffix + ".tmp")
    tmp.write_bytes(ciphertext)
    os.replace(str(tmp), str(f))


# ---------------------------------------------------------------------------
# API publique
# ---------------------------------------------------------------------------
def save_api_key(provider: ProviderId, api_key: str) -> None:
    """Stocke la cle API chiffree pour ce provider."""
    keys = _load_all_keys()
    keys[provider] = api_key
    _save_all_keys(keys)


def load_api_key(provider: ProviderId) -> Optional[str]:
    """Retourne la cle API dechiffree, ou None si absente."""
    return _load_all_keys().get(provider)


def delete_api_key(provider: ProviderId) -> None:
    keys = _load_all_keys()
    keys.pop(provider, None)
    if keys:
        _save_all_keys(keys)
    else:
        # Si plus aucune cle, supprime le fichier
        try:
            _keys_file().unlink(missing_ok=True)
        except OSError:
            pass


def save_selected_provider(provider: ProviderId) -> None:
    _provider_file().write_text(provider, encoding="utf-8")


def load_selected_provider() -> Optional[ProviderId]:
    f = _provider_file()
    if not f.exists():
        return None
    try:
        v = f.read_text(encoding="utf-8").strip()
        if v in VALID_PROVIDERS:
            return v  # type: ignore[return-value]
    except OSError:
        pass
    return None


def get_configured_provider() -> Optional[ProviderId]:
    """Retourne le provider selectionne SSI il a une cle dechiffrable. Sinon None."""
    selected = load_selected_provider()
    if not selected:
        return None
    key = load_api_key(selected)
    return selected if key else None


def reset_all() -> None:
    """Vide tout : cles + provider selectionne."""
    try:
        _keys_file().unlink(missing_ok=True)
    except OSError:
        pass
    try:
        _provider_file().unlink(missing_ok=True)
    except OSError:
        pass
