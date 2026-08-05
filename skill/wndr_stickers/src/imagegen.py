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
import shutil
import subprocess
import tempfile
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


# --- Codex CLI (GPT image по подписке ChatGPT) -------------------------------
#: Встроенный инструмент image_gen у Codex не требует OPENAI_API_KEY — он ходит
#: по той же подписке, что и обычный чат. Это основной путь: платить отдельно
#: за картинки не нужно.
CODEX_HOME = Path.home() / ".codex"
CODEX_MODEL = "gpt-5.5"
CODEX_TIMEOUT_S = 600

CODEX_INSTRUCTION = (
    "\n\nGenerate this image now using your built-in image_gen tool, then copy the "
    "final PNG into the current working directory as exactly ./{filename}. "
    "Reply with only the absolute path of that file."
)


def codex_prompt(plate_prompt: str, filename: str = "plate.png") -> str:
    return plate_prompt + CODEX_INSTRUCTION.format(filename=filename)


def build_codex_command(
    *, workdir: str, reference: str, model: str, last_message: str
) -> list[str]:
    """Аргументы codex exec. Модель прибиваем явно: в ~/.codex/config.toml может
    лежать gpt-4.1, который с аккаунтом ChatGPT не работает."""
    return [
        "codex",
        "exec",
        "--skip-git-repo-check",
        "-C",
        workdir,
        "-s",
        "workspace-write",
        "-m",
        model,
        "-i",
        reference,
        "-o",
        last_message,
    ]


def newest_generated_image(root: Path = CODEX_HOME / "generated_images") -> Path | None:
    """Запасной путь: Codex сохраняет картинки к себе, даже если не скопировал."""
    if not root.exists():
        return None
    images = list(root.rglob("*.png"))
    if not images:
        return None
    return max(images, key=lambda p: p.stat().st_mtime)


def generate_codex(
    prompt: str,
    reference: Path,
    *,
    model: str = CODEX_MODEL,
    timeout: int = CODEX_TIMEOUT_S,
) -> GeneratedImage:
    if shutil.which("codex") is None:
        raise ProviderUnavailable("codex: бинарь не найден в PATH")

    with tempfile.TemporaryDirectory(prefix="wndr-codex-") as tmp:
        workdir = Path(tmp)
        target = workdir / "plate.png"
        last_message = workdir / "last.txt"
        command = build_codex_command(
            workdir=str(workdir),
            reference=str(reference),
            model=model,
            last_message=str(last_message),
        )
        started = newest_generated_image()
        try:
            proc = subprocess.run(  # noqa: S603 — аргументы собираем сами, shell не используем
                command,
                input="",
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            raise ProviderUnavailable(f"codex: не уложился в {timeout}с") from exc

        tail = (proc.stderr or proc.stdout or "")[-600:]
        if "401" in tail or "Unauthorized" in tail or "refresh token" in tail:
            raise ProviderUnavailable(
                "codex: авторизация протухла — выполни `codex login`"
            )
        if "not supported when using Codex with a ChatGPT account" in tail:
            raise ProviderUnavailable(f"codex: модель {model} недоступна на подписке")

        if target.exists():
            return GeneratedImage(data=target.read_bytes(), provider="codex", model=model)

        # Codex мог сгенерировать, но не скопировать — берём свежую из его хранилища.
        latest = newest_generated_image()
        if latest is not None and latest != started:
            return GeneratedImage(data=latest.read_bytes(), provider="codex", model=model)

        raise ImageGenerationError(f"codex: картинка не появилась. Хвост вывода:\n{tail}")


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
            if name == "codex":
                return generate_codex(
                    codex_prompt(prompt),
                    reference,
                    model=settings.codex_model,
                )
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
