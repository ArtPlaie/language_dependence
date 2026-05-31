"""Provider clients behind one ``complete()`` interface (SPEC §4.2).

OpenRouter is the single live gateway; MockClient lets the whole pipeline run
end-to-end with zero network/keys ("mock-then-live"). Both return a uniform
:class:`Completion` carrying the verbatim raw payload, latency, and any error.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import time
from dataclasses import dataclass, field
from typing import Protocol

import httpx

# HTTP statuses worth retrying with backoff.
_RETRY_STATUS = {429, 500, 502, 503, 504}


@dataclass
class Completion:
    text: str
    raw: dict = field(default_factory=dict)   # verbatim provider payload (or request echo on error)
    model_snapshot: str | None = None          # resolved model id reported by the provider
    latency_ms: int | None = None
    error: str | None = None


class Client(Protocol):
    async def complete(
        self, model: str, messages: list[dict], **kwargs
    ) -> Completion: ...


# --------------------------------------------------------------------------- live
class OpenRouterClient:
    """Async OpenRouter client: concurrency-capped, retry w/ exponential backoff."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://openrouter.ai/api/v1",
        concurrency: int = 8,
        max_retries: int = 5,
        timeout: float = 60.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        self._sem = asyncio.Semaphore(concurrency)
        self._max_retries = max_retries
        self._client = httpx.AsyncClient(timeout=timeout)

    @classmethod
    def from_env(
        cls, api_key_env: str, base_url: str, concurrency: int
    ) -> "OpenRouterClient":
        key = os.environ.get(api_key_env)
        if not key:
            raise RuntimeError(f"{api_key_env} is not set; cannot make live calls")
        url = os.environ.get("OPENROUTER_BASE_URL", base_url)
        return cls(api_key=key, base_url=url, concurrency=concurrency)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def complete(
        self,
        model: str,
        messages: list[dict],
        temperature: float = 1.0,
        max_tokens: int = 64,
        seed: int | None = None,
        **_: object,
    ) -> Completion:
        payload: dict[str, object] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if seed is not None:
            payload["seed"] = seed

        start = time.perf_counter()
        last_error: str | None = None
        async with self._sem:
            for attempt in range(self._max_retries + 1):
                try:
                    resp = await self._client.post(
                        f"{self._base_url}/chat/completions",
                        headers=self._headers,
                        json=payload,
                    )
                except httpx.HTTPError as exc:
                    last_error = f"transport: {exc!r}"
                else:
                    if resp.status_code in _RETRY_STATUS:
                        last_error = f"http {resp.status_code}: {resp.text[:200]}"
                    elif resp.status_code >= 400:
                        # Non-retryable client error: return immediately.
                        return Completion(
                            text="",
                            raw={"status": resp.status_code, "body": resp.text[:1000]},
                            latency_ms=_elapsed_ms(start),
                            error=f"http {resp.status_code}: {resp.text[:200]}",
                        )
                    else:
                        data = resp.json()
                        return Completion(
                            text=_extract_text(data),
                            raw=data,
                            model_snapshot=data.get("model"),
                            latency_ms=_elapsed_ms(start),
                        )
                if attempt < self._max_retries:
                    await asyncio.sleep(2 ** attempt)  # 1, 2, 4, 8, 16 s

        return Completion(
            text="", raw={"payload": payload}, latency_ms=_elapsed_ms(start),
            error=last_error or "exhausted retries",
        )


# --------------------------------------------------------------------------- mock
class MockClient:
    """Deterministic offline client so the pipeline runs without network/keys.

    Picks among ``choices`` (passed by the runner: item options + a refusal) using
    a hash of the messages, yielding a stable, varied distribution per cell.
    """

    def __init__(self, refusal_rate: float = 0.2) -> None:
        self._refusal_rate = refusal_rate

    async def complete(
        self, model: str, messages: list[dict],
        choices: list[str] | None = None, **_: object,
    ) -> Completion:
        prompt = messages[-1]["content"] if messages else ""
        h = int(hashlib.sha256(f"{model}|{prompt}".encode()).hexdigest(), 16)
        opts = choices or ["A", "B"]
        if (h % 100) / 100.0 < self._refusal_rate:
            text = "I'm sorry, but I can't help with that."
        else:
            text = opts[h % len(opts)]
        return Completion(
            text=text,
            raw={"mock": True, "model": model, "prompt": prompt, "text": text},
            model_snapshot=f"{model}@mock",
            latency_ms=1,
        )


def _extract_text(data: dict) -> str:
    try:
        return data["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        return ""


def _elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)
