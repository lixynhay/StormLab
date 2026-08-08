import logging
import os
import sys
import time
from datetime import datetime, timezone
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, Update
from telegram.error import TimedOut, NetworkError
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler, ContextTypes, PicklePersistence,
)
from telegram.request import HTTPXRequest

from config import RESTART_DELAY_SECONDS, BOT_TOKEN
from logging_config import setup_logging
from openmeteo_api import OpenMeteoAPI
from openweathermap_api import OpenWeatherMapAPI
from data_fusion import fuse_current_weather
from storm_indices import build_storm_report, format_storm_text, build_skewt_context_for_ai
from chart_builder import build_profile_chart
from ai_analysis import generate_storm_analysis
from skewt_builder import build_skewt_chart
from sounding_api import get_sounding_by_wmo, probe_stations
from geocoding import resolve_city
from radar_api import get_latest_radar_frame
from radar_builder import build_radar_image
from rate_limiter import check_rate_limit
from alert_manager import add_alert, remove_alert, get_user_alerts

setup_logging()
logger = logging.getLogger(__name__)

weather_api = OpenMeteoAPI()
owm_api = OpenWeatherMapAPI()
_skewt_ctx = {}

TIME_OFFSETS = [
    {"label": "Сейчас", "hours": 0},
    {"label": "+3 часа", "hours": 3},
    {"label": "+6 часов", "hours": 6},
    {"label": "+12 часов", "hours": 12},
    {"label": "+24 часа", "hours": 24},
]

def _prune_ctx():
    if len(_skewt_ctx) > 200:
        keys = sorted(_skewt_ctx.keys())
        for k in keys[:50]:
            _skewt_ctx.pop(k, None)

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
    om_data = weather_api.get_current(lat, lon)
    pressure_data_raw = weather_api.get_pressure_levels(lat, lon)
    hourly_full = pressure_data_raw.get("hourly", {})
    sliced_hourly = _slice_hourly(hourly_full, time_index)
    
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

async def _resolve_target(context, message_target, args=None):
    if args:
        query = " ".join(args).strip()
        result = resolve_city(query)
        if result is None:
            await message_target.reply_text(
                f"❌ Не нашёл город «{query}». Проверь название или попробуй по-английски (например, 'Moscow')."
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
        current_data, pressure_data, source_label = _get_fused_current_data(lat, lon, time_index)
    except Exception as e:
        logger.error(f"Не удалось получить данные: {e}")
        await send_error_card(message_target, "Не удалось получить атмосферные данные.", action_callback="refresh")
        return
    
    try:
        report = build_storm_report(current_data, pressure_data)
        timestamp_str = datetime.now(timezone.utc).strftime("%H:%M UTC")
        text = format_storm_text(report, city, timestamp_str)
        text += f"\n_Время: {time_label} | Данные: {source_label}_"
    except Exception as e:
        logger.error(f"Ошибка расчёта: {e}", exc_info=True)
        await message_target.reply_text("❌ Не удалось рассчитать индексы.")
        return
    
    context.user_data["last_report"] = {
        "report": report, "city": city, "time_label": time_label,
        "current": current_data["current"], "pressure": pressure_data["hourly"]
    }
    
    chart = build_profile_chart(pressure_data, city, time_label)
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
        current_data, pressure_data, _ = _get_fused_current_data(lat, lon, time_index)
    except Exception as e:
        logger.error(f"Не удалось получить данные: {e}")
        await send_error_card(message_target, "Не удалось получить атмосферные данные.", action_callback="refresh")
        return
    
    try:
        report = build_storm_report(current_data, pressure_data)
    except Exception:
        report = None
    
    probe = probe_stations(lat, lon)
    current, hourly = current_data["current"], pressure_data["hourly"]
    chart = build_skewt_chart(current, hourly, None, None, city, time_label, report=report)
    
    if chart is None:
        await message_target.reply_text("❌ Не удалось построить Skew-T.")
        return
    
    markup = _build_stations_markup(probe) if probe else None
    caption = f"📈 Skew-T: модель Open-Meteo ({city}, {time_label})"
    caption += "\nВыбери реальный зонд 👇" if probe else "."
    
    msg = await message_target.reply_photo(photo=chart, caption=caption, reply_markup=markup, parse_mode="Markdown")
    
    context.user_data["last_skewt_messages"] = [msg.message_id]
    _skewt_ctx[msg.message_id] = (lat, lon, city, current, hourly, probe, time_label, report)
    _prune_ctx()

async def _send_radar(message_target, lat, lon, city, context):
    await message_target.reply_text(f"📡 Загружаю радар для *{city}*...", parse_mode="Markdown")
    try:
        radar_path, timestamp_utc, is_cached = get_latest_radar_frame()
        if radar_path is None:
            await message_target.reply_text(
                "📡 Радар временно недоступен.\n\n"
                "Сервер RainViewer обновляет данные. Попробуй через 10-15 минут."
            )
            return
            
        radar_image = build_radar_image(lat, lon, radar_path)
        if radar_image is None:
            await send_error_card(message_target, "Не удалось построить изображение радара.", action_callback="refresh")
            return
            
        time_str = timestamp_utc.strftime("%H:%M UTC")
        cache_note = " (кэш)" if is_cached else ""
        caption = f"📡 Радар осадков: *{city}*{cache_note}\n🕐 Данные: {time_str}\n📏 Масштаб: ~200x200 км"
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
            current_data, pressure_data, _ = _get_fused_current_data(lat, lon, 0)
            report = build_storm_report(current_data, pressure_data)
        except Exception as e:
            logger.error(f"AI analysis data fetch failed: {e}")
            await message_target.reply_text("❌ Не удалось получить данные для анализа.")
            return
            
    skewt_ctx = build_skewt_context_for_ai(report, current_data["current"], pressure_data)
    analysis = generate_storm_analysis(report, city, skewt_ctx)
    
    await message_target.reply_text(
        f"🤖 *AI-анализ ({city}, {time_label}):*\n\n{analysis}",
        parse_mode="Markdown"
    )

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

async def storm_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = await _resolve_target(context, update.message, context.args)
    if not target: return
    lat, lon, city = target
    
    if not check_rate_limit(update.effective_user.id, "storm")[0]:
        await update.message.reply_text("⏳ Подожди немного перед следующим запросом.")
        return
    
    msg = await update.message.reply_text(
        f"⏳ Выбери время прогноза для *{city}*:", 
        parse_mode="Markdown", reply_markup=_build_time_markup()
    )
    context.user_data["pending_action"] = "storm"
    context.user_data["pending_message_id"] = msg.message_id

async def skewt_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = await _resolve_target(context, update.message, context.args)
    if not target: return
    lat, lon, city = target
    
    if not check_rate_limit(update.effective_user.id, "skewt")[0]:
        await update.message.reply_text("⏳ Подожди немного перед следующим запросом.")
        return
    
    msg = await update.message.reply_text(
        f"⏳ Выбери время прогноза для *{city}*:", 
        parse_mode="Markdown", reply_markup=_build_time_markup()
    )
    context.user_data["pending_action"] = "skewt"
    context.user_data["pending_message_id"] = msg.message_id

async def radar_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = await _resolve_target(context, update.message, context.args)
    if not target: return
    lat, lon, city = target
    
    if not check_rate_limit(update.effective_user.id, "radar")[0]:
        await update.message.reply_text("⏳ Подожди немного перед следующим запросом.")
        return
        
    await _send_radar(update.message, lat, lon, city, context)

async def ai_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not check_rate_limit(update.effective_user.id, "ai")[0]:
        await update.message.reply_text("⏳ Подожди немного перед следующим AI-анализом.")
        return
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

async def alert_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = await _resolve_target(context, update.message, context.args)
    if not target: return
    lat, lon, city = target
    user_id = update.effective_user.id
    username = update.effective_user.username
    
    if add_alert(user_id, username, city, lat, lon):
        text = (f"✅ *Подписка активирована!*\n\n📍 {city}\n\n"
                "Бот будет проверять условия каждые 30 минут и предупреждать "
                "о риске организованных гроз или суперячеек.\n\n"
                f"Отписаться: `/unalert {city}`")
        await update.message.reply_text(text, parse_mode="Markdown")
    else:
        await update.message.reply_text(f"ℹ️ Подписка на {city} уже активна.")

async def unalert_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("❓ Укажи город:\n`/unalert Москва`", parse_mode="Markdown")
        return
    city = " ".join(context.args)
    if remove_alert(update.effective_user.id, city):
        await update.message.reply_text(f"✅ Подписка на {city} удалена.")
    else:
        await update.message.reply_text(f"ℹ️ Подписка на {city} не найдена.")

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

    lines = [f"📬 *Твои подписки ({len(alerts)}):*\n"]
    
    for alert in alerts:
        city = alert["city"]
        lat, lon = alert.get("lat"), alert.get("lon")
        threat = "⚪"
        if lat and lon:
            try:
                om_data = weather_api.get_current(lat, lon)
                pressure_data_raw = weather_api.get_pressure_levels(lat, lon)
                current_data = {"current": om_data["current"]}
                pressure_data_dict = {"hourly": pressure_data_raw.get("hourly", {})}
                report = build_storm_report(current_data, pressure_data_dict)
                t = report.get("threat_level", 0) or 0
                threat = ["⚪", "🟢", "🟡", "🟠", "🔴", "⚫"][min(t, 5)]
            except Exception:
                threat = "⚪"
        lines.append(f"{threat} {city}")

    lines.append("\n_Отписаться:_ `/unalert город`")
    await update.effective_message.reply_text("\n".join(lines), parse_mode="Markdown")

    lines.append("\n_Отписаться:_ `/unalert город`")
    await update.effective_message.reply_text("\n".join(lines), parse_mode="Markdown")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "alerts":
        await query.answer()
        user_id = update.effective_user.id
        alerts = get_user_alerts(user_id)
        if not alerts:
            text = "📭 У тебя нет активных подписок.\n\n"
            text += "Подписаться: `/alert Москва`"
        else:
            lines = [f"📬 *Твои подписки ({len(alerts)}):*\n"]
            for alert in alerts:
                city = alert["city"]
                lat, lon = alert.get("lat"), alert.get("lon")
                threat = "⚪"
                if lat and lon:
                    try:
                        om_data = weather_api.get_current(lat, lon)
                        pressure_data_raw = weather_api.get_pressure_levels(lat, lon)
                        current_data = {"current": om_data["current"]}
                        pressure_data_dict = {"hourly": pressure_data_raw.get("hourly", {})}
                        report = build_storm_report(current_data, pressure_data_dict)
                        t = report.get("threat_level", 0) or 0
                        threat = ["⚪", "🟢", "🟡", "🟠", "🔴", "⚫"][min(t, 5)]
                    except Exception:
                        threat = "⚪"
                lines.append(f"{threat} {city}")
            lines.append("\n_Отписаться:_ `/unalert город`")
            text = "\n".join(lines)
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
        
        calc_msg = await query.message.reply_text(f"⏳ Считаю для *{city}* на {time_info['label']}...", parse_mode="Markdown")
        
        if action == "storm":
            await _send_storm_report(query.message, lat, lon, city, time_idx, time_info["label"], context)
        elif action == "skewt":
            await _send_skewt(query.message, lat, lon, city, time_idx, time_info["label"], context)
            
        try:
            await context.bot.delete_message(chat_id=query.message.chat.id, message_id=calc_msg.message_id)
        except Exception:
            pass
        return

    if query.data.startswith("stn:"):
        mid = query.message.message_id
        ctx = _skewt_ctx.get(mid)
        if not ctx:
            await query.answer("Сессия устарела. Отправь /skewt заново.", show_alert=True)
            return
            
        lat, lon, city, current, hourly, probe, time_label, report = ctx
        markup = _build_stations_markup(probe)
        
        if query.data == "stn:__model__":
            chart = build_skewt_chart(current, hourly, None, None, city, time_label, report=report)
            await query.edit_message_media(
                InputMediaPhoto(chart, caption=f"📈 Skew-T: модель {city} ({time_label})"), 
                reply_markup=markup
            )
            return
            
        wmo = query.data[4:]
        meta = next((s for s in probe if s["wmo"] == wmo), None)
        df, rt = get_sounding_by_wmo(wmo)
        
        if df is None:
            await query.answer("Нет данных на этой станции.", show_alert=True)
            return
            
        station_name = meta["name"] if meta else "Зонд"
        chart = build_skewt_chart(current, hourly, df, rt, city, time_label, station_name=station_name, report=report)
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
            msg = await query.message.reply_text(f"⏳ Выбери время для *{city}*:", parse_mode="Markdown", reply_markup=_build_time_markup())
            context.user_data["pending_action"] = "storm"
            context.user_data["pending_message_id"] = msg.message_id
        elif query.data == "skewt":
            msg = await query.message.reply_text(f"⏳ Выбери время для *{city}*:", parse_mode="Markdown", reply_markup=_build_time_markup())
            context.user_data["pending_action"] = "skewt"
            context.user_data["pending_message_id"] = msg.message_id
        elif query.data == "radar":
            await query.message.reply_text(f"📡 Загружаю радар для *{city}*...", parse_mode="Markdown")
            await _send_radar(query.message, lat, lon, city, context)
        elif query.data == "help":
            await help_command(update, context)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    if isinstance(context.error, (TimedOut, NetworkError)):
        logger.warning(f"Сетевая ошибка: {context.error}")
    else:
        logger.error(f"Ошибка: {context.error}", exc_info=context.error)

def build_application() -> Application:
    os.makedirs("data", exist_ok=True)
    persistence = PicklePersistence(filepath="data/persistence.pkl")
    request_config = HTTPXRequest(read_timeout=30, write_timeout=30, connect_timeout=15, pool_timeout=15)
    
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .persistence(persistence)
        .get_updates_request(request_config)
        .request(request_config)
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
    
    return application

def main():
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