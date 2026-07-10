"""Aggregate checker report."""

from __future__ import annotations

from profile_adaptor.checkers.education import check_education
from profile_adaptor.checkers.job_content import check_job_content
from profile_adaptor.checkers.job_requirements import check_job_requirements
from profile_adaptor.checkers.work_experience import check_work_experience
from profile_adaptor.models import CheckReport, JobDescription, ResumeDocument


def run_all_checkers(jd: JobDescription, resume: ResumeDocument) -> CheckReport:
    results = [
        check_job_content(jd),
        check_job_requirements(jd),
        check_education(resume),
        check_work_experience(resume),
    ]
    return CheckReport(results=results)
