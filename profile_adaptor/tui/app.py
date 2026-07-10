"""Textual TUI for Profile Adaptor."""

from __future__ import annotations

from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Button, Footer, Header, Input, Label, RichLog, Select, Static

from profile_adaptor.config import Settings
from profile_adaptor.hitl.template_selector import list_templates
from profile_adaptor.pipeline import run_pipeline


class ProfileAdaptorApp(App):
    CSS = """
    Screen { layout: vertical; }
    #form { height: auto; padding: 1; }
    #log { height: 1fr; border: solid $accent; margin: 1; }
    Input { margin-bottom: 1; }
    Label { margin-top: 1; }
    #row { height: auto; }
    """

    BINDINGS = [("q", "quit", "Quit"), ("r", "run", "Run")]

    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self.settings = settings

    def compose(self) -> ComposeResult:
        templates = list_templates(self.settings.templates_dir)
        options = [("Use source resume layout", "source")]
        options.extend((t.name, str(t)) for t in templates)

        yield Header()
        with VerticalScroll(id="form"):
            yield Static("Profile Adaptor — adapt resume to JD", id="title")
            yield Label("JD URL (or leave empty if using JD file)")
            yield Input(placeholder="https://...", id="url")
            yield Label("JD file path (optional)")
            yield Input(placeholder="./samples/sample_jd.txt", id="jd_file")
            yield Label("Resume path (.docx / .pdf)")
            yield Input(placeholder="./samples/sample_resume.docx", id="resume")
            yield Label("Salary (HITL)")
            yield Input(placeholder="e.g. 30-40k RMB", id="salary")
            yield Label("Work years (HITL)")
            yield Input(placeholder="e.g. 5", id="years")
            yield Label("Work base (HITL)")
            yield Input(placeholder="e.g. Shanghai / Remote", id="base")
            yield Label("Template")
            yield Select(options, id="template", value="source")
            yield Label("Provider")
            yield Select(
                [("Ollama (local)", "ollama"), ("Web LLM endpoint", "web")],
                id="provider",
                value=self.settings.provider,
            )
            yield Label("Model (optional override)")
            yield Input(value=self.settings.model, id="model")
            with Horizontal(id="row"):
                yield Button("Run pipeline", variant="primary", id="run")
                yield Button("Quit", id="quit")
        yield RichLog(id="log", highlight=True, markup=True)
        yield Footer()

    def action_run(self) -> None:
        self.run_pipeline_async()

    @on(Button.Pressed, "#run")
    def on_run_pressed(self) -> None:
        self.run_pipeline_async()

    @on(Button.Pressed, "#quit")
    def on_quit_pressed(self) -> None:
        self.exit()

    @work(thread=True)
    def run_pipeline_async(self) -> None:
        log = self.query_one("#log", RichLog)
        self.call_from_thread(log.write, "[bold]Starting pipeline…[/bold]")

        url = self.query_one("#url", Input).value.strip()
        jd_file = self.query_one("#jd_file", Input).value.strip()
        resume = self.query_one("#resume", Input).value.strip()
        salary = self.query_one("#salary", Input).value.strip()
        years = self.query_one("#years", Input).value.strip()
        base = self.query_one("#base", Input).value.strip()
        template_val = self.query_one("#template", Select).value
        provider = self.query_one("#provider", Select).value
        model = self.query_one("#model", Input).value.strip()

        if not resume:
            self.call_from_thread(log.write, "[red]Resume path is required[/red]")
            return
        if not url and not jd_file:
            self.call_from_thread(log.write, "[red]Provide JD URL or JD file[/red]")
            return
        if not salary or not years or not base:
            self.call_from_thread(log.write, "[red]HITL fields salary / years / base are required[/red]")
            return

        self.settings.provider = provider  # type: ignore
        if model:
            if provider == "ollama":
                self.settings.ollama_model = model
            else:
                self.settings.web_llm_model = model

        template = None if template_val in (None, Select.BLANK, "source") else str(template_val)

        result = run_pipeline(
            settings=self.settings,
            resume_path=resume,
            salary=salary,
            work_years=years,
            work_base=base,
            url=url or None,
            jd_file=jd_file or None,
            template=template,
            override_checker_errors=True,
        )

        if result.error:
            self.call_from_thread(log.write, f"[red]ERROR: {result.error}[/red]")
            if result.checks:
                for r in result.checks.results:
                    self.call_from_thread(log.write, f"  [{r.severity}] {r.name}: {r.message}")
            return

        self.call_from_thread(log.write, f"[green]Done[/green] run_id={result.run_id}")
        self.call_from_thread(log.write, f"DOCX: {result.output_docx}")
        if result.output_pdf:
            self.call_from_thread(log.write, f"PDF: {result.output_pdf}")
        self.call_from_thread(log.write, f"Audit: {result.audit_json}")
        if result.audit:
            self.call_from_thread(log.write, result.audit.summary)
            for f in result.audit.flags:
                self.call_from_thread(log.write, f"  [{f.severity}] {f.message}")


def run_tui(settings: Settings) -> None:
    settings.ensure_dirs()
    ProfileAdaptorApp(settings).run()
