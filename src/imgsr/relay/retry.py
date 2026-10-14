"""Retry retryable relay errors with fixed back-off delays."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import TypeVar

from imgsr.relay.errors import RelayError

T = TypeVar("T")
DEFAULT_DELAYS: tuple[float, ...] = (10.0, 30.0)


async def with_retries(
    fn: Callable[[], Awaitable[T]],
    *,
    delays: tuple[float, ...] = DEFAULT_DELAYS,
    sleep: Callable[[float], Awaitable[object]] = asyncio.sleep,
) -> T:
    for attempt in range(len(delays) + 1):
        try:
            return await fn()
        except RelayError as exc:
            if not exc.retryable or attempt == len(delays):
                raise
            await sleep(delays[attempt])
    raise AssertionError("unreachable")
