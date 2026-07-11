"""Education presence + JD education requirement match."""

from __future__ import annotations

from profile_adaptor.checkers.matching import jd_required_degree, resume_highest_degree
from profile_adaptor.models import CheckResult, JobDescription, ResumeDocument

_LEVEL_NAME = {4: "PhD", 3: "Master", 2: "Bachelor", 1: "Associate"}


def check_education(jd: JobDescription, resume: ResumeDocument) -> CheckResult:
    missing = []
    if not resume.education:
        missing.append("education_entries")
    else:
        first = resume.education[0]
        if not (first.school or "").strip():
            missing.append("school")
        if not (first.degree or first.time_range or "").strip():
            missing.append("degree_or_time")

    if missing:
        return CheckResult(
            name="education_match",
            ok=False,
            severity="error",
            message=f"Education incomplete on resume: {', '.join(missing)}",
            missing_fields=missing,
        )

    required = jd_required_degree(jd)
    have = resume_highest_degree(resume)

    if required is None:
        return CheckResult(
            name="education_match",
            ok=True,
            severity="info",
            message="Education present; JD has no explicit degree requirement to match.",
            missing_fields=[],
        )

    if have is None:
        return CheckResult(
            name="education_match",
            ok=False,
            severity="warn",
            message=(
                f"JD expects {_LEVEL_NAME.get(required, required)}-level education, "
                "but degree level could not be inferred from the resume."
            ),
            missing_fields=["degree_level_unparsed"],
        )

    if have >= required:
        return CheckResult(
            name="education_match",
            ok=True,
            severity="info",
            message=(
                f"Education matches: resume {_LEVEL_NAME.get(have, have)} "
                f"meets JD {_LEVEL_NAME.get(required, required)}."
            ),
            missing_fields=[],
        )

    gap = required - have
    return CheckResult(
        name="education_match",
        ok=False,
        severity="error" if gap >= 1 else "warn",
        message=(
            f"Education gap: resume has {_LEVEL_NAME.get(have, have)}, "
            f"JD expects {_LEVEL_NAME.get(required, required)}. "
            "Review before rewriting."
        ),
        missing_fields=["education_level_gap"],
    )
