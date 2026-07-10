"""Fetch and structure job descriptions from URLs or local files."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import httpx
import trafilatura
from bs4 import BeautifulSoup

from profile_adaptor.models import JobDescription

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 "
    "ProfileAdaptor/0.1"
)

_REQ_HEADERS = [
    r"requirements?",
    r"qualifications?",
    r"what\s+(?:you|we)\s+(?:need|look|bring)",
    r"must\s+have",
    r"you\s+have",
    r"skills?",
    r"任职要求",
    r"岗位要求",
    r"要求",
]
_RESP_HEADERS = [
    r"responsibilities",
    r"what\s+you(?:'ll| will)\s+do",
    r"about\s+the\s+(?:role|job)",
    r"the\s+role",
    r"job\s+description",
    r"duties",
    r"岗位职责",
    r"工作职责",
    r"职责",
]
_SALARY_RE = re.compile(
    r"(?:salary|compensation|pay|包薪|薪资|月薪|年薪)[:\s]*([^\n]{3,80})",
    re.I,
)
_LOC_RE = re.compile(
    r"(?:location|based\s+in|work\s+from|remote|hybrid|办公地点|工作地点|基地)[:\s]*([^\n]{2,80})",
    re.I,
)


def _section_after(text: str, header_patterns: list, stop_patterns: list) -> str:
    lines = text.splitlines()
    start = None
    header_re = re.compile("|".join(f"(?:{p})" for p in header_patterns), re.I)
    stop_re = re.compile("|".join(f"(?:{p})" for p in stop_patterns), re.I)
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if header_re.search(stripped) and len(stripped) < 80:
            start = i + 1
            break
    if start is None:
        return ""
    collected = []
    for line in lines[start:]:
        stripped = line.strip()
        if stripped and stop_re.search(stripped) and len(stripped) < 80:
            break
        collected.append(line)
    return "\n".join(collected).strip()


def _guess_title(text: str, html: Optional[str] = None) -> str:
    if html:
        soup = BeautifulSoup(html, "lxml")
        h1 = soup.find("h1")
        if h1 and h1.get_text(strip=True):
            return h1.get_text(strip=True)[:200]
        if soup.title and soup.title.string:
            return soup.title.string.strip()[:200]
    for line in text.splitlines():
        s = line.strip()
        if 8 <= len(s) <= 120:
            return s
    return ""


def _guess_company(text: str, url: str = "") -> str:
    m = re.search(r"(?:company|about\s+us|雇主|公司)[:\s]+([^\n]{2,80})", text, re.I)
    if m:
        return m.group(1).strip()[:120]
    host = urlparse(url).netloc
    if host:
        return host.replace("www.", "").split(".")[0].title()
    return ""


def structure_jd_text(raw_text: str, source: str = "", html: Optional[str] = None) -> JobDescription:
    text = (raw_text or "").strip()
    if not text:
        raise ValueError("Empty job description text")

    responsibilities = _section_after(text, _RESP_HEADERS, _REQ_HEADERS)
    requirements = _section_after(
        text,
        _REQ_HEADERS,
        _RESP_HEADERS + [r"benefits?", r"福利", r"about\s+(?:us|the\s+company)"],
    )

    if not responsibilities and not requirements:
        mid = max(len(text) // 2, 1)
        responsibilities = text[:mid].strip()
        requirements = text[mid:].strip()
    elif not responsibilities:
        responsibilities = text[: min(2000, len(text))].strip()
    elif not requirements:
        requirements = text[min(len(text) // 2, 2000) :].strip()

    salary_m = _SALARY_RE.search(text)
    loc_m = _LOC_RE.search(text)

    return JobDescription(
        title=_guess_title(text, html),
        company=_guess_company(text, source if source.startswith("http") else ""),
        responsibilities=responsibilities,
        requirements=requirements,
        location_hints=(loc_m.group(1).strip() if loc_m else ""),
        salary_hints=(salary_m.group(1).strip() if salary_m else ""),
        raw_text=text,
        source=source,
    )


def fetch_url(url: str, timeout: float = 30.0) -> JobDescription:
    with httpx.Client(
        follow_redirects=True, timeout=timeout, headers={"User-Agent": USER_AGENT}
    ) as client:
        resp = client.get(url)
        resp.raise_for_status()
        html = resp.text

    extracted = trafilatura.extract(html, include_comments=False, include_tables=True) or ""
    if not extracted.strip():
        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
            tag.decompose()
        extracted = soup.get_text("\n", strip=True)

    if not extracted.strip():
        raise ValueError(f"Could not extract job text from URL: {url}")

    return structure_jd_text(extracted, source=url, html=html)


def load_jd_file(path: str) -> JobDescription:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"JD file not found: {path}")
    text = p.read_text(encoding="utf-8", errors="replace")
    return structure_jd_text(text, source=str(p))


def load_job_description(url: Optional[str] = None, jd_file: Optional[str] = None) -> JobDescription:
    if jd_file:
        return load_jd_file(jd_file)
    if url:
        return fetch_url(url)
    raise ValueError("Provide either --url or --jd-file")
