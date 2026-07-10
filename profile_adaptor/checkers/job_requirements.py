"""Job requirements checker."""

from __future__ import annotations

from profile_adaptor.models import CheckResult, JobDescription


def check_job_requirements(jd: JobDescription) -> CheckResult:
    text = (jd.requirements or "").strip()
    missing = []
    if len(text) < 30:
        missing.append("requirements")
    ok = not missing
    return CheckResult(
        name="job_requirements",
        ok=ok,
        severity="error" if not ok else "info",
        message=(
            "Job requirements section present."
            if ok
            else "Job requirements missing or too short."
        ),
        missing_fields=missing,
    )
