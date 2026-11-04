from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    re.compile(r"(?im)^\s*(?:SWITCH_TOKEN|MODEL_API_KEY)\s*=\s*(?!<|replace-with|\$\{)[^\s#]+"),
)
LOG_SENSITIVE_NAMES = {"invoice_text", "payload", "prompt", "content", "token", "api_key", "password"}


def tracked_files() -> list[Path]:
    result = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True)
    return [ROOT / item for item in result.stdout.decode().split("\0") if item]


def _logging_sensitive_calls(path: Path) -> list[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return []
    findings: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in {"debug", "info", "warning", "error", "exception", "critical"}:
            continue
        source = ast.unparse(node).lower()
        if any(name in source for name in LOG_SENSITIVE_NAMES):
            findings.append(f"{path}:{node.lineno}")
    return findings


def run_audit() -> list[str]:
    findings: list[str] = []
    for path in tracked_files():
        if not path.is_file() or path.suffix in {".pdf", ".png", ".jpg", ".jpeg"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                findings.append(f"possible committed secret pattern: {path}")

    for path in (ROOT / "Dockerfile", ROOT / "docker-compose.yml"):
        text = path.read_text(encoding="utf-8")
        if re.search(r"(?im)^\s*(?:SWITCH_TOKEN|MODEL_API_KEY)\s*:\s*(?!\$\{)[^\s#]+", text):
            findings.append(f"literal credential in Docker configuration: {path}")

    for path in (ROOT / "app",):
        for source in path.rglob("*.py"):
            findings.extend(f"sensitive logging call: {item}" for item in _logging_sensitive_calls(source))

    agents_text = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "app" / "agents").glob("*.py"))
    for forbidden in ("apply_human_decision", "create_simulated_ledger_entry", ".decide(", "ledger_entries"):
        if forbidden in agents_text:
            findings.append(f"agent boundary contains forbidden mutation path: {forbidden}")
    return findings


def main() -> int:
    findings = run_audit()
    if findings:
        print("SECURITY AUDIT FAILED")
        print("\n".join(findings))
        return 1
    print("SECURITY AUDIT PASSED: no committed credential patterns, sensitive logs, or agent mutation paths found")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
