"""Shared JD ↔ resume matching helpers for pre-rewrite checkers."""

from __future__ import annotations

import re
from datetime import datetime
from typing import List, Optional, Set, Tuple

from profile_adaptor.models import ExperienceEntry, JobDescription, ResumeDocument

STOPWORDS = {
    "and",
    "or",
    "the",
    "a",
    "an",
    "to",
    "of",
    "in",
    "for",
    "with",
    "on",
    "at",
    "by",
    "from",
    "as",
    "is",
    "are",
    "be",
    "will",
    "you",
    "we",
    "our",
    "your",
    "this",
    "that",
    "role",
    "job",
    "work",
    "team",
    "using",
    "etc",
    "plus",
    "years",
    "year",
    "experience",
    "including",
    "ability",
    "strong",
    "good",
    "etc",
    # SPA / job-board chrome — never treat as skill themes
    "boss",
    "zhipin",
    "直聘",
    "加载中",
    "请稍候",
    "请稍后",
    "正在加载",
    "loading",
    "javascript",
    "browser",
    "cookie",
}

DEGREE_LEVELS = [
    ("phd", 4, [r"\bph\.?d\b", r"doctorate", r"博士"]),
    ("master", 3, [r"\bm\.?s\.?\b", r"\bm\.?sc\b", r"\bmba\b", r"master", r"硕士", r"研究生"]),
    ("bachelor", 2, [r"\bb\.?s\.?\b", r"\bb\.?sc\b", r"\bb\.?a\.?\b", r"bachelor", r"本科", r"学士"]),
    ("associate", 1, [r"associate", r"大专", r"专科"]),
]


def tokenize(text: str) -> Set[str]:
    tokens = re.findall(
        r"[A-Za-z][A-Za-z0-9+.#-]{1,}|[\u4e00-\u9fff]{2,}",
        text or "",
    )
    out = set()
    for t in tokens:
        low = t.lower()
        if low in STOPWORDS or len(low) < 2:
            continue
        out.add(low)
    return out


def overlap_ratio(a: Set[str], b: Set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / max(1, min(len(a), len(b)))


def extract_required_years(text: str) -> Optional[float]:
    """Best-effort minimum years from JD text."""
    patterns = [
        r"(\d+(?:\.\d+)?)\s*\+?\s*(?:-\s*\d+)?\s*(?:years?|yrs?|年)",
        r"(?:至少|不少于|满)\s*(\d+(?:\.\d+)?)\s*年",
        r"(\d+(?:\.\d+)?)\s*年以上",
    ]
    found: List[float] = []
    for pat in patterns:
        for m in re.finditer(pat, text or "", re.I):
            try:
                found.append(float(m.group(1)))
            except ValueError:
                continue
    return max(found) if found else None


def parse_human_years(value: str) -> Optional[float]:
    if not value:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)", value)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def _parse_year_token(token: str) -> Optional[int]:
    token = token.strip().lower()
    if token in {"present", "now", "current", "至今", "今", "目前"}:
        return datetime.now().year
    m = re.search(r"(19|20)\d{2}", token)
    if m:
        return int(m.group(0))
    return None


def estimate_resume_years(resume: ResumeDocument) -> Optional[float]:
    """Sum approximate tenure from experience time ranges (best effort)."""
    total = 0.0
    counted = False
    for exp in resume.experience:
        tr = exp.time_range or ""
        m = re.search(
            r"((?:19|20)\d{2}|present|now|current|至今|今)\s*[-–—to至]+\s*((?:19|20)\d{2}|present|now|current|至今|今)",
            tr,
            re.I,
        )
        if not m:
            # try from employer/title line already in time_range-less entries via raw
            m = re.search(
                r"((?:19|20)\d{2})\s*[-–—to至]+\s*((?:19|20)\d{2}|present|now|current|至今|今)",
                f"{exp.employer} {exp.title} {tr}",
                re.I,
            )
        if not m:
            continue
        start = _parse_year_token(m.group(1))
        end = _parse_year_token(m.group(2))
        if start is None or end is None or end < start:
            continue
        total += max(0, end - start)
        counted = True
    return total if counted else None


def extract_salary_numbers(text: str) -> List[float]:
    """Extract salary-like numbers; normalize k/K and 万."""
    if not text:
        return []
    nums: List[float] = []
    for m in re.finditer(
        r"(\d+(?:\.\d+)?)\s*(k|K|万|w|W)?",
        text.replace(",", ""),
    ):
        val = float(m.group(1))
        unit = (m.group(2) or "").lower()
        if unit in {"k"}:
            val *= 1000
        elif unit in {"万", "w"}:
            val *= 10000
        # ignore tiny numbers unlikely to be salary
        if val >= 1000 or unit:
            nums.append(val)
    return nums


def salary_ranges_overlap(jd_hint: str, human: str) -> Tuple[bool, str]:
    jd_nums = extract_salary_numbers(jd_hint)
    human_nums = extract_salary_numbers(human)
    if not jd_nums:
        return True, "JD has no clear salary hint; human salary recorded."
    if not human_nums:
        return False, "Human salary could not be parsed for comparison with JD."
    jd_min, jd_max = min(jd_nums), max(jd_nums)
    # expand single value to ±20% band
    if jd_min == jd_max:
        jd_min *= 0.8
        jd_max *= 1.2
    h_min, h_max = min(human_nums), max(human_nums)
    if h_min == h_max:
        h_min *= 0.9
        h_max *= 1.1
    overlap = not (h_max < jd_min or h_min > jd_max)
    if overlap:
        return True, f"Human salary agrees with JD hint ({jd_hint.strip()[:60]})."
    return (
        False,
        f"Large salary gap: human={human!r} vs JD hint={jd_hint.strip()[:80]!r}.",
    )


def location_agrees(jd_hint: str, human_base: str) -> Tuple[bool, str]:
    if not (jd_hint or "").strip():
        return True, "JD has no clear location hint; human work base recorded."
    jd_toks = tokenize(jd_hint)
    human_toks = tokenize(human_base)
    # remote/hybrid soft match
    remote_words = {"remote", "hybrid", "远程", "居家", "混合"}
    if jd_toks & remote_words and human_toks & remote_words:
        return True, "Work base agrees on remote/hybrid."
    if human_toks & jd_toks:
        return True, f"Work base agrees with JD location ({jd_hint.strip()[:60]})."
    # substring fallback
    j = jd_hint.lower()
    h = human_base.lower()
    if any(len(t) >= 2 and t in j for t in human_toks) or any(len(t) >= 2 and t in h for t in jd_toks):
        return True, "Work base partially matches JD location."
    return False, f"Work base gap: human={human_base!r} vs JD location={jd_hint.strip()[:80]!r}."


def detect_degree_level(text: str) -> Optional[int]:
    for _name, level, pats in DEGREE_LEVELS:
        for pat in pats:
            if re.search(pat, text or "", re.I):
                return level
    return None


def jd_required_degree(jd: JobDescription) -> Optional[int]:
    blob = f"{jd.requirements}\n{jd.raw_text}"
    # only treat as required if near education keywords
    edu_window = []
    for m in re.finditer(
        r".{0,40}(?:degree|education|学历|本科|硕士|博士|bachelor|master|phd).{0,40}",
        blob,
        re.I,
    ):
        edu_window.append(m.group(0))
    text = "\n".join(edu_window) if edu_window else ""
    if not text:
        return None
    return detect_degree_level(text)


def resume_highest_degree(resume: ResumeDocument) -> Optional[int]:
    blob = " ".join(
        f"{e.school} {e.degree} {e.details}" for e in resume.education
    ) or resume.raw_text
    return detect_degree_level(blob)


def experience_blob(resume: ResumeDocument) -> str:
    parts: List[str] = []
    for e in resume.experience:
        parts.append(e.employer)
        parts.append(e.title)
        parts.extend(e.bullets)
    parts.extend(resume.skills)
    parts.append(resume.summary)
    return "\n".join(p for p in parts if p)


def job_content_vs_experience(jd: JobDescription, resume: ResumeDocument) -> Tuple[float, Set[str], Set[str]]:
    jd_tokens = tokenize(f"{jd.title}\n{jd.responsibilities}\n{jd.requirements}")
    # Prefer content words from responsibilities for "job content"
    content_tokens = tokenize(f"{jd.title}\n{jd.responsibilities}") or jd_tokens
    exp_tokens = tokenize(experience_blob(resume))
    ratio = overlap_ratio(content_tokens, exp_tokens)
    missing = content_tokens - exp_tokens
    matched = content_tokens & exp_tokens
    return ratio, matched, missing
