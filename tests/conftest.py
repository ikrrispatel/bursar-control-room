from __future__ import annotations

import os


# Tests deliberately opt into the named local-development auth mode. Production
# defaults to fail-closed authentication when this variable is absent.
os.environ.setdefault("BURSAR_API_AUTH_MODE", "local")
