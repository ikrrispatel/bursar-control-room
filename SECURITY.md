# Security Policy

## Supported Versions

This repository is a prototype. Security fixes are accepted for the latest `main` branch and tagged releases.

## Reporting a Vulnerability

Please do not open public issues for vulnerabilities involving financial documents, parser artifacts, uploaded files, payment details, credentials, or audit logs.

Report privately by emailing the maintainer listed in `pyproject.toml` with:

- a short description of the issue,
- affected files or routes,
- reproduction steps,
- impact assessment,
- any suggested fix.

## Sensitive Data Rules

- Do not commit real invoices, bank data, tax identifiers, ERP credentials, customer files, or vendor master data.
- Treat files under `data/processed/` as sensitive when running with real documents.
- Keep future API keys, ERP credentials, object-storage secrets, and database URLs in environment variables.
- Scrub generated reports before sharing them publicly.

## Implemented controls

- Non-health API routes fail closed unless bearer/API-key authentication is configured. Local bypass is available only through the explicit `BURSAR_API_AUTH_MODE=local` development setting.
- Approve, reject, override, and ledger-related paths require a server-derived finance-reviewer identity; caller-supplied actor fields are not trusted.
- Uploads use bounded request/file counts and sizes, accepted document types, server-generated filenames, parser timeouts, and cleanup on failure. Uploaded contents are not logged.
- SQLite uses per-thread connections, transaction commits, WAL mode, and a busy timeout so concurrent API requests do not share a thread-affine connection.

## Residual risks

This prototype still requires additional production hardening: rate limiting and abuse controls, automated dependency vulnerability scans, idempotency keys for retryable POST operations, and a provider-supported external client connection to the Console-managed agent. Current standalone Switch agent clients use WebSocket; SSE is legacy/deprecated compatibility transport. Switch Console or its sidecar owns the managed watcher and connection, and the attempted external connection returned HTTP 410. The verified Console-compatible Mattermost relay remains the available live inbound path.
