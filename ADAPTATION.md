# Bursar Control Room Adaptation

## Source and license

This repository was bootstrapped from the MIT-licensed primary repository:

- Source: https://github.com/mshojaei77/invoice-to-pay-agent
- Source commit: `98658e583f72dfa4edeaf4fa4eb534a716e71d73`
- Original authorship: `mshojaei77` (copyright notice preserved in `LICENSE`)

The secondary reference repository was not used. The original MIT `LICENSE`,
`SECURITY.md`, and attribution are retained.

## Reused modules

The first adaptation slice retains the base repository's typed AP document
schemas, parser and extraction foundations, deterministic validation,
duplicate detection, purchase-order and delivery matching, audit utilities,
synthetic samples, and existing test suite.

## Bursar additions

`app/bursar/` is the new product-domain boundary. It defines typed models for
cases, evidence references, agent findings, human decisions, audit events, and
simulated ledger entries. Its decision service is deterministic and limits
state changes to the four product actions: approve, reject,
request_clarification, and override.

The service requires a finance-reviewer identity for human decisions, requires
reasons for rejection and override, rejects agent decision attempts, prevents
decisions after terminal states, and permits a simulated ledger entry only
after a recorded human approval or human override event.

The base parser's LiteParse adapter invokes the installed module through the
active Python interpreter (`python -m liteparse.cli`) rather than assuming a
shell-global `lit` executable. This keeps the documented local virtualenv and
`uv run` paths deterministic.

The isolated `app/switch_adapter/` package now defines the typed room, message,
agent-role, message-type, and case-correlation boundary. Its
`LocalFixtureSwitchAdapter` provides deterministic in-memory room/message
storage and allowlisted human-command parsing for tests. It intentionally has
no external Switch/Mattermost client, model calls, dashboard coupling, or
LangGraph dependency.

`app/bursar/workflow.py` now coordinates that fixture adapter with the Bursar
case and decision domain. It validates structured invoice intake, runs
deterministic fixture checks, publishes typed findings and a human decision
request, routes commands through the adapter parser and decision service, and
creates a simulated ledger entry only after human approval or override. Reject
and clarification paths never create ledger entries. The coordinator stores
cases, messages, audit events, and ledger entries in memory and remains
independent of the legacy LangGraph workflow.

The reproducible fixture layer in `app/bursar/scenarios.py` supplies five
typed cases: clean invoice, duplicate invoice, missing evidence, conflicting
evidence, and human override. It calls the existing duplicate and
invoice/PO/delivery matching services rather than replacing them with filename
or string heuristics. `app/bursar/evidence.py` hashes fixture files with
SHA-256 and creates case-scoped evidence references.

`app/bursar/passport.py` aggregates the extracted invoice fields, evidence,
check results, agent findings, human decision, audit events, and simulated
ledger result into an `EvidencePassport`. `app/bursar/timeline.py` provides an
append-only, ordered, case-filtered timeline. The local command
`scripts/run_bursar_scenarios.py` executes all five scenarios and verifies the
expected duplicate, matching, case, and ledger outcomes. This remains local
fixture behavior; it does not add the external Switch API, model calls,
SQLite, or a rewrite of the legacy graph.

## External transport boundary

The Switch-connected path is implemented in
`app/switch_adapter/agent_protocol.py` and `app/switch_adapter/runtime.py`.
Its environment-backed default identity is the existing `bursar-reviewer`
agent; the numeric/UUID agent ID and API credential remain deployment
configuration and are never hard-coded.
It follows Switch's documented agent bridge: the configured Switch-managed
agent posts to the configured Bursar room, listens on the room-scoped SSE
event stream, and keeps the connection lease alive with the documented
heartbeat. Room creation and bridge configuration remain Switch Console
responsibilities; the application does not invent provider endpoints or
credentials. `scripts/run_bursar_switch_runtime.py --post-demo-task` is the
live demo entry point. The runtime ignores platform-originated agent messages,
requires the configured room ID, and routes only human allowlisted commands to
the deterministic decision service.

The live workflow is therefore Switch-dependent: the agent identity, room
bridge, event stream, and human collaboration all come from Switch. Without
Switch, only the explicitly supported local fixture adapter can run; a direct
Mattermost post is not treated as proof of Switch centrality.

In live verification, the existing `bursar-reviewer` task post succeeds, but
its inbound connection returns HTTP 410 because the connection is reserved for
the Switch Console host. The runtime refuses to take it over and reports that
an external agent bridge or Console-supported handoff is required. This is an
explicit environment limitation, not a simulated success claim.

The optional `MattermostSwitchAdapter` now implements the same protocol using
only documented Mattermost REST v4 operations: channel lookup or creation,
post creation, and channel post retrieval. `SwitchConfiguration` reads
`SWITCH_BASE_URL`, `SWITCH_TOKEN`, `SWITCH_TEAM_ID`, optional
`SWITCH_CHANNEL_ID`, and `SWITCH_TIMEOUT_SECONDS` from the environment. Tokens
are represented as secret values and are never logged.

Messages are serialized as a typed Bursar JSON envelope inside Mattermost's
documented post `message` field. The adapter validates case correlation,
message types, sender boundaries, configured room identity, bounded retries,
timeouts, and provider response shapes. Human command parsing remains the
same allowlist as the local adapter. Contract tests use an injected fake HTTP
transport and do not require live credentials.

The Mattermost adapter is retained for compatibility with the earlier
provider-neutral boundary and its tests. It is not used by the authentic
Switch agent runtime described above.

`LiveMattermostBursarBoundary` connects the adapter to the Bursar coordinator
without touching the legacy LangGraph graph. `POST /switch/messages` accepts
only a typed invoice-intake message from the configured room and starts the
case. `POST /switch/commands` validates the room and routes the allowlisted
human command through the existing deterministic decision service. Typed
findings, human decision records, and ledger results are posted through the
same Mattermost adapter. The `--offline` mode of
`scripts/run_bursar_live_demo.py` continues to use `LocalFixtureSwitchAdapter`.

## Safe AI boundary

`app/agents/` defines the typed `AgentProvider` protocol and the sole agent
role currently enabled: `intake_extraction_agent`. `ModelAgentProvider` sends
only bounded invoice text and case-scoped evidence locations to an
OpenAI-compatible JSON endpoint. It uses explicit anti-prompt-injection system
instructions, a timeout, secret-backed configuration, and strict Pydantic
output validation. Invalid, incomplete, mismatched, or unsafe model output is
rejected without changing case state.

`FixtureAgentProvider` returns a visibly marked `fixture` result for offline
tests and demos; live model results are marked `model_assisted`. The agent can
extract fields, identify evidence locations, explain uncertainty, and summarize
for a reviewer. It cannot perform duplicate detection, matching, policy or
risk decisions, human decisions, or ledger creation. Those deterministic
services and the human decision gate remain the final authority.

## Inspection surface

`app/bursar/inspection.py` provides read-only projections for case lists, case
details, evidence passports, timelines, agent findings, human decisions, and
simulated ledger results. The corresponding `GET /bursar/cases...` endpoints
never call the decision service and expose no mutation operation.
`app/ui/bursar_dashboard.py` is a small Streamlit inspection surface with
status chips, empty/missing-case handling, escaped untrusted text, grouped
agent findings, passport evidence, timeline events, and decision/ledger
display. Start it with:

```bash
.venv/bin/python -m streamlit run app/ui/bursar_dashboard.py
```

The dashboard is intentionally secondary. Mattermost/Switch remains the
required product surface for invoice intake, agent collaboration, and the
human decision gate; the dashboard cannot approve, reject, override, request
clarification, or create ledger entries.

The final submission verification command is
`scripts/run_bursar_submission_verification.py`. It checks all five scenarios,
the human approval gate, duplicate blocking, missing-evidence clarification,
conflict escalation, reasoned override, evidence passports, case timelines,
and simulated-ledger gating. `scripts/security_audit.py` checks tracked files
for committed credential patterns, sensitive logging, credentials in Docker
configuration, and forbidden agent mutation paths.

The 90-second demo sequence is documented in
`docs/BURSAR_DEMO_RUNBOOK.md`. The explicit live smoke command is
`scripts/run_bursar_switch_smoke.py --send`; without `--send` it performs no
network write. Missing live credentials fail safely, while all offline fixture
commands remain independent of Mattermost and model credentials.

## SQLite persistence boundary

`app/bursar/repository.py` provides an explicit SQLite schema for Bursar cases,
Switch messages, evidence references, agent findings, human decisions,
append-only audit events, timeline events, evidence passports, and simulated
ledger entries. It is a storage boundary only: policy, human decision gates,
and ledger eligibility remain in the deterministic domain services.

Configure `BURSAR_DATABASE_PATH` or a `sqlite:///...` `BURSAR_DATABASE_URL`.
The schema is initialized on repository construction. Delete the configured
database file to reset local state. Omitting both variables preserves the
in-memory fixture mode used by focused tests and offline demos.

## Docker Compose runtime

`Dockerfile` packages the application as a non-root Python 3.12 image.
`docker-compose.yml` provides an API service and the read-only Streamlit
inspection service. Both mount the named `bursar_control_room_data` volume at
`/data` and use `/data/bursar.db`; the dashboard remains an inspection surface
and has no mutation controls. Mattermost/Switch and model credentials are
passed only through runtime environment variables.

Start locally with:

```bash
docker compose up --build
```

Run the deterministic five-scenario check without external credentials:

```bash
docker compose run --rm api python scripts/run_bursar_scenarios.py
```

Stop with `docker compose down`. Reset the SQLite volume with
`docker compose down -v`; this affects only the named Docker volume, not the
source checkout. `docker compose config` validates the resolved Compose file.

## Modules to modify later

The legacy LangGraph workflow and legacy Streamlit AP review UI remain
separate from the Bursar persistence and inspection surfaces. The Bursar
repository does not alter the legacy graph or become a policy authority.

## Disabled or out of scope for the Bursar MVP

Broad payment execution, ERP integrations, NetSuite readiness, order-to-cash,
billing-revenue, and other enterprise-expansion modules are not part of the
Bursar product boundary. No real payment or accounting mutation is enabled.

## Product differences

Bursar Control Room is a Switch-centered procurement and invoice-review
workflow. Humans and agents collaborate in a team-chat room; agents extract,
explain, and suggest, while deterministic services enforce policy and humans
make approval decisions. A dashboard may inspect evidence later, but it is not
the product's primary surface.
When a local Switch Console-managed agent reserves its inbound connection for
the Console host, the runtime refuses to take it over and reports that an
external agent bridge or Console-supported handoff is required. This is an
explicit environment limitation, not a simulated success claim.
