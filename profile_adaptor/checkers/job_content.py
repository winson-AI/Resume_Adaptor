"""Primary job content completeness + match against resume work experience."""

from __future__ import annotations

from profile_adaptor.checkers.matching import job_content_vs_experience
from profile_adaptor.models import CheckResult, JobDescription, ResumeDocument


def check_job_content(jd: JobDescription, resume: ResumeDocument) -> CheckResult:
    missing = []
    text = (jd.responsibilities or "").strip()
    if len(text) < 40:
        missing.append("responsibilities")
    if not (jd.title or "").strip():
        missing.append("title")
    if missing:
        return CheckResult(
            name="job_content_match",
            ok=False,
            severity="error",
            message=f"Missing or thin primary job content: {', '.join(missing)}",
            missing_fields=missing,
        )

    if not resume.experience:
        return CheckResult(
            name="job_content_match",
            ok=False,
            severity="error",
            message="Cannot match job content: resume has no work experience entries.",
            missing_fields=["work_experience"],
        )

    ratio, matched, missing_toks = job_content_vs_experience(jd, resume)
    sample_missing = ", ".join(sorted(missing_toks)[:8])
    sample_matched = ", ".join(sorted(matched)[:8])

    if ratio >= 0.35:
        return CheckResult(
            name="job_content_match",
            ok=True,
            severity="info",
            message=(
                f"Job content aligns with work experience "
                f"(overlap={ratio:.0%}; matched: {sample_matched or 'n/a'})."
            ),
            missing_fields=[],
        )

    if ratio >= 0.18:
        return CheckResult(
            name="job_content_match",
            ok=False,
            severity="warn",
            message=(
                f"Moderate gap between JD job content and resume experience "
                f"(overlap={ratio:.0%}). Weak/missing themes: {sample_missing or 'n/a'}."
            ),
            missing_fields=["content_moderate_gap"],
        )

    return CheckResult(
        name="job_content_match",
        ok=False,
        severity="error",
        message=(
            f"Large gap between JD job content and resume work experience "
            f"(overlap={ratio:.0%}). Missing themes include: {sample_missing or 'n/a'}. "
            "Notice: rewriting may not be faithful — confirm or pick another JD/resume."
        ),
        missing_fields=["content_large_gap"],
    )
