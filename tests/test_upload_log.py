"""An upload leaves one line in the log, also when the browser leaves halfway."""

from __future__ import annotations

import logging
from collections.abc import Iterator

import anyio
import pytest
from fastapi.testclient import TestClient
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from odas.upload_log import UploadLogMiddleware


@pytest.fixture
def upload_log(caplog: pytest.LogCaptureFixture) -> Iterator[pytest.LogCaptureFixture]:
    """The middleware's own lines. `setup_logging` stops propagation to the root logger."""
    logger = logging.getLogger("odas.upload_log")
    logger.addHandler(caplog.handler)
    caplog.set_level(logging.INFO, logger=logger.name)
    yield caplog
    logger.removeHandler(caplog.handler)


def _leave_halfway(app: ASGIApp, head: bytes, total: int) -> list[Message]:
    """Send the first part of a multipart body, then close the connection."""
    incoming: list[Message] = [
        {"type": "http.request", "body": head, "more_body": True},
        {"type": "http.disconnect"},
    ]
    sent: list[Message] = []

    async def receive() -> Message:
        return incoming.pop(0) if incoming else {"type": "http.disconnect"}

    async def send(message: Message) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/indienen",
        "raw_path": b"/indienen",
        "root_path": "",
        "query_string": b"",
        "server": ("testserver", 80),
        "client": ("203.0.113.9", 50000),
        "headers": [
            (b"content-type", b"multipart/form-data; boundary=grens"),
            (b"content-length", str(total).encode()),
            (b"user-agent", b"Safari/605.1.15"),
        ],
    }
    anyio.run(app, scope, receive, send)
    return sent


def test_an_upload_is_one_line_with_its_size_and_browser(
    client: TestClient, upload_log: pytest.LogCaptureFixture
) -> None:
    client.post(
        "/zaken/zk-00001/log",
        data={"direction": "LOG", "onderwerp": "Stukken", "body": "x"},
        files=[("documenten", ("a.txt", b"0123456789", "text/plain"))],
        headers={"user-agent": "Safari/605.1.15"},
    )
    [line] = [r for r in upload_log.records if r.message.startswith("Upload:")]
    assert "status=303" in line.message
    assert "path='/zaken/zk-00001/log'" in line.message
    assert "agent='Safari/605.1.15'" in line.message


def test_an_upload_that_fails_on_the_server_still_leaves_its_line(
    upload_log: pytest.LogCaptureFixture,
) -> None:
    async def broken(scope: Scope, receive: Receive, send: Send) -> None:
        await receive()
        raise RuntimeError("disk full")

    with pytest.raises(RuntimeError):
        _leave_halfway(UploadLogMiddleware(broken), b"--grens", total=100)

    [line] = upload_log.records
    assert line.levelname == "ERROR"
    assert line.message.startswith("Upload: status=500")


def test_a_browser_that_leaves_halfway_is_one_warning_not_a_stack_trace(
    client: TestClient, upload_log: pytest.LogCaptureFixture
) -> None:
    head = b'--grens\r\nContent-Disposition: form-data; name="documenten"; filename="a.pdf"\r\n\r\n%PDF'
    sent = _leave_halfway(client.app, head, total=9_000_000)

    assert sent == []  # nobody is there to answer
    [line] = upload_log.records
    assert line.levelname == "WARNING"
    assert line.message.startswith("Upload broken off:")
    assert f"bytes={len(head)} of=9000000" in line.message
