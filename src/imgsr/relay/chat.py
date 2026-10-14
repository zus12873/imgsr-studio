"""Streaming vision chat client used to transcribe text in images."""

from __future__ import annotations

import asyncio
import base64
import json

import httpx

from imgsr.relay.base import normalize_base
from imgsr.relay.errors import RelayError, classify


class ChatClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float = 240.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base = normalize_base(base_url)
        self._key = api_key
        self._timeout = timeout
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=15.0), transport=transport)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def transcribe(self, *, model: str, prompt: str, image_png: bytes) -> str:
        data_uri = "data:image/png;base64," + base64.b64encode(image_png).decode()
        body = {
            "model": model,
            "stream": True,  # non-streamed calls over 100 s die at Cloudflare with 524
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_uri, "detail": "high"}},
                    ],
                }
            ],
        }
        parts: list[str] = []
        try:
            async with asyncio.timeout(self._timeout):
                async with self._client.stream(
                    "POST",
                    f"{self.base}/v1/chat/completions",
                    headers={"Authorization": f"Bearer {self._key}"},
                    json=body,
                ) as response:
                    if response.status_code >= 400:
                        await response.aread()
                        raise classify(response.status_code, response.text)
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        payload = line[5:].strip()
                        if payload == "[DONE]":
                            break
                        try:
                            chunk = json.loads(payload)
                        except ValueError:
                            continue
                        if not isinstance(chunk, dict):
                            continue
                        for choice in chunk.get("choices") or []:
                            content = (choice.get("delta") or {}).get("content")
                            if isinstance(content, str):
                                parts.append(content)
        except TimeoutError as exc:
            raise RelayError("转写超时", kind="timeout", retryable=True) from exc
        except httpx.TimeoutException as exc:
            raise RelayError("转写超时", kind="timeout", retryable=True) from exc
        except httpx.TransportError as exc:
            raise RelayError(f"连接上游失败：{exc.__class__.__name__}", kind="network", retryable=True) from exc
        text = "".join(parts).strip()
        if not text:
            raise RelayError("上游返回了空转写", kind="empty", retryable=True)
        return text
