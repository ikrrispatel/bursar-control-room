from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.switch_adapter import CaseCorrelation, MattermostSwitchAdapter, MessageType, SwitchConfiguration, SwitchMessage


def main() -> int:
    parser = argparse.ArgumentParser(description="Explicitly post one synthetic Bursar Switch smoke message.")
    parser.add_argument("--send", action="store_true", help="actually post the synthetic message")
    args = parser.parse_args()
    if not args.send:
        print("Switch smoke test is dry-run; no message posted. Pass --send to post one synthetic test message.")
        return 0
    try:
        configuration = SwitchConfiguration.from_env()
        if not configuration.channel_id:
            raise ValueError("SWITCH_CHANNEL_ID is required for the live smoke test")
        adapter = MattermostSwitchAdapter(configuration)
    except (ValueError, TypeError) as exc:
        print(f"Live Switch smoke test cannot start safely: {exc}", file=sys.stderr)
        return 2
    message = SwitchMessage(
        room_id=configuration.channel_id,
        case=CaseCorrelation(case_id="smoke-test-case"),
        message_type=MessageType.INVOICE_INTAKE,
        sender_type="human",
        sender_id="bursar-smoke-test",
        payload={"vendor_name": "Synthetic Smoke Vendor", "invoice_number": "SMOKE-001", "total": "1.00", "currency": "USD"},
    )
    try:
        posted = adapter.post_message(message)
        print(f"Live Switch smoke test posted message_id={posted.message_id} case_id={posted.case.case_id}")
    except Exception as exc:  # provider errors are already safe and bounded
        print(f"Live Switch smoke test failed safely: {exc}", file=sys.stderr)
        return 1
    finally:
        adapter.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
