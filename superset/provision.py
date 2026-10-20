"""Provision the local Superset instance from SQLite mart tables, then export assets.

Idempotent by name: re-running updates the existing database/datasets/charts
instead of duplicating them. Uses only the standard library so it runs in the
Superset venv without extra dependencies.

    python superset/provision.py --base-url http://localhost:8088 \
        --db-uri sqlite:////abs/path/data/marts/promo.db
"""

from __future__ import annotations

import argparse
import json
import http.cookiejar
import urllib.error
import urllib.request
from pathlib import Path

TABLES = ["promo_waves", "promo_cells", "model_eval", "breakeven"]
CHARTS = [
    {
        "slice_name": "Net profit by category",
        "viz_type": "bar",
        "table": "promo_waves",
        "params": {
            "metrics": [{"expressionType": "SIMPLE", "column": {"column_name": "net_profit"}, "aggregate": "SUM", "label": "SUM(net_profit)"}],
            "groupby": ["category"],
            "row_limit": 20,
            "order_desc": False,
        },
    },
    {
        "slice_name": "Revenue delta by category",
        "viz_type": "bar",
        "table": "promo_waves",
        "params": {
            "metrics": [{"expressionType": "SIMPLE", "column": {"column_name": "revenue_delta"}, "aggregate": "SUM", "label": "SUM(revenue_delta)"}],
            "groupby": ["category"],
            "row_limit": 20,
        },
    },
    {
        "slice_name": "Lift bias by estimator",
        "viz_type": "bar",
        "table": "model_eval",
        "params": {
            "metrics": [{"expressionType": "SIMPLE", "column": {"column_name": "promo_bias_pct"}, "aggregate": "AVG", "label": "AVG(promo_bias_pct)"}],
            "groupby": ["estimator"],
            "row_limit": 10,
        },
    },
    {
        "slice_name": "Weekly net profit",
        "viz_type": "line",
        "table": "promo_waves",
        "params": {
            "metrics": [{"expressionType": "SIMPLE", "column": {"column_name": "net_profit"}, "aggregate": "SUM", "label": "SUM(net_profit)"}],
            "groupby": ["week"],
            "row_limit": 200,
            "x_axis": "week",
        },
    },
]
DASHBOARD = {"dashboard_title": "Promo Margin Lab", "slug": "promo-margin-lab"}


class Client:
    def __init__(self, base: str, username: str, password: str) -> None:
        self.base = base.rstrip("/")
        self.token: str | None = None
        self.csrf: str | None = None
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.login(username, password)

    def _call(self, method: str, path: str, payload: dict | None = None, raw: bool = False):
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(
            f"{self.base}{path}",
            data=data,
            method=method,
            headers={
                "Content-Type": "application/json",
                **({"Authorization": f"Bearer {self.token}"} if self.token else {}),
                **({"X-CSRFToken": self.csrf} if getattr(self, "csrf", None) else {}),
            },
        )
        try:
            with self.opener.open(request, timeout=120) as response:
                body = response.read()
                return body if raw else json.loads(body or b"{}")
        except urllib.error.HTTPError as error:
            detail = error.read().decode(errors="replace")[:500]
            raise SystemExit(f"{method} {path} → {error.code}: {detail}") from error

    def login(self, username: str, password: str) -> None:
        body = self._call(
            "POST",
            "/api/v1/security/login",
            {"username": username, "password": password, "provider": "db", "refresh": True},
        )
        self.token = body["access_token"]
        # CSRF token is required for state-changing calls in 4.x.
        self.csrf = self._call("GET", "/api/v1/security/csrf_token/")["result"]

    def get(self, path: str) -> dict:
        return self._call("GET", path)

    def post(self, path: str, payload: dict) -> dict:
        return self._call("POST", path, payload)


def ensure_database(client: Client, name: str, uri: str) -> int:
    found = client.get("/api/v1/database/?q=(page_size:100)")["result"]
    for row in found:
        if row["database_name"] == name:
            return row["id"]
    created = client.post(
        "/api/v1/database/",
        {
            "database_name": name,
            "sqlalchemy_uri": uri,
            "expose_in_sqllab": True,
            "allow_run_async": False,
        },
    )
    return created["id"]


def ensure_dataset(client: Client, database_id: int, table: str) -> int:
    found = client.get("/api/v1/dataset/?q=(page_size:200)")["result"]
    for row in found:
        if row["table_name"] == table and row["database"]["id"] == database_id:
            return row["id"]
    created = client.post(
        "/api/v1/dataset/",
        {"database": database_id, "schema": None, "table_name": table},
    )
    return created["id"]


def ensure_chart(client: Client, spec: dict, dataset_id: int) -> int:
    found = client.get("/api/v1/chart/?q=(page_size:200)")["result"]
    for row in found:
        if row["slice_name"] == spec["slice_name"]:
            return row["id"]
    created = client.post(
        "/api/v1/chart/",
        {
            "slice_name": spec["slice_name"],
            "viz_type": spec["viz_type"],
            "datasource_id": dataset_id,
            "datasource_type": "table",
            "params": json.dumps(spec["params"]),
        },
    )
    return created["id"]


def dashboard_layout(chart_ids: list[int]) -> str:
    """2x2 grid: the four charts above the fold, in the order they were created."""
    layout: dict = {
        "DASHBOARD_VERSION_KEY": "v2",
        "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"], "parents": []},
        "GRID_ID": {
            "type": "GRID",
            "id": "GRID_ID",
            "children": ["ROW-1", "ROW-2"],
            "parents": ["ROOT_ID"],
        },
        "HEADER_ID": {"type": "HEADER", "id": "HEADER_ID", "meta": {"text": "Promo Margin Lab"}},
    }
    for row, pair in enumerate((chart_ids[:2], chart_ids[2:4]), start=1):
        row_id = f"ROW-{row}"
        children = []
        for chart_id in pair:
            key = f"CHART-{chart_id}"
            children.append(key)
            layout[key] = {
                "type": "CHART",
                "id": key,
                "children": [],
                "parents": ["ROOT_ID", "GRID_ID", row_id],
                "meta": {"chartId": chart_id, "width": 6, "height": 50},
            }
        layout[row_id] = {
            "type": "ROW",
            "id": row_id,
            "children": children,
            "parents": ["ROOT_ID", "GRID_ID"],
            "meta": {"background": "BACKGROUND_TRANSPARENT"},
        }
    return json.dumps(layout)


def ensure_dashboard(client: Client, chart_ids: list[int]) -> int:
    found = client.get("/api/v1/dashboard/?q=(page_size:100)")["result"]
    existing = next((row for row in found if row["slug"] == DASHBOARD["slug"]), None)
    payload = {**DASHBOARD, "position_json": dashboard_layout(chart_ids)}
    if existing:
        identifier = existing["id"]
        client._call("PUT", f"/api/v1/dashboard/{identifier}", payload)
        return identifier
    created = client.post("/api/v1/dashboard/", payload)
    return created["id"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8088")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default="admin")
    parser.add_argument("--db-uri", required=True)
    parser.add_argument("--export", default="superset/export/superset-assets.zip")
    args = parser.parse_args()

    client = Client(args.base_url, args.username, args.password)
    database_id = ensure_database(client, "promo-marts", args.db_uri)
    datasets = {table: ensure_dataset(client, database_id, table) for table in TABLES}
    charts = [ensure_chart(client, spec, datasets[spec["table"]]) for spec in CHARTS]
    dashboard_id = ensure_dashboard(client, charts)
    print(
        json.dumps(
            {
                "database_id": database_id,
                "datasets": datasets,
                "charts": charts,
                "dashboard_id": dashboard_id,
            },
            indent=2,
        )
    )

    export = Path(args.export)
    export.parent.mkdir(parents=True, exist_ok=True)
    body = client._call("GET", "/api/v1/assets/export/", raw=True)
    export.write_bytes(body)
    print(f"exported → {export} ({len(body)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
