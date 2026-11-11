"""Session token management and OIDC helpers."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any
from urllib.parse import urlencode

import httpx2 as httpx
from joserfc import jwt as joserfc_jwt
from joserfc.jwk import KeySet

from odas.config import Config

COOKIE_NAME = "hv_session"
COOKIE_MAX_AGE = 30 * 24 * 3600  # 30 days
TOKEN_MAX_AGE = COOKIE_MAX_AGE
SECRET_KEY_FILE_MODE = 0o600

STATE_COOKIE_NAME = "oidc_state"
NEXT_COOKIE_NAME = "oidc_next"
STATE_MAX_AGE = 600  # 10 minutes

PROFILE_COOKIE_NAME = "hv_user"


def _secret_key_path() -> str:
    config = Config()
    config.ensure_dirs()
    return str(config.data_dir / ".secret_key")


def _get_secret_key() -> bytes:
    """Read or create the HMAC secret key file (used to sign session cookies)."""
    path = _secret_key_path()
    try:
        with open(path, encoding="utf8") as f:
            key = bytes.fromhex(f.read().strip())
        os.chmod(path, SECRET_KEY_FILE_MODE)
        return key
    except FileNotFoundError:
        key = secrets.token_bytes(32)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, SECRET_KEY_FILE_MODE)
        except FileExistsError:
            with open(path, encoding="utf8") as f:
                return bytes.fromhex(f.read().strip())
        with os.fdopen(fd, "w", encoding="utf8") as f:
            f.write(key.hex())
        return key


def create_session_token(email: str) -> str:
    """Sign one fact: which account this browser proved it holds.

    Membership of the team group is deliberately *not* in here. It is a grant,
    it changes in pocket-id, and a copy in a 30-day cookie would go on opening
    every zaak long after the directory withdrew it.
    """
    payload = json.dumps({"ts": int(time.time()), "email": email})
    payload_b64 = base64.urlsafe_b64encode(payload.encode()).decode()
    sig = hmac.new(_get_secret_key(), payload_b64.encode(), hashlib.sha256).hexdigest()
    return f"{payload_b64}:{sig}"


def verify_session_token(token: str) -> dict[str, Any] | None:
    """Verify the signed session token; return {email} or None."""
    try:
        payload_b64, sig = token.split(":", 1)
    except (ValueError, AttributeError):
        return None

    expected = hmac.new(_get_secret_key(), payload_b64.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None

    try:
        data = json.loads(base64.urlsafe_b64decode(payload_b64.encode()).decode())
        if time.time() - int(data["ts"]) > TOKEN_MAX_AGE:
            return None
        return {"email": str(data.get("email", ""))}
    except Exception:
        return None


def is_team_member(groups: list[str], group_team: str) -> bool:
    """Is this OIDC groups claim the team group? Everyone else gets in per zaak."""
    return group_team in groups


def create_state_cookie(state: str, code_verifier: str) -> str:
    """Return a signed cookie value encoding OIDC state + PKCE verifier."""
    payload = json.dumps({"s": state, "cv": code_verifier, "ts": int(time.time())})
    sig = hmac.new(_get_secret_key(), payload.encode(), hashlib.sha256).hexdigest()
    combined = f"{payload}|{sig}"
    return base64.urlsafe_b64encode(combined.encode()).decode()


def verify_state_cookie(cookie_value: str, state: str) -> str | None:
    """Verify signed state cookie; return the PKCE code_verifier or None if invalid."""
    try:
        decoded = base64.urlsafe_b64decode(cookie_value.encode()).decode()
        payload_str, sig = decoded.rsplit("|", 1)
        expected = hmac.new(_get_secret_key(), payload_str.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        data = json.loads(payload_str)
        if time.time() - data["ts"] > STATE_MAX_AGE:
            return None
        if data["s"] != state:
            return None
        return str(data["cv"])
    except Exception:
        return None


def pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) for PKCE S256."""
    verifier = secrets.token_urlsafe(64)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    return verifier, challenge


async def get_oidc_config(issuer: str) -> dict[str, Any]:
    """Read once per login. Held state would survive a key rotation and break it."""
    async with httpx.AsyncClient() as client:
        r = await client.get(f"{issuer}/.well-known/openid-configuration")
        r.raise_for_status()
        return dict(r.json())


async def get_jwks(jwks_uri: str) -> dict[str, Any]:
    async with httpx.AsyncClient() as client:
        r = await client.get(jwks_uri)
        r.raise_for_status()
        return dict(r.json())


def build_auth_url(
    authorization_endpoint: str,
    client_id: str,
    redirect_uri: str,
    state: str,
    code_challenge: str,
) -> str:
    params = urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": "openid profile email groups",
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
    )
    return f"{authorization_endpoint}?{params}"


async def exchange_code(
    token_endpoint: str,
    client_id: str,
    client_secret: str,
    code: str,
    redirect_uri: str,
    code_verifier: str,
) -> dict[str, Any]:
    async with httpx.AsyncClient() as client:
        r = await client.post(
            token_endpoint,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": client_id,
                "client_secret": client_secret,
                "code_verifier": code_verifier,
            },
        )
        r.raise_for_status()
        return r.json()  # type: ignore[no-any-return]


def create_profile_cookie(claims: dict[str, Any]) -> str:
    """Base64url-encode display fields from OIDC claims (unsigned, display-only)."""
    payload = {
        "name": claims.get("name", ""),
        "email": claims.get("email", ""),
        "picture": claims.get("picture", ""),
    }
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()


def set_session_cookies(response: Any, claims: dict[str, Any], secure: bool) -> None:
    """Attach session + profile cookies to an existing response."""
    response.set_cookie(
        COOKIE_NAME,
        create_session_token(claims.get("email", "")),
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=secure,
    )
    response.set_cookie(
        PROFILE_COOKIE_NAME,
        create_profile_cookie(claims),
        max_age=COOKIE_MAX_AGE,
        httponly=False,
        samesite="lax",
        secure=secure,
    )


def read_profile_cookie(value: str) -> dict[str, Any] | None:
    """Decode the profile cookie; return a dict or None on error."""
    try:
        return dict(json.loads(base64.urlsafe_b64decode(value.encode()).decode()))
    except Exception:
        return None


def verify_id_token(
    id_token: str,
    jwks_data: dict[str, Any],
    client_id: str,
    issuer: str,
) -> dict[str, Any]:
    """Decode and verify the OIDC ID token; return the claims dict."""
    key_set = KeySet.import_key_set(jwks_data)  # type: ignore[arg-type]
    token = joserfc_jwt.decode(id_token, key_set)
    claims = token.claims
    if claims.get("iss") != issuer:
        raise ValueError(f"Invalid issuer: {claims.get('iss')!r}")
    aud = claims.get("aud")
    if isinstance(aud, list):
        if client_id not in aud:
            raise ValueError("client_id not in audience")
    elif aud != client_id:
        raise ValueError(f"Invalid audience: {aud!r}")
    return dict(claims)
