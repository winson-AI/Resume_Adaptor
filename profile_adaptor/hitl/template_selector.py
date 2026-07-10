"""Template discovery and selection helpers."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple


def list_templates(templates_dir: Path) -> List[Path]:
    if not templates_dir.exists():
        return []
    files = []
    for pattern in ("*.docx", "*.DOCX"):
        files.extend(sorted(templates_dir.glob(pattern)))
    # de-dupe
    seen = set()
    out = []
    for f in files:
        key = str(f.resolve())
        if key not in seen:
            seen.add(key)
            out.append(f)
    return out


def resolve_template(
    templates_dir: Path,
    choice: Optional[str],
    resume_path: str,
    resume_format: str,
) -> Tuple[Optional[Path], bool]:
    """
    Returns (template_path, use_source_layout).
    choice:
      - None / "" / "source" => use source resume layout (docx only)
      - absolute/relative path to a docx
      - filename under templates_dir
    """
    c = (choice or "").strip()
    if not c or c.lower() in {"source", "use_source", "resume"}:
        if resume_format != "docx":
            raise ValueError(
                "Source resume is PDF; select a DOCX template via --template or templates/"
            )
        return Path(resume_path), True

    p = Path(c)
    if p.is_file():
        return p.resolve(), False
    candidate = templates_dir / c
    if candidate.is_file():
        return candidate.resolve(), False
    raise FileNotFoundError(f"Template not found: {c}")
