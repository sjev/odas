"""The Dutch manual, served directly from its one Markdown source file."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import Response

from odas import handleiding
from odas.templating import templates

router = APIRouter()


def _render(request: Request) -> Response:
    return templates.TemplateResponse(
        request=request,
        name="handleiding.html",
        context={"titel": "Handleiding", "body": handleiding.body()},
    )


@router.get("/handleiding", tags=["ui"])
async def handleiding_page(request: Request) -> Response:
    """One compact page for everyone who has signed in."""
    return _render(request)
