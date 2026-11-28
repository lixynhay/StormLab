import logging

from stormlab.config import GEMINI_API_TIMEOUT, LLM_REQUEST_TIMEOUT
from stormlab.core.season_regime import thresholds_for

logger = logging.getLogger(__name__)


class BaseProvider:
    name = "base"
    
    def is_available(self) -> bool:
        return False
    
    def generate(self, prompt: str, **kwargs) -> str:
        """Default: prompt-only. Structured kwargs are ignored by LLM providers."""
        raise NotImplementedError


class OpenAICompatProvider(BaseProvider):
    def __init__(self, name, api_key, base_url, model, extra_headers=None,
                 timeout=None, max_retries=0):
        self.name = name
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.extra_headers = extra_headers or {}
        self.timeout = timeout or LLM_REQUEST_TIMEOUT
        self.max_retries = max_retries
        self._client = None
    
    def is_available(self) -> bool:
        return bool(self.api_key)
    
    def _get_client(self):
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                default_headers=self.extra_headers,
                timeout=self.timeout,
                max_retries=self.max_retries,
            )
        return self._client
    
    def generate(self, prompt: str) -> str:
        client = self._get_client()
        logger.info(f"[{self.name}] запрос к модели {self.model}")
        response = client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=1000,
        )
        text = response.choices[0].message.content
        if not text:
            raise ValueError("Пустой ответ от модели")
        return text.strip()


class GeminiProvider(BaseProvider):
    name = "Gemini"
    
    def __init__(self, api_key, model, timeout=None):
        self.api_key = api_key
        self.model = model or "gemini-2.0-flash"
        self.timeout = timeout or GEMINI_API_TIMEOUT
        self._client = None
    
    def is_available(self) -> bool:
        return bool(self.api_key)
    
    def _get_client(self):
        if self._client is None:
            from google import genai
            from google.genai import types
            self._client = genai.Client(
                api_key=self.api_key,
                http_options=types.HttpOptions(timeout=int(self.timeout * 1000)),
            )
        return self._client
    
    def generate(self, prompt: str) -> str:
        from google.genai import types
        client = self._get_client()
        logger.info(f"[Gemini] запрос к модели {self.model}")
        response = client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.2, max_output_tokens=1000),
        )
        if response.prompt_feedback and response.prompt_feedback.block_reason:
            raise ValueError(f"Запрос заблокирован фильтрами: {response.prompt_feedback.block_reason}")
        if not response.text:
            raise ValueError("Пустой ответ от Gemini")
        return response.text.strip()


class LocalProvider(BaseProvider):
    """Deterministic fallback: reads the structured report, never scrapes the prompt.

    The old regex scraper produced silent zeros for ``CAPE (SB)``, ``STP
    (торнадо)``, ``SCP (суперячейки)`` and ``DCAPE (шквалы)`` because ``grab``
    looked for bare ``KEY:`` labels. Structured fields from ``build_storm_report``
    are the single source of truth; the prompt is kept only as a compatibility
    argument for the provider chain.
    """

    name = "Local"
    accepts_report = True  # call-site signal in ai_analysis.generate_storm_analysis

    def is_available(self) -> bool:
        return True

    def generate(self, prompt: str = "", report: dict = None, city: str = None, **kwargs) -> str:
        if not report:
            # Noisy fallback: never silently degrade to zeros / warm.
            logger.warning(
                "LocalProvider: структурированный report не передан — "
                "скрейп промпта отключён, анализ выполняется по пустому профилю"
            )
            report = {}
        return _rule_based_analysis(report, city or "города")


def _cap(text: str) -> str:
    """Capitalize the first letter without lowercasing CAPE/STP/SCP acronyms."""
    return text[:1].upper() + text[1:] if text else text


def _num(value) -> float:
    try:
        return float(value) if value is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _nd(value, spec: str = ".1f") -> str:
    """Render an optional number as «н/д» — never coerce missing data to 0.0.

    Effective composites (stp_eff/scp_eff) and dcape legitimately have no value
    on real profiles; substituting 0 would be a new silent-zero, not a guard.
    """
    if value is None:
        return "н/д"
    try:
        return f"{float(value):{spec}}"
    except (TypeError, ValueError):
        return "н/д"


def _rule_based_analysis(report: dict, city: str) -> str:
    """Fallback analysis built from the structured report + seasonal thresholds.

    All season-sensitive numbers come from ``season_regime.thresholds_for``;
    narratives already produced by ``build_storm_report`` (batch 2.3) are reused
    verbatim. Domain cut-offs that remain here are cited in the batch-2.5/3
    verification table (SPC help pages; DCAPE > 1000 J/kg).
    """
    regime = report.get("regime", "warm")
    th = thresholds_for(regime)

    cape = _num(report.get("cape"))
    cin = abs(_num(report.get("cin")))
    shear06 = _num(report.get("bulk_shear_06"))
    srh = _num(report.get("srh"))
    dcape = _num(report.get("dcape"))
    li = _num(report.get("lifted_index"))
    k_index = _num(report.get("k_index"))
    tt = _num(report.get("total_totals"))
    lcl_height = report.get("lcl_height_m")

    # Raw optional values are kept separately from the guarded float copies:
    # a missing effective composite must be rendered as «н/д», not as 0.0.
    dcape_raw = report.get("dcape")
    stp_eff = report.get("stp_eff")
    scp_eff = report.get("scp_eff")
    ehi_raw = report.get("ehi")
    brn_raw = report.get("brn")
    sweat_raw = report.get("sweat_index")
    si_raw = report.get("showalter_index")
    stp_fixed = report.get("stp")
    scp_fixed = report.get("scp")
    lcl_raw = report.get("lcl")

    cape_ok = cape >= th["cape_min"]
    shear_ok = shear06 >= th["shear06_min"]

    cape_text = report.get("cape_interpretation") or (
        "конвекция маловероятна" if cape < th["cape_min"] else "нестабильность выше сезонного порога"
    )
    cin_text = report.get("cin_interpretation") or (
        "крышка слабая" if cin <= th["cin_max"] else "крышка сильная"
    )
    lcl_text = report.get("lcl_interpretation") or (
        "н/д" if lcl_height is None else (
            "низкий LCL" if lcl_height <= th["lcl_max"] else "высокий LCL"
        )
    )
    shear_text = report.get("shear_interpretation") or (
        "сдвиг ветра" if shear_ok else "сдвиг ниже сезонного порога"
    )
    stp_text = report.get("stp_interpretation") or ""
    scp_text = report.get("scp_interpretation") or ""

    if cape <= 0:
        conv_type = "конвекция маловероятна"
        detail = "нет доступной нестабильности (CAPE = 0) — грозы не ожидаются"
    elif regime == "cool":
        if cape_ok and shear_ok:
            conv_type = "зимняя конвекция (thundersnow/snow-squall)"
            detail = (
                "CAPE и сдвиг достигли порогов холодного сезона "
                f"(CAPE ≥ {th['cape_min']}, сдвиг ≥ {th['shear06_min']} м/с) — "
                "прокси thundersnow/snow-squall, не суперячейки"
            )
        elif cape_ok or shear_ok:
            conv_type = "слабая зимняя конвекция / снежные заряды"
            detail = "только один из сезонных порогов достигнут — возможны снежные заряды"
        else:
            conv_type = "зимняя конвекция маловероятна"
            detail = "ни CAPE, ни сдвиг не достигли порогов холодного сезона"
    elif cape_ok and shear_ok:
        conv_type = "организованные грозы (суперячейки/шквалистые линии)"
        detail = (
            f"CAPE ≥ {th['cape_min']} Дж/кг и сдвиг ≥ {th['shear06_min']} м/с — "
            "среда благоприятна для organized convection"
        )
    elif cape_ok:
        conv_type = "одиночные/мультиячейковые грозы"
        detail = "нестабильность есть, но сдвиг ниже сезонного порога — организация ограничена"
    else:
        conv_type = "слабая/изолированная конвекция"
        detail = "CAPE ниже сезонного порога — грозы если и будут, то точечные и слабые"

    hazards = []
    if cape > 0:
        if regime == "cool" and cape_ok and shear_ok:
            # NWS glossary: snow squall = intense short-duration snow with strong
            # gusty winds and POSSIBLE lightning. "Thundersnow" is kept as the
            # project's conventional shorthand (NWS glossary has no such entry).
            hazards.append("❄️ thundersnow / snow-squall")
        if dcape >= 1000:
            # SPC help/params2.html: DCAPE > 1000 J/kg -> strong downdrafts /
            # damaging outflow winds.
            hazards.append(
                "💨 шквал/микропорыв" if regime == "warm" else "💨 снежный шквал/микропорыв"
            )
        if stp_text and "торнадо" in stp_text.lower() and regime == "warm":
            hazards.append("🌪 торнадо (по STP)")
        if scp_text and "суперячей" in scp_text.lower() and regime == "warm":
            hazards.append("⚡ суперячейки (по SCP)")
    if not hazards:
        hazards.append(
            "значимые зимние опасные явления маловероятны" if regime == "cool"
            else "значимые опасные явления маловероятны"
        )

    contradictions = []
    if cape >= th["cape_min"] and shear06 < th["shear06_min"]:
        contradictions.append(
            f"CAPE ≥ {th['cape_min']}, но сдвиг < {th['shear06_min']} м/с — организация слабая"
        )
    if shear06 >= th["shear06_min"] and cape < th["cape_min"]:
        contradictions.append(
            f"сдвиг ≥ {th['shear06_min']} м/с, но CAPE < {th['cape_min']} — энергии недостаточно"
        )
    if cin > th["cin_max"]:
        contradictions.append(
            f"CIN {cin:.0f} Дж/кг выше порога {th['cin_max']} — крышка подавит конвекцию"
        )
    if lcl_height is not None and lcl_height > th["lcl_max"]:
        contradictions.append(
            f"LCL {int(lcl_height)} м выше порога {th['lcl_max']} м — подъём затруднён"
        )
    consistency = (
        "Обнаружены противоречия: " + "; ".join(contradictions) + "."
        if contradictions
        else "Индексы согласованы между собой."
    )

    analysis = (
        f"Анализ:\n"
        f"Для {city} наиболее вероятный характер конвекции — {conv_type}. "
        f"{_cap(detail)}. "
        f"По термодинамике: {cape_text} "
        f"(CAPE={cape:.0f} Дж/кг, LI={li:.1f}, K={k_index:.1f}, TT={tt:.1f}); "
        f"крышка: {cin_text} (CIN={cin:.0f} Дж/кг); подъём: {lcl_text} "
        f"(LCL={_nd(lcl_raw, '.0f')} гПа, высота="
        f"{'н/д' if lcl_height is None else str(int(lcl_height))} м). "
        f"По динамике: {shear_text} (сдвиг 0-6км={shear06:.1f} м/с, SRH={srh:.0f}). "
        f"Опасные явления: {', '.join(hazards)}. "
        f"Композитные индексы: STP(fixed)={_nd(stp_fixed)}, "
        f"SCP(fixed)={_nd(scp_fixed)}, "
        f"STP(effective)={_nd(stp_eff)}, SCP(effective)={_nd(scp_eff)}, "
        f"EHI={_nd(ehi_raw)}, BRN={_nd(brn_raw)}, "
        f"DCAPE={_nd(dcape_raw, '.0f')} Дж/кг, "
        f"SWEAT={_nd(sweat_raw, '.0f')}, SI={_nd(si_raw)}. "
        f"Сезонный режим: {regime}."
    )

    return analysis + "\n\n⚠️ Проверка согласованности:\n" + consistency + \
        "\n\n_Примечание: анализ выполнен локальным алгоритмом (AI-провайдеры временно недоступны)._"


def build_provider_chain():
    from stormlab.config import (
        GEMINI_API_KEY, GEMINI_MODEL,
        GROQ_API_KEY, OPENROUTER_API_KEY, GITHUB_TOKEN,
    )
    
    chain = []
    
    if GROQ_API_KEY:
        chain.append(OpenAICompatProvider(
            name="Groq-70B",
            api_key=GROQ_API_KEY,
            base_url="https://api.groq.com/openai/v1",
            model="llama-3.3-70b-versatile",
        ))
    
    if GITHUB_TOKEN:
        chain.append(OpenAICompatProvider(
            name="GitHub-GPT4o-mini",
            api_key=GITHUB_TOKEN,
            base_url="https://models.github.ai/inference",
            model="openai/gpt-4o-mini",
            extra_headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        ))
    
    if GEMINI_API_KEY:
        chain.append(GeminiProvider(GEMINI_API_KEY, GEMINI_MODEL))
    
    if OPENROUTER_API_KEY:
        chain.append(OpenAICompatProvider(
            name="OpenRouter",
            api_key=OPENROUTER_API_KEY,
            base_url="https://openrouter.ai/api/v1",
            model="meta-llama/llama-3.3-70b-instruct:free",
            extra_headers={
                "HTTP-Referer": "https://github.com/lixynhay/StormLab",
                "X-Title": "StormLab MeteoBot",
            },
        ))
    
    chain.append(LocalProvider())
    
    return chain