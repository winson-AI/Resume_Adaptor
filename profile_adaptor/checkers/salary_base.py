"""HITL salary & work-base agreement against JD hints (optional fields)."""

from __future__ import annotations

from profile_adaptor.checkers.matching import location_agrees, salary_ranges_overlap
from profile_adaptor.models import CheckResult, HitlContext, JobDescription


def check_salary_base_agreement(jd: JobDescription, hitl: HitlContext) -> CheckResult:
    has_salary = bool((hitl.salary or "").strip())
    has_base = bool((hitl.work_base or "").strip())

    if not has_salary and not has_base:
        return CheckResult(
            name="salary_base_agreement",
            ok=True,
            severity="info",
            message=(
                "Salary/base left blank (optional). "
                f"JD hints — salary: {jd.salary_hints or '—'}; location: {jd.location_hints or '—'}."
            ),
            missing_fields=[],
        )

    messages = []
    missing = []
    sal_ok = True
    loc_ok = True

    if has_salary:
        sal_ok, sal_msg = salary_ranges_overlap(jd.salary_hints or "", hitl.salary)
        if not (jd.salary_hints or "").strip():
            sal_ok2, sal_msg2 = salary_ranges_overlap(jd.raw_text or "", hitl.salary)
            if "no clear salary" not in sal_msg2.lower() and not sal_ok2:
                sal_ok, sal_msg = sal_ok2, sal_msg2
            elif "agrees" in sal_msg2.lower():
                sal_ok, sal_msg = True, sal_msg2
        messages.append(sal_msg)
        if not sal_ok:
            missing.append("salary_agreement")
    else:
        messages.append("Salary not provided (optional).")

    if has_base:
        loc_ok, loc_msg = location_agrees(jd.location_hints or "", hitl.work_base)
        if not (jd.location_hints or "").strip():
            loc_ok2, loc_msg2 = location_agrees(
                " ".join(
                    line
                    for line in (jd.raw_text or "").splitlines()
                    if any(
                        k in line.lower()
                        for k in (
                            "location",
                            "remote",
                            "hybrid",
                            "地点",
                            "基地",
                            "shanghai",
                            "beijing",
                        )
                    )
                ),
                hitl.work_base,
            )
            if "no clear location" not in loc_msg2.lower():
                loc_ok, loc_msg = loc_ok2, loc_msg2
        messages.append(loc_msg)
        if not loc_ok:
            missing.append("work_base_agreement")
    else:
        messages.append("Work base not provided (optional).")

    if sal_ok and loc_ok:
        return CheckResult(
            name="salary_base_agreement",
            ok=True,
            severity="info",
            message=" ".join(messages),
            missing_fields=[],
        )

    # Informational when optional fields disagree — warn, not hard error (agreement gates rewrite)
    return CheckResult(
        name="salary_base_agreement",
        ok=False,
        severity="warn",
        message="HITL vs JD mismatch — " + " ".join(messages),
        missing_fields=missing,
    )
