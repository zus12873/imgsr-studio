"""Test doubles for the relay clients (no network)."""

import asyncio
import io

from PIL import Image


def png_of(size, color="white"):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


class FakeImages:
    """Echoes the input image back resized by `scale`; records every call."""

    def __init__(self, scale=1.0, fail=None):
        self.scale = scale
        self.fail = fail
        self.calls = []
        self.gate = None  # threading.Event: when set, edit() blocks until it is released

    async def edit(self, *, model, prompt, image_png, size):
        self.calls.append({"model": model, "prompt": prompt, "size": size})
        if self.gate is not None:
            await asyncio.to_thread(self.gate.wait, 10)
        if self.fail is not None:
            raise self.fail
        img = Image.open(io.BytesIO(image_png)).convert("RGB")
        out = img.resize((max(1, round(img.width * self.scale)), max(1, round(img.height * self.scale))))
        buf = io.BytesIO()
        out.save(buf, "PNG")
        return buf.getvalue()


class FakeChat:
    """Returns reply(call_index, image_size); records every call."""

    def __init__(self, reply=None, fail=None):
        self.reply = reply or (lambda i, size: "默认转写文字。")
        self.fail = fail
        self.calls = []

    async def transcribe(self, *, model, prompt, image_png):
        size = Image.open(io.BytesIO(image_png)).size
        self.calls.append({"model": model, "size": size})
        if self.fail is not None:
            raise self.fail
        return self.reply(len(self.calls) - 1, size)
