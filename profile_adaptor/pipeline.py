"""Shared orchestration for crawl → check → HITL → adapt → audit → export."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from profile_adaptor.audit.fidelity import audit_fidelity
from profile_adaptor.checkers.report import run_all_checkers
from profile_adaptor.config import Settings
from profile_adaptor.crawler.jd_crawler import load_job_description
from profile_adaptor.export.docx_filler import create_docx_from_adapted, fill_docx
from profile_adaptor.export.pdf_export import export_pdf
from profile_adaptor.hitl.gates import build_hitl, validate_hitl
from profile_adaptor.hitl.template_selector import resolve_template
from profile_adaptor.llm import create_llm_client
from profile_adaptor.llm.rewriter import rewrite_resume
from profile_adaptor.models import HitlContext, PipelineResult
from profile_adaptor.parse.resume_parser import parse_resume


def run_pipeline(
    settings: Settings,
    resume_path: str,
    salary: str,
    work_years: str,
    work_base: str,
    url: Optional[str] = None,
    jd_file: Optional[str] = None,
    template: Optional[str] = None,
    override_checker_errors: bool = False,
    skip_llm_audit: bool = False,
) -> PipelineResult:
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]
    settings.ensure_dirs()

    hitl = build_hitl(
        salary=salary,
        work_years=work_years,
        work_base=work_base,
        template_path=template,
        use_source_layout=not bool((template or "").strip()),
        override_checker_errors=override_checker_errors,
    )
    ok_hitl, hitl_errors = validate_hitl(hitl)
    if not ok_hitl:
        return PipelineResult(
            run_id=run_id,
            hitl=hitl,
            error="HITL validation failed: " + "; ".join(hitl_errors),
        )

    try:
        jd = load_job_description(url=url, jd_file=jd_file)
        resume = parse_resume(resume_path)
        checks = run_all_checkers(jd, resume)

        if checks.has_errors and not hitl.override_checker_errors:
            context_path = settings.output_dir / f"{run_id}_context.json"
            context_path.write_text(
                json.dumps(
                    {
                        "run_id": run_id,
                        "hitl": hitl.to_dict(),
                        "checks": checks.to_dict(),
                        "jd": jd.to_dict(),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            return PipelineResult(
                run_id=run_id,
                jd=jd,
                resume=resume,
                checks=checks,
                hitl=hitl,
                adapted=None,
                audit=None,
                context_json=str(context_path),
                error="Checker errors present. Re-run with --override-checkers or fix inputs.",
            )

        tmpl_path, use_source = resolve_template(
            settings.templates_dir,
            template,
            resume.source_path,
            resume.source_format,
        )
        hitl.template_path = str(tmpl_path) if tmpl_path else None
        hitl.use_source_layout = use_source

        client = create_llm_client(settings)
        adapted = rewrite_resume(client, jd, resume, hitl)
        audit = audit_fidelity(
            resume,
            adapted,
            client=None if skip_llm_audit else client,
        )

        if settings.strict and audit.has_high:
            audit_path = settings.output_dir / f"{run_id}_audit.json"
            audit_path.write_text(
                json.dumps(audit.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return PipelineResult(
                run_id=run_id,
                jd=jd,
                resume=resume,
                checks=checks,
                hitl=hitl,
                adapted=adapted,
                audit=audit,
                audit_json=str(audit_path),
                error="Strict mode: high-severity fidelity flags detected.",
            )

        out_docx = settings.output_dir / f"{run_id}_adapted.docx"
        try:
            fill_docx(tmpl_path, adapted, out_docx)
        except Exception:
            create_docx_from_adapted(adapted, out_docx)

        out_pdf = None
        if settings.export_pdf:
            out_pdf = export_pdf(out_docx, adapted, settings.output_dir)

        context_path = settings.output_dir / f"{run_id}_context.json"
        context_path.write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "provider": settings.provider,
                    "model": settings.model,
                    "hitl": hitl.to_dict(),
                    "checks": checks.to_dict(),
                    "change_log": adapted.change_log,
                    "jd_source": jd.source,
                    "resume_source": resume.source_path,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        audit_path = settings.output_dir / f"{run_id}_audit.json"
        audit_path.write_text(
            json.dumps(audit.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        return PipelineResult(
            run_id=run_id,
            jd=jd,
            resume=resume,
            checks=checks,
            hitl=hitl,
            adapted=adapted,
            audit=audit,
            output_docx=str(out_docx),
            output_pdf=str(out_pdf) if out_pdf else None,
            context_json=str(context_path),
            audit_json=str(audit_path),
        )
    except Exception as exc:
        return PipelineResult(
            run_id=run_id,
            hitl=hitl,
            error=str(exc),
        )
