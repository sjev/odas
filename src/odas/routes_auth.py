"""Auth routes: OIDC login, callback, logout."""

from __future__ import annotations

import logging
import secrets
from urllib.parse import urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse, Response

from odas import appsecrets
from odas.appconfig import demo
from odas.appconfig import oidc as oidc_settings
from odas.auth import (
    COOKIE_NAME,
    NEXT_COOKIE_NAME,
    PROFILE_COOKIE_NAME,
    STATE_COOKIE_NAME,
    STATE_MAX_AGE,
    build_auth_url,
    create_state_cookie,
    exchange_code,
    get_jwks,
    get_oidc_config,
    is_team_member,
    pkce_pair,
    set_session_cookies,
    verify_id_token,
    verify_state_cookie,
)
from odas.config import Config
from odas.templating import templates

log = logging.getLogger(__name__)

router = APIRouter()


def _set_temp_cookie(response: Response, name: str, value: str, secure: bool) -> None:
    response.set_cookie(
        name, value, max_age=STATE_MAX_AGE, httponly=True, samesite="lax", secure=secure
    )


def _sanitize_next_url(next_url: str) -> str:
    candidate = next_url.strip()
    if not candidate:
        return "/zaken"
    parts = urlsplit(candidate)
    if parts.scheme or parts.netloc:
        return "/zaken"
    if not parts.path.startswith("/") or "\\" in parts.path:
        return "/zaken"
    return urlunsplit(("", "", parts.path, parts.query, parts.fragment))


@router.get("/login", tags=["auth"])
async def login(request: Request, next: str = "/zaken", error: str = "") -> Response:
    if error:
        return templates.TemplateResponse(
            request=request, name="login.html", context={"error": error}
        )
    config = Config()
    secure = request.url.scheme == "https"
    if demo() is not None:
        return RedirectResponse("/zaken", status_code=303)  # a demo has no door to knock on

    if config.test_mode:
        response = RedirectResponse(url=_sanitize_next_url(next), status_code=303)
        set_session_cookies(
            response,
            {"name": "Test User", "email": "test@example.com", "picture": ""},
            secure,
        )
        return response
    settings = oidc_settings()
    oidc = await get_oidc_config(settings.issuer)
    state = secrets.token_urlsafe(32)
    verifier, challenge = pkce_pair()
    auth_url = build_auth_url(
        oidc["authorization_endpoint"],
        settings.client_id,
        settings.redirect_uri,
        state,
        challenge,
    )
    log.info(f"Login initiated: next={_sanitize_next_url(next)!r}")
    response = RedirectResponse(url=auth_url, status_code=302)
    _set_temp_cookie(response, STATE_COOKIE_NAME, create_state_cookie(state, verifier), secure)
    _set_temp_cookie(response, NEXT_COOKIE_NAME, _sanitize_next_url(next), secure)
    return response


@router.get("/auth/callback", tags=["auth"])
async def auth_callback(
    request: Request, code: str = "", state: str = "", error: str = ""
) -> Response:
    if error:
        log.warning(f"Login failed: error={error!r}")
        return RedirectResponse(f"/login?error={error}", status_code=302)

    state_cookie = request.cookies.get(STATE_COOKIE_NAME)
    if not state_cookie:
        return RedirectResponse("/login?error=missing_state", status_code=302)

    code_verifier = verify_state_cookie(state_cookie, state)
    if not code_verifier:
        return RedirectResponse("/login?error=invalid_state", status_code=302)

    next_url = _sanitize_next_url(request.cookies.get(NEXT_COOKIE_NAME, "/zaken"))
    settings = oidc_settings()
    try:
        oidc = await get_oidc_config(settings.issuer)
        tokens = await exchange_code(
            oidc["token_endpoint"],
            settings.client_id,
            appsecrets.require("oidc_client_secret"),
            code,
            settings.redirect_uri,
            code_verifier,
        )
        jwks = await get_jwks(oidc["jwks_uri"])
        claims = verify_id_token(tokens["id_token"], jwks, settings.client_id, settings.issuer)
    except Exception:
        log.exception("OIDC callback failed")
        return RedirectResponse("/login?error=auth_failed", status_code=302)

    # Recorded, never stored: access is resolved from the directory on every
    # request, so this line only says what pocket-id claimed at sign-in.
    groups = claims.get("groups") or []
    team = is_team_member(groups if isinstance(groups, list) else [], settings.group_team)
    log.info(f"Login success: sub={claims.get('sub')} email={claims.get('email')} team={team}")
    secure = request.url.scheme == "https"
    response = RedirectResponse(url=next_url, status_code=303)
    set_session_cookies(response, claims, secure)
    response.delete_cookie(STATE_COOKIE_NAME)
    response.delete_cookie(NEXT_COOKIE_NAME)
    return response


@router.get("/logout", tags=["auth"])
async def logout(request: Request) -> RedirectResponse:
    redirect_url = "/login"
    if demo() is not None:
        return RedirectResponse("/zaken", status_code=303)

    if not Config().test_mode:
        try:
            oidc = await get_oidc_config(oidc_settings().issuer)
            end_session = oidc.get("end_session_endpoint")
            if end_session:
                base = str(request.base_url).rstrip("/")
                params = urlencode({"post_logout_redirect_uri": f"{base}/login"})
                redirect_url = f"{end_session}?{params}"
        except Exception:
            log.warning("Could not fetch end_session_endpoint; falling back to /login")
    log.info(f"Logout: email={request.state.email!r}")
    response = RedirectResponse(url=redirect_url, status_code=303)
    response.delete_cookie(COOKIE_NAME)
    response.delete_cookie(PROFILE_COOKIE_NAME)
    return response
