# Bursar Control Room 90-second demo runbook

This runbook keeps Mattermost/Switch as the workflow surface. The dashboard is
read-only and should be shown only as an optional inspection view.

## Before recording

1. Confirm the Bursar Mattermost channel is configured with
   `SWITCH_BASE_URL`, `SWITCH_TOKEN`, `SWITCH_TEAM_ID`, and
   `SWITCH_CHANNEL_ID`.
2. Configure `MODEL_API_KEY`, `MODEL_BASE_URL`, and `MODEL_NAME` if showing a
   model-assisted extraction finding. Never display the terminal, environment,
   tokens, prompts, or raw invoice text in the recording.
3. Run the safe preflight:

   ```bash
   .venv/bin/python scripts/run_bursar_submission_verification.py
   ```

## Recording sequence

- 0:00–0:10 — Open the dedicated Bursar Mattermost room and identify the
  requester, finance reviewer, and `intake_extraction_agent` roles.
- 0:10–0:25 — Post the clean synthetic invoice intake. Show the typed intake
  acknowledgement and the visible extraction finding. The finding must be
  labeled `model_assisted` for a live model or `fixture` for offline mode.
- 0:25–0:45 — Show deterministic extraction, duplicate, evidence,
  purchase-order/delivery matching, policy, and risk findings. Explain that
  these checks, not the model, determine the review state.
- 0:45–1:00 — As the finance reviewer, post `approve <case-id>` in the room.
  Show the recorded human decision and the simulated ledger result.
- 1:00–1:20 — Post or select the duplicate or missing-evidence synthetic case.
  Show duplicate blocking or `request_clarification`; show that no ledger
  result is created.
- 1:20–1:30 — Optionally show the read-only dashboard passport/timeline and
  repeat that Mattermost remains the primary product surface.

For an offline rehearsal without external credentials:

```bash
.venv/bin/python scripts/run_bursar_scenarios.py
.venv/bin/python scripts/run_bursar_live_demo.py --offline --scenario clean_invoice
```

Offline extraction is intentionally labeled fixture mode and is not presented
as a live model result. The explicit live smoke test is dry-run by default;
only `scripts/run_bursar_switch_smoke.py --send` posts a synthetic message.
