from __future__ import annotations

import os

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class ModelConfiguration(BaseModel):
    """Environment-backed configuration for an OpenAI-compatible model API."""

    model_config = ConfigDict(extra="forbid")

    api_key: SecretStr = Field(min_length=1)
    base_url: str = Field(min_length=1)
    model_name: str = Field(min_length=1)
    timeout_seconds: float = Field(default=20.0, gt=0, le=120)

    @field_validator("base_url")
    @classmethod
    def normalize_base_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if not value.startswith(("http://", "https://")):
            raise ValueError("MODEL_BASE_URL must use http:// or https://")
        return value

    @classmethod
    def from_env(cls) -> "ModelConfiguration":
        missing = [
            name
            for name in ("MODEL_API_KEY", "MODEL_BASE_URL", "MODEL_NAME")
            if not os.getenv(name)
        ]
        if missing:
            raise ValueError(f"missing model configuration: {', '.join(missing)}")
        return cls(
            api_key=os.environ["MODEL_API_KEY"],
            base_url=os.environ["MODEL_BASE_URL"],
            model_name=os.environ["MODEL_NAME"],
            timeout_seconds=float(os.getenv("MODEL_TIMEOUT_SECONDS", "20")),
        )
