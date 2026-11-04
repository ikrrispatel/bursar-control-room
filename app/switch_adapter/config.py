from __future__ import annotations

import os

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


class SwitchConfiguration(BaseModel):
    """Environment-backed settings for the documented Mattermost REST API."""

    model_config = ConfigDict(extra="forbid")

    base_url: str = Field(min_length=1)
    token: SecretStr = Field(min_length=1)
    team_id: str = Field(min_length=1)
    channel_id: str | None = None
    timeout_seconds: float = Field(default=10.0, gt=0, le=120)

    @field_validator("base_url")
    @classmethod
    def normalize_base_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if not value.startswith(("http://", "https://")):
            raise ValueError("SWITCH_BASE_URL must use http:// or https://")
        return value

    @classmethod
    def from_env(cls) -> "SwitchConfiguration":
        missing = [
            name
            for name in ("SWITCH_BASE_URL", "SWITCH_TOKEN", "SWITCH_TEAM_ID")
            if not os.getenv(name)
        ]
        if missing:
            raise ValueError(f"missing Switch configuration: {', '.join(missing)}")
        return cls(
            base_url=os.environ["SWITCH_BASE_URL"],
            token=os.environ["SWITCH_TOKEN"],
            team_id=os.environ["SWITCH_TEAM_ID"],
            channel_id=os.getenv("SWITCH_CHANNEL_ID") or None,
            timeout_seconds=float(os.getenv("SWITCH_TIMEOUT_SECONDS", "10")),
        )
