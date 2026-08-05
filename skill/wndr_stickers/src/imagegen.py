"""Генерация плашек. Провайдеры сменные, цепочка с автоматическим fallback.

Референсный лист прикладывается к каждому запросу картинкой — модель держит
стиль по нему, а не по описанию словами. Буквы модель не рисует вообще.

Провайдеры:
  openrouter_gpt — GPT image через OpenRouter (нужны кредиты на openrouter.ai)
  openai         — прямой api.openai.com, Responses API + tool image_generation
  gemini         — Google Gemini, работает и на бесплатном ключе
"""
from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass
from pathlib import Path

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

log = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(300.0, connect=30.0)


class ImageGenerationError(RuntimeError):
    """Провайдер не отдал картинку."""


class ProviderUnavailable(ImageGenerationError):
    """Нет ключа, кончились кредиты, отказ по квоте — есть смысл идти дальше по цепочке."""


@dataclass
class GeneratedImage:
    data: bytes
    provider: str
    model: str

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.data)
        return path


def _data_uri(image_path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(image_path.read_bytes()).decode()


def _client(proxy: str | None) -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT, proxy=proxy or None, trust_env=not proxy)


_RETRY = retry(
    retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=20),
    reraise=True,
)


def _raise_for_soft_failure(response: httpx.Response, provider: str) -> None:
    """402/429/401/403 — повод перейти к следующему провайдеру, а не падать."""
    if response.status_code in (401, 402, 403, 429):
        detail = response.text[:300]
        raise ProviderUnavailable(f"{provider}: HTTP {response.status_code} — {detail}")


# --- OpenRouter (GPT image) --------------------------------------------------
def generate_openrouter(
    prompt: str,
    reference: Path,
    *,
    api_key: str,
    model: str = "openai/gpt-5-image",
    proxy: str | None = None,
) -> GeneratedImage:
    if not api_key:
        raise ProviderUnavailable("openrouter_gpt: нет OPENROUTER_API_KEY")

    payload = {
        "model": model,
        "modalities": ["image", "text"],
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": _data_uri(reference)}},
                ],
            }
        ],
    }

    @_RETRY
    def _call() -> httpx.Response:
        with _client(proxy) as client:
            r = client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "HTTP-Referer": "https://github.com/essesum/wndr-stickers",
                    "X-Title": "WNDR stickers",
                },
                json=payload,
            )
        _raise_for_soft_failure(r, "openrouter_gpt")
        r.raise_for_status()
        return r

    body = _call().json()
    message = (body.get("choices") or [{}])[0].get("message", {})
    for image in message.get("images") or []:
        url = (image.get("image_url") or {}).get("url", "")
        if url.startswith("data:") and "base64," in url:
            return GeneratedImage(
                data=base64.b64decode(url.split("base64,", 1)[1]),
                provider="openrouter_gpt",
                model=model,
            )
    raise ImageGenerationError(f"openrouter_gpt: картинки нет в ответе — {json.dumps(body)[:400]}")


# --- OpenAI напрямую ---------------------------------------------------------
def generate_openai(
    prompt: str,
    reference: Path,
    *,
    api_key: str,
    model: str = "gpt-image-1",
    reasoning_model: str = "gpt-5.4",
    proxy: str | None = None,
) -> GeneratedImage:
    """Responses API с инструментом image_generation — умеет опираться на референс."""
    if not api_key:
        raise ProviderUnavailable("openai: нет OPENAI_API_KEY")

    payload = {
        "model": reasoning_model,
        "input": [
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_image", "image_url": _data_uri(reference)},
                ],
            }
        ],
        "tools": [{"type": "image_generation", "model": model}],
        "tool_choice": {"type": "image_generation"},
    }

    @_RETRY
    def _call() -> httpx.Response:
        with _client(proxy) as client:
            r = client.post(
                "https://api.openai.com/v1/responses",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
            )
        _raise_for_soft_failure(r, "openai")
        r.raise_for_status()
        return r

    body = _call().json()
    for item in body.get("output") or []:
        if item.get("type") == "image_generation_call" and item.get("result"):
            return GeneratedImage(
                data=base64.b64decode(item["result"]), provider="openai", model=model
            )
    raise ImageGenerationError(f"openai: картинки нет в ответе — {json.dumps(body)[:400]}")


# --- Gemini ------------------------------------------------------------------
def generate_gemini(
    prompt: str,
    reference: Path,
    *,
    api_key: str,
    model: str = "gemini-3-pro-image-preview",
    image_size: str = "2K",
    proxy: str | None = None,
) -> GeneratedImage:
    if not api_key:
        raise ProviderUnavailable("gemini: нет GEMINI_API_KEY")

    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": prompt},
                    {
                        "inline_data": {
                            "mime_type": "image/png",
                            "data": base64.b64encode(reference.read_bytes()).decode(),
                        }
                    },
                ],
            }
        ],
        "generationConfig": {
            "responseModalities": ["IMAGE", "TEXT"],
            "imageConfig": {"image_size": image_size},
        },
    }
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}"
        f":streamGenerateContent?key={api_key}"
    )

    @_RETRY
    def _call() -> httpx.Response:
        with _client(proxy) as client:
            r = client.post(url, json=payload)
        _raise_for_soft_failure(r, "gemini")
        r.raise_for_status()
        return r

    body = _call().json()
    chunks = body if isinstance(body, list) else [body]
    for chunk in chunks:
        for candidate in chunk.get("candidates") or []:
            for part in (candidate.get("content") or {}).get("parts") or []:
                inline = part.get("inlineData") or part.get("inline_data")
                if inline and inline.get("data"):
                    return GeneratedImage(
                        data=base64.b64decode(inline["data"]), provider="gemini", model=model
                    )
    raise ImageGenerationError(f"gemini: картинки нет в ответе — {json.dumps(body)[:400]}")


# --- Цепочка -----------------------------------------------------------------
def generate(prompt: str, reference: Path, settings) -> GeneratedImage:
    """Идём по IMAGE_PROVIDER_CHAIN слева направо до первой удачи."""
    proxy = settings.https_proxy or None
    failures: list[str] = []

    for name in settings.provider_chain:
        try:
            if name == "openrouter_gpt":
                return generate_openrouter(
                    prompt,
                    reference,
                    api_key=settings.openrouter_api_key,
                    model=settings.openrouter_image_model,
                    proxy=proxy,
                )
            if name == "openai":
                return generate_openai(
                    prompt,
                    reference,
                    api_key=settings.openai_api_key,
                    model=settings.openai_image_model,
                    proxy=proxy,
                )
            if name == "gemini":
                return generate_gemini(
                    prompt,
                    reference,
                    api_key=settings.gemini_api_key,
                    model=settings.gemini_image_model,
                    proxy=proxy,
                )
            failures.append(f"{name}: неизвестный провайдер")
        except ProviderUnavailable as exc:
            log.warning("провайдер %s недоступен, идём дальше: %s", name, exc)
            failures.append(str(exc))
        except Exception as exc:  # noqa: BLE001 — падение одного не должно рвать цепочку
            log.exception("провайдер %s упал", name)
            failures.append(f"{name}: {type(exc).__name__} {exc}")

    raise ImageGenerationError("ни один провайдер не отдал картинку:\n" + "\n".join(failures))
