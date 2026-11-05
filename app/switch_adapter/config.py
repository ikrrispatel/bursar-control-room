from __future__ import annotations

import os

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator


class SwitchConfiguration(BaseModel):
    """Environment-backed settings for the documented Mattermost REST API."""

    model_config = ConfigDict(extra="forbid")

    base_url: str = Field(min_length=1)
    token: SecretStr = Field(min_length=1)
    team_id: str = Field(min_length=1)
    channel_id: str | None = None
    agent_user_id: str | None = None
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
            agent_user_id=os.getenv("SWITCH_AGENT_USER_ID") or None,
            timeout_seconds=float(os.getenv("SWITCH_TIMEOUT_SECONDS", "10")),
        )


class MattermostRelayConfiguration(BaseModel):
    """Minimal Mattermost settings for an existing Console-bridged channel."""

    model_config = ConfigDict(extra="forbid")

    base_url: str = Field(min_length=1)
    token: SecretStr | None = None
    username: SecretStr | None = None
    password: SecretStr | None = None
    channel_id: str | None = None
    channel_name: str | None = None
    team_id: str | None = None
    team_name: str | None = None
    agent_user_id: str | None = None
    finance_reviewer_ids: frozenset[str] | None = None
    timeout_seconds: float = Field(default=10.0, gt=0, le=120)

    @field_validator("base_url")
    @classmethod
    def normalize_base_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if not value.startswith(("http://", "https://")):
            raise ValueError("SWITCH_BASE_URL must use http:// or https://")
        return value

    @model_validator(mode="after")
    def validate_channel_target(self) -> "MattermostRelayConfiguration":
        if self.token is None and (self.username is None or self.password is None):
            raise ValueError("Mattermost relay requires SWITCH_TOKEN or SWITCH_USERNAME and SWITCH_PASSWORD")
        if not self.channel_id and not self.channel_name:
            raise ValueError("Mattermost relay requires SWITCH_CHANNEL_ID or SWITCH_CHANNEL_NAME")
        if not self.team_id and not self.team_name:
            raise ValueError("SWITCH_TEAM_ID or SWITCH_TEAM_NAME is required for strict team validation")
        return self

    @classmethod
    def from_env(cls) -> "MattermostRelayConfiguration":
        missing = [
            name
            for name in ("SWITCH_BASE_URL",)
            if not os.getenv(name)
        ]
        if missing:
            raise ValueError(f"missing Mattermost relay configuration: {', '.join(missing)}")
        token = os.getenv("SWITCH_TOKEN") or None
        username = os.getenv("SWITCH_USERNAME") or None
        password = os.getenv("SWITCH_PASSWORD") or None
        if token is None and (username is None or password is None):
            raise ValueError("missing Mattermost relay credentials: SWITCH_TOKEN or SWITCH_USERNAME and SWITCH_PASSWORD")
        channel_id = os.getenv("SWITCH_CHANNEL_ID") or None
        channel_name = os.getenv("SWITCH_CHANNEL_NAME") or None
        if not channel_id and not channel_name:
            raise ValueError("missing Mattermost relay configuration: SWITCH_CHANNEL_ID or SWITCH_CHANNEL_NAME")
        return cls(
            base_url=os.environ["SWITCH_BASE_URL"],
            token=token,
            username=username,
            password=password,
            channel_id=channel_id,
            channel_name=None if channel_id else channel_name,
            team_id=os.getenv("SWITCH_TEAM_ID") or None,
            team_name=None if os.getenv("SWITCH_TEAM_ID") else (os.getenv("SWITCH_TEAM_NAME") or None),
            agent_user_id=os.getenv("SWITCH_AGENT_USER_ID") or None,
            finance_reviewer_ids=frozenset(
                value.strip() for value in os.getenv("BURSAR_FINANCE_REVIEWER_IDS", "").split(",") if value.strip()
            ) or None,
            timeout_seconds=float(os.getenv("SWITCH_TIMEOUT_SECONDS", "10")),
        )
