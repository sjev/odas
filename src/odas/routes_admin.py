"""The Admin page: a test mail, back-ups, and the audit and log tails. Team only."""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse, Response
from starlette.concurrency import run_in_threadpool

from odas import audit, backup, mail
from odas.appconfig import smtp
from odas.config import Config
from odas.templating import templates
from odas.web_helpers import require_admin

router = APIRouter()

TAIL_LINES = 200
EVENT_LIMIT = 500  # how far the audit log reaches; a page size, not organisation behaviour


def _tail(name: str) -> str:
    path = Config().log_file(name)
    if not path.exists():
        return ""
    lines = path.read_text(encoding="utf8", errors="replace").splitlines()
    return "\n".join(lines[-TAIL_LINES:])


@router.get("/admin", tags=["ui"])
async def admin_page(request: Request, sent: str = "") -> Response:
    require_admin(request)
    return templates.TemplateResponse(
        request=request,
        name="admin.html",
        context={
            "template_names": list(smtp().templates),
            "sent": sent,  # "" before a test mail, "ok" after one, else the reason it stayed
            "events": audit.recent(EVENT_LIMIT),
            "app_log": _tail("app"),
            "mail_log": _tail("mail"),
            "backups": backup.list_backups(),
            "backup_running": backup.RUNNING.locked(),
        },
    )


@router.post("/admin/testmail", tags=["ui"])
async def send_testmail(
    request: Request, template: str = Form(), to: str = Form()
) -> RedirectResponse:
    require_admin(request)
    try:
        msg = await run_in_threadpool(
            mail.send_template, template, [to.strip()], values=mail.sample_values()
        )
        sent = "ok" if msg is not None else f"Het sjabloon {template} is niet aangegeven."
    except mail.MailError as e:
        sent = str(e)
    return RedirectResponse(f"/admin?sent={quote(sent)}", status_code=303)


@router.post("/admin/backup", tags=["ui"])
async def make_backup(request: Request, tasks: BackgroundTasks) -> RedirectResponse:
    require_admin(request)
    if backup.start():  # a sync task runs in a worker thread, after the redirect is sent
        tasks.add_task(backup.run)
    return RedirectResponse("/admin", status_code=303)


@router.get("/admin/backups/{name}", tags=["ui"])
async def download_backup(request: Request, name: str) -> Response:
    require_admin(request)
    path = backup.find(name)
    if path is None:
        raise HTTPException(status_code=404, detail="back-up niet gevonden")
    return FileResponse(path, media_type="application/zip", filename=name)


@router.post("/admin/backups/{name}/verwijderen", tags=["ui"])
async def delete_backup(request: Request, name: str) -> RedirectResponse:
    require_admin(request)
    path = backup.find(name)
    if path is None:
        raise HTTPException(status_code=404, detail="back-up niet gevonden")
    backup.delete(path)
    return RedirectResponse("/admin", status_code=303)
