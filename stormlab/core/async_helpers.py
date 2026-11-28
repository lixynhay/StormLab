"""Small helpers for offloading blocking synchronous work from async code."""

import asyncio
from typing import Any, Callable, TypeVar

T = TypeVar("T")


async def run_sync(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Run blocking synchronous work in the default thread pool.

    Keeps the asyncio event loop responsive while HTTP requests, MetPy
    calculations or other CPU/IO-bound code execute. Context variables are
    copied into the worker thread by :func:`asyncio.to_thread`.
    """
    return await asyncio.to_thread(func, *args, **kwargs)
