# Bursar Control Room demo

This is the honest 90-second submission path. Switch/Mattermost is the primary
product surface; the dashboard is read-only and secondary.

| Time | Action | Verification label |
|---|---|---|
| 0:00–0:10 | Open the existing Bursar Control Room and show `bursar-reviewer` in the room. | LIVE SWITCH |
| 0:10–0:25 | Post a synthetic invoice-review request and show `bursar-reviewer` responding with its typed review role and no approval, policy-override, or ledger authority. | LIVE SWITCH; verified |
| 0:25–0:45 | Run `scripts/run_bursar_scenarios.py` and show clean, duplicate, missing-evidence, conflicting-evidence, and override outcomes. | LOCAL DETERMINISTIC |
| 0:45–1:05 | Show the clean fixture's human approval gate and simulated ledger result. | LOCAL DETERMINISTIC |
| 1:05–1:20 | Show duplicate blocking or missing-evidence clarification with no ledger result. | LOCAL DETERMINISTIC |
| 1:20–1:30 | Show the evidence passport/timeline, then state that the external Switch agent inbound path is unavailable in this local Console setup. | UNVERIFIED boundary; relay path separately verified |

## Verified live Switch path

Switch owns the room bridge and agent identity. The existing `bursar-reviewer`
agent is real, is present in Bursar Control Room, and responds to human room
messages. The repository can post a typed task through the Switch agent
protocol:

```bash
.venv/bin/python scripts/run_bursar_switch_runtime.py \
  --post-demo-task --case-id switch-demo
```

## Unverified boundary

The repository runtime must not claim a live human approval or ledger result.
The local Switch Console reserves `bursar-reviewer`'s inbound agent host, so
the external listener receives HTTP 410:

```text
Switch event stream is owned by the local Switch Console agent host
```

The runtime refuses takeover. Full live verification requires an external
Switch agent bridge/API key or a Switch Console-supported event-stream handoff.

## Verified Console-compatible relay flow

The clean case `relay-clean-20261104-01` was verified in the existing room
through the Mattermost relay: intake, extraction/duplicate/evidence/policy/risk
findings, human approval, `human_decision_recorded`, and `ledger_result` were
observed. This is a verified local Console-compatible relay path, not proof
that the repository owns the Switch agent SSE stream.

SQLite persistence is verified by repository tests. The live room run above
used in-memory state; a follow-up temporary-database run was not completed, so
live post-exit persistence remains unverified. Do not present that as a live
database result in a recording.

## Offline verification

```bash
.venv/bin/python scripts/run_bursar_scenarios.py
.venv/bin/python scripts/run_bursar_submission_verification.py
```

These commands verify the deterministic human decision gate, evidence passport,
case timeline, duplicate blocking, clarification paths, reasoned override, and
simulated ledger gating without external credentials.
