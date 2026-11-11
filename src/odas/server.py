"""Entry point: run the FastAPI app with uvicorn."""

from __future__ import annotations

import uvicorn

from odas.settings import ServerSettings


def _settings() -> ServerSettings:
    """Where to listen. Neutral defaults while the config is missing or broken:
    the app's own startup check reports what is wrong, once it is running."""
    from odas.appconfig import server

    try:
        return server()
    except Exception:
        return ServerSettings()


def main(port: int | None = None) -> None:
    settings = _settings()
    uvicorn.run("odas.app:app", host=settings.host, port=port or settings.port)
