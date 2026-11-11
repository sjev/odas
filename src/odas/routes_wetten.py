"""Wetten routes: the tracked laws, one law's table of contents, one article.

The law is public, so no access rule runs here. The ordinary sign-in gate is the
only one.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from odas import wetten_read
from odas.templating import templates

router = APIRouter()


@router.get("/wetten", tags=["ui"])
async def wetten_index(request: Request) -> Response:
    """The laws this organisation tracks, and the box over all their text."""
    q = request.query_params.get("q", "")
    wet = request.query_params.get("wet", "")
    laws = wetten_read.laws()
    # An unknown slug in a hand-typed address narrows to nothing, never to an error.
    return templates.TemplateResponse(
        request=request,
        name="wetten.html",
        context={
            "laws": laws,
            "groups": wetten_read.search(q, wet) if q else [],
            "q": q,
            "wet": wet,
        },
    )


@router.get("/wetten/{slug}", tags=["ui"])
async def wet_view(request: Request, slug: str) -> Response:
    """One law: what it is, when its text became current, and its contents."""
    law = wetten_read.law(slug)
    if law is None:
        raise HTTPException(status_code=404, detail="Wet niet gevonden.")
    return templates.TemplateResponse(
        request=request,
        name="wet.html",
        context={"law": law, "toc": wetten_read.toc(slug)},
    )


@router.get("/wetten/{slug}/{name}", tags=["ui"])
async def artikel_view(request: Request, slug: str, name: str) -> Response:
    """One article: its text, its own date, and the way back to its source."""
    found = wetten_read.article(slug, name)
    law = wetten_read.law(slug)
    if found is None or law is None:
        raise HTTPException(status_code=404, detail="Artikel niet gevonden.")
    frontmatter, text = found
    titel = next((e.titel for h in wetten_read.toc(slug) for e in h.entries if e.name == name), "")
    return templates.TemplateResponse(
        request=request,
        name="artikel.html",
        context={"law": law, "artikel": frontmatter, "titel": titel, "text": text},
    )
