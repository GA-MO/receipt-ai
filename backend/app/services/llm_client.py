"""OpenRouter-backed LLM client.

OpenRouter (OpenAI-compatible) fronts dozens of models (Gemini, Claude, GPT,
OSS) behind one API. We use the OpenAI SDK pointed at OpenRouter's base URL
so we can swap the underlying model via ``OPENROUTER_MODEL`` without code
changes.

Public surface:

  * :func:`generate_json` — single-shot text/vision request that must return
    JSON. Used by extraction. Handles retry + transient auth recovery.
"""

from __future__ import annotations

import base64
import logging
import time

from ..config import settings

logger = logging.getLogger(__name__)


_openai_client = None  # type: ignore[var-annotated]


def _get_openai_client():
    """Return a cached OpenAI SDK client pointed at OpenRouter."""
    global _openai_client
    if _openai_client is not None:
        return _openai_client

    if not settings.openrouter_api_key:
        raise RuntimeError("ต้องตั้งค่า OPENROUTER_API_KEY")

    from openai import OpenAI

    default_headers: dict[str, str] = {}
    if settings.openrouter_app_url:
        default_headers["HTTP-Referer"] = settings.openrouter_app_url
    if settings.openrouter_app_title:
        default_headers["X-Title"] = settings.openrouter_app_title

    _openai_client = OpenAI(
        base_url=settings.openrouter_base_url,
        api_key=settings.openrouter_api_key,
        default_headers=default_headers or None,
        timeout=settings.llm_request_timeout,
    )
    logger.info("OpenRouter client configured (model=%s)", settings.openrouter_model)
    return _openai_client


def reset_openai_client() -> None:
    global _openai_client
    _openai_client = None


def model_routing_list() -> list[str]:
    """Primary model first, then configured fallbacks, de-duplicated."""
    models = [settings.openrouter_model]
    for name in (settings.openrouter_fallback_models or "").split(","):
        name = name.strip()
        if name and name not in models:
            models.append(name)
    return models


def generate_json(
    *,
    prompt: str,
    system_instruction: str = "",
    file_bytes: bytes | None = None,
    mime_type: str | None = None,
    temperature: float = 0.1,
) -> str:
    """Generate a JSON string from OpenRouter, retrying on transient errors.

    ``file_bytes`` + ``mime_type`` add a single image or PDF to the user turn.
    Pass ``None`` for text-only prompts.
    """
    routing = model_routing_list()
    last_error: Exception | None = None
    for position, model in enumerate(routing):
        try:
            return _retry(
                lambda m=model, rest=routing[position:]: _generate_json_openrouter(
                    m, rest, system_instruction, prompt, file_bytes, mime_type, temperature
                )
            )
        except RuntimeError as exc:
            # A retired or mistyped model id is rejected outright — OpenRouter's
            # own `models` routing only covers a model that exists but is
            # unavailable. Walk to the next candidate ourselves rather than
            # failing every upload in the queue.
            if not _is_model_unavailable(exc):
                raise
            last_error = exc
            if position + 1 < len(routing):
                logger.warning(
                    "OpenRouter model %s unavailable — falling back to %s",
                    model,
                    routing[position + 1],
                )
    raise RuntimeError(f"No usable OpenRouter model in {routing}: {last_error}")


def _is_model_unavailable(exc: Exception) -> bool:
    msg = str(exc).lower()
    return (
        "not a valid model id" in msg
        or "no endpoints found" in msg
        or "model not found" in msg
        or "404" in msg
    )


def _retry(call) -> str:
    last_error: Exception | None = None
    for attempt in range(1, settings.llm_max_retries + 1):
        try:
            return call()
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            msg = str(exc).lower()
            is_auth_error = "401" in msg or "403" in msg or "credentials" in msg
            logger.warning(
                "OpenRouter API attempt %d/%d failed: %s",
                attempt,
                settings.llm_max_retries,
                exc,
            )
            if is_auth_error:
                reset_openai_client()
            # Retrying a model that does not exist just burns the backoff before
            # the caller can try the next one.
            if _is_model_unavailable(exc):
                break
            if attempt < settings.llm_max_retries:
                delay = settings.llm_retry_delay * (2 ** (attempt - 1))
                time.sleep(delay)
    raise RuntimeError(
        f"OpenRouter API failed after {settings.llm_max_retries} attempts: {last_error}"
    )


def _generate_json_openrouter(
    model: str,
    routing: list[str],
    system_instruction: str,
    prompt: str,
    file_bytes: bytes | None,
    mime_type: str | None,
    temperature: float,
) -> str:
    user_content: list[dict] = [{"type": "text", "text": prompt}]

    if file_bytes and mime_type:
        b64 = base64.b64encode(file_bytes).decode("ascii")
        if mime_type == "application/pdf":
            # OpenRouter PDF format: distinct "file" content type with
            # file_data data URL. Gemini and Claude families parse PDFs
            # natively; other models fall back to OpenRouter's mistral-ocr
            # plugin automatically.
            user_content.append(
                {
                    "type": "file",
                    "file": {
                        "filename": "document.pdf",
                        "file_data": f"data:application/pdf;base64,{b64}",
                    },
                }
            )
        else:
            user_content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{b64}"},
                }
            )

    messages: list[dict] = []
    if system_instruction:
        # ``cache_control: ephemeral`` lets OpenRouter cache the large stable
        # catalog/schema portion of the prompt. Honoured by Anthropic / Gemini;
        # other providers ignore it. TTL on Gemini is ~5min.
        messages.append(
            {
                "role": "system",
                "content": [
                    {
                        "type": "text",
                        "text": system_instruction,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
            }
        )
    messages.append({"role": "user", "content": user_content})

    client = _get_openai_client()
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        response_format={"type": "json_object"},
        # OpenRouter routes down this list when a model is unavailable or has
        # been retired, so losing one does not take the pipeline down with it.
        extra_body={"models": routing} if len(routing) > 1 else None,
    )
    served = getattr(response, "model", None)
    if served and served.split(":")[0] != model.split(":")[0]:
        logger.warning(
            "OpenRouter served %s instead of %s — primary model may be retired",
            served,
            model,
        )
    if response.usage and response.usage.prompt_tokens_details:
        details = response.usage.prompt_tokens_details
        cached = getattr(details, "cached_tokens", 0) or 0
        if cached:
            logger.info(
                "OpenRouter cache hit: cached=%d/%d tokens",
                cached,
                response.usage.prompt_tokens,
            )
    text = response.choices[0].message.content or ""
    return text.strip()
