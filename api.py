import io
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel

from config import API_TIMEOUT
from openmeteo_api import OpenMeteoAPI
from openweathermap_api import OpenWeatherMapAPI
from data_fusion import fuse_current_weather
from storm_indices import build_storm_report, format_storm_text, build_skewt_context_for_ai
from chart_builder import build_profile_chart
from skewt_builder import build_skewt_chart
from geocoding import resolve_city
from radar_api import get_latest_radar_frame
from radar_builder import build_radar_image
from ai_analysis import generate_storm_analysis

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

weather_api = OpenMeteoAPI()
owm_api = OpenWeatherMapAPI()

app = FastAPI(
    title="StormLab API",
    description="API для метеорологического приложения с расчётом грозовых индексов",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
    lat: float
    lon: float
    city: str
    time_index: int = 0

class AIAnalysisResponse(BaseModel):
    city: str
    analysis: str
    timestamp: str

def _get_fused_data(lat: float, lon: float, time_index: int):
    om_data = weather_api.get_current(lat, lon)
    pressure_data_raw = weather_api.get_pressure_levels(lat, lon)
    hourly_full = pressure_data_raw.get("hourly", {})
    
    sliced_hourly = {}
    for key, values in hourly_full.items():
        if isinstance(values, list) and len(values) > time_index:
            val = values[time_index]
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
            logger.warning(f"OpenWeatherMap недоступен: {e}")
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
    
    return {"current": fused}, {"hourly": sliced_hourly}, source_label

@app.get("/api/health")
async def health_check():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/api/geocode", response_model=GeocodeResponse)
async def geocode(query: str = Query(..., description="Название города")):
    result = resolve_city(query)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Город '{query}' не найден")
    lat, lon, name = result
    return GeocodeResponse(name=name, lat=lat, lon=lon, country="")


@app.get("/api/storm", response_model=StormReportResponse)
async def get_storm_report(
    lat: float = Query(..., description="Широта"),
    lon: float = Query(..., description="Долгота"),
    city: str = Query("Неизвестно", description="Название города"),
    time_index: int = Query(0, description="Индекс времени (0=сейчас, 1=+3ч, 2=+6ч, 3=+12ч, 4=+24ч)")
):
    try:
        current_data, pressure_data, source_label = _get_fused_data(lat, lon, time_index)
        report = build_storm_report(current_data, pressure_data)
        timestamp_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        formatted_text = format_storm_text(report, city, timestamp_str)
        
        return StormReportResponse(
            city=city,
            timestamp=timestamp_str,
            source=source_label,
            report=report,
            formatted_text=formatted_text
        )
    except Exception as e:
        logger.error(f"Ошибка расчёта индексов: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Ошибка расчёта: {str(e)}")


@app.get("/api/chart/profile")
async def get_profile_chart(
    lat: float = Query(..., description="Широта"),
    lon: float = Query(..., description="Долгота"),
    city: str = Query("Неизвестно", description="Название города"),
    time_index: int = Query(0, description="Индекс времени")
):
    try:
        _, pressure_data, _ = _get_fused_data(lat, lon, time_index)
        chart = build_profile_chart(pressure_data, city, f"t+{time_index}ч")
        
        if chart is None:
            raise HTTPException(status_code=500, detail="Не удалось построить график")
        
        return StreamingResponse(chart, media_type="image/png")
    except Exception as e:
        logger.error(f"Ошибка построения графика: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/chart/skewt")
async def get_skewt_chart(
    lat: float = Query(..., description="Широта"),
    lon: float = Query(..., description="Долгота"),
    city: str = Query("Неизвестно", description="Название города"),
    time_index: int = Query(0, description="Индекс времени")
):
    try:
        current_data, pressure_data, _ = _get_fused_data(lat, lon, time_index)
        report = build_storm_report(current_data, pressure_data)
        current = current_data["current"]
        hourly = pressure_data["hourly"]
        
        chart = build_skewt_chart(current, hourly, None, None, city, f"t+{time_index}ч", report=report)
        
        if chart is None:
            raise HTTPException(status_code=500, detail="Не удалось построить Skew-T")
        
        return StreamingResponse(chart, media_type="image/png")
    except Exception as e:
        logger.error(f"Ошибка построения Skew-T: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/radar")
async def get_radar(
    lat: float = Query(..., description="Широта"),
    lon: float = Query(..., description="Долгота"),
    city: str = Query("Неизвестно", description="Название города")
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
    except Exception as e:
        logger.error(f"Ошибка получения радара: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/ai-analysis", response_model=AIAnalysisResponse)
async def get_ai_analysis(request: AIAnalysisRequest):
    try:
        current_data, pressure_data, _ = _get_fused_data(request.lat, request.lon, request.time_index)
        report = build_storm_report(current_data, pressure_data)
        
        skewt_ctx = build_skewt_context_for_ai(report, current_data["current"], pressure_data)
        analysis = generate_storm_analysis(report, request.city, skewt_ctx)
        
        return AIAnalysisResponse(
            city=request.city,
            analysis=analysis,
            timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        )
    except Exception as e:
        logger.error(f"Ошибка AI-анализа: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


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
    uvicorn.run(app, host="0.0.0.0", port=8000)