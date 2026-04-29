from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol


class LlmClient(Protocol):
    def generate(self, prompt: str) -> str:
        ...


@dataclass(frozen=True)
class OllamaClient:
    model: str
    api_base: str = "http://127.0.0.1:11434"
    timeout_seconds: int = 600

    def generate(self, prompt: str) -> str:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.1},
        }
        return _post_json(f"{self.api_base.rstrip('/')}/api/generate", payload, timeout_seconds=self.timeout_seconds)["response"]


@dataclass(frozen=True)
class OpenAICompatibleClient:
    model: str
    api_base: str
    api_key_env: str = "OPENAI_API_KEY"
    timeout_seconds: int = 600

    def generate(self, prompt: str) -> str:
        api_key = os.environ.get(self.api_key_env)
        if not api_key:
            raise RuntimeError(f"Missing API key environment variable: {self.api_key_env}")
        payload = {
            "model": self.model,
            "temperature": 0.1,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": "You are a Java coding agent. Return only valid JSON.",
                },
                {"role": "user", "content": prompt},
            ],
        }
        headers = {"Authorization": f"Bearer {api_key}"}
        return _post_json(
            f"{self.api_base.rstrip('/')}/chat/completions",
            payload,
            headers,
            timeout_seconds=self.timeout_seconds,
        )["choices"][0]["message"]["content"]


def build_llm_client(
    provider: str,
    model: str,
    api_base: str | None,
    api_key_env: str,
    timeout_seconds: int,
) -> LlmClient:
    if provider == "ollama":
        return OllamaClient(
            model=model,
            api_base=api_base or "http://127.0.0.1:11434",
            timeout_seconds=timeout_seconds,
        )
    if provider == "openai-compatible":
        return OpenAICompatibleClient(
            model=model,
            api_base=api_base or "https://api.openai.com/v1",
            api_key_env=api_key_env,
            timeout_seconds=timeout_seconds,
        )
    raise ValueError(f"Unsupported LLM provider: {provider}")


def parse_json_response(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text, strict=False)
    except json.JSONDecodeError:
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
        if not match:
            match = re.search(r"(\{.*\})", text, re.DOTALL)
        if not match:
            raise ValueError(f"LLM response did not contain JSON:\n{text}") from None
        value = json.loads(match.group(1), strict=False)
    if not isinstance(value, dict):
        raise ValueError("LLM response JSON must be an object.")
    return value


def _post_json(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
    timeout_seconds: int = 600,
) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
    except (TimeoutError, urllib.error.URLError) as exc:
        raise RuntimeError(f"LLM request failed for {url}: {exc}") from exc
