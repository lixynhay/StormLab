"""Text-safety helpers: secret redaction + legacy Markdown escaping."""
from core.text_safety import escape_markdown, redact_secrets


def test_redact_query_param():
    text = "GET /weather?lat=1&appid=SECRET123&units=metric"
    out = redact_secrets(text)
    assert "SECRET123" not in out
    assert "***REDACTED***" in out
    assert "appid=" not in out


def test_redact_bearer_header():
    text = "Authorization: Bearer ABCDEF123456"
    out = redact_secrets(text)
    assert "ABCDEF123456" not in out
    assert "***REDACTED***" in out
    assert "Bearer" not in out


def test_redact_password_and_none():
    assert "hunter2" not in redact_secrets("password=hunter2&user=ivan")
    assert "s3cr3t" not in redact_secrets("client_secret=s3cr3t")
    assert redact_secrets(None) == ""


def test_escape_markdown_dynamic_text():
    out = escape_markdown("Москва_тест*[x]`")
    for escaped in (r"\_", r"\*", r"\[", r"\]", "\\`"):
        assert escaped in out


def test_escape_markdown_leaves_plain_labels_alone():
    assert escape_markdown("🌩 STP: ") == "🌩 STP: "
