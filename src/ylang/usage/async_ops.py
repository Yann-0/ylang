"""Async wrappers for blocking usage store operations."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

import anyio

T = TypeVar("T")


async def run_store_sync(func: Callable[..., T], /, *args: object, **kwargs: object) -> T:
    """Run a synchronous store operation in a worker thread."""
    return await anyio.to_thread.run_sync(lambda: func(*args, **kwargs))
