"""FastAPI application — wiring only (mounts, middleware, routers)."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from odas.appconfig import all_types, get_config, intake_type
from odas.config import Config
from odas.dataversion import ensure
from odas.fields import FlagField
from odas.logging import setup_logging, startup_banner
from odas.middleware import AuthMiddleware
from odas.routes_admin import router as admin_router
from odas.routes_api import router as api_router
from odas.routes_auth import router as auth_router
from odas.routes_handleiding import router as handleiding_router
from odas.routes_intake import router as intake_router
from odas.routes_inzien import router as inzien_router
from odas.routes_log import router as log_router
from odas.routes_summary import router as summary_router
from odas.routes_team import router as team_router
from odas.routes_wetten import router as wetten_router
from odas.routes_zaak import router as zaak_router
from odas.routes_zaak_edit import router as zaak_edit_router

_BASE_DIR = Path(__file__).resolve().parent
log = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Build the app for the data dir's config; intake/inzien are opt-in per org."""
    get_config.cache_clear()  # startup is when config is (re)read; invalid config fails here
    setup_logging("app")  # here, not at import: the log belongs to the data dir this app serves
    config = Config()
    ensure()  # migrate or refuse here, never halfway through serving the data
    mode = "DEV MODE (auth bypassed)" if config.test_mode else "production"
    startup_banner("web app starting", {"org": config.org.display_name, "mode": mode})
    if not any(isinstance(f, FlagField) for t in all_types().values() for f in t.values()):
        # The migration wrote the flags, but nothing reads them until a type declares one.
        log.warning("No type declares a flag field: an IN marks no zaak in the overview")
    app = FastAPI()
    app.mount("/static", StaticFiles(directory=str(_BASE_DIR / "static")), name="static")
    # An org's logo belongs to its data dir, never to this package.
    if (assets := config.data_dir / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")
    app.add_middleware(AuthMiddleware)
    # Caddy terminates TLS and is a container of its own, so uvicorn's default
    # (trust 127.0.0.1 only) drops X-Forwarded-Proto: every mailed link came out
    # http:// and no session cookie carried Secure. Added last, so it wraps the
    # others and the scheme is right before any route reads it. `*` is safe
    # because the port is exposed to the compose network, never published.
    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")
    app.include_router(auth_router)
    if intake_type():  # the route exists because a type declares it, never because of a flag
        app.include_router(intake_router)
    app.include_router(zaak_router)
    app.include_router(zaak_edit_router)
    app.include_router(inzien_router)
    app.include_router(log_router)
    app.include_router(summary_router)
    app.include_router(team_router)
    app.include_router(admin_router)
    # Unconditional: a law can be fetched while the app runs, so the page carries
    # its own empty state rather than the route disappearing at startup.
    app.include_router(wetten_router)
    app.include_router(handleiding_router)
    app.include_router(api_router)

    # Case data and a demo's hourly sandbox alike must never reach an index.
    @app.get("/robots.txt", response_class=PlainTextResponse)
    def robots() -> str:
        return "User-agent: *\nDisallow: /\n"

    return app


app: FastAPI = create_app()
