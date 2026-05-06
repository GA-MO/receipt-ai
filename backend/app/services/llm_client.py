"""Provider-neutral LLM client.

Supports two providers, switched by ``settings.llm_provider``:

  * ``"gemini"`` — google-genai SDK, either Vertex AI (service account) or
    direct Gemini API key. This is the default and matches the original
    implementation.
  * ``"openrouter"`` — OpenAI-compatible SDK pointed at OpenRouter, which
    fronts dozens of models (Gemini, Claude, GPT, OSS) behind one API.
    Lets us swap the underlying model via ``OPENROUTER_MODEL`` without
    touching code.

Public surface:

  * :func:`generate_json` — single-shot text/vision request that must return
    JSON. Used by extraction (legacy + combined), fraud, and dashboard AI
    insight. Handles retry + transient auth recovery uniformly.
  * :func:`get_gemini_client` — escape hatch for code paths that still need
    the raw google-genai client (currently only the agentic tool-calling
    loop, which uses Gemini-specific function-call types).

Adding a new provider is a matter of adding another branch in
:func:`generate_json` and a client factory below.
"""

from __future__ import annotations

import base64
import logging
import time
from typing import TYPE_CHECKING

from ..config import settings

if TYPE_CHECKING:  # pragma: no cover
    from google import genai

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Client caches
# ---------------------------------------------------------------------------

_gemini_client = None  # type: ignore[var-annotated]
_openai_client = None  # type: ignore[var-annotated]


def get_gemini_client():
    """Return a cached google-genai client (Vertex AI or direct API key).

    Used by simple Gemini calls in :func:`generate_json` and by the agentic
    extraction loop which still depends on Gemini-native tool-calling types.
    """
    global _gemini_client
    if _gemini_client is not None:
        return _gemini_client

    from google import genai

    if settings.gemini_api_key:
        _gemini_client = genai.Client(api_key=settings.gemini_api_key)
        logger.info("Gemini client configured via API key")
    elif settings.gcp_credentials_path:
        _gemini_client = _create_vertex_client()
    else:
        raise RuntimeError(
            "ต้องตั้งค่า GEMINI_API_KEY หรือ GCP_CREDENTIALS_PATH อย่างน้อย 1 อย่าง"
        )
    return _gemini_client


def _create_vertex_client():
    import os

    from google import genai

    os.environ.setdefault(
        "GOOGLE_APPLICATION_CREDENTIALS", settings.gcp_credentials_path
    )
    import google.auth
    from google.auth.transport.requests import Request

    scopes = ["https://www.googleapis.com/auth/cloud-platform"]
    credentials, project = google.auth.default(scopes=scopes)
    credentials.refresh(Request())
    project = settings.gcp_project_id or project

    client = genai.Client(
        vertexai=True,
        project=project,
        location=settings.gcp_location,
        credentials=credentials,
    )
    logger.info("Gemini client configured via Vertex AI (project=%s)", project)
    return client


def reset_gemini_client() -> None:
    global _gemini_client
    _gemini_client = None
    logger.info("Gemini client reset — will re-create on next call")


def _get_openai_client():
    """Return a cached OpenAI SDK client pointed at OpenRouter."""
    global _openai_client
    if _openai_client is not None:
        return _openai_client

    if not settings.openrouter_api_key:
        raise RuntimeError(
            "ต้องตั้งค่า OPENROUTER_API_KEY เมื่อใช้ LLM_PROVIDER=openrouter"
        )

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
        timeout=settings.gemini_request_timeout,
    )
    logger.info(
        "OpenRouter client configured (model=%s)", settings.openrouter_model
    )
    return _openai_client


def reset_openai_client() -> None:
    global _openai_client
    _openai_client = None


# ---------------------------------------------------------------------------
# Public: provider-neutral JSON generator
# ---------------------------------------------------------------------------


def generate_json(
    *,
    prompt: str,
    system_instruction: str = "",
    file_bytes: bytes | None = None,
    mime_type: str | None = None,
    temperature: float = 0.1,
) -> str:
    """Generate a JSON string from the configured provider.

    The model is instructed to return JSON via the provider's native JSON
    mode (``response_mime_type`` for Gemini, ``response_format`` for
    OpenRouter). Retries on transient errors with exponential backoff.

    ``file_bytes`` + ``mime_type`` add a single image or PDF to the user
    turn. Pass ``None`` for text-only prompts (fraud analysis, dashboard
    insight).
    """
    if settings.llm_provider == "openrouter":
        return _retry(
            lambda: _generate_json_openrouter(
                system_instruction, prompt, file_bytes, mime_type, temperature
            ),
            provider="openrouter",
        )
    return _retry(
        lambda: _generate_json_gemini(
            system_instruction, prompt, file_bytes, mime_type, temperature
        ),
        provider="gemini",
    )


# ---------------------------------------------------------------------------
# Retry wrapper
# ---------------------------------------------------------------------------


def _retry(call, *, provider: str) -> str:
    last_error: Exception | None = None
    for attempt in range(1, settings.gemini_max_retries + 1):
        try:
            return call()
        except Exception as exc:  # noqa: BLE001 — retry surface
            last_error = exc
            msg = str(exc).lower()
            is_auth_error = "401" in msg or "403" in msg or "credentials" in msg
            logger.warning(
                "%s API attempt %d/%d failed: %s",
                provider,
                attempt,
                settings.gemini_max_retries,
                exc,
            )
            if is_auth_error:
                if provider == "gemini":
                    reset_gemini_client()
                else:
                    reset_openai_client()
            if attempt < settings.gemini_max_retries:
                delay = settings.gemini_retry_delay * (2 ** (attempt - 1))
                time.sleep(delay)
    raise RuntimeError(
        f"{provider} API failed after {settings.gemini_max_retries} attempts: {last_error}"
    )


# ---------------------------------------------------------------------------
# Gemini path
# ---------------------------------------------------------------------------


def _generate_json_gemini(
    system_instruction: str,
    prompt: str,
    file_bytes: bytes | None,
    mime_type: str | None,
    temperature: float,
) -> str:
    from google.genai import types

    contents: list = [prompt]
    if file_bytes and mime_type:
        contents.append(types.Part.from_bytes(data=file_bytes, mime_type=mime_type))

    config = types.GenerateContentConfig(
        system_instruction=system_instruction or None,
        temperature=temperature,
        response_mime_type="application/json",
    )

    client = get_gemini_client()
    response = client.models.generate_content(
        model=settings.gemini_model,
        contents=contents,
        config=config,
    )
    return response.text.strip()


# ---------------------------------------------------------------------------
# OpenRouter path
# ---------------------------------------------------------------------------


def _generate_json_openrouter(
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
            # OpenRouter PDF format: distinct "file" content type with file_data data URL.
            # Gemini and Claude families parse PDFs natively; other models fall back
            # to OpenRouter's mistral-ocr plugin automatically.
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
        # Wrap the system text as a structured content block with a
        # ``cache_control: ephemeral`` breakpoint so OpenRouter can cache the
        # (large, stable) catalog/schema portion of the prompt.
        # Anthropic / Gemini both honour this marker via OpenRouter; other
        # providers ignore it. TTL on Gemini is ~5min.
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
        model=settings.openrouter_model,
        messages=messages,
        temperature=temperature,
        response_format={"type": "json_object"},
    )
    # Surface cache hit details to logs so operators can see when the 5-min
    # OpenRouter cache window is paying off.
    if response.usage and response.usage.prompt_tokens_details:
        details = response.usage.prompt_tokens_details
        cached = getattr(details, "cached_tokens", 0) or 0
        if cached:
            logger.info(
                "OpenRouter cache hit: cached=%d/%d tokens", cached, response.usage.prompt_tokens
            )
    text = response.choices[0].message.content or ""
    return text.strip()
