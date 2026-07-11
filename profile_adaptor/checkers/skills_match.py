"""Skills ↔ JD requirements match checker."""

from __future__ import annotations

from profile_adaptor.checkers.matching import experience_blob, overlap_ratio, tokenize
from profile_adaptor.models import CheckResult, JobDescription, ResumeDocument


def check_skills_match(jd: JobDescription, resume: ResumeDocument) -> CheckResult:
    req_tokens = tokenize(jd.requirements or "")
    if len(req_tokens) < 3:
        # Fall back to broader JD text
        req_tokens = tokenize(f"{jd.requirements}\n{jd.responsibilities}\n{jd.title}")
    if not req_tokens:
        return CheckResult(
            name="skills_match",
            ok=True,
            severity="info",
            message="JD has few extractable skill keywords; skills match skipped.",
            missing_fields=[],
        )

    evidence = tokenize(
        " ".join(resume.skills)
        + "\n"
        + experience_blob(resume)
        + "\n"
        + (resume.summary or "")
    )
    ratio = overlap_ratio(req_tokens, evidence)
    missing = sorted(req_tokens - evidence)
    sample_missing = ", ".join(missing[:10])
    sample_matched = ", ".join(sorted(req_tokens & evidence)[:10])

    if ratio >= 0.35:
        return CheckResult(
            name="skills_match",
            ok=True,
            severity="info",
            message=(
                f"Skills align with JD requirements (overlap={ratio:.0%}; "
                f"matched: {sample_matched or 'n/a'})."
            ),
            missing_fields=[],
        )
    if ratio >= 0.18:
        return CheckResult(
            name="skills_match",
            ok=False,
            severity="warn",
            message=(
                f"Moderate skills gap vs JD requirements (overlap={ratio:.0%}). "
                f"Weak/missing: {sample_missing or 'n/a'}."
            ),
            missing_fields=["skills_moderate_gap"],
        )
    return CheckResult(
        name="skills_match",
        ok=False,
        severity="error",
        message=(
            f"Large skills gap vs JD requirements (overlap={ratio:.0%}). "
            f"Missing themes: {sample_missing or 'n/a'}."
        ),
        missing_fields=["skills_large_gap"],
    )
