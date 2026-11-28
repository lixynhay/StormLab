"""Small text-safety helpers shared by bot/REST logging and message rendering.

No network, no Telegram dependency: safe to import from any layer.
"""
import re

_SECRET_PARAM_RE = re.compile(
    r"(?i)\b(appid|api[_-]?key|apikey|key|token)=([^&\s]+)"
)
_HEADER_SECRET_RE = re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)(\S+)")
_PWD_RE = re.compile(r"(?i)\b(password|secret|client[_-]?secret)=([^&\s]+)")
_MARKDOWN_SPECIAL_RE = re.compile(r"([\\_*\[\]()~`>#+\-=|{}.!])")


def redact_secrets(text) -> str:
    """Remove secret values from logs/LLM text. ``None`` renders as an empty string."""
    if text is None:
        return ""
    value = str(text)
    for pattern in (_SECRET_PARAM_RE, _HEADER_SECRET_RE, _PWD_RE):
        value = pattern.sub("***REDACTED***", value)
    return value


def escape_markdown(text) -> str:
    """Escape Telegram legacy-Markdown specials in dynamic text (V1)."""
    return _MARKDOWN_SPECIAL_RE.sub(r"\\\1", str(text))
