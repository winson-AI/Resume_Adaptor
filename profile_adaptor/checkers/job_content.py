"""Primary job content checker."""

from __future__ import annotations

from profile_adaptor.models import CheckResult, JobDescription


def check_job_content(jd: JobDescription) -> CheckResult:
    missing = []
    text = (jd.responsibilities or "").strip()
    if len(text) < 40:
        missing.append("responsibilities")
    if not (jd.title or "").strip():
        missing.append("title")
    ok = len(missing) == 0
    return CheckResult(
        name="primary_job_content",
        ok=ok,
        severity="error" if not ok else "info",
        message=(
            "Primary job content (title/responsibilities) looks complete."
            if ok
            else f"Missing or thin primary job content: {', '.join(missing)}"
        ),
        missing_fields=missing,
    )
