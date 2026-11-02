"""Model providers used by Donatello."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen


class ProviderError(RuntimeError):
    """Raised when a model provider cannot complete a request."""


@dataclass
class ModelResponse:
    text: str
    model: str
    duration_seconds: float
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class OllamaProvider:
    def __init__(
        self,
        model: str = "qwen2.5-coder:7b",
        base_url: str | None = None,
        timeout: int = 300,
    ) -> None:
        self.model = model
        self.base_url = (base_url or os.getenv("DONATELLO_OLLAMA_URL", "http://localhost:11434")).rstrip("/")
        self.timeout = timeout

    def complete(self, messages: list[dict[str, str]], json_response: bool = False) -> ModelResponse:
        payload: dict[str, Any] = {"model": self.model, "messages": messages, "stream": False}
        if json_response:
            payload["format"] = "json"
        return self._post("/api/chat", payload)

    def _post(self, path: str, payload: dict[str, Any]) -> ModelResponse:
        return _request_json(
            self.base_url + path,
            payload,
            self.model,
            self.timeout,
        )


class OpenAICompatibleProvider:
    """Provider for external services exposing the OpenAI chat-completions API."""

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout: int = 300,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key or os.getenv("DONATELLO_EXTERNAL_API_KEY")
        self.timeout = timeout

    def complete(self, messages: list[dict[str, str]], json_response: bool = False) -> ModelResponse:
        payload: dict[str, Any] = {"model": self.model, "messages": messages}
        if json_response:
            payload["response_format"] = {"type": "json_object"}
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = "Bearer " + self.api_key
        return _request_json(
            self.base_url + "/chat/completions",
            payload,
            self.model,
            self.timeout,
            headers,
        )


class FallbackProvider:
    """Use an external provider if the primary provider fails or returns invalid JSON."""

    def __init__(self, primary: Any, fallback: Any) -> None:
        self.primary = primary
        self.fallback = fallback

    def complete(self, messages: list[dict[str, str]], json_response: bool = False) -> ModelResponse:
        try:
            response = self.primary.complete(messages, json_response=json_response)
            if json_response:
                json.loads(response.text)
            return response
        except (ProviderError, json.JSONDecodeError, URLError, TimeoutError, OSError):
            return self.fallback.complete(messages, json_response=json_response)


def _request_json(
    url: str,
    payload: dict[str, Any],
    model: str,
    timeout: int,
    headers: dict[str, str] | None = None,
) -> ModelResponse:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers or {"Content-Type": "application/json"},
        method="POST",
    )
    started = time.monotonic()
    try:
        with urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProviderError(f"Model request failed for {model}: {error}") from error

    if "message" in data:
        text = data["message"].get("content", "")
        prompt_tokens = data.get("prompt_eval_count")
        completion_tokens = data.get("eval_count")
    else:
        choices = data.get("choices", [])
        text = choices[0].get("message", {}).get("content", "") if choices else ""
        usage = data.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")
    if not isinstance(text, str) or not text:
        raise ProviderError(f"Model {model} returned an empty response")
    return ModelResponse(
        text=text,
        model=model,
        duration_seconds=time.monotonic() - started,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )
