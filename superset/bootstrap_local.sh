#!/usr/bin/env bash
# Local Superset without Docker (the build machine could not reach Docker Hub).
# Python 3.11 is required: Superset 4.1 pins numpy 1.23.5, which has no 3.12 wheel.
#
#   bash superset/bootstrap_local.sh          # install + init + run on :8088
#   bash superset/bootstrap_local.sh --init   # install + init, do not run
set -euo pipefail
cd "$(dirname "$0")/.."

VENV=.superset-venv
uv venv --python 3.11 "$VENV"
# python-geohash 0.9.2 needs Rust; 0.8.5 builds with a C compiler.
uv pip install --python "$VENV/bin/python" "apache-superset==4.1.2" "python-geohash==0.8.5"
uv pip install --python "$VENV/bin/python" "setuptools<81"

export SUPERSET_CONFIG_PATH="$PWD/superset/local_superset_config.py"
export FLASK_APP=superset

"$VENV/bin/superset" db upgrade
"$VENV/bin/superset" fab create-admin \
  --username admin --password admin \
  --firstname Admin --lastname User --email admin@example.com || true
"$VENV/bin/superset" init

if [[ "${1:-}" == "--init" ]]; then
  echo "initialised; run: SUPERSET_CONFIG_PATH=$SUPERSET_CONFIG_PATH FLASK_APP=superset $VENV/bin/superset run -p 8088 --with-threads"
  exit 0
fi

"$VENV/bin/superset" run -p 8088 --with-threads
