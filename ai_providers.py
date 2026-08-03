import logging
import time

logger = logging.getLogger(__name__)


class BaseProvider:
    name = "base"
    
    def is_available(self) -> bool:
        return False
    
    def generate(self, prompt: str) -> str:
        raise NotImplementedError


class OpenAICompatProvider(BaseProvider):
    def __init__(self, name, api_key, base_url, model, extra_headers=None):
        self.name = name
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
        self.extra_headers = extra_headers or {}
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
    
    def __init__(self, api_key, model):
        self.api_key = api_key
        self.model = model or "gemini-2.0-flash"
        self._client = None
    
    def is_available(self) -> bool:
        return bool(self.api_key)
    
    def _get_client(self):
        if self._client is None:
            from google import genai
            self._client = genai.Client(api_key=self.api_key)
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
    name = "Local"
    
    def is_available(self) -> bool:
        return True
    
    def generate(self, prompt: str) -> str:
        data = _parse_prompt_data(prompt)
        city = _parse_city(prompt)
        return _rule_based_analysis(data, city)


def _parse_city(prompt: str) -> str:
    for line in prompt.splitlines():
        if "для " in line and "." in line:
            try:
                return line.split("для ", 1)[1].split(".")[0].strip()
            except Exception:
                pass
    return "города"


def _parse_prompt_data(prompt: str) -> dict:
    import re
    
    def grab(key):
        m = re.search(rf"{key}:\s*([-0-9.]+)", prompt)
        try:
            return float(m.group(1)) if m else 0.0
        except Exception:
            return 0.0
    
    return {
        "cape": grab("CAPE"),
        "cape_type": "SB",
        "cin": grab("CIN"),
        "lcl": grab("LCL"),
        "k": grab("K-Index"),
        "tt": grab("Total Totals"),
        "li": grab("Lifted Index"),
        "si": grab("Showalter"),
        "sweat": grab("SWEAT"),
        "shear06": grab("Сдвиг 0-6 км"),
        "shear03": grab("Сдвиг 0-3 км"),
        "srh": grab("SRH"),
        "ehi": grab("EHI"),
        "brn": grab("BRN"),
        "stp": grab("STP"),
        "scp": grab("SCP"),
        "dcape": grab("DCAPE"),
    }


def _rule_based_analysis(d: dict, city: str) -> str:
    cape, k, li = d["cape"], d["k"], d["li"]
    shear06, srh, ehi = d["shear06"], d["srh"], d["ehi"]
    tt, sweat = d["tt"], d["sweat"]
    stp, scp, dcape = d["stp"], d["scp"], d["dcape"]
    
    if stp >= 2.0:
        conv_type = "торнадо-опасные суперячейки"
        detail = "STP ≥ 2.0 указывает на высокий потенциал значительных торнадо (EF1-EF3)"
    elif scp >= 4.0 and cape >= 1000:
        conv_type = "суперячейки"
        detail = "SCP ≥ 4.0 с высоким CAPE создаёт условия для организованных суперячеек"
    elif cape >= 1000 and shear06 >= 18 and srh >= 150:
        conv_type = "суперячейки"
        detail = "сочетание высокой нестабильности, сильного сдвига и заметной спиральности"
    elif cape >= 800 and shear06 >= 12:
        conv_type = "мультиячейковые грозы"
        detail = "достаточная нестабильность при умеренном сдвиге favoreт кластерную организацию"
    elif cape >= 400 and k >= 25:
        conv_type = "одиночные ячейки"
        detail = "нестабильность есть, но сдвига недостаточно для организации"
    elif cape >= 100 or k >= 20:
        conv_type = "слабая/изолированная конвекция"
        detail = "условия пограничные, грозы если и будут, то точечные и слабые"
    else:
        conv_type = "конвекция маловероятна"
        detail = "недостаточно ни нестабильности, ни триггеров для развития гроз"
    
    if cape >= 2500:
        instab = "экстремальная нестабильность (CAPE очень высок)"
    elif cape >= 1000:
        instab = "сильная нестабильность"
    elif cape >= 400:
        instab = "умеренная нестабильность"
    elif cape >= 100:
        instab = "слабая нестабильность"
    else:
        instab = "атмосфера стабильна"
    
    if shear06 >= 20:
        shear_desc = "сдвиг ветра сильный — благоприятен для суперячеек"
    elif shear06 >= 12:
        shear_desc = "сдвиг умеренный — поддерживает мультиячейковые структуры"
    elif shear06 >= 6:
        shear_desc = "сдвиг слабый — конвекция будет разрозненной"
    else:
        shear_desc = "сдвиг минимальный — организация маловероятна"
    
    hazards = []
    if stp >= 1.0:
        hazards.append("🌪 торнадо")
    if dcape >= 1000:
        hazards.append("💨 шквалы/микропорывы")
    if cape >= 2500 and shear06 >= 15:
        hazards.append("🧊 град")
    if not hazards:
        hazards.append("значимые опасные явления маловероятны")
    
    contradictions = []
    if cape >= 1000 and shear06 < 8:
        contradictions.append("высокий CAPE при слабом сдвиге → суперячейки маловероятны")
    if cape < 300 and shear06 >= 18:
        contradictions.append("сильный сдвиг при низкой нестабильности → мощная конвекция не разовьётся")
    if stp >= 2.0 and srh < 100:
        contradictions.append("высокий STP но низкий SRH → возможна переоценка торнадо-потенциала")
    if k >= 30 and cape < 200:
        contradictions.append("K-Index высок, но CAPE мал → влага есть, а энергии нет")
    
    if contradictions:
        consistency = "Обнаружены противоречия: " + "; ".join(contradictions) + "."
    else:
        consistency = "Индексы согласованы между собой."
    
    analysis = (
        f"Анализ:\n"
        f"Для {city} наиболее вероятный характер конвекции — {conv_type}. "
        f"{detail.capitalize()}. По термодинамике: {instab} "
        f"(CAPE={cape:.0f} Дж/кг, LI={li:.1f}, K={k:.1f}, TT={tt:.1f}). "
        f"По динамике: {shear_desc} (сдвиг 0-6км={shear06:.1f} м/с, SRH={srh:.0f}). "
        f"Опасные явления: {', '.join(hazards)}. "
        f"Композитные индексы: STP={stp:.1f}, SCP={scp:.1f}, DCAPE={dcape:.0f} Дж/кг."
    )
    
    return analysis + "\n\n⚠️ Проверка согласованности:\n" + consistency + \
        "\n\n_Примечание: анализ выполнен локальным алгоритмом (AI-провайдеры временно недоступны)._"


def build_provider_chain():
    from config import (
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
        chain.append(OpenAICompatProvider(
            name="Groq-8B",
            api_key=GROQ_API_KEY,
            base_url="https://api.groq.com/openai/v1",
            model="llama-3.1-8b-instant",
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