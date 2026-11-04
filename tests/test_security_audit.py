from scripts.security_audit import run_audit


def test_security_audit_passes():
    assert run_audit() == []
