from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.main import app
from app.api.routes import configure_bursar_coordinator
from app.bursar.repository import BursarRepository
from app.bursar.workflow import LocalBursarWorkflowCoordinator


client = TestClient(app)


def test_health_is_public_but_production_api_fails_closed(monkeypatch):
    monkeypatch.setenv("BURSAR_API_AUTH_MODE", "required")
    monkeypatch.delenv("BURSAR_API_KEY", raising=False)
    monkeypatch.delenv("BURSAR_FINANCE_REVIEWER_API_KEY", raising=False)
    assert client.get("/health").status_code == 200
    assert client.get("/bursar/cases").status_code == 503


def test_api_key_auth_and_server_side_finance_identity(monkeypatch):
    monkeypatch.setenv("BURSAR_API_AUTH_MODE", "required")
    monkeypatch.setenv("BURSAR_API_KEY", "read-key")
    monkeypatch.setenv("BURSAR_FINANCE_REVIEWER_API_KEY", "review-key")
    monkeypatch.setenv("BURSAR_FINANCE_REVIEWER_ID", "finance-server-identity")
    assert client.get("/bursar/cases", headers={"Authorization": "Bearer read-key"}).status_code == 200
    response = client.post(
        "/runs/missing/approve",
        headers={"Authorization": "Bearer review-key"},
    )
    assert response.status_code == 200


def test_read_key_cannot_make_finance_decision(monkeypatch):
    monkeypatch.setenv("BURSAR_API_AUTH_MODE", "required")
    monkeypatch.setenv("BURSAR_API_KEY", "read-key")
    monkeypatch.setenv("BURSAR_FINANCE_REVIEWER_API_KEY", "review-key")
    monkeypatch.setenv("BURSAR_FINANCE_REVIEWER_ID", "finance-server-identity")
    assert client.post("/runs/missing/approve", headers={"X-API-Key": "read-key"}).status_code == 403


def test_upload_rejects_traversal_and_unsupported_type_without_writing(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    response = client.post(
        "/runs",
        files=[("files", ("../escape.exe", b"not an invoice", "application/octet-stream"))],
    )
    assert response.status_code == 415
    assert not (tmp_path / "escape.exe").exists()


def test_upload_request_size_limit_is_enforced():
    response = client.post("/runs", headers={"Content-Length": str(50 * 1024 * 1024 + 1)})
    assert response.status_code == 413


def test_repository_supports_concurrent_api_reads(tmp_path: Path):
    repository = BursarRepository(tmp_path / "bursar.db")
    configure_bursar_coordinator(LocalBursarWorkflowCoordinator(repository=repository))
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(lambda _: client.get("/bursar/cases"), range(16)))
    assert all(response.status_code == 200 for response in responses)
