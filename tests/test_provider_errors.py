import httpx
import pytest

from skill.wndr_stickers.src import imagegen

GEMINI_KEY = "AIzaSyNOT_A_REAL_KEY_0123456789"


def test_provider_error_body_is_not_persistable_in_exception():
    secretish_body = "request payload with private context"
    response = httpx.Response(429, text=secretish_body)
    with pytest.raises(imagegen.ProviderUnavailable) as caught:
        imagegen._raise_for_soft_failure(response, "provider")
    assert "HTTP 429" in str(caught.value)
    assert secretish_body not in str(caught.value)


def test_gemini_sends_key_as_header_not_in_url():
    """Ключ в query утекал бы в текст httpx-ошибки, а оттуда в лог и в SQLite."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["header"] = request.headers.get("x-goog-api-key")
        return httpx.Response(200, json={"candidates": []})

    transport = httpx.MockTransport(handler)
    original = imagegen._client
    imagegen._client = lambda proxy: httpx.Client(transport=transport)
    try:
        with pytest.raises(imagegen.ImageGenerationError):
            imagegen.generate_gemini(
                "prompt", _png(), api_key=GEMINI_KEY, model="m"
            )
    finally:
        imagegen._client = original

    assert seen["header"] == GEMINI_KEY
    assert GEMINI_KEY not in seen["url"]
    assert "key=" not in seen["url"]


def test_httpx_status_error_text_is_redacted_before_it_is_stored():
    """str(HTTPStatusError) содержит полный URL — он не должен нести секрет."""
    request = httpx.Request(
        "POST",
        f"https://generativelanguage.googleapis.com/v1beta/models/m:x?key={GEMINI_KEY}",
    )
    with pytest.raises(httpx.HTTPStatusError) as caught:
        httpx.Response(400, request=request).raise_for_status()

    redacted = imagegen.redact(str(caught.value))
    assert GEMINI_KEY not in redacted
    assert "key=<redacted>" in redacted


@pytest.mark.parametrize(
    "raw",
    [
        "Authorization: Bearer NOT-A-REAL-TOKEN-FOR-TESTS",
        "token=NOT-A-REAL-TOKEN-FOR-TESTS",
        "api_key=NOT-A-REAL-TOKEN-FOR-TESTS",
        "https://user:NOT-A-REAL-PASSWORD@proxy.internal:8080 refused",
    ],
)
def test_redact_removes_every_known_secret_shape(raw):
    # Значения намеренно нечитаемы как секреты: иначе сканеры вроде gitleaks
    # помечают собственные тесты как утечку и прячут настоящие находки в шуме.
    cleaned = imagegen.redact(raw)
    assert "NOT-A-REAL-TOKEN-FOR-TESTS" not in cleaned
    assert "NOT-A-REAL-PASSWORD" not in cleaned


def _png():
    """Минимальный валидный PNG на диске — референс читается как байты."""
    import base64
    import tempfile
    from pathlib import Path

    data = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )
    path = Path(tempfile.mkdtemp()) / "ref.png"
    path.write_bytes(data)
    return path
