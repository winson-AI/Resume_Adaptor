"""Local FastAPI browser UI — stepped wizard with agreement-to-rewrite."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Dict, Optional

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from profile_adaptor.config import Settings
from profile_adaptor.event_log import EventLog, setup_app_logging
from profile_adaptor.hitl.template_selector import list_templates
from profile_adaptor.models import WizardSession
from profile_adaptor.pipeline import (
    apply_ingest_to_session,
    apply_match_audit_to_session,
    apply_review_corrections_to_session,
    apply_rewrite_to_session,
    refresh_ingest_in_session,
    refresh_jd_in_session,
    refresh_resume_in_session,
)

setup_app_logging()

_WEB_DIR = Path(__file__).resolve().parent
_TEMPLATES = Jinja2Templates(directory=str(_WEB_DIR / "templates"))
_SESSIONS: Dict[str, WizardSession] = {}


def _get_session(session_id: Optional[str], settings: Settings) -> WizardSession:
    if session_id and session_id in _SESSIONS:
        return _SESSIONS[session_id]
    sid = session_id or uuid.uuid4().hex[:12]
    sess = WizardSession(
        session_id=sid,
        provider=settings.provider,
        model=settings.model,
        event_log=EventLog(session_id=sid, log_dir=settings.output_dir),
    )
    _SESSIONS[sid] = sess
    return sess


def _ctx(request: Request, settings: Settings, session: WizardSession, **extra):
    data = {
        "request": request,
        "session": session,
        "templates": list_templates(settings.templates_dir),
        "provider": session.provider or settings.provider,
        "model": session.model or settings.model,
        "steps": ["ingest", "review", "match_audit", "hitl", "done"],
    }
    data.update(extra)
    return data


def create_app(settings: Settings) -> FastAPI:
    settings.ensure_dirs()
    app = FastAPI(title="Profile Adaptor", version="0.1.0")
    upload_dir = settings.output_dir / "_uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request, session_id: Optional[str] = None):
        session = _get_session(session_id, settings)
        return _TEMPLATES.TemplateResponse("wizard.html", _ctx(request, settings, session))

    @app.post("/ingest", response_class=HTMLResponse)
    async def ingest(
        request: Request,
        session_id: str = Form(""),
        url: str = Form(""),
        jd_text: str = Form(""),
        provider: str = Form("ollama"),
        model: str = Form(""),
        resume_file: UploadFile = File(...),
        jd_file_upload: Optional[UploadFile] = File(None),
    ):
        session = _get_session(session_id or None, settings)
        session.provider = "web" if provider == "web" else "ollama"
        session.model = model.strip()

        resume_name = Path(resume_file.filename or "resume.docx").name
        resume_path = upload_dir / f"{session.session_id}_{resume_name}"
        with resume_path.open("wb") as f:
            shutil.copyfileobj(resume_file.file, f)

        jd_file = ""
        if jd_file_upload and jd_file_upload.filename:
            jname = Path(jd_file_upload.filename).name
            jpath = upload_dir / f"{session.session_id}_{jname}"
            with jpath.open("wb") as f:
                shutil.copyfileobj(jd_file_upload.file, f)
            # If text file, use as jd_file; otherwise still try as text
            jd_file = str(jpath)
        elif jd_text.strip():
            jd_path = upload_dir / f"{session.session_id}_jd.txt"
            jd_path.write_text(jd_text, encoding="utf-8")
            jd_file = str(jd_path)

        if not url.strip() and not jd_file:
            session.error = "Provide a JD URL, paste text, or upload a JD file."
            session.step = "ingest"
            return _TEMPLATES.TemplateResponse(
                "wizard.html",
                _ctx(request, settings, session),
                status_code=400,
            )

        apply_ingest_to_session(
            session,
            resume_path=str(resume_path),
            url=url.strip(),
            jd_file=jd_file,
            settings=settings,
        )
        return RedirectResponse(f"/?session_id={session.session_id}", status_code=303)

    @app.post("/review-save")
    async def review_save(
        session_id: str = Form(...),
        summary: str = Form(""),
        skills: str = Form(""),
        notes: str = Form(""),
        skip_llm: Optional[str] = Form(None),
    ):
        session = _get_session(session_id, settings)
        apply_review_corrections_to_session(
            session, summary=summary, skills=skills, notes=notes
        )
        apply_match_audit_to_session(
            session, settings, skip_llm=skip_llm is not None
        )
        return RedirectResponse(f"/?session_id={session.session_id}", status_code=303)

    @app.post("/refresh")
    async def refresh(
        request: Request,
        session_id: str = Form(...),
        target: str = Form("both"),  # jd | resume | both
        url: str = Form(""),
        jd_text: str = Form(""),
        resume_file: Optional[UploadFile] = File(None),
        jd_file_upload: Optional[UploadFile] = File(None),
    ):
        session = _get_session(session_id, settings)
        if session.step not in {"review", "match_audit"}:
            # Allow refresh from review; if later steps, snap back to review after refresh
            pass

        if url.strip():
            session.url = url.strip()

        if jd_text.strip():
            jd_path = upload_dir / f"{session.session_id}_jd.txt"
            jd_path.write_text(jd_text, encoding="utf-8")
            session.jd_file = str(jd_path)
            session.url = ""  # prefer pasted/file content for this refresh

        if jd_file_upload and jd_file_upload.filename:
            jname = Path(jd_file_upload.filename).name
            jpath = upload_dir / f"{session.session_id}_{jname}"
            with jpath.open("wb") as f:
                shutil.copyfileobj(jd_file_upload.file, f)
            session.jd_file = str(jpath)

        if resume_file and resume_file.filename:
            resume_name = Path(resume_file.filename).name
            resume_path = upload_dir / f"{session.session_id}_{resume_name}"
            with resume_path.open("wb") as f:
                shutil.copyfileobj(resume_file.file, f)
            session.resume_path = str(resume_path)

        if target == "jd":
            refresh_jd_in_session(
                session, url=session.url, jd_file=session.jd_file, settings=settings
            )
        elif target == "resume":
            refresh_resume_in_session(
                session, resume_path=session.resume_path, settings=settings
            )
        else:
            refresh_ingest_in_session(session, settings=settings)

        session.step = "review"
        return RedirectResponse(f"/?session_id={session.session_id}", status_code=303)

    @app.post("/audit", response_class=HTMLResponse)
    async def audit(
        session_id: str = Form(...),
        skip_llm: Optional[str] = Form(None),
    ):
        session = _get_session(session_id, settings)
        apply_match_audit_to_session(
            session, settings, skip_llm=skip_llm is not None
        )
        return RedirectResponse(f"/?session_id={session.session_id}", status_code=303)

    @app.post("/to-hitl")
    async def to_hitl(session_id: str = Form(...)):
        session = _get_session(session_id, settings)
        if session.step in {"match_audit", "review"}:
            session.step = "hitl"
        return RedirectResponse(f"/?session_id={session.session_id}", status_code=303)

    @app.post("/rewrite", response_class=HTMLResponse)
    async def rewrite(
        request: Request,
        session_id: str = Form(...),
        salary: str = Form(""),
        work_years: str = Form(""),
        work_base: str = Form(""),
        template_choice: str = Form("source"),
        agree: Optional[str] = Form(None),
        allow_fallback: Optional[str] = Form(None),
        export_pdf: Optional[str] = Form(None),
        template_file: Optional[UploadFile] = File(None),
    ):
        session = _get_session(session_id, settings)
        if agree is None:
            session.error = "Please confirm agreement to proceed with rewrite."
            session.step = "hitl"
            return _TEMPLATES.TemplateResponse(
                "wizard.html",
                _ctx(request, settings, session),
                status_code=400,
            )

        template_arg: Optional[str] = None
        if template_file and template_file.filename:
            tname = Path(template_file.filename).name
            tpath = settings.templates_dir / tname
            with tpath.open("wb") as f:
                shutil.copyfileobj(template_file.file, f)
            template_arg = str(tpath)
        elif template_choice and template_choice != "source":
            template_arg = template_choice

        apply_rewrite_to_session(
            session,
            settings,
            salary=salary,
            work_years=work_years,
            work_base=work_base,
            template=template_arg,
            customer_agreed_to_rewrite=True,
            allow_fallback=allow_fallback is not None,
            export_pdf=export_pdf is not None,
        )
        return RedirectResponse(f"/?session_id={session.session_id}", status_code=303)

    @app.post("/restart")
    async def restart(session_id: str = Form("")):
        if session_id in _SESSIONS:
            del _SESSIONS[session_id]
        return RedirectResponse("/", status_code=303)

    @app.get("/download")
    async def download(path: str):
        p = Path(path).resolve()
        out = settings.output_dir.resolve()
        if out not in p.parents and p.parent != out:
            return HTMLResponse("Forbidden", status_code=403)
        if not p.is_file():
            return HTMLResponse("Not found", status_code=404)
        return FileResponse(p, filename=p.name)

    return app


def run_web(settings: Settings, host: str = "127.0.0.1", port: int = 8765) -> None:
    import uvicorn

    app = create_app(settings)
    uvicorn.run(app, host=host, port=port, log_level="info")
