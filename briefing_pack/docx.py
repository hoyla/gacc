"""Docx output for the briefing pack — parallel surface to `03_Findings.md`.

Lisa-facing surface. The markdown stays canonical (NotebookLM-feed,
per `memory/architecture_journalist_surfaces.md` — keep LLM output /
interpretation OUTSIDE documents downstream LLM tools will read).
Verified Drive → Google Docs round-trip fidelity 2026-05-16; see
`dev_notes/2026-05-16_docx-drive-spike.md`.

Architecture (v4, 2026-05-16 evening — full markdown-content parity):

1. Render the canonical `findings.md` via `briefing_pack.render.render()`.
2. Compute the top-N movers and build a PNG chart for each — same
   24-month rolling-window line chart shape as v1.
3. Hand both into `MarkdownToDocxTranslator` from `briefing_pack.md_to_docx`,
   which walks the markdown AST and emits the equivalent docx blocks.
   Charts inject after the top-N list items via a finding/{id} → PNG
   lookup callable.
4. Apply A4 portrait + 10mm margins page setup (spike-verified).
5. Save.

The output is therefore *the same content as the .md* (Tier 1 diff,
Tier 2 state-of-play, mirror gaps, partner share, trajectories,
methodology footer, sources appendix) *plus charts at top-N movers*.

v1 (this module's earlier shape) shipped a chart-bearing top-N
extract; v4 replaces it with full content parity. The single
`render_findings_docx` entry point is what callers use.
"""

from __future__ import annotations

import io
import logging
import math
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # non-interactive backend; deterministic on a
                       # given host. See dev_notes design doc step 5
                       # for the known cross-host determinism caveat.

# Silence matplotlib's "Using categorical units to plot a list of
# strings..." INFO logs. We deliberately plot month labels (strings)
# on a categorical x-axis; matplotlib's heuristic flags this as
# "did you mean to parse them as dates?" every time. Harmless but
# spammy — once per chart × 10 charts per run × every run.
logging.getLogger("matplotlib.category").setLevel(logging.WARNING)

import matplotlib.pyplot as plt
import psycopg2.extras
from docx import Document
from docx.shared import Mm, Pt

from briefing_pack._helpers import (
    DEFAULT_TOP_N,
    _compute_predictability_per_group,
    _compute_top_movers,
    _conn,
)
from briefing_pack.md_to_docx import MarkdownToDocxTranslator

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Page-setup constants — values verified by the 2026-05-16 docx fidelity
# spike to round-trip cleanly through Drive → Google Docs.
# ---------------------------------------------------------------------------

_PAGE_WIDTH_MM = 210     # A4 portrait
_PAGE_HEIGHT_MM = 297    # A4 portrait
_MARGIN_MM = 10          # all four sides
_BODY_FONT_PT = 11
_CHART_WIDTH_MM = 190    # 210 - 2×10 usable width

# EU-27 reporter exclusion (matches anomalies.EU27_EXCLUDE_REPORTERS).
_EU27_EXCLUDE_REPORTERS = ("GB",)

_MONTH_LABEL = {
    1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
    7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec",
}


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def _months_back(d: date, n: int) -> date:
    """Return `date(d - n months, day=1)`. 23 months back from 2026-02-01
    → 2024-03-01."""
    total = d.year * 12 + (d.month - 1) - n
    return date(total // 12, (total % 12) + 1, 1)


def _month_iter(start: date, end: date):
    """Yield consecutive month-anchored dates from `start` to `end` inclusive."""
    cur = date(start.year, start.month, 1)
    end_anchor = date(end.year, end.month, 1)
    while cur <= end_anchor:
        yield cur
        cur = (
            date(cur.year + 1, 1, 1) if cur.month == 12
            else date(cur.year, cur.month + 1, 1)
        )


# ---------------------------------------------------------------------------
# Data fetch — finding detail + monthly chart series
# ---------------------------------------------------------------------------

def _fetch_finding_detail(cur, finding_id: int) -> dict | None:
    """Load the full `detail` JSONB for a finding by id."""
    cur.execute(
        "SELECT detail FROM findings WHERE id = %s",
        (finding_id,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return row[0] if not isinstance(row, dict) else row["detail"]


def _fetch_monthly_eur_series(
    cur,
    *,
    hs_patterns: list[str],
    flow: int,
    partners: list[str],
    start: date,
    end: date,
) -> dict[date, float]:
    """Return {month_date: value_eur} summing `eurostat_raw_rows`.

    Matches the filter shape of `_hs_group_top_cn8s` in `anomalies.py`:
    flow ∈ {1=import, 2=export}, partners filter, HS pattern OR-LIKE,
    EU-27 reporter exclusion."""
    if not hs_patterns:
        return {}
    like_clause = "(" + " OR ".join(
        ["product_nc LIKE %s"] * len(hs_patterns)
    ) + ")"
    sql = f"""
        SELECT date_trunc('month', period)::date AS month,
               SUM(value_eur)::float8 AS value_eur
          FROM eurostat_raw_rows
         WHERE period >= %s AND period <= %s
           AND flow = %s
           AND partner = ANY(%s)
           AND {like_clause}
           AND reporter <> ALL(%s)
      GROUP BY 1
      ORDER BY 1
    """
    params = (
        start, end, flow, list(partners),
        *hs_patterns,
        list(_EU27_EXCLUDE_REPORTERS),
    )
    cur.execute(sql, params)
    return {r[0]: float(r[1] or 0.0) for r in cur.fetchall()}


# ---------------------------------------------------------------------------
# Chart rendering
# ---------------------------------------------------------------------------

def _pick_eur_scale(max_value: float) -> tuple[float, str]:
    """Pick a divisor + label for a y-axis based on the series' max."""
    if max_value >= 1e9:
        return 1e9, "€ billions"
    if max_value >= 1e6:
        return 1e6, "€ millions"
    if max_value >= 1e3:
        return 1e3, "€ thousands"
    return 1.0, "€"


def _flow_label_for_subkind(subkind: str) -> str:
    if subkind.endswith("_export"):
        return "EU-27 exports (reporter→CN)"
    return "EU-27 imports (CN→reporter)"


def _build_chart_png(
    *,
    current_end: date,
    monthly_eur: dict[date, float],
    group_name: str,
    flow_label: str,
) -> bytes:
    """Render a 24-month line chart, prior-12mo grey vs current-12mo red."""
    start = _months_back(current_end, 23)
    months = list(_month_iter(start, current_end))
    values = [monthly_eur.get(m, float("nan")) for m in months]

    prior_vals = values[:12]
    current_vals = [float("nan")] * 11 + values[11:]
    labels = [
        f"{_MONTH_LABEL[m.month]} {m.year % 100:02d}" for m in months
    ]

    scale, unit_label = _pick_eur_scale(
        max((v for v in values if not math.isnan(v)), default=0.0)
    )
    prior_scaled = [v / scale if not math.isnan(v) else float("nan")
                    for v in prior_vals]
    current_scaled = [v / scale if not math.isnan(v) else float("nan")
                      for v in current_vals]

    fig, ax = plt.subplots(figsize=(7.5, 3.2), dpi=150)
    ax.plot(
        labels[:12], prior_scaled,
        label="Prior 12mo", linewidth=2, color="#888888",
    )
    ax.plot(
        labels, current_scaled,
        label="Current 12mo", linewidth=2.5, color="#cc3333",
    )
    ax.set_title(
        f"{group_name} — {flow_label}", fontsize=11, loc="left",
    )
    ax.set_ylabel(unit_label, fontsize=9)
    ax.tick_params(axis="x", labelsize=7, rotation=45)
    ax.tick_params(axis="y", labelsize=8)
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best", fontsize=8, frameon=False)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    plt.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


# ---------------------------------------------------------------------------
# Top-movers chart lookup — pre-compute PNGs keyed by finding_id
# ---------------------------------------------------------------------------

def _build_top_mover_charts(
    cur, top_n: int,
) -> dict[int, bytes]:
    """Compute the top-N movers and build a chart PNG for each, keyed
    by finding id. The translator's chart_for_finding callable does
    O(1) lookups against this dict during the markdown walk.

    Returns {finding_id: png_bytes} for every mover where the chart
    data fetch succeeded. Movers with missing detail / no underlying
    raw rows are silently absent — the translator simply doesn't
    inject a chart for those (matching v1's defensive behaviour).
    """
    predictability = _compute_predictability_per_group(cur)
    movers = _compute_top_movers(
        cur, predictability=predictability, limit=top_n,
    )

    charts: dict[int, bytes] = {}
    for m in movers:
        current_end = m["current_end"]
        flow_label = _flow_label_for_subkind(m["subkind"])
        detail = _fetch_finding_detail(cur, m["id"])
        if not detail:
            continue
        method_q = detail.get("method_query", {})
        hs_patterns = (
            method_q.get("hs_patterns")
            or detail.get("group", {}).get("hs_patterns")
            or []
        )
        flow = int(method_q.get("flow") or 0)
        partners = method_q.get("partners") or []
        if not (hs_patterns and flow and partners):
            continue
        series = _fetch_monthly_eur_series(
            cur,
            hs_patterns=hs_patterns,
            flow=flow,
            partners=partners,
            start=_months_back(current_end, 23),
            end=current_end,
        )
        if not series:
            continue
        png = _build_chart_png(
            current_end=current_end,
            monthly_eur=series,
            group_name=m["group_name"],
            flow_label=flow_label,
        )
        charts[m["id"]] = png
    return charts


# ---------------------------------------------------------------------------
# Docx assembly
# ---------------------------------------------------------------------------

def _apply_page_setup(doc: Document) -> None:
    """Apply A4 + 10mm margins + 11pt body to a fresh Document."""
    section = doc.sections[0]
    section.page_height = Mm(_PAGE_HEIGHT_MM)
    section.page_width = Mm(_PAGE_WIDTH_MM)
    section.top_margin = Mm(_MARGIN_MM)
    section.bottom_margin = Mm(_MARGIN_MM)
    section.left_margin = Mm(_MARGIN_MM)
    section.right_margin = Mm(_MARGIN_MM)
    doc.styles["Normal"].font.size = Pt(_BODY_FONT_PT)


def render_findings_docx(
    out_path: str | Path,
    *,
    top_n: int = DEFAULT_TOP_N,
    scope_label: str | None = None,
    companion_filename: str | None = None,
    groups_filename: str | None = None,
) -> Path:
    """Render the full findings.md content into a docx at `out_path`,
    with charts inserted after each top-N mover's list item.

    v4 — full markdown-content parity. The docx now contains the same
    sections as the markdown (period coverage, top movers, Tier 1
    diff, Tier 2 state-of-play, low base, mirror gaps, partner share,
    trajectories, methodology footer, sources appendix) plus charts
    at the top-N movers' list items.

    Returns the resolved Path of the written file.
    """
    # Lazy import to avoid the briefing_pack → docx → md_to_docx →
    # briefing_pack import cycle that would otherwise trip on module
    # initialisation.
    from briefing_pack.render import render

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. Render the canonical markdown. Same call the .md write path uses,
    # so the .docx and .md stay in lock-step content-wise.
    markdown = render(
        top_n=top_n,
        companion_filename=companion_filename,
        groups_filename=groups_filename,
        scope_label=scope_label,
    )

    # 2. Pre-compute chart PNGs for the top movers, keyed by finding_id.
    # The translator's chart-lookup callable will fire on each
    # finding/N token it encounters in a list item.
    with _conn() as conn, conn.cursor(
        cursor_factory=psycopg2.extras.DictCursor,
    ) as cur:
        charts_by_id = _build_top_mover_charts(cur, top_n=top_n)

    # 3. Translate markdown → docx with chart injection.
    doc = Document()
    _apply_page_setup(doc)

    translator = MarkdownToDocxTranslator(
        doc,
        chart_for_finding=charts_by_id.get,
        chart_width_mm=_CHART_WIDTH_MM,
    )
    translator.translate(markdown)

    doc.save(str(out_path))
    log.info(
        "Wrote findings docx to %s (%d charts injected, %d markdown chars)",
        out_path,
        len(charts_by_id),
        len(markdown),
    )
    return out_path


