# Superset demo — promo-margin-lab

A local, reproducible Apache Superset instance over `data/marts/promo.db`
(SQLite, built by `run.py --stage marts`). No warehouse, no credentials.

## Status (honest)

| Item | State |
|---|---|
| Mart SQL, SQLite database, dataset contract | **built and tested** (`tests/test_marts.py`) |
| Compose stack | written, **never run here** — `docker pull` timed out on 2026-10-20 (Docker Hub unreachable) |
| Live instance, Docker-free route | **running and verified** — `superset/bootstrap_local.sh` (pinned Python 3.11 venv) + `superset/provision.py` on `:8088` |
| Exported asset ZIP | **built**: `superset/export/superset-assets.zip`, 21,231 B — 1 database, 4 datasets, 4 charts, 1 dashboard as YAML |
| Static render | **built**: `reports/superset/dashboard.html`, regenerated from the same SQL |

The Docker-free route replaces the compose path rather than documenting it: Docker
Hub is unreachable from this machine, so `bootstrap_local.sh` installs Superset
4.1.2 into `.superset-venv`, upgrades the metadata DB and serves it; `provision.py`
then registers the mart database, four datasets, four charts and one dashboard and
exports the bundle above (the same `/api/v1/assets/export/` endpoint the recipe
below uses). SQL Lab on that instance returns `COUNT(*)=9053` and
`SUM(net_profit)=−17 584 046.0`, the same numbers as `reports/margin.json`.

So do not read the PNG/HTML as "the interactive instance". It is a render, and it
says so in its footer.

## Run it

```bash
cd promo-margin-lab
uv run python run.py --stage marts        # builds data/marts/promo.db + render
cd superset
docker compose up -d
docker compose logs -f superset           # wait for "Booting worker"
open http://localhost:8088                # admin / admin (local demo only)
```

`SUPERSET_SECRET_KEY` is read from the environment; the default is a local-only
placeholder. Nothing here is production-hardened: no Redis, no Celery, no SSO.

If Docker Hub is unreachable, use the route that actually ran here instead:

```bash
cd promo-margin-lab
uv run python run.py --stage marts        # builds data/marts/promo.db + render
bash superset/bootstrap_local.sh          # Superset 4.1.2 in .superset-venv, serves :8088
# in a second shell:
python3 superset/provision.py --db-uri sqlite:///$PWD/data/marts/promo.db
```

## Connect the mart database

```bash
docker compose exec superset \
  superset set-database-uri -a promo-marts -u sqlite:////app/marts/promo.db
```

Or through the UI: *Settings → Database Connections → + Database → Other*,
SQLAlchemy URI `sqlite:////app/marts/promo.db`, **Test connection**, **Connect**.
The file is mounted read-only at `/app/marts`.

## Datasets

Each mart is one saved SQL query, registered as a dataset. Paste the file
contents into **SQL Lab**, run, then **Save → Save dataset**:

| Dataset | SQL file | Grain |
|---|---|---|
| `promo_pnl` | `sql/marts/01_promo_pnl.sql` | category |
| `model_quality` | `sql/marts/02_model_quality.sql` | estimator |
| `guardrails` | `sql/marts/03_guardrails.sql` | week |
| `breakeven_vs_actual` | `sql/marts/04_breakeven_vs_actual.sql` | category |

Why datasets and not raw tables: the dashboard must not be able to drift from
the SQL. A number on a chart has exactly one definition, in `sql/marts/`, and
`tests/test_marts.py` pins it to `reports/ledger.json`.

## Charts and dashboards

Spec: [`dashboards.md`](dashboards.md). Three dashboards — *Promo P&L*, *Model
Quality*, *Guardrails* — plus one row-level-security demo (filter by `format`)
that is described but not yet applied.

## Export

Once the instance is up:

```bash
TOKEN=$(curl -s -X POST http://localhost:8088/api/v1/security/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin","provider":"db","refresh":false}' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')

curl -s -H "Authorization: Bearer $TOKEN" \
  http://localhost:8088/api/v1/assets/export/ -o export/superset-assets.zip
```

The ZIP is a YAML bundle of databases, datasets, charts and dashboards — a
config artefact, not a rendered dashboard. The committed bundle
(`export/superset-assets.zip`, 21,231 B, 11 files) was exported by
`provision.py` from the Docker-free instance after that instance answered the
SQL Lab queries above. It has not been re-imported into a *separate* clean
instance; the verification is on the exporting side, not a round trip.
