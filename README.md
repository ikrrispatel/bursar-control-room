# Invoice-to-Pay Agent

Open-source accounts-payable automation prototype built with FastAPI, LangGraph,
Pydantic, LiteParse, and Docling.

The project models the invoice-to-payment control path around typed data,
deterministic checks, human approval, ERP-ready posting payloads, and audit
evidence.

[![CI](https://github.com/mshojaei77/invoice-to-pay-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/mshojaei77/invoice-to-pay-agent/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![FastAPI](https://img.shields.io/badge/FastAPI-ready-009688)
![LangGraph](https://img.shields.io/badge/LangGraph-agentic-purple)

## What It Does

The workflow accepts invoice support documents and runs them through a finance
control graph:

```text
upload
  -> parse with LiteParse / Docling
  -> normalize AP documents
  -> validate schema and business rules
  -> duplicate check
  -> PO / delivery matching
  -> exception and fraud controls
  -> approval routing
  -> payment and ERP sync planning
  -> mock ERP post
  -> audit log
```

It is intended for engineers, AP managers, controllers, ERP consultants, and
finance automation reviewers who want a runnable reference implementation of an
invoice-to-pay agent.

## Bursar Control Room domain boundary

This repository is being adapted into Bursar Control Room, a Switch-centered
procurement and invoice-review workflow. The new `app/bursar/` package is the
product-domain boundary for typed cases, evidence references, agent findings,
human decisions, append-only audit events, and simulated ledger entries.

Its deterministic decision service allowlists `approve`, `reject`,
`request_clarification`, and `override`. Agents can only produce findings;
only an identified finance reviewer can make a decision, rejection and
override require reasons, terminal cases cannot be decided again, and a
simulated ledger entry requires a recorded human approval or override first.

The existing AP workflow remains the reusable foundation during this staged
adaptation. Switch/Mattermost integration and the companion inspection UI are
separate later slices; this domain package does not claim to implement them.

### Reproducible local scenarios

The local Bursar coordinator includes five deterministic fixtures:
`clean_invoice`, `duplicate_invoice`, `missing_evidence`,
`conflicting_evidence`, and `human_override`. Each reuses the typed invoice,
purchase-order, delivery-note, duplicate, and matching controls from the AP
foundation. Run all five with:

```bash
.venv/bin/python scripts/run_bursar_scenarios.py
```

Each case builds an evidence passport containing extracted fields, SHA-256
evidence references, check results, findings, decisions, audit events, and any
simulated ledger result. The in-memory timeline is append-only and can be
queried by case ID; events from another case are never included. A ledger
result is printed only for human approval or a reasoned human override.

### External Switch/Mattermost transport

The `MattermostSwitchAdapter` is an optional HTTP transport behind the same
`SwitchAdapter` protocol. It uses the documented Mattermost REST v4 channel and
post endpoints; local tests and offline demos continue to use
`LocalFixtureSwitchAdapter`.

Configure a live room with environment variables (copy `.env.example` and
load it using your deployment's secret manager):

```text
SWITCH_BASE_URL=https://mattermost.example.com
SWITCH_TOKEN=<personal-access-token-or-bot-token>
SWITCH_TEAM_ID=<mattermost-team-id>
SWITCH_CHANNEL_ID=<existing-bursar-channel-id>
SWITCH_TIMEOUT_SECONDS=10
```

Live setup path: create a Mattermost bot or personal access token with access
to the Bursar team/channel, obtain the team and channel IDs from Mattermost,
set the variables above, then construct `MattermostSwitchAdapter` from
`SwitchConfiguration.from_env()`. If `SWITCH_CHANNEL_ID` is omitted, the
adapter uses the documented channel-create endpoint and resolves the returned
channel. No live credentials are required for the test suite. The adapter
does not connect the legacy graph or add model calls.

The live API boundary exposes:

```text
POST /switch/messages   # typed invoice-intake message from the Bursar room
POST /switch/commands   # human command plus room_id and actor_id
```

Both routes validate the configured channel before invoking the deterministic
Bursar coordinator. The coordinator posts findings, the decision record, and
the simulated ledger result back through Mattermost. For a live synthetic demo
use `scripts/run_bursar_live_demo.py`; it fails clearly when live credentials
are absent and supports `--offline` for the local fixture transport:

```bash
.venv/bin/python scripts/run_bursar_live_demo.py --scenario clean_invoice
.venv/bin/python scripts/run_bursar_live_demo.py --offline --scenario duplicate_invoice
```

## Bursar inspection dashboard

Start the read-only Bursar inspection surface:

```bash
.venv/bin/python -m streamlit run app/ui/bursar_dashboard.py
```

It displays deterministic local fixture cases, status chips, case details,
evidence passports, grouped findings, timelines, human decisions, and
simulated ledger results. It has no approval or mutation controls. Mattermost/
Switch remains the primary workflow surface for intake, collaboration, agent
findings, and human decisions. Read-only API projections are available at
`GET /bursar/cases`, `GET /bursar/cases/{case_id}`, and the case's
`/passport`, `/timeline`, `/findings`, `/decision`, and `/ledger` subroutes.

### SQLite persistence

The Bursar coordinator can persist cases, typed Switch messages, evidence,
findings, decisions, audit events, timeline events, passports, and simulated
ledger results in SQLite. Set either `BURSAR_DATABASE_PATH=data/bursar.db` or
`BURSAR_DATABASE_URL=sqlite:///absolute/path/to/bursar.db`. The schema is
created and migrated on startup. Remove the configured database file to reset
local state; do not put credentials, prompts, or secrets in it. If neither
variable is set, the coordinator remains in-memory for isolated offline tests.

### Docker Compose

Docker Compose runs the API and read-only inspection dashboard locally, sharing
the named `bursar_control_room_data` volume for SQLite:

```bash
cp .env.example .env  # optional; leave Switch/model values blank for offline mode
docker compose up --build
```

The API is available at `http://localhost:8000` and the dashboard at
`http://localhost:8501`. Switch/Mattermost remains external and is configured
only through runtime environment variables. Offline verification runs without
credentials:

```bash
docker compose run --rm api python scripts/run_bursar_scenarios.py
```

Stop with `docker compose down`. Reset only the SQLite volume with
`docker compose down -v`; this removes container data but never deletes source
files. Restart with `docker compose up --build`.

### Safe extraction agent boundary

The optional `intake_extraction_agent` accepts only bounded invoice text and
case-scoped evidence locations. Its typed result contains extracted fields,
confidence, source locations, missing fields, uncertainty explanations, and a
reviewer summary. Model output is validated before it becomes a typed
`extraction_finding` message in the case room.

Configure the model provider with `MODEL_API_KEY`, `MODEL_BASE_URL`,
`MODEL_NAME`, and optional `MODEL_TIMEOUT_SECONDS`. The live boundary uses the
configured OpenAI-compatible JSON endpoint; missing model configuration fails
safely. Use `FixtureAgentProvider` through `--offline` for deterministic local
verification. Invoice text is explicitly marked untrusted in the prompt,
bounded in length, and never combined with unrelated room history.

The agent can extract, locate evidence, explain uncertainty, and summarize. It
cannot decide duplicates, policy, risk, approval, rejection, clarification, or
override, and it has no case-state or ledger mutation capability. Deterministic
services and the human decision gate remain authoritative.

## Features

- FastAPI service for run creation, lookup, approval, rejection, and audit lookup.
- LangGraph workflow with an approval interrupt and in-memory checkpointing.
- Strict Pydantic schemas for invoices, purchase orders, delivery notes, parsed
  documents, and audit records.
- Parser routing with LiteParse as the fast path and Docling for heavier parsing.
- Deterministic AP controls for validation, duplicate detection, 2-way / 3-way
  matching, exceptions, fraud, risk, GL coding, compliance, payment planning, and
  mock ERP posting.
- Streamlit review UI for local upload, run inspection, and audit report download.
- Real sample PDFs plus pytest coverage for the graph, services, API, parser
  contracts, schemas, and demo path.

## Quick Start

Prerequisites:

- Python 3.11+
- `uv`

Install and test:

```bash
uv sync
uv run pytest
```

Run the clean invoice demo:

```bash
uv run python scripts/run_demo.py \
  --invoice samples/invoice_001_canada_post_sample.pdf \
  --po samples/purchase_order_001_polychemtex.pdf \
  --delivery-note samples/delivery_note_001_bunker_receipt.pdf \
  --parser liteparse
```

Expected summary:

```text
final_status=completed
risk_level=low
erp_status=posted
```

Run an exception case:

```bash
uv run python scripts/run_demo.py \
  --invoice samples/invoice_002_tax_sample_local_supply.pdf
```

Expected summary:

```text
final_status=requires_approval
erp_status=not_posted
```

Write a markdown report:

```bash
uv run python scripts/run_demo.py \
  --invoice samples/invoice_001_canada_post_sample.pdf \
  --po samples/purchase_order_001_polychemtex.pdf \
  --delivery-note samples/delivery_note_001_bunker_receipt.pdf \
  --output-md data/processed/reports/latest-demo.md
```

## Legacy AP review UI

Start the local Streamlit review app:

```bash
uv run streamlit run app/ui/streamlit_app.py
```

The UI supports local document upload, graph execution, control inspection, and
markdown audit report download.

## API

Start the FastAPI service:

```bash
uv run invoice-to-pay-agent
```

The server listens on `http://localhost:8000`.

Available routes:

| Method | Route | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Health check |
| `POST` | `/runs` | Upload one or more files and start a run |
| `GET` | `/runs/{run_id}` | Fetch a run result |
| `POST` | `/runs/{run_id}/approve` | Resume an approval-gated run as approved |
| `POST` | `/runs/{run_id}/reject` | Resume an approval-gated run as rejected |
| `GET` | `/runs/{run_id}/audit` | Read audit events for a run |

Example upload:

```bash
curl -F "files=@samples/invoice_001_canada_post_sample.pdf" \
  -F "files=@samples/purchase_order_001_polychemtex.pdf" \
  -F "files=@samples/delivery_note_001_bunker_receipt.pdf" \
  http://localhost:8000/runs
```

## CLI

Main demo command:

```bash
uv run python scripts/run_demo.py --help
```

Current options:

```text
--invoice INVOICE
--po PO
--delivery-note DELIVERY_NOTE
--parser {liteparse,docling}
--output-md OUTPUT_MD
```

Approval helper scripts are available for local graph-resume experiments:

```bash
uv run python scripts/approve_demo.py --run-id <run_id>
uv run python scripts/reject_demo.py --run-id <run_id>
```

## Project Structure

```text
app/
  api/          FastAPI app and routes
  graph/        LangGraph state, workflow, and nodes
  schemas/      Pydantic data contracts
  services/     AP controls, parser routing, ERP mock, risk, matching, audit
  ui/           Streamlit review app
docs/           Demo report, launch notes, release notes
samples/        Sample invoice, PO, delivery, remittance, and reference PDFs
scripts/        CLI demo and approval helpers
tests/          Pytest suite
```

## Configuration

This project currently needs no external service credentials for the default
demo and test path.

Environment placeholders live in `.env.example` for future OpenAI and storage
settings. Keep dependency changes in `pyproject.toml` and `uv.lock`; add Python
packages with:

```bash
uv add <package>
```

## Testing

Run the full suite:

```bash
uv run pytest
```

Useful focused checks:

```bash
uv run pytest tests/test_graph.py
uv run pytest tests/test_api.py
uv run pytest tests/test_parser_router.py
uv run pytest tests/test_run_demo.py
```

## Sample Data

The `samples/` directory contains demo invoices, purchase orders, delivery
notes, statements, remittance advice, credit notes, and reference documents.

`samples/eval_manifest.jsonl` provides smoke-level scenario coverage for the
demo corpus.

## Current Limitations

- Active API runs are stored in memory and are lost when the server restarts.
- The LangGraph checkpointer is in-memory.
- ERP posting is mocked; no live ERP connector is included.
- The review UI is local Streamlit, not a production approval portal.
- Parser behavior is suitable for prototype evaluation and tests, not certified
  financial document processing.
- Payment execution is represented as a control plan; this project does not move
  money.

## Documentation

- [Demo report](docs/demo-report.md)
- [Launch kit](docs/launch-kit.md)
- [Release notes](docs/release-v0.1.0.md)
- [Repository launch checklist](docs/repository-launch-checklist.md)
- [Contributing guide](CONTRIBUTING.md)
- [Security policy](SECURITY.md)
- [Code of conduct](CODE_OF_CONDUCT.md)

## Contributing

Issues and pull requests are welcome. Before opening a PR:

```bash
uv sync
uv run pytest
```

Keep changes focused, update tests when behavior changes, and keep public docs
aligned with the actual command and API surface.

## License

MIT. See [LICENSE](LICENSE).
