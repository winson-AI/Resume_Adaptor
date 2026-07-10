"""Application configuration from environment and CLI overrides."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

from dotenv import load_dotenv

Provider = Literal["ollama", "web"]

_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class Settings:
    provider: Provider = "ollama"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3.5:9b"
    web_llm_base_url: str = "https://api.openai.com/v1"
    web_llm_api_key: str = ""
    web_llm_model: str = "gpt-4o-mini"
    templates_dir: Path = field(default_factory=lambda: _ROOT / "templates")
    output_dir: Path = field(default_factory=lambda: _ROOT / "output")
    strict: bool = False
    export_pdf: bool = False

    @property
    def model(self) -> str:
        return self.ollama_model if self.provider == "ollama" else self.web_llm_model

    def ensure_dirs(self) -> None:
        self.templates_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)


def load_settings(
    provider: Optional[str] = None,
    model: Optional[str] = None,
    strict: bool = False,
    export_pdf: bool = False,
    templates_dir: Optional[str] = None,
    output_dir: Optional[str] = None,
) -> Settings:
    load_dotenv(_ROOT / ".env")
    env_provider = os.getenv("PROVIDER", "ollama").strip().lower()
    chosen: Provider = "web" if (provider or env_provider) == "web" else "ollama"

    settings = Settings(
        provider=chosen,
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/"),
        ollama_model=os.getenv("OLLAMA_MODEL", "qwen3.5:9b"),
        web_llm_base_url=os.getenv("WEB_LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
        web_llm_api_key=os.getenv("WEB_LLM_API_KEY", ""),
        web_llm_model=os.getenv("WEB_LLM_MODEL", "gpt-4o-mini"),
        templates_dir=Path(templates_dir or os.getenv("TEMPLATES_DIR", str(_ROOT / "templates"))),
        output_dir=Path(output_dir or os.getenv("OUTPUT_DIR", str(_ROOT / "output"))),
        strict=strict,
        export_pdf=export_pdf,
    )
    if model:
        if settings.provider == "ollama":
            settings.ollama_model = model
        else:
            settings.web_llm_model = model
    settings.ensure_dirs()
    return settings