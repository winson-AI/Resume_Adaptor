"""Shared data models for JD, resume, adaptation, audit, and HITL context."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class JobDescription:
    title: str = ""
    company: str = ""
    responsibilities: str = ""
    requirements: str = ""
    location_hints: str = ""
    salary_hints: str = ""
    raw_text: str = ""
    source: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ExperienceEntry:
    employer: str = ""
    title: str = ""
    time_range: str = ""
    bullets: List[str] = field(default_factory=list)


@dataclass
class EducationEntry:
    school: str = ""
    degree: str = ""
    time_range: str = ""
    details: str = ""


@dataclass
class ResumeDocument:
    contact: str = ""
    summary: str = ""
    skills: List[str] = field(default_factory=list)
    experience: List[ExperienceEntry] = field(default_factory=list)
    education: List[EducationEntry] = field(default_factory=list)
    extras: str = ""
    raw_text: str = ""
    source_path: str = ""
    source_format: str = ""  # docx | pdf

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CheckResult:
    name: str
    ok: bool
    severity: str  # info | warn | error
    message: str
    missing_fields: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CheckReport:
    results: List[CheckResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(r.ok or r.severity != "error" for r in self.results)

    @property
    def has_errors(self) -> bool:
        return any(not r.ok and r.severity == "error" for r in self.results)

    def to_dict(self) -> Dict[str, Any]:
        return {"ok": self.ok, "results": [r.to_dict() for r in self.results]}


@dataclass
class HitlContext:
    salary: str = ""
    work_years: str = ""
    work_base: str = ""
    template_path: Optional[str] = None  # None => use source resume layout
    use_source_layout: bool = True
    override_checker_errors: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AdaptedResume:
    contact: str = ""
    summary: str = ""
    skills: List[str] = field(default_factory=list)
    experience: List[ExperienceEntry] = field(default_factory=list)
    education: List[EducationEntry] = field(default_factory=list)
    extras: str = ""
    change_log: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AuditFlag:
    severity: str  # info | warn | high
    message: str
    field: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AuditReport:
    flags: List[AuditFlag] = field(default_factory=list)
    summary: str = ""

    @property
    def has_high(self) -> bool:
        return any(f.severity == "high" for f in self.flags)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "summary": self.summary,
            "has_high": self.has_high,
            "flags": [f.to_dict() for f in self.flags],
        }


@dataclass
class PipelineResult:
    run_id: str
    hitl: HitlContext
    jd: Optional[JobDescription] = None
    resume: Optional[ResumeDocument] = None
    checks: Optional[CheckReport] = None
    adapted: Optional[AdaptedResume] = None
    audit: Optional[AuditReport] = None
    output_docx: Optional[str] = None
    output_pdf: Optional[str] = None
    context_json: Optional[str] = None
    audit_json: Optional[str] = None
    error: Optional[str] = None
