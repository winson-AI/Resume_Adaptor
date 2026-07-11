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

    @property
    def has_warnings(self) -> bool:
        return any(not r.ok and r.severity == "warn" for r in self.results)

    @property
    def notices(self) -> List[str]:
        return [r.message for r in self.results if not r.ok]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "has_errors": self.has_errors,
            "has_warnings": self.has_warnings,
            "notices": self.notices,
            "results": [r.to_dict() for r in self.results],
        }


@dataclass
class HitlContext:
    salary: str = ""
    work_years: str = ""
    work_base: str = ""
    template_path: Optional[str] = None  # None => use source resume layout
    use_source_layout: bool = True
    override_checker_errors: bool = False
    customer_agreed_to_rewrite: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class FillReport:
    sections_filled: List[str] = field(default_factory=list)
    sections_missing: List[str] = field(default_factory=list)
    degraded: bool = False
    notes: List[str] = field(default_factory=list)

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
    used_fallback: bool = False
    fallback_reason: str = ""

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
    hitl: Optional[HitlContext] = None
    jd: Optional[JobDescription] = None
    resume: Optional[ResumeDocument] = None
    checks: Optional[CheckReport] = None
    match_audit: Optional[AuditReport] = None
    adapted: Optional[AdaptedResume] = None
    audit: Optional[AuditReport] = None
    fill_report: Optional[FillReport] = None
    output_docx: Optional[str] = None
    output_pdf: Optional[str] = None
    context_json: Optional[str] = None
    audit_json: Optional[str] = None
    events_jsonl: Optional[str] = None
    error: Optional[str] = None
    step: str = ""  # ingest | review | match_audit | hitl | done


@dataclass
class WizardSession:
    """In-memory multi-step session for TUI/web."""

    session_id: str
    run_id: str = ""
    step: str = "ingest"
    url: str = ""
    jd_file: str = ""
    resume_path: str = ""
    provider: str = "ollama"
    model: str = ""
    jd: Optional[JobDescription] = None
    resume: Optional[ResumeDocument] = None
    checks: Optional[CheckReport] = None
    match_audit: Optional[AuditReport] = None
    hitl: Optional[HitlContext] = None
    result: Optional[PipelineResult] = None
    error: Optional[str] = None
    notices: List[str] = field(default_factory=list)
    event_log: Any = None  # EventLog; typed loosely to avoid circular import
    events: List[Dict[str, Any]] = field(default_factory=list)

    def to_public_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "run_id": self.run_id,
            "step": self.step,
            "url": self.url,
            "jd_file": self.jd_file,
            "resume_path": self.resume_path,
            "provider": self.provider,
            "model": self.model,
            "jd": self.jd.to_dict() if self.jd else None,
            "resume": self.resume.to_dict() if self.resume else None,
            "checks": self.checks.to_dict() if self.checks else None,
            "match_audit": self.match_audit.to_dict() if self.match_audit else None,
            "hitl": self.hitl.to_dict() if self.hitl else None,
            "notices": self.notices,
            "error": self.error,
            "events": self.events[-50:],
            "result": {
                "output_docx": self.result.output_docx if self.result else None,
                "output_pdf": self.result.output_pdf if self.result else None,
                "context_json": self.result.context_json if self.result else None,
                "audit_json": self.result.audit_json if self.result else None,
                "events_jsonl": self.result.events_jsonl if self.result else None,
                "error": self.result.error if self.result else None,
            }
            if self.result
            else None,
        }
