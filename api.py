import logging
import hmac
import hashlib
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse, HTMLResponse
from pydantic import BaseModel, Field

from config import API_ACCESS_KEY, API_HOST
from clients.openmeteo_api import OpenMeteoAPI, resolve_hour_index
from clients.openweathermap_api import OpenWeatherMapAPI
from clients.data_fusion import fuse_current_weather
from core.storm_indices import build_storm_report, format_storm_text, build_skewt_context_for_ai
from core.season_regime import get_regime
from core.text_safety import redact_secrets
from core.async_helpers import run_sync
from render.chart_builder import build_profile_chart
from render.skewt_builder import build_skewt_chart
from clients.geocoding import resolve_city
from clients.radar_api import get_latest_radar_frame
from render.radar_builder import build_radar_image
from ai.ai_analysis import generate_storm_analysis

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

weather_api = OpenMeteoAPI()
owm_api = OpenWeatherMapAPI()

MIN_API_KEY_LENGTH = 16

# REST button index -> offset hours (mirrors /api/time-offsets and bot.TIME_OFFSETS).
_TIME_OFFSET_HOURS = (0, 3, 6, 12, 24)


def _utc_now():
    """Injectable clock so TestClient can freeze 'now' for time-index tests."""
    return datetime.now(timezone.utc)


def _require_strong_api_key():
    if API_ACCESS_KEY and len(API_ACCESS_KEY) < MIN_API_KEY_LENGTH:
        message = f"API_ACCESS_KEY слишком короткий: нужно минимум {MIN_API_KEY_LENGTH} символов"
        logger.critical(message)
        raise SystemExit(message)


@asynccontextmanager
async def lifespan(_app):
    _require_strong_api_key()
    yield


def _internal_error(context: str, exc: Exception) -> HTTPException:
    request_id = uuid.uuid4().hex
    logger.error(f"{context} [request_id={request_id}]: {exc}", exc_info=True)
    return HTTPException(status_code=500, detail=f"Internal error (request_id={request_id})")


def _build_storm_report_sync(lat: float, lon: float, time_index: int, city: str):
    """Blocking work for /api/storm, executed in a worker thread."""
    current_data, pressure_data, source_label, regime = _get_fused_data(lat, lon, time_index)
    report = build_storm_report(current_data, pressure_data, regime=regime)
    timestamp_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    formatted_text = format_storm_text(report, city, timestamp_str)
    return current_data, pressure_data, source_label, regime, report, timestamp_str, formatted_text


def _ai_analysis_sync(lat: float, lon: float, time_index: int, city: str) -> str:
    """Blocking work for /api/ai-analysis, executed in a worker thread."""
    current_data, pressure_data, _, regime = _get_fused_data(lat, lon, time_index)
    report = build_storm_report(current_data, pressure_data, regime=regime)
    skewt_ctx = build_skewt_context_for_ai(report, current_data["current"], pressure_data)
    return generate_storm_analysis(report, city, skewt_ctx)


app = FastAPI(
    title="StormLab API",
    description="API для метеорологического приложения с расчётом грозовых индексов",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

REST_RATE_LIMIT = 60
_rest_rate_limits = {}


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def documentation():
    """Serve the interactive API documentation; the page itself is public."""
    docs_path = Path(__file__).parent / "docs" / "api_docs.html"
    return HTMLResponse(docs_path.read_text(encoding="utf-8"))


def _api_key_matches(supplied_key: str, configured_key: str) -> bool:
    return hmac.compare_digest(supplied_key.encode(), configured_key.encode())


@app.middleware("http")
async def require_api_key(request: Request, call_next):
    if request.url.path.startswith("/api/") and request.url.path != "/api/health":
        if not API_ACCESS_KEY:
            return JSONResponse(
                status_code=401,
                content={"detail": "Unauthorized"},
            )

        supplied_key = request.headers.get("X-API-Key")
        if not supplied_key or not _api_key_matches(supplied_key, API_ACCESS_KEY):
            return JSONResponse(
                status_code=401,
                content={"detail": "Unauthorized"},
            )

        now = time.time()
        window_start = int(now // 60) * 60
        rate_key = hashlib.sha256(supplied_key.encode()).digest()
        counter = _rest_rate_limits.get(rate_key)
        if counter is None or counter[0] != window_start:
            counter = (window_start, 0)
        count = counter[1] + 1
        _rest_rate_limits[rate_key] = (window_start, count)

        if len(_rest_rate_limits) > 1000:
            expired = [
                key for key, (start, _) in _rest_rate_limits.items()
                if start != window_start
            ]
            for key in expired:
                _rest_rate_limits.pop(key, None)

        if count > REST_RATE_LIMIT:
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests"},
            )

    return await call_next(request)

class StormReportResponse(BaseModel):
    city: str
    timestamp: str
    source: str
    report: dict
    formatted_text: str

class GeocodeResponse(BaseModel):
    name: str
    lat: float
    lon: float
    country: str

class AIAnalysisRequest(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    city: str = Field(min_length=1, max_length=100)
    time_index: int = Field(default=0, ge=0, le=len(_TIME_OFFSET_HOURS) - 1)

class AIAnalysisResponse(BaseModel):
    city: str
    analysis: str
    timestamp: str

def _regime_for(lat: float, lon: float) -> str:
    """Seasonal regime for a REST request (same UTC-month heuristic as bot.py)."""
    return get_regime(lat, datetime.now(timezone.utc).month)


def _get_fused_data(lat: float, lon: float, time_index: int):
    # Compute the regime BEFORE fuse_current_weather drops the top-level
    # latitude/longitude of the raw Open-Meteo response.
    regime = _regime_for(lat, lon)
    om_data = weather_api.get_current(lat, lon)
    pressure_data_raw = weather_api.get_pressure_levels(lat, lon)
    hourly_full = pressure_data_raw.get("hourly", {})

    # time_index is a button index (0..4), not a raw array slot: hourly.time
    # starts at 00:00 UTC. Use the same base+offset logic as bot.py.
    try:
        offset_hours = _TIME_OFFSET_HOURS[time_index]
    except IndexError:
        raise HTTPException(
            status_code=422,
            detail=f"time_index must be in 0..{len(_TIME_OFFSET_HOURS) - 1}",
        )
    slot = resolve_hour_index(
        hourly_full.get("time", []), offset_hours, now=_utc_now()
    )
    if slot is None:
        slot = max(0, len(hourly_full.get("time", [])) - 1)

    sliced_hourly = {}
    for key, values in hourly_full.items():
        if isinstance(values, list) and len(values) > slot:
            val = values[slot]
            sliced_hourly[key] = [val] if val is not None else [None]
        else:
            sliced_hourly[key] = values

    surface_pressure = om_data["current"].get("surface_pressure")
    if surface_pressure is None:
        sp_list = hourly_full.get("surface_pressure", [None])
        surface_pressure = sp_list[0] if sp_list else 1013.25

    if time_index == 0:
        owm_current = None
        try:
            owm_current = owm_api.get_current(lat, lon)
        except Exception as e:
            logger.warning(f"OpenWeatherMap недоступен: {redact_secrets(e)}")
        fused = fuse_current_weather(om_data["current"], owm_current)
        source_label = "Open-Meteo + OpenWeatherMap" if owm_current else "Open-Meteo"
    else:
        fused = {
            "temperature_2m": sliced_hourly.get("temperature_2m", [None])[0],
            "dew_point_2m": sliced_hourly.get("dew_point_2m", [None])[0],
            "surface_pressure": surface_pressure,
            "wind_speed_10m": sliced_hourly.get("wind_speed_10m", [None])[0],
            "wind_direction_10m": sliced_hourly.get("wind_direction_10m", [None])[0],
        }
        source_label = "Open-Meteo (Прогноз)"

    return (
        {"current": fused, "latitude": lat, "longitude": lon, "regime": regime},
        {"hourly": sliced_hourly},
        source_label,
        regime,
    )

@app.get("/api/health")
async def health_check():
    return {"status": "ok"}


@app.get("/api/geocode", response_model=GeocodeResponse)
async def geocode(query: str = Query(..., min_length=1, max_length=100, description="Название города")):
    result = await run_sync(resolve_city, query)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Город '{query}' не найден")
    lat, lon, name = result
    return GeocodeResponse(name=name, lat=lat, lon=lon, country="")


@app.get("/api/storm", response_model=StormReportResponse)
async def get_storm_report(
    lat: float = Query(..., ge=-90, le=90, description="Широта"),
    lon: float = Query(..., ge=-180, le=180, description="Долгота"),
    city: str = Query("Неизвестно", min_length=1, max_length=100, description="Название города"),
    time_index: int = Query(0, ge=0, le=len(_TIME_OFFSET_HOURS) - 1, description="Индекс времени (0=сейчас, 1=+3ч, 2=+6ч, 3=+12ч, 4=+24ч)")
):
    try:
        (current_data, pressure_data, source_label, regime,
         report, timestamp_str, formatted_text) = await run_sync(
            _build_storm_report_sync, lat, lon, time_index, city
        )

        return StormReportResponse(
            city=city,
            timestamp=timestamp_str,
            source=source_label,
            report=report,
            formatted_text=formatted_text
        )
    except HTTPException:
        raise
    except Exception as e:
        raise _internal_error("Ошибка расчёта индексов", e)


@app.get("/api/chart/profile")
def get_profile_chart(
    lat: float = Query(..., ge=-90, le=90, description="Широта"),
    lon: float = Query(..., ge=-180, le=180, description="Долгота"),
    city: str = Query("Неизвестно", min_length=1, max_length=100, description="Название города"),
    time_index: int = Query(0, ge=0, le=len(_TIME_OFFSET_HOURS) - 1, description="Индекс времени")
):
    try:
        _, pressure_data, _, regime = _get_fused_data(lat, lon, time_index)
        chart = build_profile_chart(pressure_data, city, f"t+{time_index}ч")

        if chart is None:
            raise HTTPException(status_code=500, detail="Не удалось построить график")

        return StreamingResponse(chart, media_type="image/png")
    except HTTPException:
        raise
    except Exception as e:
        raise _internal_error("Ошибка построения графика", e)


@app.get("/api/chart/skewt")
def get_skewt_chart(
    lat: float = Query(..., ge=-90, le=90, description="Широта"),
    lon: float = Query(..., ge=-180, le=180, description="Долгота"),
    city: str = Query("Неизвестно", min_length=1, max_length=100, description="Название города"),
    time_index: int = Query(0, ge=0, le=len(_TIME_OFFSET_HOURS) - 1, description="Индекс времени")
):
    try:
        current_data, pressure_data, _, regime = _get_fused_data(lat, lon, time_index)
        report = build_storm_report(current_data, pressure_data, regime=regime)
        current = current_data["current"]
        hourly = pressure_data["hourly"]

        chart = build_skewt_chart(current, hourly, None, None, city, f"t+{time_index}ч", report=report)

        if chart is None:
            raise HTTPException(status_code=500, detail="Не удалось построить Skew-T")

        return StreamingResponse(chart, media_type="image/png")
    except HTTPException:
        raise
    except Exception as e:
        raise _internal_error("Ошибка построения Skew-T", e)


@app.get("/api/radar")
def get_radar(
    lat: float = Query(..., ge=-90, le=90, description="Широта"),
    lon: float = Query(..., ge=-180, le=180, description="Долгота"),
    city: str = Query("Неизвестно", min_length=1, max_length=100, description="Название города")
):
    try:
        radar_path, timestamp_utc, is_cached = get_latest_radar_frame()
        if radar_path is None:
            raise HTTPException(status_code=503, detail="Радар временно недоступен")

        radar_image = build_radar_image(lat, lon, radar_path)
        if radar_image is None:
            raise HTTPException(status_code=500, detail="Не удалось построить изображение радара")

        return StreamingResponse(radar_image, media_type="image/png", headers={
            "X-Radar-Timestamp": timestamp_utc.isoformat(),
            "X-Radar-Cached": str(is_cached).lower()
        })
    except HTTPException:
        raise
    except Exception as e:
        raise _internal_error("Ошибка получения радара", e)


@app.post("/api/ai-analysis", response_model=AIAnalysisResponse)
async def get_ai_analysis(request: AIAnalysisRequest):
    try:
        analysis = await run_sync(
            _ai_analysis_sync, request.lat, request.lon, request.time_index, request.city
        )

        return AIAnalysisResponse(
            city=request.city,
            analysis=analysis,
            timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        )
    except HTTPException:
        raise
    except Exception as e:
        raise _internal_error("Ошибка AI-анализа", e)


@app.get("/api/time-offsets")
async def get_time_offsets():
    return {
        "offsets": [
            {"index": 0, "label": "Сейчас", "hours": 0},
            {"index": 1, "label": "+3 часа", "hours": 3},
            {"index": 2, "label": "+6 часов", "hours": 6},
            {"index": 3, "label": "+12 часов", "hours": 12},
            {"index": 4, "label": "+24 часа", "hours": 24},
        ]
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=API_HOST, port=8000)
