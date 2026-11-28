"""Regression tests for F-06: blocking work must not stall the asyncio loop."""

import asyncio
import threading
import time

import httpx
import pytest

import api
from core.async_helpers import run_sync

pytestmark = pytest.mark.asyncio

API_KEY = "test-secret-0123456789"
HEADERS = {"X-API-Key": API_KEY}


async def test_run_sync_executes_outside_event_loop_thread():
    loop_thread = threading.get_ident()
    worker_thread = await run_sync(threading.get_ident)
    assert worker_thread != loop_thread


async def _patch_slow_fused(monkeypatch):
    api.API_ACCESS_KEY = API_KEY
    api._rest_rate_limits.clear()

    def slow_fused(*args, **kwargs):
        time.sleep(0.25)
        raise api.HTTPException(status_code=503, detail="simulated-slow-render")

    monkeypatch.setattr(api, "_get_fused_data", slow_fused)


async def test_health_responds_while_storm_request_is_running(monkeypatch):
    await _patch_slow_fused(monkeypatch)
    transport = httpx.ASGITransport(app=api.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        heavy = asyncio.create_task(
            client.get("/api/storm?lat=55.7&lon=37.6", headers=HEADERS)
        )
        started = time.perf_counter()
        health = await client.get("/api/health")
        health_latency = time.perf_counter() - started
        heavy_response = await heavy

    assert health.status_code == 200
    assert health_latency < 0.05  # generous CI threshold; local target < 10 ms
    assert heavy_response.status_code == 503


async def test_ten_parallel_storm_requests_do_not_serialize(monkeypatch):
    await _patch_slow_fused(monkeypatch)
    transport = httpx.ASGITransport(app=api.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        started = time.perf_counter()
        responses = await asyncio.gather(*[
            client.get(f"/api/storm?lat=55.7&lon=37.6&city=c{i}", headers=HEADERS)
            for i in range(10)
        ])
        elapsed = time.perf_counter() - started

    assert [r.status_code for r in responses] == [503] * 10
    assert elapsed < 1.5  # local target: p95 < 1000 ms
