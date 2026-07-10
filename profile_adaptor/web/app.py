"""Local FastAPI browser UI for Profile Adaptor."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from profile_adaptor.config import Settings
from profile_adaptor.hitl.template_selector import list_templates
from profile_adaptor.pipeline import run_pipeline

_WEB_DIR = Path(__file__).resolve().parent
_TEMPLATES = Jinja2Templates(directory=str(_WEB_DIR / "templates"))


def create_app(settings: Settings) -> FastAPI:
    settings.ensure_dirs()
    app = FastAPI(title="Profile Adaptor", version="0.1.0")
    upload_dir = settings.output_dir / "_uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request):
        templates = list_templates(settings.templates_dir)
        return _TEMPLATES.TemplateResponse(
            "index.html",
            {
                "request": request,
                "templates": templates,
                "provider": settings.provider,
                "model": settings.model,
                "result": None,
                "error": None,
            },
        )

    @app.post("/run", response_class=HTMLResponse)
    async def run(
        request: Request,
        url: str = Form(""),
        jd_text: str = Form(""),
        salary: str = Form(...),
        work_years: str = Form(...),
        work_base: str = Form(...),
        provider: str = Form("ollama"),
        model: str = Form(""),
        template_choice: str = Form("source"),
        export_pdf: Optional[str] = Form(None),
        override_checkers: Optional[str] = Form(None),
        resume_file: UploadFile = File(...),
        template_file: Optional[UploadFile] = File(None),
    ):
        settings.provider = "web" if provider == "web" else "ollama"
        if model.strip():
            if settings.provider == "ollama":
                settings.ollama_model = model.strip()
            else:
                settings.web_llm_model = model.strip()
        settings.export_pdf = export_pdf is not None

        # Save resume
        resume_name = Path(resume_file.filename or "resume.docx").name
        resume_path = upload_dir / resume_name
        with resume_path.open("wb") as f:
            shutil.copyfileobj(resume_file.file, f)

        # Optional uploaded template
        template_arg: Optional[str] = None
        if template_file and template_file.filename:
            tname = Path(template_file.filename).name
            tpath = settings.templates_dir / tname
            with tpath.open("wb") as f:
                shutil.copyfileobj(template_file.file, f)
            template_arg = str(tpath)
        elif template_choice and template_choice != "source":
            template_arg = template_choice

        jd_file = None
        if jd_text.strip():
            jd_path = upload_dir / "pasted_jd.txt"
            jd_path.write_text(jd_text, encoding="utf-8")
            jd_file = str(jd_path)

        if not url.strip() and not jd_file:
            templates = list_templates(settings.templates_dir)
            return _TEMPLATES.TemplateResponse(
                "index.html",
                {
                    "request": request,
                    "templates": templates,
                    "provider": settings.provider,
                    "model": settings.model,
                    "result": None,
                    "error": "Provide a JD URL or paste JD text.",
                },
                status_code=400,
            )

        result = run_pipeline(
            settings=settings,
            resume_path=str(resume_path),
            salary=salary,
            work_years=work_years,
            work_base=work_base,
            url=url.strip() or None,
            jd_file=jd_file,
            template=template_arg,
            override_checker_errors=override_checkers is not None,
        )

        templates = list_templates(settings.templates_dir)
        return _TEMPLATES.TemplateResponse(
            "index.html",
            {
                "request": request,
                "templates": templates,
                "provider": settings.provider,
                "model": settings.model,
                "result": result,
                "error": result.error,
            },
        )

    @app.get("/download")
    async def download(path: str):
        p = Path(path).resolve()
        # Restrict to output dir
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
