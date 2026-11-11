"""The internal pages: who is on the team, what the app logged."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import Response

from odas import users
from odas.config import Config
from odas.templating import templates
from odas.web_helpers import require_admin, require_team

router = APIRouter()


def _read_log(request: Request, name: str) -> Response:
    """Serve one entry point's file. The daemon writes to the same volume."""
    require_admin(request)
    log_path = Config().log_file(name)
    if not log_path.exists():
        return Response(content="Log file not found.", media_type="text/plain")
    try:
        return Response(content=log_path.read_text(encoding="utf8"), media_type="text/plain")
    except OSError as e:
        return Response(content=f"Error reading log: {e}", media_type="text/plain")


@router.get("/log", tags=["ui"])
async def view_log(request: Request) -> Response:
    return _read_log(request, "app")


@router.get("/log/mail", tags=["ui"])
async def view_mail_log(request: Request) -> Response:
    return _read_log(request, "mail")


@router.get("/team", tags=["ui"])
async def team_page(request: Request) -> Response:
    require_team(request)
    return templates.TemplateResponse(
        request=request,
        name="team.html",
        context={"users": users.load_users()},
    )
