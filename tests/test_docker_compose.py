from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_compose_declares_local_first_services_and_shared_volume():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    assert set(compose["services"]) == {"api", "dashboard"}
    assert compose["services"]["api"]["volumes"] == ["bursar_data:/data"]
    assert compose["services"]["dashboard"]["volumes"] == ["bursar_data:/data"]
    assert compose["services"]["api"]["healthcheck"]["test"][0] == "CMD"
    assert compose["services"]["dashboard"]["healthcheck"]["test"][0] == "CMD"
    assert "SWITCH_TOKEN" in compose["services"]["api"]["environment"]
    assert "${SWITCH_TOKEN" in compose["services"]["api"]["environment"]["SWITCH_TOKEN"]


def test_dockerignore_excludes_runtime_state_and_secrets():
    content = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    for entry in (".venv", "data", "*.db", "*.log", ".env", "*.key"):
        assert entry in content
    assert "!.env.example" in content


def test_dockerfile_has_non_root_runtime_and_api_default():
    content = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "FROM python:3.12-slim" in content
    assert "USER bursar" in content
    assert '"app.api.main:app"' in content
