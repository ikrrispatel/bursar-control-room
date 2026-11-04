from __future__ import annotations

import hashlib
from pathlib import Path

from app.bursar.models import EvidenceReference


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def evidence_reference(case_id: str, kind: str, path: Path, source_location: str | None = None) -> EvidenceReference:
    if not path.is_file():
        raise FileNotFoundError(path)
    return EvidenceReference(
        evidence_id=f"evidence-{case_id}-{path.name}",
        case_id=case_id,
        kind=kind,
        file_name=path.name,
        sha256=sha256_file(path),
        source_location=source_location or str(path),
    )
