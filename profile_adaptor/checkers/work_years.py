"""Work years match: JD requirement vs human HITL and resume tenure."""

from __future__ import annotations

from typing import Optional

from profile_adaptor.checkers.matching import (
    estimate_resume_years,
    extract_required_years,
    parse_human_years,
)
from profile_adaptor.models import CheckResult, HitlContext, JobDescription, ResumeDocument


def check_work_years_match(
    jd: JobDescription,
    resume: ResumeDocument,
    hitl: Optional[HitlContext] = None,
) -> CheckResult:
    jd_text = f"{jd.requirements}\n{jd.raw_text}"
    required = extract_required_years(jd_text)
    human = parse_human_years(hitl.work_years) if hitl and hitl.work_years else None
    resume_years = estimate_resume_years(resume)

    missing = []
    if hitl is not None and human is None and (hitl.work_years or "").strip():
        missing.append("human_work_years_unparsed")

    # Prefer human-confirmed years; fall back to resume estimate
    candidate = human if human is not None else resume_years
    source_label = "human" if human is not None else "resume"

    if required is None:
        return CheckResult(
            name="work_years_match",
            ok=True,
            severity="info",
            message=(
                "JD has no explicit years requirement"
                + (f"; {source_label}≈{candidate:g}y" if candidate is not None else "")
                + "."
            ),
            missing_fields=missing,
        )

    if candidate is None:
        return CheckResult(
            name="work_years_match",
            ok=False,
            severity="error",
            message=f"Cannot verify work years against JD requirement of {required:g}+ years.",
            missing_fields=missing or ["work_years"],
        )

    gap = required - candidate
    human_vs_resume = ""
    if human is not None and resume_years is not None and abs(human - resume_years) >= 3:
        human_vs_resume = (
            f" Notice: human years ({human:g}) differ from resume tenure estimate (≈{resume_years:.0f})."
        )

    if gap <= 0:
        return CheckResult(
            name="work_years_match",
            ok=True,
            severity="info",
            message=(
                f"Work years match: {source_label}={candidate:g}y meets JD {required:g}+ years."
                + human_vs_resume
            ),
            missing_fields=missing,
        )

    if gap < 2:
        return CheckResult(
            name="work_years_match",
            ok=False,
            severity="warn",
            message=(
                f"Work years slight gap: {source_label}={candidate:g}y vs JD {required:g}+ years."
                + human_vs_resume
            ),
            missing_fields=["years_gap"],
        )

    return CheckResult(
        name="work_years_match",
        ok=False,
        severity="error",
        message=(
            f"Large work-years gap: {source_label}={candidate:g}y vs JD requires {required:g}+ years. "
            "Confirm HITL years or choose another JD before rewriting."
            + human_vs_resume
        ),
        missing_fields=["years_large_gap"],
    )
