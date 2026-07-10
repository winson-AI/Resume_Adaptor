"""OpenAI-compatible web LLM client."""

from __future__ import annotations

from typing import Dict, List

import httpx


class WebLLMClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 180.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def chat(self, messages: List[Dict[str, str]], temperature: float = 0.2) -> str:
        if not self.api_key:
            raise RuntimeError("WEB_LLM_API_KEY is required when provider=web")
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
        try:
            return data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError, AttributeError) as exc:
            raise RuntimeError(f"Unexpected web LLM response: {data!r}") from exc
