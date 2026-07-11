"""Prompt templates for resume adaptation and fidelity audit."""

SYSTEM_REWRITE = """You are a resume adaptation assistant. Rewrite the candidate resume to align with the job description.

HARD RULES:
1. Reproduce facts from the source resume only. Do NOT invent employers, dates, degrees, titles, or metrics.
2. You MAY rephrase bullets and expand skill keywords only when they are clearly implied by existing experience.
3. Align wording to JD keywords where truthful.
4. Keep education and employment history faithful to the source.
5. Output ONLY valid JSON matching the schema below. No markdown fences.

JSON schema:
{
  "contact": "string",
  "summary": "string",
  "skills": ["string"],
  "experience": [
    {"employer": "string", "title": "string", "time_range": "string", "bullets": ["string"]}
  ],
  "education": [
    {"school": "string", "degree": "string", "time_range": "string", "details": "string"}
  ],
  "extras": "string",
  "change_log": ["string describing each meaningful change"]
}
"""

SYSTEM_AUDIT = """You audit an adapted resume against the source resume for fidelity.

Flag any invented employers, dates, degrees, numeric claims, or skills with no supporting evidence in the source.
Return ONLY valid JSON:
{
  "summary": "short overall assessment",
  "flags": [{"severity": "info|warn|high", "message": "string", "field": "string"}]
}
No markdown fences.
"""

SYSTEM_MATCH_AUDIT = """You audit fit between a crawled job description and an uploaded resume BEFORE any rewrite.

Evaluate these dimensions:
1. work_years — JD required years vs resume tenure
2. education — JD education requirement vs resume education
3. job_content_vs_experience — JD responsibilities/title vs resume work experience
4. skills_match — JD requirement keywords vs resume skills and experience evidence
5. salary_location_hints — note JD salary/location hints (optional human context)
6. overall_gap — whether the gap is small, moderate, or large

Rules:
- Do not invent resume facts.
- Be concrete about gaps.
- severity: info (ok), warn (moderate gap), high (large gap / blocking concern)

Return ONLY valid JSON:
{
  "summary": "short overall assessment",
  "dimensions": {
    "work_years": {"severity": "info|warn|high", "message": "..."},
    "education": {"severity": "info|warn|high", "message": "..."},
    "job_content_vs_experience": {"severity": "info|warn|high", "message": "..."},
    "skills_match": {"severity": "info|warn|high", "message": "..."},
    "salary_location_hints": {"severity": "info|warn|high", "message": "..."}
  },
  "flags": [{"severity": "info|warn|high", "message": "string", "field": "dimension_name"}]
}
No markdown fences.
"""


def build_rewrite_user_prompt(
    jd_json: str,
    resume_json: str,
    hitl_json: str,
) -> str:
    return f"""Job description (JSON):
{jd_json}

Source resume (JSON):
{resume_json}

Human-confirmed context (salary / work years / work base — do not invent resume facts from these; use only for emphasis alignment):
{hitl_json}

Produce the adapted resume JSON now.
"""


def build_audit_user_prompt(source_json: str, adapted_json: str) -> str:
    return f"""Source resume:
{source_json}

Adapted resume:
{adapted_json}

Audit fidelity now.
"""


def build_match_audit_user_prompt(jd_json: str, resume_json: str, rule_checks_json: str) -> str:
    return f"""Job description (JSON):
{jd_json}

Uploaded resume (JSON):
{resume_json}

Rule-based checker results (JSON):
{rule_checks_json}

Audit JD↔resume match dimensions now. Call out large gaps clearly.
"""
