import asyncio
import threading
from collections import OrderedDict
import logging
import os
import pickle
import sys
import time
from datetime import datetime, timezone
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, Update
from telegram.error import TimedOut, NetworkError, Forbidden
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler, ContextTypes,
)
from telegram.request import HTTPXRequest

from config import (
    RESTART_DELAY_SECONDS, BOT_TOKEN, IO_TIMEOUT, AI_ANALYSIS_TIMEOUT,
    SOUNDING_PROBE_TIMEOUT, MAX_ALERTS_PER_USER,
)
from logging_config import setup_logging
from persistence import AtomicPicklePersistence
from clients.openmeteo_api import OpenMeteoAPI, resolve_hour_index
from clients.openweathermap_api import OpenWeatherMapAPI
from clients.data_fusion import fuse_current_weather
from core.storm_indices import build_storm_report, format_storm_text, build_skewt_context_for_ai
from core.season_regime import get_regime, interpret
from core.text_safety import escape_markdown, redact_secrets
from render.chart_builder import build_profile_chart
from ai.ai_analysis import generate_storm_analysis
from render.skewt_builder import build_skewt_chart
from clients.sounding_api import get_sounding_by_wmo, probe_stations
from clients.geocoding import resolve_city
from clients.radar_api import get_latest_radar_frame
from render.radar_builder import build_radar_image
from rate_limiter import rate_limited, check_rate_limit
from alert_manager import (
    add_alert, remove_alert, get_user_alerts, get_all_alerts,
    can_send_alert, record_alert_sent, check_dangerous_conditions,
    get_user_location_keys, location_key, group_alerts_by_location, prune_history,
)

setup_logging()
logger = logging.getLogger(__name__)


def md(text: str) -> str:
    """Экранирование для parse_mode=Markdown (классический V1)."""
    return escape_markdown(text)


weather_api = OpenMeteoAPI()
owm_api = OpenWeatherMapAPI()
_skewt_ctx: "OrderedDict[tuple[int, int], tuple]" = OrderedDict()
_skewt_ctx_lock = threading.Lock()
_SKEWT_MAX = 512


def put_skewt_ctx(chat_id: int, msg_id: int, value) -> None:
    with _skewt_ctx_lock:
        key = (chat_id, msg_id)
        _skewt_ctx[key] = value
        _skewt_ctx.move_to_end(key)
        while len(_skewt_ctx) > _SKEWT_MAX:
            _skewt_ctx.popitem(last=False)


def get_skewt_ctx(chat_id: int, msg_id: int):
    with _skewt_ctx_lock:
        return _skewt_ctx.get((chat_id, msg_id))


TIME_OFFSETS = [
    {"label": "Сейчас", "hours": 0},
    {"label": "+3 часа", "hours": 3},
    {"label": "+6 часов", "hours": 6},
    {"label": "+12 часов", "hours": 12},
    {"label": "+24 часа", "hours": 24},
]

def _prune_ctx():
    """Kept for backwards compatibility; put_skewt_ctx() now bounds the dict."""



def _prune_user_data(context):
    now = time.time()
    last_activity = context.user_data.get("_last_activity")
    if last_activity is not None and now - last_activity > 24 * 60 * 60:
        context.user_data.clear()

    allowed_keys = {
        "_last_activity", "geo", "last_report", "last_storm_messages",
        "last_skewt_messages", "pending_action", "pending_message_id",
    }
    for key in list(context.user_data):
        if key not in allowed_keys:
            context.user_data.pop(key, None)

    context.user_data["_last_activity"] = now

def _slice_hourly(hourly: dict, time_index: int) -> dict:
    sliced = {}
    for key, values in hourly.items():
        if isinstance(values, list) and len(values) > time_index:
            val = values[time_index]
            sliced[key] = [val] if val is not None else [None]
        else:
            sliced[key] = values
    return sliced

def _get_fused_current_data(lat, lon, time_index):
    """Fused surface data + pressure profile for a button hour offset (0/3/6/12/24).

    ``time_index`` is an hour offset, not a raw array index: the base slot is the
    current UTC hour found via searchsorted over hourly.time (00:00 UTC = index 0).
    """
    om_data = weather_api.get_current(lat, lon)
    pressure_data_raw = weather_api.get_pressure_levels(lat, lon)
    hourly_full = pressure_data_raw.get("hourly", {})
    slot = resolve_hour_index(hourly_full.get("time", []), time_index)
    sliced_hourly = _slice_hourly(hourly_full, slot)
    
    surface_pressure = om_data["current"].get("surface_pressure")
    if time_index > 0:
        sp_list = sliced_hourly.get("surface_pressure", [None])
        if sp_list and sp_list[0] is not None:
            surface_pressure = sp_list[0]
    elif surface_pressure is None:
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
        
    return {"current": fused}, {"hourly": sliced_hourly}, source_label

async def _resolve_target(context, message_target, args=None):
    _prune_user_data(context)
    if args:
        user = getattr(message_target, "from_user", None)
        uid = getattr(user, "id", None)
        if uid is not None:
            allowed, remaining = check_rate_limit(uid, "geocode")
            if not allowed:
                await message_target.reply_text(
                    f"⏳ Геокодер: подожди {remaining} с.", parse_mode="Markdown"
                )
                return None
        query = " ".join(args).strip()[:100]  # защита от чрезмерно длинных строк (DoS на геокодер)
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(resolve_city, query), timeout=IO_TIMEOUT
            )
        except asyncio.TimeoutError:
            logger.warning(f"Геокодер не ответил за {IO_TIMEOUT} с: {query}")
            await message_target.reply_text("⏳ Геокодер не ответил. Попробуй ещё раз.")
            return None
        if result is None:
            await message_target.reply_text(
                f"❌ Не нашёл город «{md(query)}». Проверь название или попробуй по-английски (например, 'Moscow').",
                parse_mode="Markdown"
            )
            return None
        context.user_data["geo"] = result
        return result
        
    if context.user_data.get("geo"):
        return context.user_data["geo"]
        
    await message_target.reply_text(
        "📍 Город не задан. Укажи его, например:\n"
        "`/storm Москва`\n`/skewt Сочи`\n`/ai Казань`\n\n"
        "После этого я запомню его для кнопок ниже."
    )
    return None

def _build_time_markup():
    rows = [[InlineKeyboardButton(t["label"], callback_data=f"time:{i}")] for i, t in enumerate(TIME_OFFSETS)]
    return InlineKeyboardMarkup(rows)

def _build_stations_markup(probe):
    rows = []
    for s in probe:
        mark = "✅ " if s["has_data"] else "   "
        rows.append([InlineKeyboardButton(
            f"{mark} {s['name']} · {s['dist_km']} км", callback_data=f"stn:{s['wmo']}"
        )])
    rows.append([InlineKeyboardButton("🔄 Только модель", callback_data="stn:__model__")])
    return InlineKeyboardMarkup(rows)

def _build_report_actions() -> InlineKeyboardMarkup:
    # Используем короткие callback_data, чтобы избежать ошибки Button_data_invalid (лимит 64 байта)
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 Обновить", callback_data="refresh"),
            InlineKeyboardButton("📍 Сменить город", callback_data="change_city"),
        ],
        [
            InlineKeyboardButton("📈 Skew-T", callback_data="skewt"),
            InlineKeyboardButton("🤖 AI-анализ", callback_data="ai"),
        ],
    ])

async def send_error_card(message_target, error_text: str, action_callback: str = None):
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🔄 Попробовать снова", callback_data=action_callback)
    ]]) if action_callback else None
    await message_target.reply_text(f"❌ *Ошибка*\n\n{error_text}", parse_mode="Markdown", reply_markup=keyboard)

async def _cleanup_messages(context: ContextTypes.DEFAULT_TYPE, chat_id, msg_list_key: str):
    """Удаляет старые сообщения бота, чтобы не засорять чат."""
    last_messages = context.user_data.get(msg_list_key, [])
    for msg_id in last_messages:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except Exception:
            pass
    context.user_data[msg_list_key] = []

async def _send_storm_report(message_target, lat, lon, city, time_index, time_label, context):
    await _cleanup_messages(context, message_target.chat.id, "last_storm_messages")
    sent_messages = []
    
    try:
        current_data, pressure_data, source_label = await asyncio.wait_for(
            asyncio.to_thread(_get_fused_current_data, lat, lon, time_index),
            timeout=IO_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.error(f"Данные Open-Meteo не получены за {IO_TIMEOUT} с")
        await send_error_card(message_target, "Источник данных не ответил вовремя.", action_callback="refresh")
        return
    except Exception as e:
        logger.error(f"Не удалось получить данные: {e}")
        await send_error_card(message_target, "Не удалось получить атмосферные данные.", action_callback="refresh")
        return
    
    try:
        regime = get_regime(lat, datetime.now(timezone.utc).month)
        report = build_storm_report(current_data, pressure_data, regime=regime)
        timestamp_str = datetime.now(timezone.utc).strftime("%H:%M UTC")
        text = format_storm_text(report, md(city), timestamp_str)
        if report.get("effective_layer") is None:
            text += "\n\neffective layer не найден, показан fixed-layer"
        season_lines = interpret(
            regime, report.get("cape", 0) or 0, report.get("bulk_shear_06", 0) or 0
        )
        if season_lines:
            text += "\n\n" + "\n".join(season_lines)
        text += f"\n_Время: {time_label} | Данные: {source_label}_"
    except Exception as e:
        logger.error(f"Ошибка расчёта: {e}", exc_info=True)
        await message_target.reply_text("❌ Не удалось рассчитать индексы.")
        return
    
    context.user_data["last_report"] = {
        "report": report, "city": city, "time_label": time_label,
        "current": current_data["current"], "pressure": pressure_data["hourly"]
    }
    
    chart = await asyncio.to_thread(build_profile_chart, pressure_data, city, time_label)
    if chart is not None:
        msg = await message_target.reply_photo(photo=chart)
        sent_messages.append(msg.message_id)
    
    msg = await message_target.reply_text(text, parse_mode="Markdown")
    sent_messages.append(msg.message_id)
    
    msg = await message_target.reply_text("⚙️ Действия:", reply_markup=_build_report_actions())
    sent_messages.append(msg.message_id)
    
    context.user_data["last_storm_messages"] = sent_messages

async def _send_skewt(message_target, lat, lon, city, time_index, time_label, context):
    await _cleanup_messages(context, message_target.chat.id, "last_skewt_messages")
    
    try:
        current_data, pressure_data, _ = await asyncio.wait_for(
            asyncio.to_thread(_get_fused_current_data, lat, lon, time_index),
            timeout=IO_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.error(f"Данные Open-Meteo не получены за {IO_TIMEOUT} с")
        await send_error_card(message_target, "Источник данных не ответил вовремя.", action_callback="refresh")
        return
    except Exception as e:
        logger.error(f"Не удалось получить данные: {e}")
        await send_error_card(message_target, "Не удалось получить атмосферные данные.", action_callback="refresh")
        return
    
    try:
        regime = get_regime(lat, datetime.now(timezone.utc).month)
        report = build_storm_report(current_data, pressure_data, regime=regime)
    except Exception as e:
        logger.warning(f"Storm report failed in skewt: {e}")
        report = None
    
    try:
        probe = await asyncio.wait_for(
            asyncio.to_thread(probe_stations, lat, lon),
            timeout=SOUNDING_PROBE_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.warning(f"probe_stations не ответил за {SOUNDING_PROBE_TIMEOUT} с — только модель")
        probe = []
    current, hourly = current_data["current"], pressure_data["hourly"]
    chart = await asyncio.to_thread(
        build_skewt_chart, current, hourly, None, None, city, time_label, report=report
    )
    
    if chart is None:
        await message_target.reply_text("❌ Не удалось построить Skew-T.")
        return
    
    markup = _build_stations_markup(probe) if probe else None
    caption = f"📈 Skew-T: модель Open-Meteo ({md(city)}, {time_label})"
    caption += "\nВыбери реальный зонд 👇" if probe else "."
    
    msg = await message_target.reply_photo(photo=chart, caption=caption, reply_markup=markup, parse_mode="Markdown")
    
    context.user_data["last_skewt_messages"] = [msg.message_id]
    put_skewt_ctx(message_target.chat.id, msg.message_id, (
        lat, lon, city, current, hourly, probe, time_label, report
    ))

async def _send_radar(message_target, lat, lon, city, context):
    await message_target.reply_text(f"📡 Загружаю радар для *{md(city)}*...", parse_mode="Markdown")
    try:
        radar_path, timestamp_utc, is_cached = await asyncio.to_thread(get_latest_radar_frame)
        if radar_path is None:
            await message_target.reply_text(
                "📡 Радар временно недоступен.\n\n"
                "Сервер RainViewer обновляет данные. Попробуй через 10-15 минут."
            )
            return
            
        radar_image = await asyncio.to_thread(build_radar_image, lat, lon, radar_path)
        if radar_image is None:
            await send_error_card(
                message_target,
                "RainViewer не вернул данные радара для этого района. Попробуй позже.",
                action_callback="refresh",
            )
            return
            
        time_str = timestamp_utc.strftime("%H:%M UTC")
        cache_note = " (кэш)" if is_cached else ""
        caption = f"📡 Радар осадков: *{md(city)}*{cache_note}\n🕐 Данные: {time_str}\n📏 Масштаб: ~200x200 км"
        if getattr(radar_image, "no_echo", False):
            caption += "\nОсадков в зоне не обнаружено."
        await message_target.reply_photo(photo=radar_image, caption=caption, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Ошибка отправки радара: {e}", exc_info=True)
        await message_target.reply_text("❌ Произошла ошибка при загрузке радара.")

async def _send_ai_analysis(message_target, context):
    cached = context.user_data.get("last_report")
    if cached:
        report, city, time_label = cached["report"], cached["city"], cached["time_label"]
        current_data = {"current": cached["current"]}
        pressure_data = {"hourly": cached["pressure"]}
    else:
        target = context.user_data.get("geo")
        if not target:
            await message_target.reply_text("📍 Сначала укажи город через `/storm` или `/skewt`.", parse_mode="Markdown")
            return
        lat, lon, city = target
        time_label = "Сейчас"
        try:
            current_data, pressure_data, _ = await asyncio.to_thread(_get_fused_current_data, lat, lon, 0)
            regime = get_regime(lat, datetime.now(timezone.utc).month)
            report = build_storm_report(current_data, pressure_data, regime=regime)
        except Exception as e:
            logger.error(f"AI analysis data fetch failed: {e}")
            await message_target.reply_text("❌ Не удалось получить данные для анализа.")
            return
            
    skewt_ctx = build_skewt_context_for_ai(report, current_data["current"], pressure_data)
    # Синхронные HTTP-запросы к AI-провайдерам — в потоке, чтобы не блокировать event loop.
    try:
        analysis = await asyncio.wait_for(
            asyncio.to_thread(generate_storm_analysis, report, city, skewt_ctx),
            timeout=AI_ANALYSIS_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.warning(f"AI-анализ не уложился в {AI_ANALYSIS_TIMEOUT} с")
        await message_target.reply_text(
            "⏳ AI-провайдеры не ответили вовремя. Попробуй позже."
        )
        return
    
    # Dynamic LLM text is sent without parse_mode: arbitrary _, *, [, ] in the
    # response would otherwise cause Telegram BadRequest and lose the answer.
    await message_target.reply_text(
        f"🤖 AI-анализ ({city}, {time_label}):",
    )
    await message_target.reply_text(redact_secrets(analysis))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("⚡ Грозовые индексы", callback_data="storm"),
         InlineKeyboardButton("📉 Skew-T", callback_data="skewt")],
        [InlineKeyboardButton("🔔 Алерты", callback_data="alerts"),
         InlineKeyboardButton("📡 Радар", callback_data="radar")],
        [InlineKeyboardButton("🤖 AI-анализ", callback_data="ai"),
         InlineKeyboardButton("❓ Помощь", callback_data="help")],
    ]
    await update.message.reply_text(
        "🌩 *Привет! Я метеобот.*\n\n"
        "Укажи город: `/storm Москва`. Я запомню его.\n"
        "После этого выбирай время прогноза и тип анализа кнопками.",
        parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard),
    )

@rate_limited("storm_menu", message="⏳ Подожди немного перед новым запросом.")
async def storm_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = await _resolve_target(context, update.message, context.args)
    if not target: return
    lat, lon, city = target
    
    msg = await update.message.reply_text(
        f"⏳ Выбери время прогноза для *{md(city)}*:", 
        parse_mode="Markdown", reply_markup=_build_time_markup()
    )
    context.user_data["pending_action"] = "storm"
    context.user_data["pending_message_id"] = msg.message_id

@rate_limited("skewt_menu", message="⏳ Подожди немного перед новым запросом.")
async def skewt_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = await _resolve_target(context, update.message, context.args)
    if not target: return
    lat, lon, city = target
    
    msg = await update.message.reply_text(
        f"⏳ Выбери время прогноза для *{md(city)}*:", 
        parse_mode="Markdown", reply_markup=_build_time_markup()
    )
    context.user_data["pending_action"] = "skewt"
    context.user_data["pending_message_id"] = msg.message_id

@rate_limited("radar", message="⏳ Радар обновляется раз в 5 минут. Подожди немного.")
async def radar_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = await _resolve_target(context, update.message, context.args)
    if not target: return
    lat, lon, city = target
    
    await _send_radar(update.message, lat, lon, city, context)

@rate_limited("ai", message="⏳ Подожди немного перед следующим AI-анализом.")
async def ai_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 Анализирую последний запрос...")
    await _send_ai_analysis(update.message, context)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📋 *Доступные команды:*\n\n"
        "/start - Начать работу\n"
        "/storm [город] - Грозовые индексы + график профиля\n"
        "/skewt [город] - Skew-T диаграмма + выбор реального зонда\n"
        "/alert [город] - Подписка на уведомление при экстремальной погоде\n"
        "/unalert [город] - Отписаться от уведомлений\n"
        "/alerts - Список активных подписок\n"
        "/radar [город] - Радар осадков вокруг города\n"
        "/ai [город] - AI-анализ грозовой обстановки\n"
        "/help - Эта справка\n\n"
        "💡 *Поддержка проекта:*\n"
        "Этот бот полностью бесплатен и создан энтузиастом для метеорологического сообщества. "
        "Если он вам полезен, вы можете поддержать оплату серверов:\n"
        "💎 *TON:* `UQC-plwq4_uIPlVxTSba2IAm3L805D6iWxdMCMaVXeqwz5CZ` (нажми, чтобы скопировать)\n"
        "☕ *Boosty:* [Поддержать проект](https://boosty.to/lixynyt167/purchase/1865325?ssource=DIRECT&share=subscription_link) (безопасно и анонимно)\n\n"
        "_Расчёт по доступному профилю. Не заменяет официальный прогноз._"
    )
    await update.effective_message.reply_text(text, parse_mode="Markdown")

@rate_limited("alert", message="⏳ Подожди немного перед изменением подписок.")
async def alert_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = await _resolve_target(context, update.message, context.args)
    if not target: return
    lat, lon, city = target
    user_id = update.effective_user.id
    username = update.effective_user.username
    city_clean = city.strip()

    existing = get_user_alerts(user_id)
    if any(a.get("city") == city_clean for a in existing):
        await update.message.reply_text(f"ℹ️ Подписка на {md(city)} уже активна.", parse_mode="Markdown")
        return

    keys = get_user_location_keys(user_id)
    if location_key(lat, lon) not in keys and len(keys) >= MAX_ALERTS_PER_USER:
        await update.message.reply_text(
            f"❌ Достигнут лимит подписок: {MAX_ALERTS_PER_USER} уникальных локаций.\n"
            "Удали лишнюю через `/unalert город`.",
            parse_mode="Markdown",
        )
        return
    
    if add_alert(user_id, username, city_clean, lat, lon):
        text = (f"✅ *Подписка активирована!*\n\n📍 {md(city)}\n\n"
                "Бот будет проверять условия каждые 30 минут и предупреждать "
                "о риске организованных гроз или суперячеек.\n\n"
                f"Отписаться: `/unalert {md(city)}`")
        await update.message.reply_text(text, parse_mode="Markdown")
    else:
        await update.message.reply_text(f"ℹ️ Подписка на {md(city)} уже активна.", parse_mode="Markdown")

@rate_limited("alert", message="⏳ Подожди немного перед изменением подписок.")
async def unalert_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❓ Укажи город:\n`/unalert Москва`", parse_mode="Markdown")
        return
    city = " ".join(context.args)
    if remove_alert(update.effective_user.id, city):
        await update.message.reply_text(f"✅ Подписка на {md(city)} удалена.", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"ℹ️ Подписка на {md(city)} не найдена.", parse_mode="Markdown")

@rate_limited("alerts", message="⏳ Подожди немного перед обновлением списка.")
async def alerts_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    alerts = get_user_alerts(user_id)
    if not alerts:
        await update.effective_message.reply_text(
            "📭 У тебя нет активных подписок.\n\n"
            "Подписаться: `/alert Москва`",
            parse_mode="Markdown"
        )
        return

    text = await _alerts_list_text(alerts)
    await update.effective_message.reply_text(text, parse_mode="Markdown")


async def _alerts_list_text(alerts) -> str:
    """Список подписок с индикатором угрозы (общий для /alerts и кнопки)."""
    lines = ["\U0001f4ec *Твои подписки (" + str(len(alerts)) + "):*\n"]
    for alert in alerts:
        city = alert["city"]
        lat, lon = alert.get("lat"), alert.get("lon")
        threat = "\u26aa"
        if lat and lon:
            try:
                om_data = await asyncio.to_thread(weather_api.get_current, lat, lon)
                pressure_data_raw = await asyncio.to_thread(weather_api.get_pressure_levels, lat, lon)
                current_data = {"current": om_data["current"]}
                pressure_data_dict = {"hourly": pressure_data_raw.get("hourly", {})}
                regime = get_regime(lat, datetime.now(timezone.utc).month)
                report = build_storm_report(
                    current_data, pressure_data_dict, regime=regime
                )
                t = report.get("threat_level", 0) or 0
                threat = ["\u26aa", "\U0001f7e2", "\U0001f7e1", "\U0001f7e0", "\U0001f534", "\u26ab"][min(t, 5)]
            except Exception as e:
                logger.warning(f"Threat check failed for {city}: {e}")
                threat = "\u26aa"
        lines.append(f"{threat} {md(city)}")
    lines.append("\n_Отписаться:_ `/unalert город`")
    return "\n".join(lines)


@rate_limited()
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    _prune_user_data(context)
    query = update.callback_query
    await query.answer()

    if query.data == "alerts":
        user_id = update.effective_user.id
        alerts = get_user_alerts(user_id)
        if not alerts:
            text = "\U0001f4ed У тебя нет активных подписок.\n\n"
            text += "Подписаться: `/alert Москва`"
        else:
            text = await _alerts_list_text(alerts)
        await query.message.reply_text(text, parse_mode="Markdown")
        return

    if query.data.startswith("time:"):
        time_idx = int(query.data.split(":")[1])
        time_info = TIME_OFFSETS[time_idx]
        action = context.user_data.get("pending_action", "storm")
        target = context.user_data.get("geo")
        
        if not target:
            await query.answer("Сначала укажи город через /storm", show_alert=True)
            return
            
        lat, lon, city = target
        
        pending_msg_id = context.user_data.get("pending_message_id")
        if pending_msg_id:
            try:
                await context.bot.delete_message(chat_id=query.message.chat.id, message_id=pending_msg_id)
            except Exception:
                pass
            context.user_data.pop("pending_message_id", None)
        
        calc_msg = await query.message.reply_text(f"⏳ Считаю для *{md(city)}* на {time_info['label']}...", parse_mode="Markdown")
        
        if action == "storm":
            await _send_storm_report(query.message, lat, lon, city, time_info["hours"], time_info["label"], context)
        elif action == "skewt":
            await _send_skewt(query.message, lat, lon, city, time_info["hours"], time_info["label"], context)
            
        try:
            await context.bot.delete_message(chat_id=query.message.chat.id, message_id=calc_msg.message_id)
        except Exception:
            pass
        return

    if query.data.startswith("stn:"):
        mid = query.message.message_id
        ctx = get_skewt_ctx(query.message.chat.id, mid)
        if not ctx:
            await query.answer("Сессия устарела. Отправь /skewt заново.", show_alert=True)
            return
            
        lat, lon, city, current, hourly, probe, time_label, report = ctx
        markup = _build_stations_markup(probe)
        
        if query.data == "stn:__model__":
            chart = await asyncio.to_thread(
                build_skewt_chart, current, hourly, None, None, city, time_label, report=report
            )
            await query.edit_message_media(
                InputMediaPhoto(chart, caption=f"📈 Skew-T: модель {city} ({time_label})"), 
                reply_markup=markup
            )
            return
            
        wmo = query.data[4:]
        meta = next((s for s in probe if s["wmo"] == wmo), None)
        if meta is None:
            await query.answer("Станция не найдена в этой сессии.", show_alert=True)
            return
        try:
            df, rt = await asyncio.wait_for(
                asyncio.to_thread(get_sounding_by_wmo, wmo),
                timeout=SOUNDING_PROBE_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.warning(f"Wyoming не ответил за {SOUNDING_PROBE_TIMEOUT} с (wmo={wmo})")
            await query.answer("Зонд не ответил вовремя. Попробуй позже.", show_alert=True)
            return
        
        if df is None:
            await query.answer("Нет данных на этой станции.", show_alert=True)
            return
            
        station_name = meta["name"] if meta else "Зонд"
        chart = await asyncio.to_thread(
            build_skewt_chart, current, hourly, df, rt, city, time_label,
            station_name=station_name, report=report
        )
        cap = f"📈 Skew-T: {city} ({time_label}) + зонд {station_name} (~{meta['dist_km']} км)" if meta else f"📈 Skew-T: {city} ({time_label}) + зонд"
        
        await query.edit_message_media(InputMediaPhoto(chart, caption=cap), reply_markup=markup)
        return

    target = context.user_data.get("geo")
    if not target and query.data in ["refresh", "skewt", "ai"]:
        await query.answer("Сначала укажи город через /storm", show_alert=True)
        return
        
    if target:
        lat, lon, city = target

        if query.data == "refresh":
            await _send_storm_report(query.message, lat, lon, city, 0, "Сейчас", context)
            return
            
        if query.data == "skewt":
            context.user_data["pending_action"] = "skewt"
            await _send_skewt(query.message, lat, lon, city, 0, "Сейчас", context)
            return
            
        if query.data == "ai":
            await query.message.reply_text("🤖 Анализирую...")
            await _send_ai_analysis(query.message, context)
            return
            
        if query.data == "change_city":
            context.user_data.pop("geo", None)
            await query.message.reply_text("📍 Укажи новый город:\n`/storm Москва`", parse_mode="Markdown")
            return

    if target:
        lat, lon, city = target
        if query.data == "storm":
            msg = await query.message.reply_text(f"⏳ Выбери время для *{md(city)}*:", parse_mode="Markdown", reply_markup=_build_time_markup())
            context.user_data["pending_action"] = "storm"
            context.user_data["pending_message_id"] = msg.message_id
        elif query.data == "skewt":
            msg = await query.message.reply_text(f"⏳ Выбери время для *{md(city)}*:", parse_mode="Markdown", reply_markup=_build_time_markup())
            context.user_data["pending_action"] = "skewt"
            context.user_data["pending_message_id"] = msg.message_id
        elif query.data == "radar":
            await query.message.reply_text(f"📡 Загружаю радар для *{md(city)}*...", parse_mode="Markdown")
            await _send_radar(query.message, lat, lon, city, context)
        elif query.data == "help":
            await help_command(update, context)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    if isinstance(context.error, (TimedOut, NetworkError)):
        logger.warning(f"Сетевая ошибка: {context.error}")
    else:
        logger.error(f"Ошибка: {context.error}", exc_info=context.error)

_ALERT_CHECK_INTERVAL_SECONDS = 30 * 60


async def alerts_background_task(context: ContextTypes.DEFAULT_TYPE):
    """Каждые 30 минут проверяет опасные условия для всех подписок и рассылает алерты."""
    try:
        alerts = get_all_alerts()
    except Exception as e:
        logger.error(f"Alert job: не удалось получить список подписок: {e}")
        return

    groups = group_alerts_by_location(alerts)
    for _, group in groups.items():
        lat, lon = group[0]["lat"], group[0]["lon"]
        try:
            current_data, pressure_data, _ = await asyncio.wait_for(
                asyncio.to_thread(_get_fused_current_data, lat, lon, 0),
                timeout=IO_TIMEOUT,
            )
            regime = get_regime(lat, datetime.now(timezone.utc).month)
            report = build_storm_report(current_data, pressure_data, regime=regime)
            danger = check_dangerous_conditions(report, regime=regime)
        except asyncio.TimeoutError:
            logger.warning(f"Alert job: данные не получены за {IO_TIMEOUT} с для ({lat}, {lon})")
            continue
        except Exception as e:
            logger.warning(f"Alert job failed for ({lat}, {lon}): {e}")
            continue

        if not danger:
            continue

        for alert in group:
            user_id, city = alert["user_id"], alert["city"]
            try:
                if not can_send_alert(user_id, city):
                    continue
                await context.bot.send_message(
                    chat_id=user_id,
                    text=(
                        f"{danger}\n\n"
                        f"📍 *{md(city)}* — {datetime.now(timezone.utc).strftime('%H:%M UTC')}\n"
                        f"Подробнее: `/storm {md(city)}`"
                    ),
                    parse_mode="Markdown",
                )
                record_alert_sent(user_id, city)
            except Forbidden:
                # User blocked the bot: drop the dead subscription. Temporary
                # network errors must NOT remove subscriptions.
                try:
                    remove_alert(user_id, city)
                    logger.info(
                        f"Subscription removed: user={user_id} blocked bot (city={city})"
                    )
                except Exception as e:
                    logger.error("remove_alert failed: %s", redact_secrets(e))
                continue
            except Exception as e:
                logger.warning(f"Alert job failed for {city} (user {user_id}): {e}")
        # Пауза между уникальными локациями, чтобы не упереться в rate-limit внешних API
        await asyncio.sleep(2)

    # Housekeeping: only rows older than 30 days, so the 2-hour cooldown is safe.
    try:
        prune_history()
    except Exception as e:
        logger.warning(f"Alert job: prune_history failed: {e}")


def build_application() -> Application:
    os.makedirs("data", exist_ok=True)
    persistence_path = "data/persistence.pkl"
    try:
        with open(persistence_path, "xb") as persistence_file:
            pickle.dump({
                "user_data": {},
                "chat_data": {},
                "bot_data": {},
                "callback_data": None,
                "conversations": {},
            }, persistence_file, protocol=pickle.HIGHEST_PROTOCOL)
    except FileExistsError:
        pass
    persistence = AtomicPicklePersistence(filepath=persistence_path)
    request_config = HTTPXRequest(read_timeout=30, write_timeout=30, connect_timeout=15, pool_timeout=15)
    
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .persistence(persistence)
        .get_updates_request(request_config)
        .request(request_config)
        # п.6b audit: updates stay sequential on purpose. Enabling this requires
        # locks around module-level caches (bot._skewt_ctx, rate_limiter._rate_limits,
        # sounding_api/geocoding/radar caches), an atomic rate-limit check, and a
        # concurrency-safe persistence; PicklePersistence + to_thread HTTP would
        # otherwise race (lost user_data updates, double-limited buttons).
        .concurrent_updates(False)
        .build()
    )
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("storm", storm_command))
    application.add_handler(CommandHandler("skewt", skewt_command))
    application.add_handler(CommandHandler("radar", radar_command))
    application.add_handler(CommandHandler("ai", ai_command))
    application.add_handler(CommandHandler("alert", alert_command))
    application.add_handler(CommandHandler("unalert", unalert_command))
    application.add_handler(CommandHandler("alerts", alerts_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_error_handler(error_handler)

    # Фоновая задача рассылки алертов (подписки /alert)
    application.job_queue.run_repeating(
        alerts_background_task,
        interval=_ALERT_CHECK_INTERVAL_SECONDS,
        first=60,
        name="alerts_check",
    )

    return application

def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "BOT_TOKEN не найден. Создай файл .env на основе .env.example "
            "и укажи токен бота."
        )
    logger.info("Запуск метеобота...")
    MIN_UPTIME_SECONDS = 30
    MAX_CONSECUTIVE_FAST_FAILURES = 5
    consecutive_fast_failures = 0
    
    while True:
        start_time = time.time()
        try:
            application = build_application()
            logger.info("Бот запущен и готов к работе.")
            application.run_polling(drop_pending_updates=True)
            break
        except KeyboardInterrupt:
            break
        except Exception as e:
            uptime = time.time() - start_time
            if uptime < MIN_UPTIME_SECONDS:
                consecutive_fast_failures += 1
            else:
                consecutive_fast_failures = 0
                
            if consecutive_fast_failures >= MAX_CONSECUTIVE_FAST_FAILURES:
                logger.critical(f"Детерминированный баг: {e}", exc_info=True)
                sys.exit(1)
                
            logger.critical(f"Сбой: {e}. Рестарт через {RESTART_DELAY_SECONDS} сек...", exc_info=True)
            time.sleep(RESTART_DELAY_SECONDS)

if __name__ == "__main__":
    main()