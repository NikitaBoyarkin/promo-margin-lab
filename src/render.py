"""Static render of the Superset dashboard.

Deliberately a *render*, not a fake interactive app: it is generated from the
same `sql/marts/*.sql` queries the live instance uses, and it says so in the
footer. The live stack is `superset/docker-compose.yml`.
"""

from __future__ import annotations

import html
from pathlib import Path

import pandas as pd


def _money(value: float) -> str:
    sign = "−" if value < 0 else "+"
    return f"{sign}{abs(value) / 1e6:,.1f} m ₽".replace(",", " ")


def _table(frame: pd.DataFrame, columns: dict[str, str], highlight: str | None = None) -> str:
    head = "".join(f"<th>{html.escape(label)}</th>" for label in columns.values())
    rows = []
    for _, row in frame.iterrows():
        cells = []
        for column in columns:
            value = row[column]
            if isinstance(value, float):
                text = (
                    f"{value:,.4f}".rstrip("0").rstrip(".") if abs(value) < 100 else f"{value:,.1f}"
                )
            else:
                text = str(value)
            cls = ""
            if highlight and column == highlight and isinstance(value, (int, float)):
                cls = ' class="neg"' if value < 0 else ' class="pos"'
            cells.append(f"<td{cls}>{html.escape(text)}</td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table>"


def _bars(frame: pd.DataFrame, value: str) -> str:
    width, height, pad = 720, 160, 8
    values = frame[value].to_numpy()
    peak = max(abs(values).max(), 1.0)
    n = len(values)
    bar = (width - 2 * pad) / max(n, 1)
    zero = height / 2
    parts = []
    for i, v in enumerate(values):
        h = abs(v) / peak * (height / 2 - pad)
        y = zero - h if v >= 0 else zero
        color = "#4ade80" if v >= 0 else "#f87171"
        x = pad + i * bar
        parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{max(bar - 1, 1):.1f}" '
            f'height="{h:.1f}" fill="{color}" opacity="0.85"/>'
        )
    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="weekly profit">'
        f'<line x1="{pad}" y1="{zero}" x2="{width - pad}" y2="{zero}" stroke="#3f3f46"/>'
        f"{''.join(parts)}</svg>"
    )


def render(
    results: dict[str, pd.DataFrame],
    headline: dict,
    path: Path,
    seed: int,
    panel_hash: str,
) -> Path:
    pnl = results["promo_pnl"]
    quality = results["model_quality"]
    guard = results["guardrails"]
    gap = results["breakeven_vs_actual"]

    cards = [
        ("Инкрементальная выручка", _money(headline["revenue_delta_rub"]), "pos"),
        ("Инкрементальная прибыль", _money(headline["net_profit_rub"]), "neg"),
        ("Волн с отрицательной прибылью", f"{headline['share_negative']:.1%}", "neg"),
        ("Категорий выше потолка глубины", f"{headline['categories_beyond_ceiling']} / 6", "neg"),
    ]
    card_html = "".join(
        f'<div class="card"><div class="label">{html.escape(label)}</div>'
        f'<div class="value {cls}">{html.escape(value)}</div></div>'
        for label, value, cls in cards
    )

    page = f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Promo Margin Lab — dashboard (static render)</title>
<style>
 :root {{ color-scheme: dark; }}
 body {{ margin:0; background:#0b0b0f; color:#e4e4e7;
        font:14px/1.5 ui-sans-serif, -apple-system, "Segoe UI", sans-serif; }}
 main {{ max-width: 1080px; margin: 0 auto; padding: 48px 24px 64px; }}
 h1 {{ font-size: 26px; margin: 0 0 6px; letter-spacing:-0.02em; }}
 h2 {{ font-size: 15px; margin: 40px 0 12px; color:#a1a1aa; text-transform:uppercase;
       letter-spacing:0.08em; font-weight:600; }}
 .sub {{ color:#a1a1aa; margin:0 0 8px; }}
 .note {{ border-left:3px solid #f59e0b; padding:8px 12px; color:#d4d4d8;
          background:#18181b; margin:16px 0 0; font-size:13px; }}
 .cards {{ display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-top:28px; }}
 .card {{ background:#131317; border:1px solid #27272a; border-radius:10px; padding:16px; }}
 .label {{ color:#a1a1aa; font-size:12px; }}
 .value {{ font-size:22px; font-weight:650; margin-top:6px; font-variant-numeric:tabular-nums; }}
 .pos {{ color:#4ade80; }} .neg {{ color:#f87171; }}
 table {{ width:100%; border-collapse:collapse; background:#131317;
          border:1px solid #27272a; border-radius:10px; overflow:hidden; }}
 th, td {{ padding:9px 12px; text-align:right; border-bottom:1px solid #1f1f23;
           font-variant-numeric:tabular-nums; }}
 th {{ color:#a1a1aa; font-weight:600; font-size:12px; text-transform:uppercase;
       letter-spacing:0.04em; }}
 th:first-child, td:first-child {{ text-align:left; }}
 tbody tr:last-child td {{ border-bottom:none; }}
 td.pos, td.neg {{ font-weight:600; }}
 svg {{ width:100%; height:auto; background:#131317; border:1px solid #27272a;
        border-radius:10px; padding:12px; box-sizing:border-box; }}
 footer {{ margin-top:40px; color:#71717a; font-size:12px; }}
 code {{ color:#d4d4d8; }}
 @media (max-width: 760px) {{ .cards {{ grid-template-columns:repeat(2,1fr); }} }}
</style></head><body><main>
<h1>Promo Margin Lab</h1>
<p class="sub">Промо-экономика офлайн-ритейла: лифт, каннибализация, маржа, потолок глубины.</p>
<div class="note">Это <strong>статический рендер</strong>, а не интерактивная Superset-инстанция.
Все числа получены запросами <code>sql/marts/*.sql</code> к <code>data/marts/promo.db</code>.
Живой стек — <code>superset/docker-compose.yml</code>.</div>

<div class="cards">{card_html}</div>

<h2>Промо P&L по категориям</h2>
{
        _table(
            pnl,
            {
                "category": "Категория",
                "waves": "Волн",
                "net_units": "Net, юниты",
                "revenue_delta": "Выручка, ₽",
                "discount_cost": "Скидка, ₽",
                "net_profit": "Прибыль, ₽",
                "share_negative": "Доля убыточных",
            },
            highlight="net_profit",
        )
    }

<h2>Прибыль по неделям</h2>
{_bars(guard, "net_profit")}

<h2>Качество контрфактуала</h2>
{
        _table(
            quality,
            {
                "estimator": "Оценщик",
                "wape": "WAPE базы",
                "lift_bias": "Смещение лифта",
                "placebo_p05": "Placebo p05",
                "placebo_p50": "p50",
                "placebo_p95": "p95",
            },
            highlight="lift_bias",
        )
    }

<h2>Потолок глубины против факта</h2>
{
        _table(
            gap,
            {
                "category": "Категория",
                "cm_rate": "CM",
                "supplier_funding": "Funding",
                "breakeven_depth": "Breakeven",
                "actual_depth": "Факт",
                "depth_over_ceiling": "Выше потолка",
                "beyond_ceiling": "Флаг",
            },
            highlight="depth_over_ceiling",
        )
    }

<footer>seed {seed} · panel {html.escape(panel_hash)} · собрано из
<code>reports/ledger.json</code>, <code>reports/margin.json</code>,
<code>reports/baseline.json</code> через SQL-марты. Данные синтетические.</footer>
</main></body></html>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page, encoding="utf-8")
    return path
