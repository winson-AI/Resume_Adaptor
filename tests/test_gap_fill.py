"""Unit/smoke tests for Profile Adaptor gap-fill behaviors."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from profile_adaptor.checkers.matching import extract_required_years, parse_human_years
from profile_adaptor.checkers.report import run_structural_checkers
from profile_adaptor.checkers.skills_match import check_skills_match
from profile_adaptor.config import Settings
from profile_adaptor.crawler.jd_crawler import load_jd_file, structure_jd_text
from profile_adaptor.export.docx_filler import fill_docx
from profile_adaptor.hitl.gates import build_hitl, validate_hitl
from profile_adaptor.llm.rewriter import _fallback_adapt, rewrite_resume
from profile_adaptor.models import AdaptedResume
from profile_adaptor.parse.resume_parser import parse_resume
from profile_adaptor.pipeline import (
    apply_resume_corrections,
    ingest_sources,
    rewrite_with_hitl,
    run_match_audit_stage,
)

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_JD = ROOT / "samples" / "sample_jd.txt"
SAMPLE_RESUME = ROOT / "samples" / "sample_resume.docx"


class _FailingLLM:
    def chat(self, messages, temperature: float = 0.2) -> str:
        raise RuntimeError("simulated LLM failure")


class MatchingTests(unittest.TestCase):
    def test_years_helpers(self):
        self.assertEqual(extract_required_years("5+ years of experience"), 5.0)
        self.assertEqual(parse_human_years("5"), 5.0)
        self.assertIsNone(parse_human_years(""))


class JdCrawlerTests(unittest.TestCase):
    def test_rejects_boss_loading_shell(self):
        shell = "BOSS直聘\n加载中\n请稍候"
        with self.assertRaises(ValueError) as ctx:
            structure_jd_text(shell, source="https://www.zhipin.com/job_detail/abc.html")
        self.assertIn("SPA", str(ctx.exception))

    def test_accepts_sample_jd(self):
        jd = load_jd_file(str(SAMPLE_JD))
        self.assertTrue(len(jd.requirements) >= 30)
        self.assertTrue(len(jd.responsibilities) >= 40)

    def test_jsonld_jobposting_extract(self):
        from profile_adaptor.crawler.jd_crawler import fetch_url

        html = """
        <html><head><title>BOSS直聘</title>
        <script type="application/ld+json">
        {
          "@type": "JobPosting",
          "title": "Backend Engineer",
          "description": "Responsibilities\\n- Build APIs in Python\\nRequirements\\n- 5 years experience with FastAPI and PostgreSQL",
          "hiringOrganization": {"name": "Acme"},
          "jobLocation": {"address": {"addressLocality": "Shanghai"}}
        }
        </script>
        <body>加载中 请稍候</body></html>
        """
        with patch("profile_adaptor.crawler.jd_crawler.httpx.Client") as client_cls:
            client = client_cls.return_value.__enter__.return_value
            resp = client.get.return_value
            resp.raise_for_status = lambda: None
            resp.content = html.encode("utf-8")
            resp.encoding = "utf-8"
            jd = fetch_url("https://www.zhipin.com/job_detail/x.html")
        self.assertEqual(jd.title, "Backend Engineer")
        self.assertIn("FastAPI", jd.requirements or jd.raw_text)


class CheckerTests(unittest.TestCase):
    def test_structural_on_samples(self):
        jd = load_jd_file(str(SAMPLE_JD))
        resume = parse_resume(str(SAMPLE_RESUME))
        report = run_structural_checkers(jd, resume)
        names = {r.name for r in report.results}
        self.assertIn("skills_match", names)
        self.assertIn("job_content_match", names)
        self.assertTrue(any(r.name == "skills_match" for r in report.results))

    def test_skills_checker_runs(self):
        jd = load_jd_file(str(SAMPLE_JD))
        resume = parse_resume(str(SAMPLE_RESUME))
        result = check_skills_match(jd, resume)
        self.assertEqual(result.name, "skills_match")


class HitlTests(unittest.TestCase):
    def test_agreement_required_fields_optional(self):
        ok, errs = validate_hitl(build_hitl(customer_agreed_to_rewrite=False))
        self.assertFalse(ok)
        self.assertTrue(any("agreement" in e for e in errs))

        ok2, errs2 = validate_hitl(build_hitl(customer_agreed_to_rewrite=True))
        self.assertTrue(ok2)
        self.assertEqual(errs2, [])


class DocxFillTests(unittest.TestCase):
    def test_fill_preserves_sections(self):
        resume = parse_resume(str(SAMPLE_RESUME))
        adapted = AdaptedResume(
            contact=resume.contact,
            summary="Adapted summary for platform role.",
            skills=resume.skills + ["Observability"],
            experience=list(resume.experience),
            education=list(resume.education),
        )
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "out.docx"
            path, report = fill_docx(SAMPLE_RESUME, adapted, out)
            self.assertTrue(path.is_file())
            self.assertFalse(report.degraded)
            self.assertIn("summary", report.sections_filled)
            self.assertIn("experience", report.sections_filled)


class FallbackTests(unittest.TestCase):
    def test_fallback_flags(self):
        jd = load_jd_file(str(SAMPLE_JD))
        resume = parse_resume(str(SAMPLE_RESUME))
        adapted = _fallback_adapt(resume, jd, reason="unit-test")
        self.assertTrue(adapted.used_fallback)
        self.assertEqual(adapted.fallback_reason, "unit-test")

    def test_rewrite_fail_closed(self):
        jd = load_jd_file(str(SAMPLE_JD))
        resume = parse_resume(str(SAMPLE_RESUME))
        hitl = build_hitl(customer_agreed_to_rewrite=True)
        with self.assertRaises(RuntimeError):
            rewrite_resume(_FailingLLM(), jd, resume, hitl, allow_fallback=False)

    def test_rewrite_uses_fallback_when_allowed(self):
        jd = load_jd_file(str(SAMPLE_JD))
        resume = parse_resume(str(SAMPLE_RESUME))
        hitl = build_hitl(customer_agreed_to_rewrite=True)
        adapted = rewrite_resume(_FailingLLM(), jd, resume, hitl, allow_fallback=True)
        self.assertTrue(adapted.used_fallback)


class ReviewEditTests(unittest.TestCase):
    def test_apply_resume_corrections(self):
        resume = parse_resume(str(SAMPLE_RESUME))
        updated = apply_resume_corrections(
            resume,
            summary="Corrected summary",
            skills="Python, Go",
            notes="Parsed note",
        )
        self.assertEqual(updated.summary, "Corrected summary")
        self.assertEqual(updated.skills, ["Python", "Go"])
        self.assertEqual(updated.extras, "Parsed note")


class PipelineSmokeTests(unittest.TestCase):
    def test_rewrite_with_agree_empty_optional_fields_and_fallback(self):
        ingested = ingest_sources(
            resume_path=str(SAMPLE_RESUME),
            jd_file=str(SAMPLE_JD),
        )
        self.assertIsNone(ingested.error)
        self.assertIsNotNone(ingested.jd)
        self.assertIsNotNone(ingested.resume)

        with tempfile.TemporaryDirectory() as td:
            settings = Settings(output_dir=Path(td), templates_dir=Path(td) / "templates")
            settings.ensure_dirs()
            audited = run_match_audit_stage(
                settings,
                ingested.jd,
                ingested.resume,
                run_id=ingested.run_id,
                skip_llm=True,
            )
            with patch(
                "profile_adaptor.pipeline.create_llm_client",
                return_value=_FailingLLM(),
            ):
                result = rewrite_with_hitl(
                    settings=settings,
                    jd=ingested.jd,
                    resume=ingested.resume,
                    salary="",
                    work_years="",
                    work_base="",
                    customer_agreed_to_rewrite=True,
                    allow_fallback=True,
                    skip_llm_audit=True,
                    prior_checks=audited.checks,
                    prior_match_audit=audited.match_audit,
                    run_id=ingested.run_id,
                )
            self.assertIsNone(result.error)
            self.assertEqual(result.step, "done")
            self.assertTrue(result.adapted and result.adapted.used_fallback)
            self.assertTrue(result.output_docx and Path(result.output_docx).is_file())
            self.assertIsNotNone(result.fill_report)
            self.assertTrue(result.events_jsonl and Path(result.events_jsonl).is_file())

    def test_rewrite_without_agree_blocked(self):
        ingested = ingest_sources(
            resume_path=str(SAMPLE_RESUME),
            jd_file=str(SAMPLE_JD),
        )
        with tempfile.TemporaryDirectory() as td:
            settings = Settings(output_dir=Path(td), templates_dir=Path(td) / "templates")
            settings.ensure_dirs()
            result = rewrite_with_hitl(
                settings=settings,
                jd=ingested.jd,
                resume=ingested.resume,
                customer_agreed_to_rewrite=False,
                allow_fallback=True,
                skip_llm_audit=True,
                run_id=ingested.run_id,
            )
            self.assertIsNotNone(result.error)
            self.assertIn("agreement", result.error.lower())


if __name__ == "__main__":
    unittest.main()
