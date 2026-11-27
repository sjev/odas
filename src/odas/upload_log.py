"""One log line per upload: how much arrived, how long it took, from what browser.

An upload that fails in the browser leaves nothing else behind on the server.
These lines are what tells a slow link from a dropped one, and a client that
gave up from a server that stalled.
"""

from __future__ import annotations

import logging
import time

from starlette.requests import ClientDisconnect
from starlette.types import ASGIApp, Message, Receive, Scope, Send

log = logging.getLogger(__name__)


def _header(scope: Scope, name: bytes) -> str:
    return next((v.decode("latin-1") for k, v in scope["headers"] if k == name), "")


class UploadLogMiddleware:
    """Log every multipart POST; a client that leaves halfway is one WARNING line."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or scope["method"] != "POST"
            or not _header(scope, b"content-type").startswith("multipart/")
        ):
            await self.app(scope, receive, send)
            return

        start = time.monotonic()
        got = 0
        status = 0

        async def counting_receive() -> Message:
            nonlocal got
            message = await receive()
            got += len(message.get("body", b""))
            return message

        async def status_send(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            await send(message)

        def facts() -> str:
            return (
                f"path={scope['path']!r} bytes={got} of={_header(scope, b'content-length') or '?'}"
                f" seconds={time.monotonic() - start:.1f}"
                f" agent={_header(scope, b'user-agent')!r}"
            )

        try:
            await self.app(scope, counting_receive, status_send)
        except ClientDisconnect:
            # The browser is gone, so no answer can reach it: the line is all there is.
            log.warning(f"Upload broken off: {facts()}")
            return
        except Exception:
            log.error(f"Upload: status=500 {facts()}")  # the traceback follows from Starlette
            raise
        log.info(f"Upload: status={status} {facts()}")
