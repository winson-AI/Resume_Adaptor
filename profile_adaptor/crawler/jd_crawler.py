"""Fetch and structure job descriptions from URLs or local files (fast path)."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Pattern, Tuple
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

# Cap download / parse work for responsiveness
_MAX_HTML_BYTES = 2_000_000
_DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=12.0, write=5.0, pool=5.0)

_SPA_HOST_MARKERS = (
    "zhipin.com",
    "boss.zhipin",
    "lagou.com",
    "liepin.com",
    "51job.com",
    "zhaopin.com",
    "linkedin.com",
    "indeed.com",
)

_SPA_SHELL_MARKERS = (
    "加载中",
    "请稍候",
    "请稍后",
    "正在加载",
    "页面加载中",
    "enable javascript",
    "javascript is required",
    "浏览器版本过低",
    "请升级浏览器",
    "验证后继续访问",
    "滑动验证",
    "人机验证",
    "access denied",
    "just a moment",
)

_NOISE_TITLE_MARKERS = (
    "boss直聘",
    "加载中",
    "请稍候",
    "linkedin",
    "indeed",
    "拉勾",
    "猎聘",
)

_REQ_HEADERS = (
    r"requirements?",
    r"qualifications?",
    r"what\s+(?:you|we)\s+(?:need|look|bring)",
    r"must\s+have",
    r"you\s+have",
    r"skills?",
    r"任职要求",
    r"岗位要求",
    r"职位要求",
    r"要求",
)
_RESP_HEADERS = (
    r"responsibilities",
    r"what\s+you(?:'ll| will)\s+do",
    r"about\s+the\s+(?:role|job)",
    r"the\s+role",
    r"job\s+description",
    r"duties",
    r"岗位职责",
    r"工作职责",
    r"职位描述",
    r"职责",
)
_STOP_AFTER_REQ = _RESP_HEADERS + (r"benefits?", r"福利", r"about\s+(?:us|the\s+company)")

_SALARY_RE = re.compile(
    r"(?:salary|compensation|pay|包薪|薪资|月薪|年薪)[:\s]*([^\n]{3,80})",
    re.I,
)
_LOC_RE = re.compile(
    r"(?:location|based\s+in|work\s+from|remote|hybrid|办公地点|工作地点|基地)[:\s]*([^\n]{2,80})",
    re.I,
)
_COMPANY_RE = re.compile(r"(?:company|about\s+us|雇主|公司)[:\s]+([^\n]{2,80})", re.I)

_JSONLD_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.I | re.S,
)
_NEXT_DATA_RE = re.compile(
    r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>',
    re.I | re.S,
)
_INIT_STATE_RE = re.compile(
    r"window\.(?:__INITIAL_STATE__|INIT_DATA|pageData)\s*=\s*(\{.*?\});?\s*</script>",
    re.I | re.S,
)


@lru_cache(maxsize=16)
def _compiled_pair(header_key: str, stop_key: str) -> Tuple[Pattern[str], Pattern[str]]:
    headers = _REQ_HEADERS if header_key == "req" else _RESP_HEADERS
    stops = _STOP_AFTER_REQ if stop_key == "after_req" else _REQ_HEADERS
    header_re = re.compile("|".join(f"(?:{p})" for p in headers), re.I)
    stop_re = re.compile("|".join(f"(?:{p})" for p in stops), re.I)
    return header_re, stop_re


def _section_after(text: str, header_key: str, stop_key: str) -> str:
    header_re, stop_re = _compiled_pair(header_key, stop_key)
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        if len(stripped) < 80 and header_re.search(stripped):
            start = i + 1
            break
    if start is None:
        return ""
    collected = []
    for line in lines[start:]:
        stripped = line.strip()
        if stripped and len(stripped) < 80 and stop_re.search(stripped):
            break
        collected.append(line)
    return "\n".join(collected).strip()


def _host_is_spa_board(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return any(m in host for m in _SPA_HOST_MARKERS)


def _looks_like_spa_shell(text: str) -> bool:
    compact = re.sub(r"\s+", "", (text or "").lower())
    if not compact:
        return True
    hits = sum(1 for m in _SPA_SHELL_MARKERS if m.lower().replace(" ", "") in compact)
    if hits >= 1 and len(compact) < 400:
        return True
    if hits >= 2:
        return True
    # Tiny pages that are mostly brand chrome
    if len(compact) < 80:
        return True
    return False


def _is_noise_title(title: str) -> bool:
    t = (title or "").strip().lower()
    if not t:
        return True
    return any(m in t for m in _NOISE_TITLE_MARKERS)


def _guess_title_from_soup(soup: BeautifulSoup) -> str:
    h1 = soup.find("h1")
    if h1:
        t = h1.get_text(" ", strip=True)
        if t and not _is_noise_title(t):
            return t[:200]
    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        t = str(og["content"]).strip()
        if t and not _is_noise_title(t):
            return t[:200]
    if soup.title and soup.title.string:
        t = soup.title.string.strip()
        if t and not _is_noise_title(t):
            return t[:200]
    return ""


def _guess_title_from_text(text: str) -> str:
    for line in text.splitlines():
        s = line.strip()
        if 8 <= len(s) <= 120 and not _is_noise_title(s):
            return s
    return ""


def _guess_company(text: str, url: str = "") -> str:
    m = _COMPANY_RE.search(text)
    if m:
        return m.group(1).strip()[:120]
    host = urlparse(url).netloc
    if host and not _host_is_spa_board(url):
        return host.replace("www.", "").split(".")[0].title()
    return ""


def _soup_fallback_text(html: str) -> Tuple[str, BeautifulSoup]:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "svg", "iframe"]):
        tag.decompose()
    return soup.get_text("\n", strip=True), soup


def _walk_strings(obj: Any, out: List[str], depth: int = 0) -> None:
    if depth > 8 or len(out) > 80:
        return
    if isinstance(obj, str):
        s = obj.strip()
        if 40 <= len(s) <= 8000 and not _looks_like_spa_shell(s):
            out.append(s)
        return
    if isinstance(obj, dict):
        # Prefer known JD keys first
        preferred = (
            "description",
            "postDescription",
            "jobDescription",
            "jobDesc",
            "responsibilities",
            "requirements",
            "qualification",
            "qualifications",
            "duty",
            "content",
            "text",
            "jobName",
            "title",
            "positionName",
        )
        for key in preferred:
            if key in obj:
                _walk_strings(obj[key], out, depth + 1)
        for key, val in obj.items():
            if key in preferred:
                continue
            if any(
                k in str(key).lower()
                for k in ("desc", "duty", "require", "respons", "skill", "job", "post")
            ):
                _walk_strings(val, out, depth + 1)
        return
    if isinstance(obj, list):
        for item in obj[:40]:
            _walk_strings(item, out, depth + 1)


def _jobposting_from_jsonld(data: Any) -> Dict[str, str]:
    nodes: List[Any]
    if isinstance(data, list):
        nodes = data
    elif isinstance(data, dict) and "@graph" in data:
        nodes = list(data.get("@graph") or [])
    else:
        nodes = [data]
    for node in nodes:
        if not isinstance(node, dict):
            continue
        typ = node.get("@type") or node.get("type") or ""
        typ_l = " ".join(typ) if isinstance(typ, list) else str(typ)
        if "jobposting" not in typ_l.lower():
            continue
        title = str(node.get("title") or "")
        desc = str(node.get("description") or "")
        company = ""
        org = node.get("hiringOrganization") or {}
        if isinstance(org, dict):
            company = str(org.get("name") or "")
        loc = ""
        jl = node.get("jobLocation") or {}
        if isinstance(jl, dict):
            addr = jl.get("address") or jl
            if isinstance(addr, dict):
                loc = str(
                    addr.get("addressLocality")
                    or addr.get("addressRegion")
                    or addr.get("name")
                    or ""
                )
        salary = ""
        base = node.get("baseSalary") or {}
        if isinstance(base, dict):
            val = base.get("value") or base
            if isinstance(val, dict):
                salary = " ".join(
                    str(x)
                    for x in (
                        val.get("minValue"),
                        val.get("maxValue"),
                        val.get("unitText"),
                    )
                    if x
                )
            else:
                salary = str(val)
        return {
            "title": title,
            "description": desc,
            "company": company,
            "location": loc,
            "salary": salary,
        }
    return {}


def _extract_embedded_job_text(html: str) -> Dict[str, str]:
    """Pull JobPosting / embedded state when static HTML is an SPA shell."""
    # JSON-LD JobPosting
    for m in _JSONLD_RE.finditer(html or ""):
        raw = m.group(1).strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        found = _jobposting_from_jsonld(data)
        if found.get("description"):
            return found

    # Next.js payload
    m = _NEXT_DATA_RE.search(html or "")
    if m:
        try:
            data = json.loads(m.group(1))
            blobs: List[str] = []
            _walk_strings(data, blobs)
            if blobs:
                return {"description": "\n\n".join(blobs[:12]), "title": "", "company": ""}
        except json.JSONDecodeError:
            pass

    # Generic initial state
    m = _INIT_STATE_RE.search(html or "")
    if m:
        try:
            data = json.loads(m.group(1))
            blobs = []
            _walk_strings(data, blobs)
            if blobs:
                return {"description": "\n\n".join(blobs[:12]), "title": "", "company": ""}
        except json.JSONDecodeError:
            pass

    return {}


def _spa_failure_message(url: str) -> str:
    host = urlparse(url).netloc or url
    return (
        f"Could not extract a usable job description from {host}. "
        "This looks like a JavaScript/SPA hiring page (e.g. BOSS直聘 loading shell: "
        "“加载中 / 请稍候”). Paste the JD text or upload a .txt/.html file, then Refresh JD."
    )


def assert_jd_usable(jd: JobDescription) -> None:
    """Raise if structured JD is still an SPA shell / empty chrome."""
    blob = "\n".join(
        [
            jd.title or "",
            jd.company or "",
            jd.responsibilities or "",
            jd.requirements or "",
            jd.raw_text or "",
        ]
    )
    if _looks_like_spa_shell(blob):
        raise ValueError(_spa_failure_message(jd.source or "URL"))
    useful = len((jd.responsibilities or "").strip()) + len((jd.requirements or "").strip())
    if useful < 60 and _host_is_spa_board(jd.source or ""):
        raise ValueError(_spa_failure_message(jd.source or "URL"))
    if useful < 40 and len((jd.raw_text or "").strip()) < 120:
        raise ValueError(
            "Extracted job text is too thin to audit. Paste the full JD or upload a JD file."
        )


def structure_jd_text(
    raw_text: str,
    source: str = "",
    html: Optional[str] = None,
    soup: Optional[BeautifulSoup] = None,
    *,
    enforce_quality: bool = True,
) -> JobDescription:
    text = (raw_text or "").strip()
    if not text:
        raise ValueError("Empty job description text")

    # Bound structuring work on huge pages
    if len(text) > 40_000:
        text = text[:40_000]

    responsibilities = _section_after(text, "resp", "req")
    requirements = _section_after(text, "req", "after_req")

    if not responsibilities and not requirements:
        # Avoid inventing fake halves from SPA chrome
        if _looks_like_spa_shell(text) or len(text) < 120:
            responsibilities = ""
            requirements = ""
        else:
            mid = max(len(text) // 2, 1)
            responsibilities = text[:mid].strip()
            requirements = text[mid:].strip()
    elif not responsibilities:
        responsibilities = text[: min(2000, len(text))].strip()
    elif not requirements:
        requirements = text[min(len(text) // 2, 2000) :].strip()

    title = ""
    if soup is not None:
        title = _guess_title_from_soup(soup)
    elif html:
        soup_quick = BeautifulSoup(html, "lxml")
        title = _guess_title_from_soup(soup_quick)
    if not title:
        title = _guess_title_from_text(text)

    salary_m = _SALARY_RE.search(text)
    loc_m = _LOC_RE.search(text)

    jd = JobDescription(
        title=title,
        company=_guess_company(text, source if source.startswith("http") else ""),
        responsibilities=responsibilities,
        requirements=requirements,
        location_hints=(loc_m.group(1).strip() if loc_m else ""),
        salary_hints=(salary_m.group(1).strip() if salary_m else ""),
        raw_text=text,
        source=source,
    )
    if enforce_quality:
        assert_jd_usable(jd)
    return jd


def fetch_url(url: str, timeout: Optional[httpx.Timeout] = None) -> JobDescription:
    timeout = timeout or _DEFAULT_TIMEOUT
    limits = httpx.Limits(max_keepalive_connections=2, max_connections=4)
    with httpx.Client(
        follow_redirects=True,
        timeout=timeout,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        },
        limits=limits,
    ) as client:
        resp = client.get(url)
        resp.raise_for_status()
        raw = resp.content[:_MAX_HTML_BYTES]
        html = raw.decode(resp.encoding or "utf-8", errors="replace")

    extracted = (
        trafilatura.extract(
            html,
            include_comments=False,
            include_tables=False,
            include_links=False,
            include_images=False,
            favor_recall=False,
            no_fallback=False,
        )
        or ""
    )

    soup = None
    if len(extracted.strip()) < 80 or _looks_like_spa_shell(extracted):
        # Prefer embedded JobPosting / app state over SPA chrome text
        embedded = _extract_embedded_job_text(html)
        if embedded.get("description"):
            desc = embedded["description"]
            # Strip crude HTML tags if description is HTML
            if "<" in desc and ">" in desc:
                desc = BeautifulSoup(desc, "lxml").get_text("\n", strip=True)
            jd = structure_jd_text(
                desc,
                source=url,
                enforce_quality=False,
            )
            if embedded.get("title"):
                jd.title = embedded["title"][:200]
            if embedded.get("company"):
                jd.company = embedded["company"][:120]
            if embedded.get("location"):
                jd.location_hints = embedded["location"][:120]
            if embedded.get("salary"):
                jd.salary_hints = embedded["salary"][:120]
            assert_jd_usable(jd)
            return jd

        extracted, soup = _soup_fallback_text(html)

    if not extracted.strip() or _looks_like_spa_shell(extracted):
        raise ValueError(_spa_failure_message(url))

    return structure_jd_text(
        extracted,
        source=url,
        html=html if soup is None else None,
        soup=soup,
    )


def load_jd_file(path: str) -> JobDescription:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"JD file not found: {path}")
    data = p.read_bytes()[:_MAX_HTML_BYTES]
    text = data.decode("utf-8", errors="replace")
    suffix = p.suffix.lower()
    if suffix in {".html", ".htm"}:
        extracted = trafilatura.extract(
            text,
            include_comments=False,
            include_tables=False,
            include_links=False,
            favor_recall=False,
        ) or ""
        if len(extracted.strip()) < 80 or _looks_like_spa_shell(extracted):
            embedded = _extract_embedded_job_text(text)
            if embedded.get("description"):
                desc = embedded["description"]
                if "<" in desc and ">" in desc:
                    desc = BeautifulSoup(desc, "lxml").get_text("\n", strip=True)
                jd = structure_jd_text(desc, source=str(p), enforce_quality=False)
                if embedded.get("title"):
                    jd.title = embedded["title"][:200]
                assert_jd_usable(jd)
                return jd
            extracted, soup = _soup_fallback_text(text)
            return structure_jd_text(extracted, source=str(p), soup=soup)
        return structure_jd_text(extracted or text, source=str(p), html=text)
    # Pasted/plain text: still reject pure loading shells
    return structure_jd_text(text, source=str(p))


def load_job_description(url: Optional[str] = None, jd_file: Optional[str] = None) -> JobDescription:
    """Tool invoker: load JD from file first, else URL, with SPA-shell guards."""
    if jd_file:
        return load_jd_file(jd_file)
    if url:
        return fetch_url(url)
    raise ValueError("Provide either a JD URL or a JD file / pasted text")
