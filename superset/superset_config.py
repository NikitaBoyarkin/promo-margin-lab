"""Minimal Superset config for the local promo-margin-lab demo.

Everything here is deliberately local-only: no SSO, no cache, no Celery.
"""

import os

SECRET_KEY = os.environ.get("SUPERSET_SECRET_KEY", "local-dev-only-change-me")

SQLALCHEMY_DATABASE_URI = os.environ.get(
    "SQLALCHEMY_DATABASE_URI",
    "postgresql+psycopg2://superset:superset@postgres/superset",
)

# Local demo: keep sessions simple; do not copy this to production.
WTF_CSRF_ENABLED = True
TALISMAN_ENABLED = False
ENABLE_PROXY_FIX = True

# The mart database is mounted read-only, so Superset only needs to read it.
PREVENT_UNSAFE_DB_CONNECTIONS = True
