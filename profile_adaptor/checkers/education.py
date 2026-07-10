"""Education experience checker."""

from __future__ import annotations

from profile_adaptor.models import CheckResult, ResumeDocument


def check_education(resume: ResumeDocument) -> CheckResult:
    missing = []
    if not resume.education:
        missing.append("education_entries")
    else:
        first = resume.education[0]
        if not (first.school or "").strip():
            missing.append("school")
        if not (first.degree or first.time_range or "").strip():
            missing.append("degree_or_time")
    ok = not missing
    return CheckResult(
        name="education_experience",
        ok=ok,
        severity="warn" if not ok else "info",
        message=(
            "Education experience present."
            if ok
            else f"Education incomplete: {', '.join(missing)}"
        ),
        missing_fields=missing,
    )
