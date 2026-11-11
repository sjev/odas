"""The `org:` section: feature flags gate routers and middleware; branding is text."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from conftest import use_config, write_config
from fastapi import FastAPI

from odas.middleware import AuthMiddleware


def _paths(app: FastAPI) -> set[str]:
    return {r.path for r in app.routes}  # type: ignore[attr-defined]


def _with_helpdesk_type(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **org: Any) -> None:
    """A data dir declaring the helpdesk type these flags act on.

    The shipped template is the plain base type, so intake has nothing to gate
    until a data dir declares a type to gate.
    """
    use_config(tmp_path, monkeypatch, **org)
    config = yaml.safe_load((tmp_path / ".app" / "config.yaml").read_text(encoding="utf8"))
    config["types"]["hulpvraag"] = {
        "public_intake": True,
        "contact_naam": {"type": "str", "public": True, "editable": ["team", "public"]},
        "reply_token": {"type": "reply_token"},
    }
    write_config(tmp_path, config)


async def _dummy_asgi(scope: Any, receive: Any, send: Any) -> None:  # pragma: no cover
    pass


def test_a_type_declaring_public_intake_is_what_opens_the_public_form(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The public form exists because a type claims it, never because a flag is set."""
    from odas.app import create_app

    use_config(tmp_path, monkeypatch)  # the plain template: no type claims intake
    paths = _paths(create_app())
    assert "/indienen" not in paths
    assert AuthMiddleware(_dummy_asgi).public_exact == {"/robots.txt"}
    assert "/zaken" in paths and "/zaken/{zaak_id}" in paths  # base features stay
    assert any(p.startswith("/inzien-") for p in paths)  # public links are always on

    _with_helpdesk_type(tmp_path, monkeypatch)
    assert "/indienen" in _paths(create_app())
    assert AuthMiddleware(_dummy_asgi).public_exact == {"/robots.txt", "/", "/indienen"}
