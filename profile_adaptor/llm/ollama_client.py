"""Local Ollama chat client."""

from __future__ import annotations

from typing import Dict, List

import httpx


class OllamaClient:
    def __init__(self, base_url: str, model: str, timeout: float = 180.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def chat(self, messages: List[Dict[str, str]], temperature: float = 0.2) -> str:
        url = f"{self.base_url}/api/chat"
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature},
        }
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
        message = data.get("message") or {}
        content = message.get("content") or data.get("response") or ""
        if not content:
            raise RuntimeError(f"Empty Ollama response: {data!r}")
        return content.strip()
