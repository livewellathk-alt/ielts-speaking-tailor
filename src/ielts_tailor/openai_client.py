from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

import certifi


@dataclass(frozen=True)
class OpenAICompatibleClient:
    base_url: str
    api_key_env: str
    model: str
    timeout_seconds: int = 120
    max_retries: int = 2

    def complete_json(self, *, messages: list[dict[str, str]], schema_name: str, temperature: float) -> dict[str, Any]:
        api_key = os.environ.get(self.api_key_env)
        if not api_key:
            raise RuntimeError(f"Missing API key environment variable: {self.api_key_env}")
        url = self.base_url.rstrip("/") + "/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "response_format": {"type": "json_object"},
        }
        last_error: Exception | None = None
        for _ in range(self.max_retries + 1):
            try:
                request = urllib.request.Request(
                    url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    method="POST",
                )
                context = ssl.create_default_context(cafile=certifi.where())
                with urllib.request.urlopen(request, timeout=self.timeout_seconds, context=context) as response:
                    body = json.loads(response.read().decode("utf-8"))
                content = body["choices"][0]["message"]["content"]
                parsed = json.loads(content)
                if not isinstance(parsed, dict):
                    raise ValueError(f"{schema_name} response must be a JSON object")
                return parsed
            except (urllib.error.URLError, KeyError, json.JSONDecodeError, ValueError) as exc:
                last_error = exc
        raise RuntimeError(f"LLM request failed for {schema_name}: {last_error}")
