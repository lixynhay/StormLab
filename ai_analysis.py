import logging
from ai_providers import build_provider_chain

logger = logging.getLogger(__name__)

_chain = build_provider_chain()
logger.info(f"AI-цепочка провайдеров: {[p.name for p in _chain]}")


def _build_prompt(report: dict, city: str, skewt_ctx: str) -> str:
    return (
        f"Ты — профессиональный метеоролог-аналитик, специализирующийся на "
        f"конвективной метеорологии. Ниже — рассчитанные грозовые индексы для {city}. "
        f"Числа посчитаны термодинамическими формулами, не пересчитывай их.\n\n"
        f"ВАЖНО: Используй ТОЛЬКО правильную русскую терминологию: одиночные ячейки, "
        f"мультиячейковые грозы, суперячейки, шквалистые линии. "
        f"Никогда не используй слово 'многоклеточные'.\n\n"
        f"Ответь строго в два раздела без markdown-разметки:\n\n"
        f"Анализ:\n(до 200 слов) Дай развёрнутый анализ атмосферы:\n"
        f"1. Тип ожидаемых гроз и почему\n"
        f"2. Вероятность опасных явлений (торнадо, град, шквалы, микропорывы)\n"
        f"3. Пробьёт ли конвекция крышку (CIN)\n"
        f"4. Рекомендации для шторм-чейзеров\n"
        f"Не упрощай терминологию, используй композитные индексы (STP, SCP, DCAPE, MCSM).\n\n"
        f"⚠️ Проверка согласованности:\n(до 80 слов) Проверь индексы на физические "
        f"противоречия (высокий CAPE при слабом сдвиге = одиночные ячейки, а не суперячейки; "
        f"сильный сдвиг при низком CAPE = нет мощной конвекции; STP высокий но SRH низкий = артефакт). "
        f"Если противоречий нет — напиши одной фразой 'Индексы согласованы между собой'.\n\n"
        f"Данные:\n"
        f"CAPE ({report.get('cape_type', 'SB')}): {report.get('cape')} Дж/кг | CIN: {abs(report.get('cin', 0))} Дж/кг | LCL: {report.get('lcl')} гПа\n"
        f"K-Index: {report.get('k_index')} | Total Totals: {report.get('total_totals')} | Lifted Index: {report.get('lifted_index')}\n"
        f"Showalter: {report.get('showalter_index')} | SWEAT: {report.get('sweat_index')} | Mid-layer spread: {report.get('mid_layer_spread')}°C\n"
        f"Сдвиг 0-6 км: {report.get('bulk_shear_06')} м/с | Сдвиг 0-3 км: {report.get('bulk_shear_03')} м/с\n"
        f"SRH: {report.get('srh')} ({report.get('srh_method')}) | EHI: {report.get('ehi')} | BRN: {report.get('brn')}\n\n"
        f"Композитные индексы:\n"
        f"🌪 STP (торнадо): {report.get('stp')} — {report.get('stp_interpretation')}\n"
        f"⚡ SCP (суперячейки): {report.get('scp')} — {report.get('scp_interpretation')}\n"
        f"💨 DCAPE (шквалы): {report.get('dcape')} Дж/кг — {report.get('dcape_interpretation')}\n"
        f"📏 MCS Maintenance: {report.get('mcsm_interpretation')}\n\n"
        f"Уровень угрозы: {report.get('threat_level')}/5\n\n"
        f"Контекст Skew-T:\n{skewt_ctx}"
    )


def generate_storm_analysis(report: dict, city: str, skewt_ctx: str) -> str:
    prompt = _build_prompt(report, city, skewt_ctx)
    
    for provider in _chain:
        if not provider.is_available():
            continue
        try:
            result = provider.generate(prompt)
            logger.info(f"AI-анализ успешно получен от {provider.name}")
            return result
        except Exception as e:
            logger.warning(f"[{provider.name}] не сработал: {e}. Пробуем следующий.")
            continue
    
    return "❌ Все AI-провайдеры недоступны, и локальный анализ не сработал."