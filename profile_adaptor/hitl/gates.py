"""HITL gate validation for salary, work years, and work base."""

from __future__ import annotations

from typing import List, Optional, Tuple

from profile_adaptor.models import HitlContext


def validate_hitl(hitl: HitlContext) -> Tuple[bool, List[str]]:
    errors: List[str] = []
    if not (hitl.salary or "").strip():
        errors.append("salary is required")
    if not (hitl.work_years or "").strip():
        errors.append("work_years is required")
    if not (hitl.work_base or "").strip():
        errors.append("work_base is required")
    return (len(errors) == 0, errors)


def build_hitl(
    salary: str,
    work_years: str,
    work_base: str,
    template_path: Optional[str] = None,
    use_source_layout: bool = True,
    override_checker_errors: bool = False,
) -> HitlContext:
    path = (template_path or "").strip() or None
    return HitlContext(
        salary=str(salary or "").strip(),
        work_years=str(work_years or "").strip(),
        work_base=str(work_base or "").strip(),
        template_path=path,
        use_source_layout=use_source_layout if path is None else False,
        override_checker_errors=override_checker_errors,
    )
