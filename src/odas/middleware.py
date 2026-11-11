"""Auth middleware: gate every request on a valid session cookie."""

from __future__ import annotations

import logging

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import PlainTextResponse, RedirectResponse, Response
from starlette.routing import Match
from starlette.types import ASGIApp

from odas import users
from odas.appconfig import demo, intake_type
from odas.auth import (
    COOKIE_NAME,
    PROFILE_COOKIE_NAME,
    read_profile_cookie,
    verify_session_token,
)
from odas.config import Config

log = logging.getLogger(__name__)

# Always-public paths; the intake root is added when a type declares public intake.
PUBLIC_PREFIXES = (
    "/login",
    "/auth/callback",
    "/static/",
    "/assets/",
    "/api/",
    "/inzien-",
    "/.well-known/",
)

DIRECTORY_DOWN = (
    "De gebruikerslijst is nu niet bereikbaar, dus toegang kan niet worden "
    "vastgesteld. Probeer het over enkele minuten opnieuw."
)


def _no_cache(response: Response) -> Response:
    """Mark HTML responses as non-cacheable so browsers always fetch fresh state."""
    if "text/html" in response.headers.get("content-type", ""):
        response.headers["Cache-Control"] = "no-store"
    return response


def _set_identity(request: Request, is_team: bool, email: str) -> None:
    request.state.is_team = is_team
    request.state.email = email


class AuthMiddleware(BaseHTTPMiddleware):
    """Check the session cookie on all requests except public paths."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        self.public_prefixes = PUBLIC_PREFIXES
        self.public_exact = {"/robots.txt"}
        if intake_type():
            self.public_exact |= {"/", "/indienen"}

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        declared = demo()
        if declared is not None:
            # A demo names one identity and every request carries it, so the audit
            # trail says a demonstration did this. No directory is asked at all.
            request.state.user_profile = {
                "name": declared.name,
                "email": declared.actor,
                "picture": "",
            }
            _set_identity(request, True, declared.actor)
            return _no_cache(await call_next(request))

        if Config().test_mode:
            request.state.user_profile = read_profile_cookie(
                request.cookies.get(PROFILE_COOKIE_NAME, "")
            ) or {"name": "Test User", "email": "test@example.com", "picture": ""}
            _set_identity(request, True, "test@example.com")
            return _no_cache(await call_next(request))

        path = request.url.path
        if path in self.public_exact or any(path.startswith(p) for p in self.public_prefixes):
            request.state.user_profile = None
            _set_identity(request, False, "")
            return _no_cache(await call_next(request))

        token = request.cookies.get(COOKIE_NAME)
        session = verify_session_token(token or "") if token else None
        if session:
            # The cookie proves the account once; only pocket-id says whether it
            # still exists and is in the team group. It is asked again on every
            # request, so an account removed or moved there is gone here at once.
            try:
                person = users.account(session["email"])
            except Exception:
                log.exception("Cannot reach the user directory; refusing to guess at access")
                return _no_cache(PlainTextResponse(DIRECTORY_DOWN, status_code=503))
            request.state.user_profile = read_profile_cookie(
                request.cookies.get(PROFILE_COOKIE_NAME, "")
            )
            if person is None:  # no account, no identity: a grant names nobody here
                _set_identity(request, False, "")
            else:
                _set_identity(request, person.is_team, session["email"])
            return _no_cache(await call_next(request))

        # Icon requests and scanners hit paths no route serves; a login cannot help them.
        if all(r.matches(request.scope)[0] == Match.NONE for r in request.app.router.routes):
            return PlainTextResponse("Not Found", status_code=404)
        log.info(f"Unauthenticated access blocked: path={path!r}")
        return RedirectResponse(f"/login?next={path}", status_code=302)
