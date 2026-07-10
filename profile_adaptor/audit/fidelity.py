"""Fidelity auditor: rule-based + optional LLM pass."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Set

from profile_adaptor.llm.base import LLMClient
from profile_adaptor.llm.prompts import SYSTEM_AUDIT, build_audit_user_prompt
from profile_adaptor.models import AdaptedResume, AuditFlag, AuditReport, ResumeDocument


def _tokens(text: str) -> Set[str]:
    return {t.lower() for t in re.findall(r"[A-Za-z\u4e00-\u9fff][A-Za-z0-9+.#\u4e00-\u9fff-]{1,}", text or "")}


def _rule_audit(source: ResumeDocument, adapted: AdaptedResume) -> List[AuditFlag]:
    flags: List[AuditFlag] = []
    src_text = source.raw_text or ""
    src_norm = src_text.lower()
    flat_emp: Set[str] = set()
    for e in source.experience:
        flat_emp |= _tokens(e.employer)

    for exp in adapted.experience:
        emp_tokens = _tokens(exp.employer)
        if exp.employer and emp_tokens and not (emp_tokens & flat_emp) and exp.employer.lower() not in src_norm:
            flags.append(
                AuditFlag(
                    severity="high",
                    message=f"Employer not found in source: {exp.employer}",
                    field="experience.employer",
                )
            )
        for bullet in exp.bullets:
            nums = re.findall(r"\b\d+(?:\.\d+)?%?\b", bullet)
            for n in nums:
                if n not in src_text and n not in src_norm:
                    flags.append(
                        AuditFlag(
                            severity="warn",
                            message=f"Numeric claim may be new: {n} in '{bullet[:80]}'",
                            field="experience.bullets",
                        )
                    )

    src_schools = " ".join(e.school for e in source.education).lower()
    for edu in adapted.education:
        if edu.school and edu.school.lower() not in src_norm and edu.school.lower() not in src_schools:
            flags.append(
                AuditFlag(
                    severity="high",
                    message=f"School not found in source: {edu.school}",
                    field="education.school",
                )
            )

    src_skill_tokens = _tokens(" ".join(source.skills) + " " + src_text)
    for skill in adapted.skills:
        st = _tokens(skill)
        if st and not (st & src_skill_tokens):
            flags.append(
                AuditFlag(
                    severity="warn",
                    message=f"Skill may lack source support: {skill}",
                    field="skills",
                )
            )
    return flags


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


def audit_fidelity(
    source: ResumeDocument,
    adapted: AdaptedResume,
    client: LLMClient = None,
) -> AuditReport:
    flags = _rule_audit(source, adapted)
    summary = "Rule-based fidelity audit completed."

    if client is not None:
        try:
            messages = [
                {"role": "system", "content": SYSTEM_AUDIT},
                {
                    "role": "user",
                    "content": build_audit_user_prompt(
                        json.dumps(source.to_dict(), ensure_ascii=False),
                        json.dumps(adapted.to_dict(), ensure_ascii=False),
                    ),
                },
            ]
            raw = client.chat(messages, temperature=0.0)
            data = _extract_json(raw)
            summary = str(data.get("summary") or summary)
            for item in data.get("flags") or []:
                if not isinstance(item, dict):
                    continue
                flags.append(
                    AuditFlag(
                        severity=str(item.get("severity") or "info"),
                        message=str(item.get("message") or ""),
                        field=str(item.get("field") or ""),
                    )
                )
        except Exception as exc:
            flags.append(
                AuditFlag(
                    severity="info",
                    message=f"LLM audit skipped due to error: {exc}",
                    field="audit",
                )
            )

    if not flags:
        summary = summary + " No fidelity issues detected."
    return AuditReport(flags=flags, summary=summary)
