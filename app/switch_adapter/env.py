from __future__ import annotations

import os
import re
from pathlib import Path


_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def load_env_file(path: str | Path) -> bool:
    """Load simple KEY=VALUE entries without overriding the process environment."""
    env_path = Path(path)
    if not env_path.is_file():
        return False
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        name, separator, value = line.partition("=")
        name = name.strip()
        if not separator or not _ENV_NAME.fullmatch(name) or name in os.environ:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[name] = value
    return True


def load_project_env(project_root: str | Path | None = None) -> bool:
    root = Path(project_root) if project_root is not None else Path(__file__).resolve().parents[2]
    return load_env_file(root / ".env")
