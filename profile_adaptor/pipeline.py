"""Shared orchestration: staged ingest → match audit → HITL agreement → rewrite."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Optional

from profile_adaptor.audit.fidelity import audit_fidelity
from profile_adaptor.audit.match_audit import llm_match_audit, merge_llm_into_checks
from profile_adaptor.checkers.report import run_hitl_checkers, run_structural_checkers
from profile_adaptor.config import Settings
from profile_adaptor.crawler.jd_crawler import load_job_description
from profile_adaptor.event_log import EventLog, setup_app_logging
from profile_adaptor.export.docx_filler import create_docx_from_adapted, fill_docx
from profile_adaptor.export.pdf_export import export_pdf
from profile_adaptor.hitl.gates import build_hitl, validate_hitl
from profile_adaptor.hitl.template_selector import resolve_template
from profile_adaptor.llm import create_llm_client
from profile_adaptor.llm.rewriter import rewrite_resume
from profile_adaptor.models import (
    CheckReport,
    JobDescription,
    PipelineResult,
    ResumeDocument,
    WizardSession,
)
from profile_adaptor.parse.resume_parser import parse_resume

setup_app_logging()


def new_run_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:6]


def _ensure_session_log(session: WizardSession, settings: Optional[Settings] = None) -> EventLog:
    log = session.event_log
    if not isinstance(log, EventLog):
        log = EventLog(session_id=session.session_id)
        session.event_log = log
    if session.run_id:
        log.run_id = session.run_id
    if settings is not None:
        log.bind(log_dir=settings.output_dir)
    session.events = log.to_list()
    return log


def _sync_session_events(session: WizardSession) -> None:
    if isinstance(session.event_log, EventLog):
        session.events = session.event_log.to_list()


def ingest_sources(
    resume_path: str,
    url: Optional[str] = None,
    jd_file: Optional[str] = None,
    event_log: Optional[EventLog] = None,
) -> PipelineResult:
    """Step 1–2: fetch JD + parse resume."""
    run_id = new_run_id()
    log = event_log or EventLog(run_id=run_id)
    log.bind(run_id=run_id)
    log.started(
        "ingest",
        "Starting JD fetch and resume parse",
        progress=0.0,
        url=url or "",
        jd_file=jd_file or "",
        resume_path=resume_path,
    )
    try:
        log.progress("ingest", "Fetching / loading job description", 0.25)
        jd = load_job_description(url=url, jd_file=jd_file)
        log.progress(
            "ingest",
            f"JD loaded: {jd.title or '(untitled)'}",
            0.55,
            title=jd.title,
            company=jd.company,
        )
        log.progress("ingest", "Parsing resume", 0.7, resume_path=resume_path)
        resume = parse_resume(resume_path)
        log.result(
            "ingest",
            "Ingest complete",
            progress=1.0,
            status="ok",
            jd_title=jd.title,
            resume_format=resume.source_format,
            skills_count=len(resume.skills),
            experience_count=len(resume.experience),
        )
        return PipelineResult(
            run_id=run_id,
            jd=jd,
            resume=resume,
            step="review",
            events_jsonl=log.path,
        )
    except Exception as exc:
        log.error("ingest", str(exc), progress=1.0)
        return PipelineResult(
            run_id=run_id, step="ingest", error=str(exc), events_jsonl=log.path
        )


def apply_resume_corrections(
    resume: ResumeDocument,
    summary: Optional[str] = None,
    skills: Optional[str] = None,
    notes: Optional[str] = None,
) -> ResumeDocument:
    """Light Review-step corrections before match audit."""
    if summary is not None:
        resume.summary = summary.strip()
    if skills is not None:
        parts = [p.strip() for p in skills.replace("\n", ",").split(",")]
        resume.skills = [p for p in parts if p]
    if notes is not None:
        resume.extras = notes.strip()
    return resume


def run_match_audit_stage(
    settings: Settings,
    jd: JobDescription,
    resume: ResumeDocument,
    run_id: Optional[str] = None,
    skip_llm: bool = False,
    event_log: Optional[EventLog] = None,
) -> PipelineResult:
    """Step 3–4: rule + LLM match audit; surface gaps as notices."""
    rid = run_id or new_run_id()
    settings.ensure_dirs()
    log = event_log or EventLog(run_id=rid, log_dir=settings.output_dir)
    log.bind(run_id=rid, log_dir=settings.output_dir)
    log.started("match_audit", "Starting match audit", progress=0.0, skip_llm=skip_llm)
    try:
        log.progress("match_audit", "Running structural checkers", 0.3)
        rule_checks = run_structural_checkers(jd, resume)
        match_audit = None
        checks = rule_checks
        if not skip_llm:
            log.progress("match_audit", "Running LLM match audit", 0.6, provider=settings.provider)
            client = create_llm_client(settings)
            match_audit = llm_match_audit(client, jd, resume, rule_checks)
            checks = merge_llm_into_checks(rule_checks, match_audit)

        error = None
        status = "ok"
        if checks.has_errors or (match_audit and match_audit.has_high):
            error = (
                "Match gaps detected between JD and resume. Review notices, "
                "then agree to proceed with rewrite."
            )
            status = "warn"
        log.result(
            "match_audit",
            error or "Match audit complete",
            progress=1.0,
            status=status,
            has_errors=checks.has_errors,
            has_warnings=checks.has_warnings,
            notices=checks.notices[:10],
            check_count=len(checks.results),
        )
        return PipelineResult(
            run_id=rid,
            jd=jd,
            resume=resume,
            checks=checks,
            match_audit=match_audit,
            step="hitl",
            error=error,
            events_jsonl=log.path,
        )
    except Exception as exc:
        log.error("match_audit", str(exc), progress=1.0)
        return PipelineResult(
            run_id=rid,
            jd=jd,
            resume=resume,
            step="match_audit",
            error=str(exc),
            events_jsonl=log.path,
        )


def rewrite_with_hitl(
    settings: Settings,
    jd: JobDescription,
    resume: ResumeDocument,
    salary: str = "",
    work_years: str = "",
    work_base: str = "",
    template: Optional[str] = None,
    customer_agreed_to_rewrite: bool = False,
    allow_fallback: bool = True,
    skip_llm_audit: bool = False,
    prior_checks=None,
    prior_match_audit=None,
    run_id: Optional[str] = None,
    event_log: Optional[EventLog] = None,
) -> PipelineResult:
    """Step 5: after customer agreement, rewrite (optional HITL context fields)."""
    rid = run_id or new_run_id()
    settings.ensure_dirs()
    log = event_log or EventLog(run_id=rid, log_dir=settings.output_dir)
    log.bind(run_id=rid, log_dir=settings.output_dir)
    log.started(
        "rewrite",
        "Starting rewrite after HITL agreement",
        progress=0.0,
        agreed=customer_agreed_to_rewrite,
    )

    hitl = build_hitl(
        salary=salary,
        work_years=work_years,
        work_base=work_base,
        template_path=template,
        use_source_layout=not bool((template or "").strip()),
        customer_agreed_to_rewrite=customer_agreed_to_rewrite,
    )
    ok_hitl, hitl_errors = validate_hitl(hitl)
    if not ok_hitl:
        msg = "HITL validation failed: " + "; ".join(hitl_errors)
        log.error("hitl", msg, progress=1.0)
        return PipelineResult(
            run_id=rid,
            jd=jd,
            resume=resume,
            hitl=hitl,
            checks=prior_checks,
            match_audit=prior_match_audit,
            step="hitl",
            error=msg,
            events_jsonl=log.path,
        )
    log.status("hitl", "ok", "Customer agreed to rewrite", progress=0.15)

    try:
        structural = prior_checks or run_structural_checkers(jd, resume)
        hitl_checks = run_hitl_checkers(jd, resume, hitl)
        kept = [
            r
            for r in structural.results
            if r.name not in {"work_years_match", "salary_location_hints"}
        ]
        checks = CheckReport(results=kept + hitl_checks.results)

        if checks.has_errors and not hitl.customer_agreed_to_rewrite:
            gap_lines = "\n".join(f"  - {n}" for n in checks.notices) or "  - (see checks)"
            msg = "Gaps remain. Agree to proceed with rewrite to continue.\n" + gap_lines
            log.error("rewrite", msg, progress=1.0)
            return PipelineResult(
                run_id=rid,
                jd=jd,
                resume=resume,
                checks=checks,
                match_audit=prior_match_audit,
                hitl=hitl,
                step="hitl",
                error=msg,
                events_jsonl=log.path,
            )

        log.progress("rewrite", "Resolving template", 0.25)
        tmpl_path, use_source = resolve_template(
            settings.templates_dir,
            template,
            resume.source_path,
            resume.source_format,
        )
        hitl.template_path = str(tmpl_path) if tmpl_path else None
        hitl.use_source_layout = use_source

        log.progress("rewrite", f"Calling LLM ({settings.provider}/{settings.model})", 0.4)
        client = create_llm_client(settings)
        try:
            adapted = rewrite_resume(
                client, jd, resume, hitl, allow_fallback=allow_fallback
            )
        except RuntimeError as exc:
            log.error("rewrite", str(exc), progress=1.0)
            return PipelineResult(
                run_id=rid,
                jd=jd,
                resume=resume,
                checks=checks,
                match_audit=prior_match_audit,
                hitl=hitl,
                step="hitl",
                error=str(exc),
                events_jsonl=log.path,
            )

        if adapted.used_fallback:
            log.status(
                "rewrite",
                "warn",
                f"LLM fallback used: {adapted.fallback_reason}",
                progress=0.55,
            )
        else:
            log.progress("rewrite", "LLM rewrite complete", 0.55)

        # Skip LLM fidelity when rewrite already fell back — Ollama is likely unavailable/slow.
        use_llm_fidelity = (not skip_llm_audit) and (not adapted.used_fallback)
        log.progress(
            "rewrite",
            "Running fidelity audit" + ("" if use_llm_fidelity else " (rules only)"),
            0.7,
        )
        audit = audit_fidelity(
            resume,
            adapted,
            client=client if use_llm_fidelity else None,
        )

        if settings.strict and audit.has_high:
            audit_path = settings.output_dir / f"{rid}_audit.json"
            audit_path.write_text(
                json.dumps(audit.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            msg = "Strict mode: high-severity fidelity flags detected."
            log.error("rewrite", msg, progress=1.0, audit=audit.to_dict())
            return PipelineResult(
                run_id=rid,
                jd=jd,
                resume=resume,
                checks=checks,
                match_audit=prior_match_audit,
                hitl=hitl,
                adapted=adapted,
                audit=audit,
                audit_json=str(audit_path),
                events_jsonl=log.path,
                step="done",
                error=msg,
            )

        log.progress("export", "Filling DOCX template", 0.85)
        out_docx = settings.output_dir / f"{rid}_adapted.docx"
        try:
            _, fill_report = fill_docx(tmpl_path, adapted, out_docx)
        except Exception as fill_exc:
            _, fill_report = create_docx_from_adapted(adapted, out_docx)
            fill_report.notes.append(f"Template fill failed ({fill_exc}); used clean DOCX.")

        out_pdf = None
        if settings.export_pdf:
            log.progress("export", "Exporting PDF", 0.92)
            out_pdf = export_pdf(out_docx, adapted, settings.output_dir)

        context_path = settings.output_dir / f"{rid}_context.json"
        context_path.write_text(
            json.dumps(
                {
                    "run_id": rid,
                    "provider": settings.provider,
                    "model": settings.model,
                    "hitl": hitl.to_dict(),
                    "checks": checks.to_dict(),
                    "match_audit": prior_match_audit.to_dict() if prior_match_audit else None,
                    "change_log": adapted.change_log,
                    "used_fallback": adapted.used_fallback,
                    "fallback_reason": adapted.fallback_reason,
                    "fill_report": fill_report.to_dict(),
                    "events": log.to_list(),
                    "jd_source": jd.source,
                    "resume_source": resume.source_path,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        audit_path = settings.output_dir / f"{rid}_audit.json"
        audit_path.write_text(
            json.dumps(audit.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        log.result(
            "export",
            "Rewrite and export complete",
            progress=1.0,
            status="ok",
            output_docx=str(out_docx),
            output_pdf=str(out_pdf) if out_pdf else None,
            fill_report=fill_report.to_dict(),
            used_fallback=adapted.used_fallback,
        )
        return PipelineResult(
            run_id=rid,
            jd=jd,
            resume=resume,
            checks=checks,
            match_audit=prior_match_audit,
            hitl=hitl,
            adapted=adapted,
            audit=audit,
            fill_report=fill_report,
            output_docx=str(out_docx),
            output_pdf=str(out_pdf) if out_pdf else None,
            context_json=str(context_path),
            audit_json=str(audit_path),
            events_jsonl=log.path,
            step="done",
        )
    except Exception as exc:
        log.error("rewrite", str(exc), progress=1.0)
        return PipelineResult(
            run_id=rid,
            jd=jd,
            resume=resume,
            hitl=hitl,
            checks=prior_checks,
            match_audit=prior_match_audit,
            step="hitl",
            error=str(exc),
            events_jsonl=log.path,
        )


def run_pipeline(
    settings: Settings,
    resume_path: str,
    salary: str = "",
    work_years: str = "",
    work_base: str = "",
    url: Optional[str] = None,
    jd_file: Optional[str] = None,
    template: Optional[str] = None,
    agree: bool = False,
    allow_fallback: bool = True,
    skip_llm_audit: bool = False,
) -> PipelineResult:
    """One-shot CLI path: ingest → match audit → agreement → rewrite."""
    settings.ensure_dirs()
    run_id = new_run_id()
    log = EventLog(run_id=run_id, log_dir=settings.output_dir)
    log.started("pipeline", "CLI one-shot pipeline started", progress=0.0)

    ingested = ingest_sources(
        resume_path=resume_path, url=url, jd_file=jd_file, event_log=log
    )
    ingested.run_id = run_id
    if ingested.error or not ingested.jd or not ingested.resume:
        log.error("pipeline", ingested.error or "Ingest failed", progress=1.0)
        ingested.events_jsonl = log.path
        return ingested

    audited = run_match_audit_stage(
        settings,
        ingested.jd,
        ingested.resume,
        run_id=run_id,
        skip_llm=skip_llm_audit,
        event_log=log,
    )
    result = rewrite_with_hitl(
        settings=settings,
        jd=ingested.jd,
        resume=ingested.resume,
        salary=salary,
        work_years=work_years,
        work_base=work_base,
        template=template,
        customer_agreed_to_rewrite=agree,
        allow_fallback=allow_fallback,
        skip_llm_audit=skip_llm_audit,
        prior_checks=audited.checks,
        prior_match_audit=audited.match_audit,
        run_id=run_id,
        event_log=log,
    )
    result.events_jsonl = log.path
    return result


def apply_ingest_to_session(
    session: WizardSession,
    resume_path: str,
    url: str = "",
    jd_file: str = "",
    settings: Optional[Settings] = None,
) -> WizardSession:
    session.url = url
    session.jd_file = jd_file
    session.resume_path = resume_path
    log = _ensure_session_log(session, settings)
    result = ingest_sources(
        resume_path=resume_path,
        url=url or None,
        jd_file=jd_file or None,
        event_log=log,
    )
    session.run_id = result.run_id
    log.bind(run_id=result.run_id, log_dir=settings.output_dir if settings else log.log_dir)
    session.error = result.error
    _sync_session_events(session)
    if result.error:
        session.step = "ingest"
        return session
    session.jd = result.jd
    session.resume = result.resume
    session.step = "review"
    session.notices = []
    session.checks = None
    session.match_audit = None
    return session


def refresh_jd_in_session(
    session: WizardSession,
    url: Optional[str] = None,
    jd_file: Optional[str] = None,
    settings: Optional[Settings] = None,
) -> WizardSession:
    """Re-fetch / re-structure JD only; keep current resume."""
    log = _ensure_session_log(session, settings)
    use_url = (url if url is not None else session.url) or ""
    use_file = (jd_file if jd_file is not None else session.jd_file) or ""
    if url is not None:
        session.url = use_url
    if jd_file is not None:
        session.jd_file = use_file
    log.started("refresh_jd", "Refreshing job description", progress=0.0)
    try:
        session.jd = load_job_description(
            url=use_url or None,
            jd_file=use_file or None,
        )
        session.error = None
        session.step = "review"
        session.checks = None
        session.match_audit = None
        session.notices = []
        log.result(
            "refresh_jd",
            f"JD refreshed: {session.jd.title or '(untitled)'}",
            progress=1.0,
            title=session.jd.title,
        )
    except Exception as exc:
        session.error = f"JD refresh failed: {exc}"
        log.error("refresh_jd", session.error, progress=1.0)
    _sync_session_events(session)
    return session


def refresh_resume_in_session(
    session: WizardSession,
    resume_path: Optional[str] = None,
    settings: Optional[Settings] = None,
) -> WizardSession:
    """Re-parse resume only; keep current JD."""
    log = _ensure_session_log(session, settings)
    path = resume_path or session.resume_path
    if resume_path:
        session.resume_path = path
    if not path:
        session.error = "No resume path to refresh."
        log.error("refresh_resume", session.error)
        _sync_session_events(session)
        return session
    log.started("refresh_resume", "Re-parsing resume", progress=0.0, path=path)
    try:
        session.resume = parse_resume(path)
        session.error = None
        session.step = "review"
        session.checks = None
        session.match_audit = None
        session.notices = []
        log.result(
            "refresh_resume",
            "Resume refreshed",
            progress=1.0,
            format=session.resume.source_format,
            skills=len(session.resume.skills),
        )
    except Exception as exc:
        session.error = f"Resume refresh failed: {exc}"
        log.error("refresh_resume", session.error, progress=1.0)
    _sync_session_events(session)
    return session


def refresh_ingest_in_session(
    session: WizardSession,
    settings: Optional[Settings] = None,
) -> WizardSession:
    """Re-run both JD fetch and resume parse from session sources."""
    return apply_ingest_to_session(
        session,
        resume_path=session.resume_path,
        url=session.url,
        jd_file=session.jd_file,
        settings=settings,
    )


def apply_review_corrections_to_session(
    session: WizardSession,
    summary: Optional[str] = None,
    skills: Optional[str] = None,
    notes: Optional[str] = None,
) -> WizardSession:
    log = _ensure_session_log(session)
    if not session.resume:
        session.error = "No resume to correct."
        log.error("review", session.error)
        _sync_session_events(session)
        return session
    session.resume = apply_resume_corrections(
        session.resume, summary=summary, skills=skills, notes=notes
    )
    log.status("review", "ok", "Applied summary/skills/notes corrections", progress=0.5)
    _sync_session_events(session)
    return session


def apply_match_audit_to_session(
    session: WizardSession,
    settings: Settings,
    skip_llm: bool = False,
) -> WizardSession:
    log = _ensure_session_log(session, settings)
    if not session.jd or not session.resume:
        session.error = "Ingest JD and resume first."
        session.step = "ingest"
        log.error("match_audit", session.error)
        _sync_session_events(session)
        return session
    if session.provider:
        settings.provider = session.provider  # type: ignore
    if session.model:
        if settings.provider == "ollama":
            settings.ollama_model = session.model
        else:
            settings.web_llm_model = session.model
    result = run_match_audit_stage(
        settings,
        session.jd,
        session.resume,
        run_id=session.run_id or None,
        skip_llm=skip_llm,
        event_log=log,
    )
    session.checks = result.checks
    session.match_audit = result.match_audit
    session.notices = list(result.checks.notices) if result.checks else []
    if result.match_audit and result.match_audit.has_high:
        session.notices.append(result.match_audit.summary)
    session.error = result.error
    session.step = "match_audit"
    _sync_session_events(session)
    return session


def apply_rewrite_to_session(
    session: WizardSession,
    settings: Settings,
    salary: str = "",
    work_years: str = "",
    work_base: str = "",
    template: Optional[str] = None,
    customer_agreed_to_rewrite: bool = False,
    allow_fallback: bool = True,
    export_pdf: bool = False,
    skip_llm_audit: bool = False,
) -> WizardSession:
    log = _ensure_session_log(session, settings)
    if not session.jd or not session.resume:
        session.error = "Ingest JD and resume first."
        session.step = "ingest"
        log.error("rewrite", session.error)
        _sync_session_events(session)
        return session
    settings.export_pdf = export_pdf
    if session.provider:
        settings.provider = session.provider  # type: ignore
    if session.model:
        if settings.provider == "ollama":
            settings.ollama_model = session.model
        else:
            settings.web_llm_model = session.model

    result = rewrite_with_hitl(
        settings=settings,
        jd=session.jd,
        resume=session.resume,
        salary=salary,
        work_years=work_years,
        work_base=work_base,
        template=template,
        customer_agreed_to_rewrite=customer_agreed_to_rewrite,
        allow_fallback=allow_fallback,
        skip_llm_audit=skip_llm_audit,
        prior_checks=session.checks,
        prior_match_audit=session.match_audit,
        run_id=session.run_id or None,
        event_log=log,
    )
    session.hitl = result.hitl
    session.checks = result.checks or session.checks
    session.result = result
    if not result.events_jsonl and log.path:
        result.events_jsonl = log.path
    _sync_session_events(session)
    if result.error:
        session.error = result.error
        session.step = "hitl"
    else:
        session.error = None
        session.step = "done"
        session.notices = (
            list(result.checks.notices)
            if result.checks and result.checks.has_warnings
            else []
        )
    return session
