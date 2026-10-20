"""Local Superset config for the pip-based demo (no Docker).

Metadata lives in a SQLite file next to the repo; the mart database is the
SQLite file built by `run.py --stage marts`. This is a demo config, not a
production one: no Redis, no Celery, no SSO.
"""

from __future__ import annotations

import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
SUPERSET_HOME = HERE.parent / ".superset"
SUPERSET_HOME.mkdir(exist_ok=True)

SECRET_KEY = os.environ.get("SUPERSET_SECRET_KEY", "local-demo-only-change-me")
SQLALCHEMY_DATABASE_URI = f"sqlite:///{SUPERSET_HOME / 'superset.db'}"

WTF_CSRF_ENABLED = True
TALISMAN_ENABLED = False
ENABLE_PROXY_FIX = True

# The demo connects to a local SQLite file by absolute path.
PREVENT_UNSAFE_DB_CONNECTIONS = False
