"""Aggregate pre-rewrite checkers: JD ↔ resume ↔ HITL matching."""

from __future__ import annotations

from typing import Optional

from profile_adaptor.checkers.education import check_education
from profile_adaptor.checkers.job_content import check_job_content
from profile_adaptor.checkers.job_requirements import check_job_requirements
from profile_adaptor.checkers.salary_base import check_salary_base_agreement
from profile_adaptor.checkers.skills_match import check_skills_match
from profile_adaptor.checkers.work_experience import check_work_experience
from profile_adaptor.checkers.work_years import check_work_years_match
from profile_adaptor.models import (
    CheckReport,
    CheckResult,
    HitlContext,
    JobDescription,
    ResumeDocument,
)


def _jd_hint_notice(jd: JobDescription) -> CheckResult:
    parts = []
    if (jd.salary_hints or "").strip():
        parts.append(f"JD salary hint: {jd.salary_hints.strip()}")
    else:
        parts.append("JD has no clear salary hint (optional HITL).")
    if (jd.location_hints or "").strip():
        parts.append(f"JD location hint: {jd.location_hints.strip()}")
    else:
        parts.append("JD has no clear location hint (optional HITL).")
    return CheckResult(
        name="salary_location_hints",
        ok=True,
        severity="info",
        message=" ".join(parts),
        missing_fields=[],
    )


def run_structural_checkers(jd: JobDescription, resume: ResumeDocument) -> CheckReport:
    """Match audit before HITL: structural + years from resume + skills + JD hints."""
    results = [
        check_job_requirements(jd),
        check_work_experience(resume),
        check_job_content(jd, resume),
        check_skills_match(jd, resume),
        check_education(jd, resume),
        check_work_years_match(jd, resume, hitl=None),
        _jd_hint_notice(jd),
    ]
    return CheckReport(results=results)


def run_hitl_checkers(
    jd: JobDescription,
    resume: ResumeDocument,
    hitl: HitlContext,
) -> CheckReport:
    """Optional years/salary/base checks after human context (non-blocking when blank)."""
    results = []
    if (hitl.work_years or "").strip():
        results.append(check_work_years_match(jd, resume, hitl))
    else:
        results.append(check_work_years_match(jd, resume, hitl=None))
    results.append(check_salary_base_agreement(jd, hitl))
    return CheckReport(results=results)


def run_all_checkers(
    jd: JobDescription,
    resume: ResumeDocument,
    hitl: Optional[HitlContext] = None,
) -> CheckReport:
    structural = run_structural_checkers(jd, resume)
    if hitl is None:
        return structural
    hitl_checks = run_hitl_checkers(jd, resume, hitl)
    kept = [
        r
        for r in structural.results
        if r.name not in {"work_years_match", "salary_location_hints"}
    ]
    return CheckReport(results=kept + hitl_checks.results)
