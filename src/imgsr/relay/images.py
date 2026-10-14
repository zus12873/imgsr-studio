"""Client for the relay's OpenAI-compatible image edit endpoint."""

from __future__ import annotations

import base64
from typing import Any

import httpx

from imgsr.relay.base import normalize_base
from imgsr.relay.errors import RelayError, classify


def _looks_like_image(raw: bytes) -> bool:
    return raw.startswith((b"\x89PNG", b"\xff\xd8\xff")) or (raw[:4] == b"RIFF" and raw[8:12] == b"WEBP")


def request_size(
    w: int, h: int, scale: float = 2.0, max_pixels: int = 8_294_400, max_edge: int = 3840
) -> str:
    """The `size` we send. The relay caps output at ~1.57 MP anyway; 2x keeps the aspect hint."""
    tw, th = w * scale, h * scale
    k = min(1.0, (max_pixels / (tw * th)) ** 0.5, max_edge / max(tw, th))
    return f"{max(16, int(tw * k) // 16 * 16)}x{max(16, int(th * k) // 16 * 16)}"


def _first_item(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        payload = None
    items = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(items, list) and items and isinstance(items[0], dict):
        return items[0]
    raise RelayError("上游返回了空结果", kind="empty", retryable=True)


class ImageClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout: float = 180.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base = normalize_base(base_url)
        self._key = api_key
        # httpx drops Authorization on cross-origin redirects, so CDN hops never see the key.
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=15.0), transport=transport, follow_redirects=True
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def edit(self, *, model: str, prompt: str, image_png: bytes, size: tuple[int, int]) -> bytes:
        data = {"model": model, "prompt": prompt, "n": "1", "size": request_size(*size)}
        files = {"image": ("image.png", image_png, "image/png")}
        response = await self._send("POST", f"{self.base}/v1/images/edits", auth=True, data=data, files=files)
        item = _first_item(response)
        if item.get("b64_json"):
            try:
                raw = base64.b64decode(item["b64_json"])
            except ValueError as exc:
                raise RelayError("上游返回的图片无法解码", kind="empty", retryable=True) from exc
        elif item.get("url"):
            url = str(item["url"])
            relative = url.startswith("/")
            raw = (await self._send("GET", self.base + url if relative else url, auth=relative)).content
        else:
            raise RelayError("上游返回了空结果", kind="empty", retryable=True)
        if not _looks_like_image(raw):
            raise RelayError("上游返回的不是图片", kind="empty", retryable=True)
        return raw

    async def _send(self, method: str, url: str, *, auth: bool, **kwargs: Any) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self._key}"} if auth else {}
        try:
            response = await self._client.request(method, url, headers=headers, **kwargs)
        except httpx.TimeoutException as exc:
            raise RelayError("上游超时", kind="timeout", retryable=True) from exc
        except httpx.TransportError as exc:
            raise RelayError(f"连接上游失败：{exc.__class__.__name__}", kind="network", retryable=True) from exc
        if response.status_code >= 400:
            raise classify(response.status_code, response.text)
        return response
