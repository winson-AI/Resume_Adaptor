"""Parse DOCX/PDF resumes into structured ResumeDocument (document-skills aligned)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import List, Tuple

from docx import Document
from pypdf import PdfReader

from profile_adaptor.models import EducationEntry, ExperienceEntry, ResumeDocument

try:
    import pdfplumber
except ImportError:  # pragma: no cover
    pdfplumber = None  # type: ignore

SECTION_ALIASES = {
    "summary": [
        "summary",
        "profile",
        "objective",
        "about",
        "professional summary",
        "个人简介",
        "自我评价",
        "概述",
    ],
    "skills": [
        "skills",
        "technical skills",
        "core competencies",
        "expertise",
        "技能",
        "专业技能",
        "技术栈",
    ],
    "experience": [
        "experience",
        "work experience",
        "employment",
        "professional experience",
        "工作经历",
        "工作经验",
        "项目经历",
    ],
    "education": [
        "education",
        "academic",
        "学历",
        "教育背景",
        "教育经历",
    ],
}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _is_heading(line: str) -> Tuple[bool, str]:
    n = _norm(line).rstrip(":")
    if not n or len(n) > 60:
        return False, ""
    for key, aliases in SECTION_ALIASES.items():
        if n in aliases:
            return True, key
    return False, ""


def _split_sections(text: str) -> dict:
    sections = {"contact": "", "summary": "", "skills": "", "experience": "", "education": "", "extras": ""}
    current = "contact"
    buckets = {k: [] for k in sections}
    for raw in text.splitlines():
        line = raw.rstrip()
        is_h, key = _is_heading(line)
        if is_h:
            current = key
            continue
        buckets[current].append(line)
    for k, lines in buckets.items():
        sections[k] = "\n".join(lines).strip()
    return sections


def _parse_skills(block: str) -> List[str]:
    if not block:
        return []
    parts = re.split(r"[,;|•·\n]+", block)
    return [p.strip() for p in parts if p.strip() and len(p.strip()) < 80]


def _parse_experience(block: str) -> List[ExperienceEntry]:
    if not block:
        return []
    entries: List[ExperienceEntry] = []
    chunks = re.split(r"\n(?=[A-Z\u4e00-\u9fff].{2,80})", block)
    if len(chunks) == 1:
        chunks = [c for c in re.split(r"\n{2,}", block) if c.strip()]
    for chunk in chunks:
        lines = [l.strip() for l in chunk.splitlines() if l.strip()]
        if not lines:
            continue
        header = lines[0]
        time_m = re.search(
            r"((?:19|20)\d{2}\s*[-–—to至]+\s*(?:(?:19|20)\d{2}|present|now|至今|今))",
            chunk,
            re.I,
        )
        bullets = [re.sub(r"^[\-•·*]\s*", "", l) for l in lines[1:] if l]
        employer, title = header, ""
        if " - " in header or " – " in header or "—" in header:
            parts = re.split(r"\s[-–—]\s", header, maxsplit=1)
            if len(parts) == 2:
                employer, title = parts[0].strip(), parts[1].strip()
        elif "|" in header:
            parts = [p.strip() for p in header.split("|", 1)]
            employer, title = parts[0], parts[1] if len(parts) > 1 else ""
        entries.append(
            ExperienceEntry(
                employer=employer,
                title=title,
                time_range=time_m.group(1).strip() if time_m else "",
                bullets=bullets or ([lines[0]] if len(lines) == 1 else []),
            )
        )
    return entries


def _parse_education(block: str) -> List[EducationEntry]:
    if not block:
        return []
    entries: List[EducationEntry] = []
    chunks = [c for c in re.split(r"\n{2,}", block) if c.strip()]
    if len(chunks) == 1:
        chunks = [c for c in block.splitlines() if c.strip()]
        # group consecutive lines loosely
        if len(chunks) > 1:
            entries.append(
                EducationEntry(
                    school=chunks[0],
                    degree=chunks[1] if len(chunks) > 1 else "",
                    time_range="",
                    details="\n".join(chunks[2:]),
                )
            )
            return entries
    for chunk in chunks:
        lines = [l.strip() for l in chunk.splitlines() if l.strip()]
        if not lines:
            continue
        time_m = re.search(
            r"((?:19|20)\d{2}\s*[-–—to至]+\s*(?:(?:19|20)\d{2}|present|now|至今|今))",
            chunk,
            re.I,
        )
        entries.append(
            EducationEntry(
                school=lines[0],
                degree=lines[1] if len(lines) > 1 else "",
                time_range=time_m.group(1).strip() if time_m else "",
                details="\n".join(lines[2:]),
            )
        )
    return entries


def _extract_pdf_text(path: Path) -> str:
    if pdfplumber is not None:
        parts = []
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages:
                parts.append(page.extract_text() or "")
        text = "\n".join(parts).strip()
        if text:
            return text
    reader = PdfReader(str(path))
    return "\n".join((page.extract_text() or "") for page in reader.pages).strip()


def _extract_docx_text(path: Path) -> str:
    doc = Document(str(path))
    return "\n".join(p.text for p in doc.paragraphs if p.text is not None)


def parse_resume(path: str) -> ResumeDocument:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"Resume not found: {path}")
    suffix = p.suffix.lower()
    if suffix == ".docx":
        raw = _extract_docx_text(p)
        fmt = "docx"
    elif suffix == ".pdf":
        raw = _extract_pdf_text(p)
        fmt = "pdf"
    else:
        raise ValueError(f"Unsupported resume format: {suffix} (use .docx or .pdf)")

    if not raw.strip():
        raise ValueError(f"Could not extract text from resume: {path}")

    sections = _split_sections(raw)
    return ResumeDocument(
        contact=sections["contact"],
        summary=sections["summary"],
        skills=_parse_skills(sections["skills"]),
        experience=_parse_experience(sections["experience"]),
        education=_parse_education(sections["education"]),
        extras=sections["extras"],
        raw_text=raw,
        source_path=str(p.resolve()),
        source_format=fmt,
    )
