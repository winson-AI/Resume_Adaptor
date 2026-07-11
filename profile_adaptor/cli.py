"""CLI entry: tui | web | run."""

from __future__ import annotations

import argparse
import sys

from profile_adaptor.config import load_settings
from profile_adaptor.event_log import setup_app_logging
from profile_adaptor.pipeline import run_pipeline

setup_app_logging()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="profile-adaptor",
        description="Adapt a resume to a crawled job description (local Ollama or web LLM).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    tui = sub.add_parser("tui", help="Launch interactive Textual TUI")
    tui.add_argument("--provider", choices=["ollama", "web"])
    tui.add_argument("--model")

    web = sub.add_parser("web", help="Launch local browser UI")
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--port", type=int, default=8765)
    web.add_argument("--provider", choices=["ollama", "web"])
    web.add_argument("--model")

    run = sub.add_parser("run", help="One-shot non-interactive pipeline")
    run.add_argument("--url", help="Hiring page URL")
    run.add_argument("--jd-file", help="Local JD text file")
    run.add_argument("--resume", required=True, help="Resume .docx or .pdf")
    run.add_argument("--template", help="DOCX template path or templates/ filename")
    run.add_argument(
        "--agree",
        action="store_true",
        required=True,
        help="Required: agree to proceed with rewrite after match review",
    )
    run.add_argument("--salary", default="", help="Optional HITL: expected salary")
    run.add_argument("--years", default="", dest="work_years", help="Optional HITL: work years")
    run.add_argument("--base", default="", dest="work_base", help="Optional HITL: work base")
    run.add_argument("--provider", choices=["ollama", "web"])
    run.add_argument("--model")
    run.add_argument("--out", dest="output_dir")
    run.add_argument("--templates-dir")
    run.add_argument("--pdf", action="store_true")
    run.add_argument("--strict", action="store_true")
    run.add_argument(
        "--no-fallback",
        action="store_true",
        help="Fail if LLM rewrite fails (do not use deterministic fallback)",
    )
    run.add_argument("--skip-llm-audit", action="store_true")

    return parser


def cmd_run(args: argparse.Namespace) -> int:
    if not args.url and not args.jd_file:
        print("error: provide --url or --jd-file", file=sys.stderr)
        return 2
    if not args.agree:
        print("error: --agree is required to proceed with rewrite", file=sys.stderr)
        return 2
    settings = load_settings(
        provider=args.provider,
        model=args.model,
        strict=args.strict,
        export_pdf=args.pdf,
        templates_dir=args.templates_dir,
        output_dir=args.output_dir,
    )
    result = run_pipeline(
        settings=settings,
        resume_path=args.resume,
        salary=args.salary,
        work_years=args.work_years,
        work_base=args.work_base,
        url=args.url,
        jd_file=args.jd_file,
        template=args.template,
        agree=args.agree,
        allow_fallback=not args.no_fallback,
        skip_llm_audit=args.skip_llm_audit,
    )
    if result.error:
        print(f"ERROR: {result.error}", file=sys.stderr)
        if result.checks:
            for r in result.checks.results:
                mark = "OK" if r.ok else r.severity.upper()
                print(f"  [{mark}] {r.name}: {r.message}", file=sys.stderr)
        if result.audit_json:
            print(f"Audit: {result.audit_json}", file=sys.stderr)
        if result.events_jsonl:
            print(f"Events: {result.events_jsonl}", file=sys.stderr)
        return 1
    print(f"Run ID: {result.run_id}")
    if result.checks:
        print("Pre-rewrite checks:")
        for r in result.checks.results:
            mark = "OK" if r.ok else r.severity.upper()
            print(f"  [{mark}] {r.name}: {r.message}")
        if result.checks.has_warnings:
            print("NOTICE: Moderate JD↔resume gaps remain; review before using the adapted resume.")
    if result.adapted and result.adapted.used_fallback:
        print(f"WARNING: LLM fallback used — {result.adapted.fallback_reason}")
    if result.fill_report:
        print(
            f"Fill report: filled={result.fill_report.sections_filled} "
            f"missing={result.fill_report.sections_missing} degraded={result.fill_report.degraded}"
        )
    print(f"DOCX:   {result.output_docx}")
    if result.output_pdf:
        print(f"PDF:    {result.output_pdf}")
    print(f"Context:{result.context_json}")
    print(f"Audit:  {result.audit_json}")
    if result.events_jsonl:
        print(f"Events: {result.events_jsonl}")
    if result.audit:
        print(f"Audit summary: {result.audit.summary}")
        for f in result.audit.flags:
            print(f"  - [{f.severity}] {f.message}")
    return 0


def cmd_tui(args: argparse.Namespace) -> int:
    from profile_adaptor.tui.app import run_tui

    settings = load_settings(provider=args.provider, model=args.model)
    run_tui(settings)
    return 0


def cmd_web(args: argparse.Namespace) -> int:
    from profile_adaptor.web.app import run_web

    settings = load_settings(provider=args.provider, model=args.model)
    run_web(settings, host=args.host, port=args.port)
    return 0


def main(argv: list = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "run":
        return cmd_run(args)
    if args.command == "tui":
        return cmd_tui(args)
    if args.command == "web":
        return cmd_web(args)
    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
