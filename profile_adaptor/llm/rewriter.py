"""JD-aware resume rewriter using configured LLM client."""

from __future__ import annotations

import json
import re
from typing import Any, Dict

from profile_adaptor.llm.base import LLMClient
from profile_adaptor.llm.prompts import SYSTEM_REWRITE, build_rewrite_user_prompt
from profile_adaptor.models import (
    AdaptedResume,
    EducationEntry,
    ExperienceEntry,
    HitlContext,
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


def _fallback_adapt(
    resume: ResumeDocument,
    jd: JobDescription,
    reason: str = "LLM rewrite failed or returned unusable output",
) -> AdaptedResume:
    """Deterministic fallback when LLM output is unusable."""
    skills = list(resume.skills)
    raw = (resume.raw_text or "").lower()
    for token in re.findall(r"[A-Za-z][A-Za-z0-9+.#-]{2,}", jd.requirements or ""):
        t = token.lower()
        if t in raw and token not in skills and len(skills) < 40:
            skills.append(token)
    summary = resume.summary
    if jd.title and summary:
        summary = f"{summary}\nTarget role alignment: {jd.title}".strip()
    elif jd.title and not summary:
        summary = f"Candidate targeting: {jd.title}"
    return AdaptedResume(
        contact=resume.contact,
        summary=summary,
        skills=skills,
        experience=list(resume.experience),
        education=list(resume.education),
        extras=resume.extras,
        change_log=[
            "Fallback adaptation: preserved source content; light skill keyword highlight."
        ],
        used_fallback=True,
        fallback_reason=reason,
    )


def _to_adapted(data: Dict[str, Any], resume: ResumeDocument) -> AdaptedResume:
    exp = []
    for item in data.get("experience") or []:
        if not isinstance(item, dict):
            continue
        exp.append(
            ExperienceEntry(
                employer=str(item.get("employer") or ""),
                title=str(item.get("title") or ""),
                time_range=str(item.get("time_range") or ""),
                bullets=[str(b) for b in (item.get("bullets") or [])],
            )
        )
    edu = []
    for item in data.get("education") or []:
        if not isinstance(item, dict):
            continue
        edu.append(
            EducationEntry(
                school=str(item.get("school") or ""),
                degree=str(item.get("degree") or ""),
                time_range=str(item.get("time_range") or ""),
                details=str(item.get("details") or ""),
            )
        )
    skills = data.get("skills")
    if not isinstance(skills, list):
        skills = resume.skills
    return AdaptedResume(
        contact=str(data.get("contact") or resume.contact),
        summary=str(data.get("summary") or resume.summary),
        skills=[str(s) for s in skills],
        experience=exp or list(resume.experience),
        education=edu or list(resume.education),
        extras=str(data.get("extras") or resume.extras),
        change_log=[str(c) for c in (data.get("change_log") or [])],
        used_fallback=False,
        fallback_reason="",
    )


def rewrite_resume(
    client: LLMClient,
    jd: JobDescription,
    resume: ResumeDocument,
    hitl: HitlContext,
    allow_fallback: bool = True,
) -> AdaptedResume:
    messages = [
        {"role": "system", "content": SYSTEM_REWRITE},
        {
            "role": "user",
            "content": build_rewrite_user_prompt(
                json.dumps(jd.to_dict(), ensure_ascii=False, indent=2),
                json.dumps(resume.to_dict(), ensure_ascii=False, indent=2),
                json.dumps(hitl.to_dict(), ensure_ascii=False, indent=2),
            ),
        },
    ]
    try:
        raw = client.chat(messages, temperature=0.2)
        data = _extract_json(raw)
        return _to_adapted(data, resume)
    except Exception as exc:
        reason = f"LLM rewrite failed: {exc}"
        if allow_fallback:
            return _fallback_adapt(resume, jd, reason=reason)
        raise RuntimeError(reason) from exc
