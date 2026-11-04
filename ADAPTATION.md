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
SQLite, dashboard, or a rewrite of the legacy graph.

## Modules to modify later

The API, LangGraph workflow, audit persistence, and demo flow will later be
adapted to correlate cases and evidence with a dedicated Switch/Mattermost
room. The existing Streamlit UI will remain a companion inspection surface,
not the primary workflow.

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
