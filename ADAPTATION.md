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
