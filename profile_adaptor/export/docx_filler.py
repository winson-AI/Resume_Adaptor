"""Fill DOCX template or source resume with adapted content."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Dict, List, Optional

from docx import Document
from docx.text.paragraph import Paragraph

from profile_adaptor.models import AdaptedResume
from profile_adaptor.parse.resume_parser import SECTION_ALIASES, _norm


def _set_paragraph_text(paragraph: Paragraph, text: str) -> None:
    """Replace paragraph text while keeping the first run's formatting when possible."""
    if paragraph.runs:
        paragraph.runs[0].text = text
        for run in paragraph.runs[1:]:
            run.text = ""
    else:
        paragraph.add_run(text)


def _heading_key(text: str) -> Optional[str]:
    n = _norm(text).rstrip(":")
    for key, aliases in SECTION_ALIASES.items():
        if n in aliases:
            return key
    return None


def _adapted_blocks(adapted: AdaptedResume) -> Dict[str, List[str]]:
    skills_line = ", ".join(adapted.skills) if adapted.skills else ""
    exp_lines: List[str] = []
    for e in adapted.experience:
        header = " — ".join(x for x in [e.employer, e.title, e.time_range] if x)
        if header:
            exp_lines.append(header)
        for b in e.bullets:
            exp_lines.append(f"• {b}")
        exp_lines.append("")
    edu_lines: List[str] = []
    for e in adapted.education:
        header = " — ".join(x for x in [e.school, e.degree, e.time_range] if x)
        if header:
            edu_lines.append(header)
        if e.details:
            edu_lines.append(e.details)
        edu_lines.append("")
    return {
        "summary": [adapted.summary] if adapted.summary else [],
        "skills": [skills_line] if skills_line else [],
        "experience": [l for l in exp_lines if l is not None],
        "education": [l for l in edu_lines if l is not None],
    }


def _clear_between(paragraphs: List[Paragraph], start: int, end: int) -> None:
    for i in range(start + 1, end):
        _set_paragraph_text(paragraphs[i], "")


def fill_docx(
    template_path: Path,
    adapted: AdaptedResume,
    output_path: Path,
    contact_override: Optional[str] = None,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(template_path, output_path)
    doc = Document(str(output_path))
    paragraphs = list(doc.paragraphs)
    blocks = _adapted_blocks(adapted)

    # Map section heading indices
    indices: Dict[str, int] = {}
    for i, p in enumerate(paragraphs):
        key = _heading_key(p.text or "")
        if key and key not in indices:
            indices[key] = i

    keys_in_order = sorted(indices.items(), key=lambda kv: kv[1])
    for idx, (key, start) in enumerate(keys_in_order):
        end = keys_in_order[idx + 1][1] if idx + 1 < len(keys_in_order) else len(paragraphs)
        content = blocks.get(key) or []
        # Write into existing body paragraphs; append via last body para if needed
        body_slots = list(range(start + 1, end))
        if not body_slots and content:
            # insert after heading by setting next available empty or append run on heading's following
            continue
        for j, slot in enumerate(body_slots):
            if j < len(content):
                _set_paragraph_text(paragraphs[slot], content[j])
            else:
                _set_paragraph_text(paragraphs[slot], "")
        # If more content than slots, append remaining into last slot joined
        if len(content) > len(body_slots) and body_slots:
            extra = "\n".join(content[len(body_slots) - 1 :])
            _set_paragraph_text(paragraphs[body_slots[-1]], extra)

    # If no recognizable headings, rebuild a simple structured doc
    if not indices:
        # Clear and rewrite
        for p in paragraphs:
            _set_paragraph_text(p, "")
        if paragraphs:
            lines = []
            if contact_override or adapted.contact:
                lines.append(contact_override or adapted.contact)
                lines.append("")
            lines.append("Summary")
            lines.extend(blocks["summary"] or [""])
            lines.append("")
            lines.append("Skills")
            lines.extend(blocks["skills"] or [""])
            lines.append("")
            lines.append("Experience")
            lines.extend(blocks["experience"] or [""])
            lines.append("")
            lines.append("Education")
            lines.extend(blocks["education"] or [""])
            _set_paragraph_text(paragraphs[0], "\n".join(lines))
        else:
            doc.add_paragraph(adapted.summary or "")

    doc.save(str(output_path))
    return output_path


def create_docx_from_adapted(adapted: AdaptedResume, output_path: Path) -> Path:
    """Create a clean DOCX when no usable template exists."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc = Document()
    if adapted.contact:
        doc.add_heading(adapted.contact.split("\n")[0][:80], level=0)
        for line in adapted.contact.splitlines()[1:]:
            doc.add_paragraph(line)
    if adapted.summary:
        doc.add_heading("Summary", level=1)
        doc.add_paragraph(adapted.summary)
    if adapted.skills:
        doc.add_heading("Skills", level=1)
        doc.add_paragraph(", ".join(adapted.skills))
    if adapted.experience:
        doc.add_heading("Experience", level=1)
        for e in adapted.experience:
            header = " — ".join(x for x in [e.employer, e.title, e.time_range] if x)
            doc.add_paragraph(header)
            for b in e.bullets:
                doc.add_paragraph(b, style="List Bullet")
    if adapted.education:
        doc.add_heading("Education", level=1)
        for e in adapted.education:
            header = " — ".join(x for x in [e.school, e.degree, e.time_range] if x)
            doc.add_paragraph(header)
            if e.details:
                doc.add_paragraph(e.details)
    if adapted.extras:
        doc.add_heading("Additional", level=1)
        doc.add_paragraph(adapted.extras)
    doc.save(str(output_path))
    return output_path
