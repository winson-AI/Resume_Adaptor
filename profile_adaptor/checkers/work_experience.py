"""Work experience presence checker (structure)."""

from __future__ import annotations

from profile_adaptor.models import CheckResult, ResumeDocument


def check_work_experience(resume: ResumeDocument) -> CheckResult:
    missing = []
    if not resume.experience:
        missing.append("work_experience_entries")
    else:
        first = resume.experience[0]
        if not (first.employer or "").strip():
            missing.append("employer")
        if not (first.title or first.time_range or "").strip():
            missing.append("title_or_time")
        if not first.bullets:
            missing.append("bullets")
    ok = not missing
    return CheckResult(
        name="work_experience",
        ok=ok,
        severity="error" if not ok else "info",
        message=(
            "Work experience present."
            if ok
            else f"Work experience incomplete: {', '.join(missing)}"
        ),
        missing_fields=missing,
    )
