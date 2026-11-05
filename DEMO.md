# Bursar Control Room demo

This is the honest 90-second submission path. Switch/Mattermost is the primary
product surface; the dashboard is read-only and secondary.

## Judge proof card

- **Use of Switch:** the live room, named `bursar-reviewer` teammate, and human
  collaboration are visible in the Switch-connected Bursar Control Room. The
  verified approval path uses the Console-compatible Mattermost relay because
  Switch Console or its sidecar owns the managed agent watcher and connection.
  Current standalone Switch agent clients use WebSocket; SSE is
  legacy/deprecated compatibility transport. The attempted external connection
  returned HTTP 410; this is not presented as an external client takeover.
- **Business outcome:** the workflow catches duplicate invoices, stops cases
  with missing or conflicting evidence, and creates a reviewable audit/timeline
  record before a simulated ledger result. It addresses control failures that
  otherwise arrive as fragmented email attachments and opaque handoffs.
- **Reproducibility:** offline mode is clone-reproducible with no credentials;
  live mode additionally requires the existing Console room, Mattermost
  authentication, and the configured finance-reviewer ID allowlist. Both paths
  use synthetic data only.
- **Human control:** the agent explains and suggests findings; only the
  server-authorized finance reviewer can decide, and only approval or reasoned
  override can create the simulated ledger entry.

## Why Switch is essential

The work happens in the Switch-connected Bursar Control Room: a human posts the
invoice intake, `bursar-reviewer` participates as the named AI teammate, and
the typed findings and human decision request return to that same room. Only
the server-authorized finance reviewer can approve, reject, request
clarification, or override. The simulated ledger result is emitted only after
the room records an allowed human approval or reasoned override. Without the
Switch room, the human-agent collaboration and visible decision handoff cannot
occur.

## Judge proof

| Human action | Agent/system response | Safety control | Persisted evidence |
|---|---|---|---|
| Post a synthetic intake in the Bursar room | `bursar-reviewer` and the coordinator return typed findings | Room, case, and message validation | Case, intake message, findings, and evidence passport |
| Review findings and post an approval command | Coordinator records `human_decision_recorded` | Server-side finance-reviewer authorization; agents cannot decide | Human decision, audit event, and ordered timeline |
| Observe the final room result | `ledger_result` reports a simulated entry only after approval | Deterministic ledger gate; no approval means no ledger entry | Simulated ledger entry linked to the case |

## Two-case demo sequence

1. **Live clean invoice — Switch/Mattermost relay:** post the synthetic intake
   in Bursar Control Room, show `bursar-reviewer` findings, post the authorized
   human approval, then show `human_decision_recorded` and `ledger_result`.
2. **Offline blocked case — deterministic fixture mode:** run the duplicate or
   missing-evidence scenario and show a rejected case with no ledger, or a
   clarification request with no ledger. This path is clone-reproducible and
   uses no credentials.

The live clean path is verified through the Console-compatible Mattermost
relay. The external client connection to the Console-managed agent is not
claimed: current standalone Switch agent clients use WebSocket, SSE is
legacy/deprecated compatibility transport, and Switch Console or its sidecar
owns the managed watcher and connection. The attempted external connection
returned HTTP 410. Fixture mode uses synthetic data and does not claim real
document extraction.

## Proof of Control

Use this short segment after the two-case sequence. The labels identify whether
the evidence is live or offline.

| Step | Exact narration | Expected visible outcome |
|---|---|---|
| 1. **LIVE — findings** | “The AI teammate can contribute findings, but findings are only suggestions for the reviewer.” | `bursar-reviewer` findings and the decision request appear in the Bursar room; the case is still awaiting a human decision and no ledger result exists. |
| 2. **OFFLINE — blocked approval attempts** | “Now we prove the control boundary: an agent-originated approval and an approval from an unlisted caller cannot become a decision.” | The agent approval is ignored/rejected, and the unauthorized caller is rejected by finance-reviewer authorization; neither creates a human decision or ledger entry. |
| 3. **LIVE — authorized approval** | “Only the configured finance reviewer can approve this case in the room.” | The authorized `approve <case-id>` command is accepted and `human_decision_recorded` appears. |
| 4. **LIVE — before the gate** | “Before that human approval, the ledger gate is still closed.” | The relay’s pre-approval state is `pending_review`; no `ledger_result` is present. |
| 5. **LIVE — after the gate** | “After the authorized room approval, and only then, the coordinator records the simulated ledger result.” | `ledger_result` appears with `status=created`, alongside the persisted human decision, audit event, and case timeline. |

The live evidence above is from the verified Console-compatible Mattermost relay;
the offline rejection evidence is deterministic fixture coverage. Neither path
claims an external client approval connection, real document extraction, or
production readiness.

| Time | Action | Verification label |
|---|---|---|
| 0:00–0:10 | Open the existing Bursar Control Room and show `bursar-reviewer` in the room. | LIVE SWITCH |
| 0:10–0:25 | Start the Console-compatible relay with `--until-terminal`, then post the exact clean intake below. Show the five typed findings and decision request. | LIVE SWITCH relay; verified |
| 0:25–0:40 | Post the exact human approval command below. Show `human_decision_recorded` followed by `ledger_result: created`. | LIVE SWITCH relay; verified |
| 0:40–0:55 | Show the persisted case evidence passport and timeline: 1 audit event, 13 timeline events, and 1 ledger entry. | LIVE SQLite relay; verified |
| 0:55–1:15 | Run `scripts/run_bursar_scenarios.py` and show clean, duplicate, missing-evidence, conflicting-evidence, and override outcomes. | LOCAL DETERMINISTIC; fixture mode |
| 1:15–1:30 | Show the blocked/clarification fixture and state that an external client connection to the Console-managed agent remains unavailable; Console owns the watcher and connection. | LOCAL DETERMINISTIC + UNVERIFIED boundary |

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

The external client connection to the Console-managed `bursar-reviewer` agent
must not claim a live human approval or ledger result. Current standalone
Switch agent clients use WebSocket; SSE is legacy/deprecated compatibility
transport. Switch Console or its sidecar owns the managed watcher and
connection, so the attempted external connection received HTTP 410:

```text
external client connection to the Console-managed agent is unavailable; Switch Console owns the managed watcher and connection
```

The runtime refuses takeover. An independent client would require a separately
registered agent with its own API key and connection. That is not required for
the verified Mattermost workflow; the separate Console-compatible relay path
above is verified.

## Verified Console-compatible relay flow

The clean case `relay-clean-20261104-01` was verified in the existing room
through the Mattermost relay: intake, extraction/duplicate/evidence/policy/risk
findings, human approval, `human_decision_recorded`, and `ledger_result` were
observed. This is a verified local Console-compatible relay path, not proof
that the repository owns an external client connection to the
Console-managed agent.

To reproduce the clean relay path, configure the existing local Console-bridged
Mattermost settings through the ignored root `.env`, set a temporary
`BURSAR_DATABASE_PATH` outside the repository, set the server-side
`BURSAR_FINANCE_REVIEWER_IDS` allowlist, and run:

```bash
BURSAR_DATABASE_PATH="$(mktemp -d /tmp/bursar-demo.XXXXXX)/bursar.db" \
BURSAR_FINANCE_REVIEWER_IDS=<configured-mattermost-reviewer-user-id> \
.venv/bin/python scripts/run_bursar_mattermost_relay.py --until-terminal
```

Post these messages manually in Bursar Control Room:

```text
/bursar intake {"case_id":"relay-demo-<fresh-id>","vendor_name":"Acme Supplies","invoice_number":"INV-DEMO-<fresh-id>","total":"110.00","currency":"USD"}
approve relay-demo-<fresh-id>
```

Expected outputs are an intake acknowledgement, extraction, duplicate,
evidence, policy, and risk findings, a human decision request,
`human_decision_recorded`, and `ledger_result` with `status=created`. When no
model credentials are configured, the fixture provider is visibly marked
fixture mode; this demo does not claim real document extraction. Query the
temporary database independently after exit to verify persistence.

The live room flow has also been verified with a temporary SQLite database
outside the repository. After the relay exited, an independent query confirmed
the persisted case, human approval, audit/timeline records, and ledger result:
1 audit event, 13 timeline events, and 1 ledger entry. This verifies the
Console-compatible Mattermost relay's post-exit persistence path; it does not
verify approval through an external client connection to the
Console-managed agent.

## Offline verification

```bash
.venv/bin/python scripts/run_bursar_scenarios.py
.venv/bin/python scripts/run_bursar_submission_verification.py
```

These commands verify the deterministic human decision gate, evidence passport,
case timeline, duplicate blocking, clarification paths, reasoned override, and
simulated ledger gating without external credentials.
