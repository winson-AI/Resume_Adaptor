"""Local Ollama chat client."""

from __future__ import annotations

from typing import Dict, List

import httpx


class OllamaClient:
    def __init__(self, base_url: str, model: str, timeout: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = httpx.Timeout(timeout, connect=5.0)

    def chat(self, messages: List[Dict[str, str]], temperature: float = 0.2) -> str:
        url = f"{self.base_url}/api/chat"
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature},
        }
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(url, json=payload)
                resp.raise_for_status()
                data = resp.json()
        except httpx.TimeoutException as exc:
            raise RuntimeError(
                f"Ollama timed out after {self.timeout.read}s talking to {self.model}. "
                "Is the model loaded? Try a smaller model or raise LLM_TIMEOUT."
            ) from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Ollama request failed: {exc}") from exc
        message = data.get("message") or {}
        content = message.get("content") or data.get("response") or ""
        if not content:
            raise RuntimeError(f"Empty Ollama response: {data!r}")
        return content.strip()
