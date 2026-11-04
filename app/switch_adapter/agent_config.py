from __future__ import annotations

import os

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class SwitchAgentConfiguration(BaseModel):
    """Credentials and room identity for the documented Switch agent bridge."""

    model_config = ConfigDict(extra="forbid")

    base_url: str = Field(min_length=1)
    agent_id: str = Field(min_length=1)
    agent_name: str = Field(default="bursar-reviewer", min_length=1)
    api_key: SecretStr = Field(min_length=1)
    room_id: str = Field(min_length=1)
    timeout_seconds: float = Field(default=10.0, gt=0, le=120)
    connection_id: str | None = None

    @classmethod
    def from_env(cls) -> "SwitchAgentConfiguration":
        values = {
            "base_url": os.getenv("SWITCH_AGENT_BASE_URL") or os.getenv("SWITCH_API_ENDPOINT"),
            "agent_id": os.getenv("SWITCH_AGENT_ID"),
            "agent_name": os.getenv("SWITCH_AGENT_NAME", "bursar-reviewer"),
            "api_key": os.getenv("SWITCH_AGENT_API_KEY") or os.getenv("SWITCH_API_TOKEN"),
            "room_id": os.getenv("SWITCH_ROOM_ID"),
            "timeout_seconds": float(os.getenv("SWITCH_AGENT_TIMEOUT_SECONDS", "10")),
            "connection_id": os.getenv("SWITCH_CONNECTION_ID") or None,
        }
        missing = [name for name in ("base_url", "agent_id", "api_key", "room_id") if not values[name]]
        if missing:
            raise ValueError(f"missing Switch agent configuration: {', '.join(missing)}")
        return cls(**values)
