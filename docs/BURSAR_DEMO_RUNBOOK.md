# Bursar Control Room 90-second demo runbook

This runbook keeps Switch/Mattermost as the primary workflow surface. It is
explicit about what is live, what is deterministic local verification, and what
is not currently verified. The dashboard is read-only and secondary.

## Before recording

1. Open the existing Bursar Control Room in Mattermost through Switch and show
   `bursar-reviewer` as a room agent. **LIVE SWITCH.**
2. Never display the terminal, environment, tokens, prompts, or raw invoice
   text in the recording.
3. Run the safe preflight for the deterministic/local portion:

   ```bash
   .venv/bin/python scripts/run_bursar_submission_verification.py
   ```

## Recording sequence

- 0:00–0:10 — Open the Bursar Control Room and show `bursar-reviewer` as the
  Switch-connected agent. **LIVE SWITCH.**
- 0:10–0:25 — Post an invoice-review request and show the agent response and
  its safety boundary: no approval, policy override, or ledger write. **LIVE
  SWITCH; response verified, external runtime intake not claimed.**
- 0:25–0:45 — Run the five deterministic scenarios and show extraction,
  duplicate, evidence,
  purchase-order/delivery matching, policy, and risk findings. Explain that
  these checks, not the agent, determine the review state. **LOCAL
  DETERMINISTIC.**
- 0:45–1:05 — Show the clean case's human approval gate and simulated ledger
  result from the local fixture coordinator. **LOCAL DETERMINISTIC; not a live
  Switch approval claim.**
- 1:05–1:20 — Show the duplicate or missing-evidence case blocked or awaiting
  clarification, with no ledger result. **LOCAL DETERMINISTIC.**
- 1:20–1:30 — Optionally show the read-only evidence passport and timeline.
  State plainly that the repository runtime's inbound event stream is
  **UNVERIFIED** because the local Console-managed `bursar-reviewer` host
  returns HTTP 410 to an external listener.

For an offline rehearsal without external credentials:

```bash
.venv/bin/python scripts/run_bursar_scenarios.py
.venv/bin/python scripts/run_bursar_live_demo.py --offline --scenario clean_invoice
```

Offline extraction is intentionally labeled fixture mode and is not presented
as a live model result. The Switch task-post smoke test is explicitly separate
from inbound approval verification; a successful post does not prove the
approval flow.
