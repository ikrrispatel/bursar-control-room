from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_release_docs_identify_switch_primary_surface_and_verified_agent():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    adaptation = (ROOT / "ADAPTATION.md").read_text(encoding="utf-8")
    demo = (ROOT / "DEMO.md").read_text(encoding="utf-8")

    for document in (readme, adaptation, demo):
        assert "bursar-reviewer" in document
        assert "HTTP 410" in document
    assert "Switch is the primary Bursar product surface" in readme
    assert "LIVE SWITCH" in demo
    assert "LOCAL DETERMINISTIC" in demo
    assert "UNVERIFIED" in demo


def test_release_docs_do_not_claim_live_inbound_approval():
    documents = "\n".join(
        (ROOT / name).read_text(encoding="utf-8")
        for name in ("README.md", "ADAPTATION.md", "DEMO.md", "docs/BURSAR_DEMO_RUNBOOK.md")
    )
    assert "no live human approval" in documents.lower()
    assert "external runtime inbound decision path is unavailable" in documents
    assert "bursar-reviewer" in (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "switch-buddy-admin" not in documents


def test_runtime_preserves_safe_console_owned_stream_refusal():
    source = (ROOT / "app/switch_adapter/agent_protocol.py").read_text(encoding="utf-8")
    assert "Switch event stream is owned by the local Switch Console agent host" in source
    assert "response.status_code == 410" in source
    assert "SwitchAgentTransportError" in source
    assert "connect_to_room" not in source
