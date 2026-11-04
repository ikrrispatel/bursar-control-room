from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.switch_adapter.runtime import runtime_from_environment
from app.switch_adapter import AgentRole, CaseCorrelation, MessageType, SenderType, SwitchMessage


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Bursar agent through the documented Switch event stream.")
    parser.add_argument("--start-from", default="head", help="Switch event cursor, usually head or a sequence number")
    parser.add_argument("--post-demo-task", action="store_true", help="Post a synthetic invoice-review task, then wait for a human room event")
    parser.add_argument("--case-id", default="switch-live-demo", help="Case ID used by --post-demo-task")
    args = parser.parse_args()
    try:
        runtime = runtime_from_environment()
    except (ValueError, TypeError) as exc:
        print(f"Switch Bursar runtime cannot start safely: {exc}", file=sys.stderr)
        return 2
    try:
        if args.post_demo_task:
            runtime.adapter.post_message(
                SwitchMessage(
                    room_id=runtime.adapter.configuration.room_id,
                    case=CaseCorrelation(case_id=args.case_id),
                    message_type=MessageType.INTAKE_ACKNOWLEDGEMENT,
                    sender_type=SenderType.AGENT,
                    sender_id=runtime.adapter.configuration.agent_id,
                    agent_role=AgentRole.INTAKE_AGENT,
                    payload={
                        "case_id": args.case_id,
                        "status": "awaiting_human_intake",
                        "task": "invoice_review",
                        "instructions": "A finance requester should post /bursar intake <JSON> in this room. The finance reviewer then decides approve, reject, request_clarification, or override <reason>.",
                        "mode": "switch_agent_protocol",
                        "agent_name": runtime.adapter.configuration.agent_name,
                    },
                    timestamp=datetime.now(timezone.utc),
                )
            )
            print(f"posted_switch_invoice_review_task={args.case_id}", flush=True)
        result = runtime.run_once(start_from=args.start_from)
    except Exception as exc:
        print(f"Switch Bursar runtime failed safely: {exc}", file=sys.stderr)
        return 1
    finally:
        runtime.adapter.close()
    if result is None:
        print("Switch Bursar runtime ended without a Bursar task")
        return 0
    print(f"switch_bursar_case={result.case.case_id} status={result.case.status.value} ledger={'created' if result.ledger_entry else 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
