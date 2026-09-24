"""Encrypted provider-secret storage and bounded connection tests."""

from __future__ import annotations

import base64
import hashlib
from dataclasses import replace
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

from .core.config import Settings
from .models.provider import ProviderConfigPublic, ProviderConfigCreate, ProviderTestResponse


class ProviderSecretError(RuntimeError):
    """Raised when the deployment cannot safely encrypt/decrypt a secret."""


def runtime_provider(settings: Settings, record: object):
    """Build the selected user's provider and an isolated runtime settings view."""

    from .ai.provider import create_ai_provider

    provider_type = str(getattr(record, "provider_type", ""))
    secret = decrypt_secret(settings, str(getattr(record, "encrypted_secret", "") or ""))
    runtime_settings = replace(
        settings,
        ai_provider=provider_type,
        ai_model=str(getattr(record, "generation_model", settings.ai_model)),
        ai_api_key=secret or None,
        ai_base_url=str(getattr(record, "base_url", settings.ai_base_url)),
        embedding_model=str(getattr(record, "embedding_model", None) or settings.embedding_model),
        embedding_provider=provider_type,
        embedding_base_url=str(getattr(record, "base_url", settings.embedding_base_url)),
        embedding_api_key=secret or None,
    )
    return create_ai_provider(runtime_settings), runtime_settings


def _fernet(settings: Settings):
    try:
        from cryptography.fernet import Fernet, InvalidToken  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - exercised only on minimal installs
        raise ProviderSecretError("Encrypted provider storage requires the cryptography package.") from exc
    configured = settings.provider_encryption_key
    if not configured:
        if settings.environment in {"staging", "production"}:
            raise ProviderSecretError("PAPERLENS_PROVIDER_ENCRYPTION_KEY is required in shared deployments.")
        # Local development gets a stable, machine-local fallback so a restart
        # can still decrypt configuration without putting a key in source.
        configured = base64.urlsafe_b64encode(hashlib.sha256(f"paperlens:{settings.database_url}".encode()).digest()).decode()
    try:
        return Fernet(configured.encode()), InvalidToken
    except (ValueError, TypeError) as exc:
        raise ProviderSecretError("PAPERLENS_PROVIDER_ENCRYPTION_KEY is not a valid Fernet key.") from exc


def encrypt_secret(settings: Settings, secret: str) -> str:
    if not secret:
        return ""
    cipher, _ = _fernet(settings)
    return cipher.encrypt(secret.encode("utf-8")).decode("ascii")


def decrypt_secret(settings: Settings, encrypted: str) -> str:
    if not encrypted:
        return ""
    cipher, invalid_token = _fernet(settings)
    try:
        return cipher.decrypt(encrypted.encode("ascii")).decode("utf-8")
    except (invalid_token, UnicodeDecodeError, ValueError) as exc:
        raise ProviderSecretError("The stored provider secret could not be decrypted.") from exc


def mask_secret(secret: str | None) -> str | None:
    if not secret:
        return None
    if len(secret) <= 8:
        return "••••"
    return f"{secret[:4]}{'•' * 8}{secret[-4:]}"


async def test_provider_connection(
    config: ProviderConfigPublic,
    secret: str,
    *,
    # Local models may need to load from disk on the first request. Keep the
    # probe bounded, but allow a cold Ollama start to complete before marking
    # an otherwise healthy provider as failed.
    timeout: float = 30.0,
    transport: httpx.AsyncBaseTransport | None = None,
) -> str:
    """Run bounded model, generation, and embedding health checks.

    The request bodies are fixed, minimal probes.  No prompt, response, or
    credential is returned or persisted; only the safe pass/fail timestamp is
    stored by the API route.
    """

    parsed = urlparse(config.base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ProviderSecretError("The provider endpoint must be an absolute HTTP(S) URL.")
    headers = {"Content-Type": "application/json"}
    if secret:
        headers["Authorization"] = f"Bearer {secret}"
    base_url = config.base_url.rstrip("/")
    if config.provider_type.value == "ollama":
        base_url = base_url.removesuffix("/v1")
    async with httpx.AsyncClient(
        base_url=base_url,
        timeout=httpx.Timeout(timeout),
        follow_redirects=False,
        headers=headers,
        transport=transport,
    ) as client:
        if config.provider_type.value == "ollama":
            response = await client.get("/api/tags")
            response.raise_for_status()
            body = response.json()
            if not isinstance(body, dict):
                raise ProviderSecretError("The provider model listing was invalid.")
            models = body.get("models", [])
            names = {str(item.get("name", "")) for item in models if isinstance(item, dict)}
            if names and config.generation_model not in names and not any(config.generation_model.split(":", 1)[0] in name for name in names):
                raise ProviderSecretError("The selected Ollama generation model is not installed.")
            await _ollama_generation_probe(client, config.generation_model)
            dimensions = await _ollama_embedding_probe(client, config.embedding_model)
            suffix = f" Embeddings returned {dimensions} dimensions." if dimensions else " Embedding probe skipped (no model configured)."
            return f"Ollama is reachable; generation and the selected model passed a bounded probe.{suffix}"
        response = await client.get("/models")
        response.raise_for_status()
        model_names = _model_names(response)
        if model_names and config.generation_model not in model_names:
            raise ProviderSecretError("The selected generation model is not available.")
        await _openai_generation_probe(client, config.generation_model)
        dimensions = await _openai_embedding_probe(client, config.embedding_model)
        suffix = f" Embeddings returned {dimensions} dimensions." if dimensions else " Embedding probe skipped (no model configured)."
        return f"Provider endpoint, credentials, and generation model passed bounded probes.{suffix}"


async def _ollama_generation_probe(client: httpx.AsyncClient, model: str) -> None:
    response = await client.post(
        "/api/chat",
        json={
            "model": model,
            "messages": [{"role": "user", "content": "Reply with JSON containing only ok=true."}],
            "stream": False,
            "think": False,
            "format": "json",
            "options": {"temperature": 0, "num_predict": 32},
        },
    )
    response.raise_for_status()
    body = response.json()
    content = body.get("message", {}).get("content") if isinstance(body, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise ProviderSecretError("The generation probe returned no usable content.")


async def _ollama_embedding_probe(client: httpx.AsyncClient, model: str | None) -> int | None:
    if not model:
        return None
    response = await client.post("/api/embed", json={"model": model, "input": ["PaperLens embedding health check"]})
    response.raise_for_status()
    body = response.json()
    vectors = body.get("embeddings") if isinstance(body, dict) else None
    if not isinstance(vectors, list) or len(vectors) != 1 or not isinstance(vectors[0], list) or not vectors[0]:
        raise ProviderSecretError("The embedding probe returned an invalid vector.")
    return len(vectors[0])


async def _openai_generation_probe(client: httpx.AsyncClient, model: str) -> None:
    response = await client.post(
        "/chat/completions",
        json={
            "model": model,
            "messages": [{"role": "user", "content": "Reply with JSON containing only ok=true."}],
            "temperature": 0,
            "max_tokens": 32,
            "response_format": {"type": "json_object"},
        },
    )
    response.raise_for_status()
    body = response.json()
    content = body.get("choices", [{}])[0].get("message", {}).get("content") if isinstance(body, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise ProviderSecretError("The generation probe returned no usable content.")


async def _openai_embedding_probe(client: httpx.AsyncClient, model: str | None) -> int | None:
    if not model:
        return None
    response = await client.post("/embeddings", json={"model": model, "input": ["PaperLens embedding health check"]})
    response.raise_for_status()
    body = response.json()
    data = body.get("data") if isinstance(body, dict) else None
    vector = data[0].get("embedding") if isinstance(data, list) and data and isinstance(data[0], dict) else None
    if not isinstance(vector, list) or not vector:
        raise ProviderSecretError("The embedding probe returned an invalid vector.")
    return len(vector)


def _model_names(response: httpx.Response) -> set[str]:
    body = response.json()
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, list):
        return set()
    return {str(item.get("id")) for item in data if isinstance(item, dict) and item.get("id")}


def public_config(record: object) -> ProviderConfigPublic:
    return ProviderConfigPublic(
        id=str(record.id), provider_type=str(record.provider_type), display_name=str(record.display_name),
        base_url=str(record.base_url), generation_model=str(record.generation_model),
        embedding_model=getattr(record, "embedding_model", None), secret_configured=bool(getattr(record, "encrypted_secret", "")),
        masked_secret=getattr(record, "secret_hint", None), enabled=bool(record.enabled),
        last_tested_at=record.last_tested_at, last_test_status=record.last_test_status,
        created_at=record.created_at, updated_at=record.updated_at,
    )
