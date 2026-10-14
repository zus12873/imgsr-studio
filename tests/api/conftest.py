import contextlib
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from imgsr.api.app import create_app
from imgsr.config import Settings
from tests.fakes import FakeChat, FakeImages


@pytest.fixture
def make_api(tmp_path):
    stack = contextlib.ExitStack()

    def _make(**overrides):
        images, chat = FakeImages(), FakeChat()
        settings = Settings(
            _env_file=None,
            data_dir=tmp_path / uuid.uuid4().hex,
            cookie_secure=False,
            trusted_proxies="127.0.0.1/32",
            open_api_key="sk-test-0000000000",
            **overrides,
        )
        app = create_app(settings, images=images, chat=chat, retry_delays=(0.0, 0.0), maintenance=False)
        client = stack.enter_context(
            TestClient(app, client=("127.0.0.1", 50000), headers={"X-Requested-With": "imgsr"})
        )
        return SimpleNamespace(client=client, app=app, images=images, chat=chat, ctx=app.state.ctx)

    yield _make
    stack.close()


@pytest.fixture
def api(make_api):
    return make_api()
