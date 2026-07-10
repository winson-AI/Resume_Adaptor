"""LLM client protocol."""

from __future__ import annotations

from typing import Dict, List, Protocol, runtime_checkable


@runtime_checkable
class LLMClient(Protocol):
    def chat(self, messages: List[Dict[str, str]], temperature: float = 0.2) -> str:
        ...
