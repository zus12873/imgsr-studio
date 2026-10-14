"""FastAPI application factory."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from imgsr.api import routes_admin, routes_auth, routes_files, routes_guest, routes_tasks
from imgsr.api.deps import AppContext
from imgsr.auth import LoginLimiter
from imgsr.clientip import parse_networks
from imgsr.config import Settings
from imgsr.config_store import SettingsProvider
from imgsr.db.session import make_engine, make_session_factory, migrate
from imgsr.jobs.handlers import ImageEditor, Pipeline, Services, Transcriber
from imgsr.jobs.runner import JobRunner
from imgsr.maintenance import maintenance_loop
from imgsr.relay.base import masked
from imgsr.relay.chat import ChatClient
from imgsr.relay.images import ImageClient
from imgsr.relay.retry import DEFAULT_DELAYS
from imgsr.storage import Storage

log = logging.getLogger("imgsr")
MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
ROUTERS = (routes_auth, routes_tasks, routes_files, routes_guest, routes_admin)


def create_app(
    settings: Settings | None = None,
    *,
    images: ImageEditor | None = None,
    chat: Transcriber | None = None,
    retry_delays: tuple[float, ...] = DEFAULT_DELAYS,
    maintenance: bool = True,
) -> FastAPI:
    base = settings or Settings()

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = make_engine(base.db_path)
        migrate(engine)
        sf = make_session_factory(engine)
        provider = SettingsProvider(base, sf)
        eff = provider()
        image_client = images or ImageClient(eff.open_api_base_url, eff.open_api_key, timeout=eff.image_timeout_s)
        chat_client = chat or ChatClient(eff.open_api_base_url, eff.open_api_key, timeout=eff.chat_timeout_s)
        storage = Storage(base.files_dir)
        runner = JobRunner(sf, workers=eff.upstream_concurrency + 2)
        pipeline = Pipeline(Services(
            session_factory=sf, storage=storage, images=image_client, chat=chat_client,
            settings=provider, gate=asyncio.Semaphore(eff.upstream_concurrency),
            enqueue=runner.enqueue, retry_delays=retry_delays,
        ))
        runner.handlers.update(pipeline.handlers())
        runner.on_interrupted = pipeline.on_interrupted
        app.state.ctx = AppContext(settings=provider, sf=sf, engine=engine, storage=storage,
                                   runner=runner, limiter=LoginLimiter(),
                                   trusted=parse_networks(base.trusted_proxies))
        log.info("imgsr start relay=%s key=%s image=%s transcribe=%s review=%s",
                 eff.open_api_base_url, masked(eff.open_api_key), eff.image_model,
                 eff.transcribe_model, eff.review_model)
        await runner.start()
        maint = (asyncio.create_task(maintenance_loop(sf, storage, engine, base.backup_dir))
                 if maintenance else None)
        try:
            yield
        finally:
            if maint is not None:
                maint.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await maint
            await runner.stop()
            if images is None:
                await image_client.aclose()  # type: ignore[union-attr]
            if chat is None:
                await chat_client.aclose()  # type: ignore[union-attr]
            engine.dispose()

    app = FastAPI(title="imgsr", lifespan=lifespan, docs_url=None, redoc_url=None,
                  openapi_url="/api/openapi.json")

    @app.middleware("http")
    async def csrf_guard(request: Request, call_next):  # noqa: ANN001, ANN202
        if (request.method in MUTATING and request.url.path.startswith("/api/")
                and request.headers.get("x-requested-with") != "imgsr"):
            return JSONResponse({"detail": "缺少请求头 X-Requested-With: imgsr"}, status_code=403)
        return await call_next(request)

    @app.get("/api/health")
    def health(request: Request) -> dict:
        ctx: AppContext = request.app.state.ctx
        free = ctx.storage.free_bytes()
        return {"ok": True, "free_bytes": free, "low_disk": free < ctx.settings().min_free_bytes}

    for module in ROUTERS:
        app.include_router(module.router)
    return app
