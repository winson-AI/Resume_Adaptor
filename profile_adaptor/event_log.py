"""Structured event log: progress, status, and results for each pipeline stage."""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

_LOGGER = logging.getLogger("profile_adaptor.events")


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


@dataclass
class LogEvent:
    ts: str
    run_id: str
    session_id: str
    stage: str
    event: str  # started | progress | status | result | error
    status: str  # running | ok | warn | error
    message: str
    progress: Optional[float] = None  # 0.0–1.0
    data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class EventLog:
    """In-memory + JSONL event recorder for a run/session."""

    def __init__(
        self,
        run_id: str = "",
        session_id: str = "",
        log_dir: Optional[Path] = None,
    ) -> None:
        self.run_id = run_id
        self.session_id = session_id
        self.log_dir = Path(log_dir) if log_dir else None
        self._events: List[LogEvent] = []
        self._lock = threading.Lock()
        self._path: Optional[Path] = None
        if self.log_dir and self.run_id:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            self._path = self.log_dir / f"{self.run_id}_events.jsonl"

    def bind(self, run_id: str = "", session_id: str = "", log_dir: Optional[Path] = None) -> "EventLog":
        if run_id:
            self.run_id = run_id
        if session_id:
            self.session_id = session_id
        if log_dir is not None:
            self.log_dir = Path(log_dir)
        if self.log_dir and self.run_id:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            self._path = self.log_dir / f"{self.run_id}_events.jsonl"
        return self

    def record(
        self,
        stage: str,
        event: str,
        status: str,
        message: str,
        progress: Optional[float] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> LogEvent:
        item = LogEvent(
            ts=_utc_now(),
            run_id=self.run_id,
            session_id=self.session_id,
            stage=stage,
            event=event,
            status=status,
            message=message,
            progress=progress,
            data=data or {},
        )
        with self._lock:
            self._events.append(item)
            if self._path is not None:
                with self._path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(item.to_dict(), ensure_ascii=False) + "\n")
        level = {
            "error": logging.ERROR,
            "warn": logging.WARNING,
            "ok": logging.INFO,
            "running": logging.INFO,
        }.get(status, logging.INFO)
        _LOGGER.log(
            level,
            "[%s/%s] %s progress=%s %s",
            stage,
            event,
            status,
            progress if progress is not None else "-",
            message,
        )
        return item

    def started(self, stage: str, message: str, progress: float = 0.0, **data: Any) -> LogEvent:
        return self.record(stage, "started", "running", message, progress=progress, data=data)

    def progress(self, stage: str, message: str, progress: float, **data: Any) -> LogEvent:
        return self.record(stage, "progress", "running", message, progress=progress, data=data)

    def status(self, stage: str, status: str, message: str, progress: Optional[float] = None, **data: Any) -> LogEvent:
        return self.record(stage, "status", status, message, progress=progress, data=data)

    def result(self, stage: str, message: str, progress: float = 1.0, status: str = "ok", **data: Any) -> LogEvent:
        return self.record(stage, "result", status, message, progress=progress, data=data)

    def error(self, stage: str, message: str, progress: Optional[float] = None, **data: Any) -> LogEvent:
        return self.record(stage, "error", "error", message, progress=progress, data=data)

    @property
    def events(self) -> List[LogEvent]:
        with self._lock:
            return list(self._events)

    def to_list(self) -> List[Dict[str, Any]]:
        return [e.to_dict() for e in self.events]

    @property
    def path(self) -> Optional[str]:
        return str(self._path) if self._path else None

    def latest_status(self) -> str:
        ev = self.events
        return ev[-1].status if ev else "idle"


def setup_app_logging(level: str = "INFO") -> None:
    """Configure root profile_adaptor logging once."""
    root = logging.getLogger("profile_adaptor")
    if root.handlers:
        return
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%H:%M:%S")
    )
    root.addHandler(handler)
    # Keep pdfminer quiet
    logging.getLogger("pdfminer").setLevel(logging.ERROR)
