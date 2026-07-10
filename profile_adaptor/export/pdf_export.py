"""Optional PDF export via LibreOffice or reportlab fallback."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from profile_adaptor.models import AdaptedResume


def export_pdf_via_soffice(docx_path: Path, output_dir: Path) -> Path:
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        raise RuntimeError("LibreOffice (soffice) not found")
    output_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [soffice, "--headless", "--convert-to", "pdf", "--outdir", str(output_dir), str(docx_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    pdf_path = output_dir / (docx_path.stem + ".pdf")
    if not pdf_path.is_file():
        raise RuntimeError(f"PDF not produced for {docx_path}")
    return pdf_path


def export_pdf_reportlab(adapted: AdaptedResume, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(str(output_path), pagesize=letter)
    story = []

    def add_heading(text: str) -> None:
        story.append(Paragraph(text.replace("\n", "<br/>"), styles["Heading2"]))
        story.append(Spacer(1, 6))

    def add_body(text: str) -> None:
        if not text:
            return
        safe = (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace("\n", "<br/>")
        )
        story.append(Paragraph(safe, styles["BodyText"]))
        story.append(Spacer(1, 8))

    if adapted.contact:
        add_heading(adapted.contact.split("\n")[0][:100])
        add_body("\n".join(adapted.contact.splitlines()[1:]))
    if adapted.summary:
        add_heading("Summary")
        add_body(adapted.summary)
    if adapted.skills:
        add_heading("Skills")
        add_body(", ".join(adapted.skills))
    if adapted.experience:
        add_heading("Experience")
        for e in adapted.experience:
            header = " — ".join(x for x in [e.employer, e.title, e.time_range] if x)
            add_body(header)
            for b in e.bullets:
                add_body(f"• {b}")
    if adapted.education:
        add_heading("Education")
        for e in adapted.education:
            header = " — ".join(x for x in [e.school, e.degree, e.time_range] if x)
            add_body(header)
            if e.details:
                add_body(e.details)

    doc.build(story)
    return output_path


def export_pdf(docx_path: Path, adapted: AdaptedResume, output_dir: Path) -> Path:
    try:
        return export_pdf_via_soffice(docx_path, output_dir)
    except Exception:
        pdf_path = output_dir / (docx_path.stem + ".pdf")
        return export_pdf_reportlab(adapted, pdf_path)
