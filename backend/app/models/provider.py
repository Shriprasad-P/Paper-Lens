"""Owner-bound provider configuration contracts.

Secrets are accepted only on write and are never represented by the public
response model.  The API stores an authenticated-encryption envelope instead
of a plaintext key.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class ProviderType(str, Enum):
    OLLAMA = "ollama"
    MLX = "mlx"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"
    OPENAI_COMPATIBLE = "openai_compatible"


class ProviderConfigCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_type: ProviderType
    display_name: str = Field(min_length=1, max_length=120)
    base_url: str = Field(min_length=1, max_length=500)
    generation_model: str = Field(min_length=1, max_length=200)
    embedding_model: str | None = Field(default=None, max_length=200)
    api_key: str | None = Field(default=None, max_length=4_000)
    enabled: bool = True


class ProviderConfigPublic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    provider_type: ProviderType
    display_name: str
    base_url: str
    generation_model: str
    embedding_model: str | None
    secret_configured: bool
    masked_secret: str | None
    enabled: bool
    last_tested_at: datetime | None
    last_test_status: str | None
    created_at: datetime
    updated_at: datetime


class ProviderTestResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_id: str
    status: str
    message: str
    tested_at: datetime
