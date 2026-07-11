"""Job requirements checker."""

from __future__ import annotations

from profile_adaptor.models import CheckResult, JobDescription


def check_job_requirements(jd: JobDescription) -> CheckResult:
    text = (jd.requirements or "").strip()
    missing = []
    if len(text) < 30:
        missing.append("requirements")
    ok = not missing
    spa_hint = any(
        m in (jd.raw_text or "")
        for m in ("加载中", "请稍候", "请稍后", "BOSS直聘")
    ) and len(text) < 80
    message = (
        "Job requirements section present."
        if ok
        else "Job requirements missing or too short."
    )
    if not ok and spa_hint:
        message += (
            " Hint: JD fetch may have returned a hiring-site loading page — "
            "paste the JD text or upload a file, then Refresh JD."
        )
    return CheckResult(
        name="job_requirements",
        ok=ok,
        severity="error" if not ok else "info",
        message=message,
        missing_fields=missing,
    )
