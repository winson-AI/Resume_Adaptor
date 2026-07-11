"""Textual TUI — stepped wizard with review edits and agreement-to-rewrite."""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Button,
    Checkbox,
    Footer,
    Header,
    Input,
    Label,
    RichLog,
    Select,
    Static,
    TextArea,
)

from profile_adaptor.config import Settings
from profile_adaptor.event_log import EventLog, setup_app_logging
from profile_adaptor.hitl.template_selector import list_templates
from profile_adaptor.models import WizardSession
from profile_adaptor.pipeline import (
    apply_ingest_to_session,
    apply_match_audit_to_session,
    apply_review_corrections_to_session,
    apply_rewrite_to_session,
)

setup_app_logging()


def _fmt_events(session: WizardSession, limit: int = 12) -> str:
    events = session.events[-limit:]
    if not events:
        return ""
    lines = []
    for e in events:
        pct = f" {int(e.get('progress', 0) * 100)}%" if e.get("progress") is not None else ""
        lines.append(f"[{e.get('status')}] {e.get('stage')}/{e.get('event')}{pct}: {e.get('message')}")
    return "\n".join(lines)


def _fmt_jd(session: WizardSession) -> str:
    jd = session.jd
    if not jd:
        return "(no JD)"
    return (
        f"Title: {jd.title}\n"
        f"Company: {jd.company}\n"
        f"Location hints: {jd.location_hints or '—'}\n"
        f"Salary hints: {jd.salary_hints or '—'}\n\n"
        f"Responsibilities:\n{jd.responsibilities[:1200]}\n\n"
        f"Requirements:\n{jd.requirements[:1200]}"
    )


def _fmt_resume(session: WizardSession) -> str:
    r = session.resume
    if not r:
        return "(no resume)"
    exp = []
    for e in r.experience[:4]:
        exp.append(f"- {e.employer} | {e.title} | {e.time_range}")
        for b in e.bullets[:2]:
            exp.append(f"    • {b}")
    edu = [f"- {e.school} | {e.degree} | {e.time_range}" for e in r.education[:3]]
    return (
        f"Contact:\n{r.contact or '—'}\n\n"
        f"Summary:\n{r.summary or '—'}\n\n"
        f"Skills: {', '.join(r.skills) or '—'}\n\n"
        f"Experience:\n" + ("\n".join(exp) or "—") + "\n\n"
        f"Education:\n" + ("\n".join(edu) or "—")
    )


class AgreeModal(ModalScreen[bool]):
    """Pop agreement for customer to proceed with rewrite."""

    CSS = """
    AgreeModal { align: center middle; }
    #dialog {
      width: 72;
      height: auto;
      border: thick $accent;
      background: $surface;
      padding: 1 2;
    }
    """

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="dialog"):
            yield Static(
                "Agreement required\n\n"
                "I have reviewed the match audit / gap notices and agree to rewrite the resume.",
                id="msg",
            )
            with Horizontal():
                yield Button("Agree & rewrite", variant="primary", id="yes")
                yield Button("Cancel", id="no")

    @on(Button.Pressed, "#yes")
    def yes(self) -> None:
        self.dismiss(True)

    @on(Button.Pressed, "#no")
    def no(self) -> None:
        self.dismiss(False)


class IngestScreen(Screen):
    BINDINGS = [("q", "app.quit", "Quit")]

    def compose(self) -> ComposeResult:
        app: ProfileAdaptorApp = self.app  # type: ignore
        yield Header()
        with VerticalScroll():
            yield Static("Step 1 — Input JD URL and customer resume", classes="title")
            yield Label("JD URL")
            yield Input(placeholder="https://...", id="url", value=app.session.url)
            yield Label("Or JD file path")
            yield Input(
                placeholder="./samples/sample_jd.txt",
                id="jd_file",
                value=app.session.jd_file,
            )
            yield Label("Or paste JD text")
            yield TextArea(id="jd_paste")
            yield Label("Resume path (.docx / .pdf)")
            yield Input(
                placeholder="./samples/sample_resume.docx",
                id="resume",
                value=app.session.resume_path,
            )
            yield Label("LLM provider")
            yield Select(
                [("Ollama (local)", "ollama"), ("Web LLM endpoint", "web")],
                id="provider",
                value=app.session.provider or app.settings.provider,
            )
            yield Label("Model")
            yield Input(value=app.session.model or app.settings.model, id="model")
            with Horizontal():
                yield Button("Fetch & parse", variant="primary", id="ingest")
                yield Button("Quit", id="quit")
            yield RichLog(id="log", highlight=True, markup=True)
        yield Footer()

    @on(Button.Pressed, "#quit")
    def quit_app(self) -> None:
        self.app.exit()

    @on(Button.Pressed, "#ingest")
    def do_ingest(self) -> None:
        self.run_ingest()

    @work(thread=True)
    def run_ingest(self) -> None:
        app: ProfileAdaptorApp = self.app  # type: ignore
        log = self.query_one("#log", RichLog)
        url = self.query_one("#url", Input).value.strip()
        jd_file = self.query_one("#jd_file", Input).value.strip()
        jd_paste = self.query_one("#jd_paste", TextArea).text.strip()
        resume = self.query_one("#resume", Input).value.strip()
        provider = self.query_one("#provider", Select).value
        model = self.query_one("#model", Input).value.strip()

        if not resume:
            self.call_from_thread(log.write, "[red]Resume path required[/red]")
            return
        if not url and not jd_file and not jd_paste:
            self.call_from_thread(log.write, "[red]Provide JD URL, file, or paste[/red]")
            return

        if jd_paste and not jd_file:
            tmp = Path(tempfile.gettempdir()) / f"pa_jd_{uuid.uuid4().hex[:8]}.txt"
            tmp.write_text(jd_paste, encoding="utf-8")
            jd_file = str(tmp)

        app.session.provider = str(provider or "ollama")
        app.session.model = model
        self.call_from_thread(log.write, "Fetching JD and parsing resume…")
        apply_ingest_to_session(
            app.session,
            resume_path=resume,
            url=url,
            jd_file=jd_file,
            settings=app.settings,
        )
        if app.session.error:
            self.call_from_thread(log.write, f"[red]{app.session.error}[/red]")
            return
        ev = _fmt_events(app.session, 6)
        if ev:
            self.call_from_thread(log.write, ev)
        self.call_from_thread(log.write, "[green]Parsed OK — opening review…[/green]")
        self.call_from_thread(app.push_screen, ReviewScreen())


class ReviewScreen(Screen):
    BINDINGS = [("escape", "app.pop_screen", "Back"), ("r", "refresh_both", "Refresh both")]

    def compose(self) -> ComposeResult:
        app: ProfileAdaptorApp = self.app  # type: ignore
        r = app.session.resume
        yield Header()
        with VerticalScroll():
            yield Static("Step 2 — Review / refresh parsed JD & resume", classes="title")
            if app.session.error:
                yield Static(f"[NOTICE] {app.session.error}", id="review_error", classes="notice")
            yield Static("Job description", classes="section")
            yield Static(_fmt_jd(app.session), id="jd_view")
            yield Static("Customer resume (parsed)", classes="section")
            yield Static(_fmt_resume(app.session), id="resume_view")
            yield Label("JD URL (for refresh)")
            yield Input(value=app.session.url, id="refresh_url", placeholder="https://...")
            yield Label("JD file path (for refresh)")
            yield Input(value=app.session.jd_file, id="refresh_jd_file")
            yield Label("Resume path (for refresh)")
            yield Input(value=app.session.resume_path, id="refresh_resume")
            with Horizontal():
                yield Button("Refresh JD", id="refresh_jd")
                yield Button("Refresh resume", id="refresh_resume_btn")
                yield Button("Refresh both", id="refresh_both")
            yield Label("Correct summary (optional)")
            yield TextArea(r.summary if r else "", id="edit_summary")
            yield Label("Correct skills, comma-separated (optional)")
            yield Input(
                value=", ".join(r.skills) if r else "",
                id="edit_skills",
            )
            yield Label("Raw notes / extras (optional)")
            yield TextArea(r.extras if r else "", id="edit_notes")
            with Horizontal():
                yield Button("Back", id="back")
                yield Button("Save corrections & run match audit", variant="primary", id="audit")
            yield RichLog(id="log", highlight=True, markup=True)
        yield Footer()

    def _sync_source_fields(self) -> None:
        app: ProfileAdaptorApp = self.app  # type: ignore
        app.session.url = self.query_one("#refresh_url", Input).value.strip()
        app.session.jd_file = self.query_one("#refresh_jd_file", Input).value.strip()
        path = self.query_one("#refresh_resume", Input).value.strip()
        if path:
            app.session.resume_path = path

    def _update_views(self) -> None:
        app: ProfileAdaptorApp = self.app  # type: ignore
        self.query_one("#jd_view", Static).update(_fmt_jd(app.session))
        self.query_one("#resume_view", Static).update(_fmt_resume(app.session))
        r = app.session.resume
        if r:
            self.query_one("#edit_summary", TextArea).text = r.summary or ""
            self.query_one("#edit_skills", Input).value = ", ".join(r.skills)
            self.query_one("#edit_notes", TextArea).text = r.extras or ""
        log = self.query_one("#log", RichLog)
        if app.session.error:
            log.write(f"[red]{app.session.error}[/red]")
        else:
            log.write("[green]Refresh OK — views updated.[/green]")

    @on(Button.Pressed, "#refresh_jd")
    def do_refresh_jd(self) -> None:
        self._sync_source_fields()
        self.run_refresh("jd")

    @on(Button.Pressed, "#refresh_resume_btn")
    def do_refresh_resume(self) -> None:
        self._sync_source_fields()
        self.run_refresh("resume")

    @on(Button.Pressed, "#refresh_both")
    def do_refresh_both(self) -> None:
        self._sync_source_fields()
        self.run_refresh("both")

    def action_refresh_both(self) -> None:
        self._sync_source_fields()
        self.run_refresh("both")

    @on(Button.Pressed, "#back")
    def go_back(self) -> None:
        self.app.pop_screen()

    @on(Button.Pressed, "#audit")
    def do_audit(self) -> None:
        self.run_audit()

    @work(thread=True)
    def run_refresh(self, which: str) -> None:
        from profile_adaptor.pipeline import (
            refresh_ingest_in_session,
            refresh_jd_in_session,
            refresh_resume_in_session,
        )

        app: ProfileAdaptorApp = self.app  # type: ignore
        log = self.query_one("#log", RichLog)
        self.call_from_thread(log.write, f"Refreshing {which}…")
        if which == "jd":
            refresh_jd_in_session(
                app.session,
                url=app.session.url,
                jd_file=app.session.jd_file,
                settings=app.settings,
            )
        elif which == "resume":
            refresh_resume_in_session(
                app.session, resume_path=app.session.resume_path, settings=app.settings
            )
        else:
            refresh_ingest_in_session(app.session, settings=app.settings)
        self.call_from_thread(self._update_views)

    @work(thread=True)
    def run_audit(self) -> None:
        app: ProfileAdaptorApp = self.app  # type: ignore
        log = self.query_one("#log", RichLog)
        summary = self.query_one("#edit_summary", TextArea).text
        skills = self.query_one("#edit_skills", Input).value
        notes = self.query_one("#edit_notes", TextArea).text
        apply_review_corrections_to_session(
            app.session, summary=summary, skills=skills, notes=notes
        )
        self.call_from_thread(log.write, "Running rule + LLM match audit…")
        apply_match_audit_to_session(app.session, app.settings, skip_llm=False)
        self.call_from_thread(app.push_screen, MatchAuditScreen())


class MatchAuditScreen(Screen):
    BINDINGS = [("escape", "app.pop_screen", "Back")]

    def compose(self) -> ComposeResult:
        app: ProfileAdaptorApp = self.app  # type: ignore
        yield Header()
        with VerticalScroll():
            yield Static("Step 3 — Match audit (JD ↔ resume)", classes="title")
            if app.session.error:
                yield Static(f"[NOTICE] {app.session.error}", id="gap_banner", classes="notice")
            if app.session.match_audit:
                yield Static(f"LLM summary: {app.session.match_audit.summary}", id="llm_summary")
            yield Static("Dimension results:", classes="section")
            lines = []
            if app.session.checks:
                for r in app.session.checks.results:
                    mark = "OK" if r.ok else r.severity.upper()
                    lines.append(f"[{mark}] {r.name}: {r.message}")
            if app.session.match_audit:
                for f in app.session.match_audit.flags:
                    if f.severity in ("high", "warn"):
                        lines.append(f"[LLM {f.severity.upper()}] {f.field}: {f.message}")
            yield Static("\n".join(lines) or "(no results)", id="audit_view")
            if app.session.notices:
                yield Static("Customer notices (gaps):", classes="section")
                yield Static("\n".join(f"• {n}" for n in app.session.notices), classes="notice")
            with Horizontal():
                yield Button("Back", id="back")
                yield Button("Continue to rewrite agreement", variant="primary", id="hitl")
        yield Footer()

    @on(Button.Pressed, "#back")
    def go_back(self) -> None:
        self.app.pop_screen()

    @on(Button.Pressed, "#hitl")
    def go_hitl(self) -> None:
        self.app.push_screen(HitlScreen())


class HitlScreen(Screen):
    BINDINGS = [("escape", "app.pop_screen", "Back")]

    def compose(self) -> ComposeResult:
        app: ProfileAdaptorApp = self.app  # type: ignore
        templates = list_templates(app.settings.templates_dir)
        options = [("Use source resume layout", "source")]
        options.extend((t.name, str(t)) for t in templates)
        jd = app.session.jd
        sal_hint = (jd.salary_hints if jd else "") or ""
        loc_hint = (jd.location_hints if jd else "") or ""

        yield Header()
        with VerticalScroll():
            yield Static("Step 4 — Optional context + agreement to rewrite", classes="title")
            if app.session.notices:
                yield Static(
                    "Gaps to acknowledge:\n" + "\n".join(f"• {n}" for n in app.session.notices[:8]),
                    classes="notice",
                )
            yield Label(f"Salary (optional; JD hint: {sal_hint or '—'})")
            yield Input(placeholder="e.g. 40-50k", id="salary")
            yield Label("Work years (optional)")
            yield Input(placeholder="e.g. 5", id="years")
            yield Label(f"Work base (optional; JD hint: {loc_hint or '—'})")
            yield Input(placeholder="e.g. Shanghai", id="base")
            yield Label("Template")
            yield Select(options, id="template", value="source")
            yield Checkbox("Allow deterministic fallback if LLM fails", id="fallback", value=True)
            yield Checkbox("Export PDF", id="pdf")
            with Horizontal():
                yield Button("Back", id="back")
                yield Button("Agree & rewrite…", variant="primary", id="rewrite")
            yield RichLog(id="log", highlight=True, markup=True)
        yield Footer()

    @on(Button.Pressed, "#back")
    def go_back(self) -> None:
        self.app.pop_screen()

    @on(Button.Pressed, "#rewrite")
    def do_rewrite(self) -> None:
        self.app.push_screen(AgreeModal(), self._after_agree)

    def _after_agree(self, agreed: bool) -> None:
        if not agreed:
            log = self.query_one("#log", RichLog)
            log.write("[yellow]Rewrite cancelled — agreement required.[/yellow]")
            return
        self.run_rewrite()

    @work(thread=True)
    def run_rewrite(self) -> None:
        app: ProfileAdaptorApp = self.app  # type: ignore
        log = self.query_one("#log", RichLog)
        salary = self.query_one("#salary", Input).value.strip()
        years = self.query_one("#years", Input).value.strip()
        base = self.query_one("#base", Input).value.strip()
        allow_fallback = self.query_one("#fallback", Checkbox).value
        export_pdf = self.query_one("#pdf", Checkbox).value
        template_val = self.query_one("#template", Select).value
        template = None if template_val in (None, Select.BLANK, "source") else str(template_val)

        self.call_from_thread(log.write, "Rewriting resume…")
        apply_rewrite_to_session(
            app.session,
            app.settings,
            salary=salary,
            work_years=years,
            work_base=base,
            template=template,
            customer_agreed_to_rewrite=True,
            allow_fallback=allow_fallback,
            export_pdf=export_pdf,
        )
        if app.session.error and app.session.step != "done":
            self.call_from_thread(log.write, f"[red]{app.session.error}[/red]")
            return
        self.call_from_thread(app.push_screen, ResultScreen())


class ResultScreen(Screen):
    def compose(self) -> ComposeResult:
        app: ProfileAdaptorApp = self.app  # type: ignore
        result = app.session.result
        yield Header()
        with VerticalScroll():
            yield Static("Step 5 — Adapted resume ready", classes="title")
            if result and not result.error:
                lines = [
                    f"Run: {result.run_id}",
                    f"DOCX: {result.output_docx}",
                    f"PDF: {result.output_pdf or '—'}",
                    f"Audit: {result.audit_json}",
                    f"Context: {result.context_json}",
                ]
                if result.adapted and result.adapted.used_fallback:
                    lines.append(
                        f"WARNING: LLM fallback used — {result.adapted.fallback_reason}"
                    )
                if result.fill_report:
                    fr = result.fill_report
                    lines.append(
                        f"Fill: filled={fr.sections_filled} missing={fr.sections_missing} "
                        f"degraded={fr.degraded}"
                    )
                if result.audit:
                    lines.append(f"Fidelity: {result.audit.summary}")
                    for f in result.audit.flags[:8]:
                        lines.append(f"  [{f.severity}] {f.message}")
                if result.events_jsonl:
                    lines.append(f"Events: {result.events_jsonl}")
                ev = _fmt_events(app.session, 15)
                if ev:
                    lines.append("")
                    lines.append("Event timeline:")
                    lines.append(ev)
                yield Static("\n".join(lines))
            else:
                yield Static(
                    f"Error: {app.session.error or (result.error if result else 'unknown')}"
                )
            with Horizontal():
                yield Button("Start over", id="restart")
                yield Button("Quit", id="quit")
        yield Footer()

    @on(Button.Pressed, "#quit")
    def quit_app(self) -> None:
        self.app.exit()

    @on(Button.Pressed, "#restart")
    def restart(self) -> None:
        app: ProfileAdaptorApp = self.app  # type: ignore
        sid = uuid.uuid4().hex[:10]
        app.session = WizardSession(
            session_id=sid,
            provider=app.settings.provider,
            model=app.settings.model,
            event_log=EventLog(session_id=sid, log_dir=app.settings.output_dir),
        )
        while len(app.screen_stack) > 1:
            app.pop_screen()


class ProfileAdaptorApp(App):
    CSS = """
    Screen { layout: vertical; }
    .title { text-style: bold; margin: 1 0; }
    .section { text-style: bold; margin-top: 1; color: $accent; }
    .notice { color: $warning; margin: 1 0; }
    Input { margin-bottom: 1; }
    Label { margin-top: 1; }
    #log { height: 8; border: solid $accent; margin: 1 0; }
    #jd_view, #resume_view, #audit_view { margin: 0 0 1 0; }
    TextArea { height: 6; margin-bottom: 1; }
    """

    BINDINGS = [("q", "quit", "Quit")]

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings
        sid = uuid.uuid4().hex[:10]
        self.session = WizardSession(
            session_id=sid,
            provider=settings.provider,
            model=settings.model,
            event_log=EventLog(session_id=sid, log_dir=settings.output_dir),
        )

    def on_mount(self) -> None:
        self.push_screen(IngestScreen())


def run_tui(settings: Settings) -> None:
    settings.ensure_dirs()
    ProfileAdaptorApp(settings).run()
