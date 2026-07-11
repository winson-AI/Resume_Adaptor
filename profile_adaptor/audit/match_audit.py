"""LLM audit of JD ↔ resume match dimensions before rewrite."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from profile_adaptor.llm.base import LLMClient
from profile_adaptor.llm.prompts import SYSTEM_MATCH_AUDIT, build_match_audit_user_prompt
from profile_adaptor.models import (
    AuditFlag,
    AuditReport,
    CheckReport,
    CheckResult,
    JobDescription,
    ResumeDocument,
)


def _extract_json(text: str) -> Dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        if not m:
            raise
        return json.loads(m.group(0))


def llm_match_audit(
    client: LLMClient,
    jd: JobDescription,
    resume: ResumeDocument,
    rule_checks: CheckReport,
) -> AuditReport:
    """Ask LLM to audit match dimensions; merge with rule-check notices."""
    flags: List[AuditFlag] = []
    for r in rule_checks.results:
        if not r.ok:
            sev = "high" if r.severity == "error" else ("warn" if r.severity == "warn" else "info")
            flags.append(AuditFlag(severity=sev, message=r.message, field=r.name))

    summary = "Rule-based match audit completed."
    try:
        messages = [
            {"role": "system", "content": SYSTEM_MATCH_AUDIT},
            {
                "role": "user",
                "content": build_match_audit_user_prompt(
                    json.dumps(jd.to_dict(), ensure_ascii=False, indent=2),
                    json.dumps(resume.to_dict(), ensure_ascii=False, indent=2),
                    json.dumps(rule_checks.to_dict(), ensure_ascii=False, indent=2),
                ),
            },
        ]
        raw = client.chat(messages, temperature=0.1)
        data = _extract_json(raw)
        summary = str(data.get("summary") or summary)
        for item in data.get("flags") or []:
            if not isinstance(item, dict):
                continue
            flags.append(
                AuditFlag(
                    severity=str(item.get("severity") or "info"),
                    message=str(item.get("message") or ""),
                    field=str(item.get("field") or item.get("dimension") or ""),
                )
            )
        # Optional per-dimension notes
        for dim, note in (data.get("dimensions") or {}).items():
            if isinstance(note, dict):
                flags.append(
                    AuditFlag(
                        severity=str(note.get("severity") or "info"),
                        message=str(note.get("message") or note),
                        field=str(dim),
                    )
                )
            elif note:
                flags.append(AuditFlag(severity="info", message=str(note), field=str(dim)))
    except Exception as exc:
        flags.append(
            AuditFlag(
                severity="info",
                message=f"LLM match audit unavailable ({exc}); showing rule-based results only.",
                field="llm_match_audit",
            )
        )

    if not any(f.severity in ("high", "warn") for f in flags):
        summary = summary + " No major JD↔resume gaps detected."
    return AuditReport(flags=flags, summary=summary)


def merge_llm_into_checks(rule_checks: CheckReport, match_audit: AuditReport) -> CheckReport:
    """Attach LLM high/warn flags as additional check results for UI notices."""
    extra: List[CheckResult] = []
    for f in match_audit.flags:
        if f.severity not in ("high", "warn"):
            continue
        # skip duplicates already covered by rule messages
        if any(f.message == r.message for r in rule_checks.results):
            continue
        extra.append(
            CheckResult(
                name=f"llm_{f.field or 'match'}",
                ok=False,
                severity="error" if f.severity == "high" else "warn",
                message=f.message,
                missing_fields=[f.field] if f.field else [],
            )
        )
    return CheckReport(results=list(rule_checks.results) + extra)
