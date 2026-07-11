"""HITL: optional context fields + required customer agreement to rewrite."""

from __future__ import annotations

from typing import List, Optional, Tuple

from profile_adaptor.models import HitlContext


def validate_hitl(hitl: HitlContext) -> Tuple[bool, List[str]]:
    """Only the proceed agreement is required; salary/years/base are optional."""
    errors: List[str] = []
    if not hitl.customer_agreed_to_rewrite:
        errors.append("customer agreement to rewrite is required")
    return (len(errors) == 0, errors)


def build_hitl(
    salary: str = "",
    work_years: str = "",
    work_base: str = "",
    template_path: Optional[str] = None,
    use_source_layout: bool = True,
    override_checker_errors: bool = False,
    customer_agreed_to_rewrite: bool = False,
) -> HitlContext:
    path = (template_path or "").strip() or None
    agreed = bool(customer_agreed_to_rewrite)
    return HitlContext(
        salary=str(salary or "").strip(),
        work_years=str(work_years or "").strip(),
        work_base=str(work_base or "").strip(),
        template_path=path,
        use_source_layout=use_source_layout if path is None else False,
        # Agreement to proceed also acknowledges remaining match gaps.
        override_checker_errors=override_checker_errors or agreed,
        customer_agreed_to_rewrite=agreed,
    )
