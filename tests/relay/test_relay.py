import base64
import io
import json

import httpx
import pytest
from PIL import Image

from imgsr.relay.base import masked, normalize_base
from imgsr.relay.chat import ChatClient
from imgsr.relay.errors import RelayError, classify
from imgsr.relay.images import ImageClient, request_size
from imgsr.relay.retry import with_retries


def png(size=(10, 10)):
    buf = io.BytesIO()
    Image.new("RGB", size, "red").save(buf, "PNG")
    return buf.getvalue()


def image_client(handler):
    return ImageClient("https://relay.test/v1/", "sk-test", transport=httpx.MockTransport(handler))


def chat_client(handler, timeout=5.0):
    return ChatClient(
        "https://relay.test", "sk-test", timeout=timeout, transport=httpx.MockTransport(handler)
    )


def sse(*chunks, done=True):
    lines = [f"data: {json.dumps(c, ensure_ascii=False)}\n\n" for c in chunks]
    if done:
        lines.append("data: [DONE]\n\n")
    return "".join(lines).encode()


def test_base_and_mask():
    assert normalize_base("https://relay.test/v1/") == "https://relay.test"
    assert normalize_base("https://relay.test") == "https://relay.test"
    assert masked("sk-8b1234567890af8e") == "sk-8b1…af8e"
    assert masked("short") == "***"


async def test_edit_returns_b64_image_and_sends_multipart():
    seen = {}

    def handler(request):
        seen.update(url=str(request.url), auth=request.headers["authorization"], body=request.content)
        return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(png()).decode()}]})

    raw = await image_client(handler).edit(
        model="gpt-image-2.5", prompt="清晰", image_png=png(), size=(100, 50)
    )
    assert raw.startswith(b"\x89PNG")
    assert seen["url"] == "https://relay.test/v1/images/edits"
    assert seen["auth"] == "Bearer sk-test"
    assert b'name="model"' in seen["body"] and b"gpt-image-2.5" in seen["body"]
    assert b"192x96" in seen["body"]


async def test_edit_downloads_relative_url_with_auth():
    calls = []

    def handler(request):
        calls.append((request.url.host, request.url.path, request.headers.get("authorization")))
        if request.url.path == "/v1/images/edits":
            return httpx.Response(200, json={"data": [{"url": "/v1/files/abc"}]})
        return httpx.Response(200, content=png())

    await image_client(handler).edit(model="m", prompt="p", image_png=png(), size=(10, 10))
    assert calls[1] == ("relay.test", "/v1/files/abc", "Bearer sk-test")


async def test_edit_downloads_absolute_url_without_auth():
    calls = []

    def handler(request):
        calls.append((request.url.host, request.headers.get("authorization")))
        if request.url.host == "relay.test":
            return httpx.Response(200, json={"data": [{"url": "https://cdn.example/x.png"}]})
        return httpx.Response(200, content=png())

    await image_client(handler).edit(model="m", prompt="p", image_png=png(), size=(10, 10))
    assert calls[1] == ("cdn.example", None)


@pytest.mark.parametrize(
    "status,body,kind,retryable",
    [
        (429, '{"error":{"message":"All available accounts are currently rate-limited"}}', "busy", True),
        (503, "no eligible account", "busy", True),
        (400, '{"error":{"message":"image too large"}}', "rejected", False),
        (401, "bad key", "auth", False),
        (524, "<!DOCTYPE html><title>524</title>", "upstream", True),
    ],
)
def test_classify(status, body, kind, retryable):
    err = classify(status, body)
    assert (err.kind, err.retryable, err.status) == (kind, retryable, status)


def test_classify_keeps_upstream_message():
    assert "image too large" in classify(400, '{"error":{"message":"image too large"}}').message


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="<html>cloudflare</html>"),
        httpx.Response(200, json={"data": []}),
        httpx.Response(200, json=["unexpected"]),
        httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(b"not an image").decode()}]}),
    ],
)
async def test_edit_unusable_200_is_retryable_empty(response):
    with pytest.raises(RelayError) as info:
        await image_client(lambda request: response).edit(
            model="m", prompt="p", image_png=png(), size=(10, 10)
        )
    assert info.value.kind == "empty" and info.value.retryable


async def test_edit_timeout_is_retryable():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(RelayError) as info:
        await image_client(handler).edit(model="m", prompt="p", image_png=png(), size=(10, 10))
    assert info.value.kind == "timeout" and info.value.retryable


def test_request_size_keeps_aspect_and_limits():
    assert request_size(100, 50) == "192x96"
    w, h = map(int, request_size(2316, 1294).split("x"))
    assert w * h <= 8_294_400 and max(w, h) <= 3840 and w % 16 == 0 and h % 16 == 0


async def test_transcribe_streams_and_joins_deltas():
    seen = {}

    def handler(request):
        seen.update(path=request.url.path, body=json.loads(request.content))
        return httpx.Response(
            200,
            content=sse(
                {"choices": [{"delta": {"content": "第一行"}}]},
                {"choices": [{"delta": {"content": "。\n第二行。"}}]},
            ),
            headers={"content-type": "text/event-stream"},
        )

    text = await chat_client(handler).transcribe(model="gpt-6-sol", prompt="转写", image_png=png())
    assert text == "第一行。\n第二行。"
    assert seen["path"] == "/v1/chat/completions" and seen["body"]["stream"] is True
    content = seen["body"]["messages"][0]["content"]
    assert content[0]["text"] == "转写"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


async def test_transcribe_skips_keepalives_and_garbage():
    body = b": ping\n\ndata: not-json\n\n" + sse({"choices": [{"delta": {"content": "好"}}]})
    text = await chat_client(lambda r: httpx.Response(200, content=body)).transcribe(
        model="m", prompt="p", image_png=png()
    )
    assert text == "好"


async def test_transcribe_error_status():
    with pytest.raises(RelayError) as info:
        await chat_client(lambda r: httpx.Response(502, text="<html>bad gateway</html>")).transcribe(
            model="m", prompt="p", image_png=png()
        )
    assert info.value.kind == "upstream" and info.value.retryable


async def test_transcribe_empty_is_retryable():
    body = sse({"choices": [{"delta": {}}]})
    with pytest.raises(RelayError) as info:
        await chat_client(lambda r: httpx.Response(200, content=body)).transcribe(
            model="m", prompt="p", image_png=png()
        )
    assert info.value.kind == "empty"


async def test_with_retries_sleeps_between_retryable_failures():
    attempts, sleeps = [], []

    async def fn():
        attempts.append(1)
        if len(attempts) < 3:
            raise RelayError("busy", kind="busy", retryable=True)
        return "ok"

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    assert await with_retries(fn, sleep=fake_sleep) == "ok"
    assert sleeps == [10.0, 30.0]


async def test_with_retries_gives_up_after_last_delay():
    sleeps = []

    async def fn():
        raise RelayError("busy", kind="busy", retryable=True)

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    with pytest.raises(RelayError):
        await with_retries(fn, sleep=fake_sleep)
    assert sleeps == [10.0, 30.0]


async def test_with_retries_does_not_retry_rejections():
    attempts = []

    async def fn():
        attempts.append(1)
        raise RelayError("bad", kind="rejected", retryable=False)

    with pytest.raises(RelayError):
        await with_retries(fn)
    assert len(attempts) == 1
