from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents import FixtureAgentProvider, ModelAgentProvider, ModelConfiguration
from app.bursar.repository import BursarRepository
from app.switch_adapter.boundary import LiveMattermostBursarBoundary
from app.switch_adapter.config import MattermostRelayConfiguration
from app.switch_adapter.env import load_project_env
from app.switch_adapter.http import MattermostSwitchAdapter
from app.switch_adapter.mattermost_relay import MattermostBursarRelay


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Console-compatible Bursar Mattermost relay.")
    parser.add_argument("--once", action="store_true", help="poll the configured room once")
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    parser.add_argument("--max-idle-seconds", type=float, default=300.0)
    parser.add_argument(
        "--until-terminal",
        action="store_true",
        help="keep polling after intake until a human decision reaches a terminal result",
    )
    args = parser.parse_args()
    load_project_env()
    adapter = None
    try:
        configuration = MattermostRelayConfiguration.from_env()
        adapter = MattermostSwitchAdapter(configuration)
        room = adapter.create_room(configuration.channel_name or configuration.channel_id or "Bursar Control Room")
        repository = BursarRepository.from_environment_optional()
        try:
            provider = ModelAgentProvider(ModelConfiguration.from_env())
        except (ValueError, TypeError):
            provider = FixtureAgentProvider()
        boundary = LiveMattermostBursarBoundary(
            adapter,
            room.room_id,
            agent_provider=provider,
            repository=repository,
        )
        relay = MattermostBursarRelay(adapter, boundary)
        started = time.monotonic()
        while True:
            result = relay.poll_once()
            if result is not None:
                print(f"bursar_case={result.case.case_id} status={result.case.status.value} ledger={'created' if result.ledger_entry else 'none'}")
                terminal = result.ledger_entry is not None or result.case.status.value == "rejected"
                if not args.until_terminal or terminal:
                    return 0
            if args.once or time.monotonic() - started >= args.max_idle_seconds:
                print("Mattermost relay ended without a Bursar task")
                return 0
            time.sleep(args.poll_seconds)
    except (ValueError, TypeError) as exc:
        print(f"Bursar Mattermost relay cannot start safely: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Bursar Mattermost relay failed safely: {exc}", file=sys.stderr)
        return 1
    finally:
        if adapter is not None:
            adapter.close()


if __name__ == "__main__":
    raise SystemExit(main())
