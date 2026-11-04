from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.bursar.scenarios import load_scenarios
from app.bursar.workflow import LocalBursarWorkflowCoordinator
from app.switch_adapter import LocalFixtureSwitchAdapter, MattermostSwitchAdapter, SwitchConfiguration


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one Bursar case through live Mattermost or offline fixture transport.")
    parser.add_argument("--scenario", default="clean_invoice", choices=[scenario.name for scenario in load_scenarios()])
    parser.add_argument("--offline", action="store_true", help="use LocalFixtureSwitchAdapter without credentials")
    args = parser.parse_args()
    fixture = next(scenario for scenario in load_scenarios() if scenario.name == args.scenario)

    if args.offline:
        adapter = LocalFixtureSwitchAdapter()
    else:
        try:
            configuration = SwitchConfiguration.from_env()
        except (ValueError, TypeError) as exc:
            print(
                "Live demo cannot start: missing or invalid Switch credentials/configuration. "
                "Set SWITCH_BASE_URL, SWITCH_TOKEN, SWITCH_TEAM_ID, and optionally SWITCH_CHANNEL_ID, "
                "or pass --offline.",
                file=sys.stderr,
            )
            return 2
        adapter = MattermostSwitchAdapter(configuration)

    try:
        result, _ = LocalBursarWorkflowCoordinator(adapter).run_scenario(fixture)
    finally:
        close = getattr(adapter, "close", None)
        if close:
            close()
    print(f"{fixture.name}: case={result.case.status.value} ledger={'created' if result.ledger_entry else 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
