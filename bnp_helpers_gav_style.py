# -*- coding: utf-8 -*-
"""
bnp_helpers_gav_style.py  (v2.0 - shared GAV-style control template)

Shared rendering + packaging helpers so every "GAV-style" control (UUT Material
Price MVT, Stale Price Check, Advisor Return Check, Advisor-UUT Check,
Investment Clearing, Cash Clearing, Negative NAV, Portfolios reconciliation)
renders with the SAME 8-part pattern agreed with the reviewer, using the
existing GAV Check panel as the reference:

  1. concise purpose and scope statement
  2. four population headers, all four genuinely meaningful for that control
  3. "Download full pack" button
  4. red investigation dataframe (one or more - some controls need more than
     one red population, e.g. Portfolios reconciliation: missing + unmapped)
  5. green OK dataframe
  6. neutral excluded dataframe
  7. invariant between population, checks (red), OK (green) and excluded totals
  8. full evidence pack retaining inclusion status and exclusion reason

Decisions confirmed with the reviewer (2026-08):
  Q1 (v359). The excluded population IS included in the full-pack download.
  Q2 (v359). Multiple exception types => multiple separate red dataframes.
  Q3 (v359). The full pack is ONE TAB (single sheet), not multi-sheet.
  v360 additions:
  - $ numbers formatted as $ to 2dp, % numbers formatted as % to 2dp, BOTH on
    screen (st.dataframe) and in the full-pack / red / green / excluded
    downloads (actual formatted strings, not just cosmetic display).
  - Paired "In <Control> population" (bool) + "<Control> scope" (text:
    "Included" / "Excluded: <reason>") columns, mirroring GAV Check's existing
    "In GAV Check population" / "GAV Check scope" pair.
  - "Human in the Loop comment" (blank, for manual annotation) and "Username"
    (blank, display-only for now) columns on every red/green/excluded/full
    frame.
  - Standardised final status column named "Check" (values Check/Ok/Excluded)
    across all controls, with each control's original/native status column
    name retained alongside it as "<original name> (legacy label)" so nothing
    downstream that keyed off the old column name breaks.
  - Control-branded section headers and download-button text, e.g.
    "UUT Material Price MVT checks requiring investigation (N)",
    "Download full UUT Material Price MVT pack".

This module is intentionally Streamlit-light (only the render function touches
`st`) and framework-light (no imports from bnp_control_app), so it can be
imported from any helper module without circular-import risk.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from io import BytesIO

import pandas as pd

GAV_STYLE_VERSION = "v2.1"

STATUS_CHECK = "Check"
STATUS_OK = "Ok"
STATUS_EXCLUDED = "Excluded"

COMMENT_COL = "Human in the Loop comment"
USERNAME_COL = "Username"


# ---------------------------------------------------------------------------
# Result container
# ---------------------------------------------------------------------------
@dataclass
class GavStyleResult:
    """Standard result shape for a GAV-style control.

    red_frames: list of (label, dataframe) - USUALLY one entry, but a control
        with more than one exception type (Portfolios reconciliation: missing
        from BNP vs unmapped in BNP) supplies one entry PER exception type so
        they are never merged into a single red table (Q2).
    green_df: the OK / passed population.
    excluded_df: the population explicitly outside scope (with a reason).
    full_df: ONE dataframe containing every row (population + excluded) with
        'Population Status', 'Inclusion Reason' and 'Exclusion Reason' columns
        - this is what the "Download full pack" button exports (Q1 + Q3).
    population_metrics: up to 4 (label, value) pairs for the header metrics.
    invariant_ok / invariant_detail: population = sum(red) + green (+ excluded
        reported separately, per Q1 - excluded sits outside the Check/Ok
        equation but is always retained in the full pack).
    status: "OK" or a short reason the control could not run this session.
    currency_cols: column names to render/export as "$#,##0.00".
    percent_cols: column names to render/export as "0.00%" where the STORED
        value is a DECIMAL (e.g. 0.0123 -> "1.23%"; multiplied by 100). Use
        for genuinely decimal-scaled fields (e.g. GAV's "% impact").
    already_percent_cols: v361 - column names to render/export as "0.00%"
        where the STORED value is ALREADY IN PERCENT UNITS (e.g. 14.52 meaning
        14.52% -> "14.52%"; NOT multiplied by 100). Use for fields sourced
        directly from a percent-unit calculation (e.g. Advisor Return Check's
        Unison Return / Benchmark / Tolerance, which are computed and stored
        in percent, not decimal). Confusing a decimal column for an
        already-percent column (or vice versa) causes a 100x display error -
        this split exists specifically to prevent that class of bug.
    population_bool_col: name of an existing boolean column (e.g. "In UUT
        population") used to derive the paired "<control_noun> scope" text
        column ("Included" / "Excluded: <reason>"), mirroring GAV Check.
    control_noun: short control name used to brand metric/section labels and
        the scope column (e.g. "UUT Material Price MVT", "Stale Price Check").
    """
    red_frames: List[Tuple[str, pd.DataFrame]] = field(default_factory=list)
    green_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    excluded_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    full_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    population_metrics: List[Tuple[str, Any]] = field(default_factory=list)
    invariant_ok: bool = True
    invariant_detail: str = ""
    status: str = "OK"
    diag: Dict[str, Any] = field(default_factory=dict)
    currency_cols: List[str] = field(default_factory=list)
    percent_cols: List[str] = field(default_factory=list)
    already_percent_cols: List[str] = field(default_factory=list)
    population_bool_col: Optional[str] = None
    control_noun: str = ""


# ---------------------------------------------------------------------------
# Invariant helper
# ---------------------------------------------------------------------------
def compute_invariant(population: int, red_counts: List[int], green_count: int) -> Tuple[bool, str]:
    """population = sum(red_counts) + green_count. Excluded is NOT part of this
    equation (it sits outside the tested population by definition), but is
    always shown and always retained in the full pack (Q1)."""
    total_red = int(sum(int(x) for x in red_counts))
    ok = int(population) == int(total_red + green_count)
    red_label = " + ".join(str(x) for x in red_counts) if len(red_counts) > 1 else str(total_red)
    detail = (f"Population ({int(population):,}) = Check ({red_label}) + Ok ({int(green_count):,}) "
              f"= {int(total_red + green_count):,}. {'OK' if ok else 'MISMATCH'}")
    return ok, detail


# ---------------------------------------------------------------------------
# v360: $ / % formatting - applied identically on screen and in downloads
# ---------------------------------------------------------------------------
def _fmt_currency(v: Any) -> str:
    try:
        if pd.isna(v):
            return ""
        n = float(v)
        sign = "-" if n < 0 else ""
        return f"{sign}${abs(n):,.2f}"
    except Exception:
        return "" if v is None else str(v)


def _fmt_percent(v: Any) -> str:
    """DECIMAL-scaled -> percent string (0.0123 -> '1.23%'). See
    GavStyleResult.percent_cols docstring."""
    try:
        if pd.isna(v):
            return ""
        n = float(v)
        return f"{n * 100:,.2f}%"
    except Exception:
        return "" if v is None else str(v)


def _fmt_percent_already(v: Any) -> str:
    """v361: ALREADY-PERCENT-scaled -> percent string (14.52 -> '14.52%'), i.e.
    NO x100 multiplication. See GavStyleResult.already_percent_cols docstring -
    this exists specifically to fix the Advisor Return Check x100 display bug
    (its Unison Return / Benchmark / Tolerance / Variance fields are computed
    and stored in percent units, not decimal)."""
    try:
        if pd.isna(v):
            return ""
        n = float(v)
        return f"{n:,.2f}%"
    except Exception:
        return "" if v is None else str(v)


def apply_number_formatting(df: pd.DataFrame, currency_cols: Optional[List[str]] = None,
                             percent_cols: Optional[List[str]] = None,
                             already_percent_cols: Optional[List[str]] = None) -> pd.DataFrame:
    """Return a COPY of df with currency_cols formatted as "$#,##0.00" strings,
    percent_cols (DECIMAL-scaled, x100 applied) formatted as "0.00%" strings,
    and already_percent_cols (ALREADY IN PERCENT UNITS, no x100) formatted as
    "0.00%" strings. Non-numeric/blank values are passed through safely.
    Applied identically for on-screen display and for the Excel/CSV downloads,
    per the reviewer's Q1 (2026-08) request. v361: split percent_cols into two
    modes to fix a 100x display bug where an already-percent field (e.g.
    Advisor Return Check's Tolerance, stored as 25.0 meaning 25%) was
    incorrectly treated as decimal (multiplied by 100 again -> 2500.00%)."""
    if not isinstance(df, pd.DataFrame) or df.empty:
        return df
    out = df.copy()
    for col in (currency_cols or []):
        if col in out.columns:
            out[col] = out[col].map(_fmt_currency)
    for col in (percent_cols or []):
        if col in out.columns:
            out[col] = out[col].map(_fmt_percent)
    for col in (already_percent_cols or []):
        if col in out.columns:
            out[col] = out[col].map(_fmt_percent_already)
    return out


# ---------------------------------------------------------------------------
# v360: paired "In <Control> population" (bool) + "<Control> scope" (text)
# ---------------------------------------------------------------------------
def add_scope_column(df: pd.DataFrame, population_bool_col: Optional[str], control_noun: str,
                      exclusion_reason_col: str = "Exclusion Reason") -> pd.DataFrame:
    """Mirrors GAV Check's paired 'In GAV Check population' (bool) / 'GAV Check
    scope' (text: 'Included' / 'Excluded: <reason>') columns for every other
    GAV-style control. No-op if population_bool_col isn't present in df."""
    if not isinstance(df, pd.DataFrame) or df.empty or not population_bool_col or not control_noun:
        return df
    if population_bool_col not in df.columns:
        return df
    out = df.copy()
    scope_col = f"{control_noun} scope"
    included = out[population_bool_col].astype("boolean").fillna(False).astype(bool)
    reason = out[exclusion_reason_col].astype(str) if exclusion_reason_col in out.columns else pd.Series([""] * len(out), index=out.index)
    scope = pd.Series("Included", index=out.index, dtype=object)
    excl_mask = ~included
    scope.loc[excl_mask] = reason.loc[excl_mask].apply(lambda r: f"Excluded: {r}" if str(r).strip() else "Excluded")
    out[scope_col] = scope
    return out


# ---------------------------------------------------------------------------
# v360: Human in the Loop comment + Username (blank, display-only for now)
# ---------------------------------------------------------------------------
def add_annotation_columns(df: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(df, pd.DataFrame) or df.empty:
        return df
    out = df.copy()
    if COMMENT_COL not in out.columns:
        out[COMMENT_COL] = ""
    if USERNAME_COL not in out.columns:
        out[USERNAME_COL] = ""
    return out


# ---------------------------------------------------------------------------
# Full-pack builder - ONE TAB for everything (Q3), excluded rows retained (Q1)
# ---------------------------------------------------------------------------
def build_full_pack_df(
    green_df: pd.DataFrame,
    red_frames: List[Tuple[str, pd.DataFrame]],
    excluded_df: pd.DataFrame,
    *,
    status_col: str = "Population Status",
    inclusion_reason_col: str = "Inclusion Reason",
    exclusion_reason_col: str = "Exclusion Reason",
) -> pd.DataFrame:
    """Stack green + all red frames + excluded into ONE dataframe (one tab),
    tagging every row with its Population Status and inclusion/exclusion
    reason so the full pack is fully self-describing without needing the
    on-screen colour coding."""
    parts: List[pd.DataFrame] = []

    def _tag(df: pd.DataFrame, status_label: str, inc_reason: str = "", exc_reason: str = "") -> pd.DataFrame:
        if not isinstance(df, pd.DataFrame) or df.empty:
            return pd.DataFrame()
        out = df.copy()
        out[status_col] = status_label
        if inclusion_reason_col not in out.columns:
            out[inclusion_reason_col] = inc_reason
        else:
            out[inclusion_reason_col] = out[inclusion_reason_col].where(
                out[inclusion_reason_col].astype(str).str.strip().ne(""), inc_reason
            )
        if exclusion_reason_col not in out.columns:
            out[exclusion_reason_col] = exc_reason
        else:
            out[exclusion_reason_col] = out[exclusion_reason_col].where(
                out[exclusion_reason_col].astype(str).str.strip().ne(""), exc_reason
            )
        return out

    if isinstance(green_df, pd.DataFrame) and not green_df.empty:
        parts.append(_tag(green_df, STATUS_OK, inc_reason="In tested population; within tolerance"))
    for label, rdf in (red_frames or []):
        if isinstance(rdf, pd.DataFrame) and not rdf.empty:
            parts.append(_tag(rdf, str(label or STATUS_CHECK), inc_reason=f"In tested population; flagged ({label})"))
    if isinstance(excluded_df, pd.DataFrame) and not excluded_df.empty:
        parts.append(_tag(excluded_df, STATUS_EXCLUDED, exc_reason="See Exclusion Reason column"))

    if not parts:
        return pd.DataFrame(columns=[status_col, inclusion_reason_col, exclusion_reason_col])

    # Union of columns across all parts, status/reason columns pinned last-ish but present everywhere.
    all_cols: List[str] = []
    for p in parts:
        for c in p.columns:
            if c not in all_cols:
                all_cols.append(c)
    parts = [p.reindex(columns=all_cols) for p in parts]
    return pd.concat(parts, ignore_index=True, sort=False)


def build_full_pack_bytes(full_df: pd.DataFrame, sheet_name: str = "Full Pack",
                           currency_cols: Optional[List[str]] = None,
                           percent_cols: Optional[List[str]] = None,
                           already_percent_cols: Optional[List[str]] = None) -> bytes:
    """ONE-TAB workbook (single sheet) for the 'Download full pack' button (Q3).
    v360: currency_cols / percent_cols are formatted as actual "$#,##0.00" /
    "0.00%" strings baked into the exported cells (not just on-screen).
    v361: already_percent_cols added (see apply_number_formatting) to fix the
    100x display bug on fields already stored in percent units."""
    output = BytesIO()
    df = full_df.copy() if isinstance(full_df, pd.DataFrame) else pd.DataFrame()
    df = apply_number_formatting(df, currency_cols, percent_cols, already_percent_cols)
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        (df if not df.empty else pd.DataFrame(columns=["No data"])).to_excel(
            writer, sheet_name=sheet_name[:31] or "Full Pack", index=False
        )
        try:
            ws = writer.book[sheet_name[:31] or "Full Pack"]
            ws.freeze_panes = "A2"
            for cells in ws.columns:
                try:
                    width = max(len(str(c.value or "")) for c in cells[:250]) + 2
                    ws.column_dimensions[cells[0].column_letter].width = min(max(width, 10), 60)
                except Exception:
                    pass
        except Exception:
            pass
    return output.getvalue()


# ---------------------------------------------------------------------------
# Styler helpers - light, accessible, solid colours (mirrors the GAV pattern)
# ---------------------------------------------------------------------------
RED_BG = "#FDECEA"     # light red
GREEN_BG = "#E9F7EF"   # light green
NEUTRAL_BG = "#F1F2F6"  # light grey


def _solid_style(df: pd.DataFrame, colour: str):
    try:
        return df.style.set_properties(**{"background-color": colour, "color": "#1f2937"})
    except Exception:
        return df


def _prepare_display_df(df: pd.DataFrame, result: "GavStyleResult", exclusion_reason_col: str = "Exclusion Reason") -> pd.DataFrame:
    """v360: apply $ / % formatting + paired scope column + Human in the Loop
    comment / Username columns identically for on-screen display and for the
    per-frame CSV download buttons."""
    out = add_scope_column(df, result.population_bool_col, result.control_noun, exclusion_reason_col)
    out = apply_number_formatting(out, result.currency_cols, result.percent_cols, result.already_percent_cols)
    out = add_annotation_columns(out)
    return out


# ---------------------------------------------------------------------------
# Shared renderer
# ---------------------------------------------------------------------------
def render_gav_style_section(
    st,
    *,
    control_key: str,
    title: str,
    purpose: str,
    result: GavStyleResult,
    download_filename_prefix: str,
) -> None:
    """Render one GAV-style control using the standard 8-part layout.

    `control_key` is only used to build unique Streamlit widget keys so
    multiple controls can render on the same page without key collisions.
    """
    st.markdown(f"**{title}**")
    st.caption(purpose)

    if result.status != "OK":
        st.warning(f"{title} unavailable: {result.status}")
        return

    noun = result.control_noun or title

    # --- 2. four population headers -----------------------------------
    metrics = list(result.population_metrics or [])[:4]
    if metrics:
        cols = st.columns(len(metrics))
        for c, (label, value) in zip(cols, metrics):
            c.metric(label, value)

    # --- 3. Download full pack (v360: $/% formatted, scope + annotation cols) --
    try:
        full_export = add_scope_column(result.full_df, result.population_bool_col, noun)
        full_export = add_annotation_columns(full_export)
        pack_bytes = build_full_pack_bytes(
            full_export, sheet_name=f"{control_key} Full Pack",
            currency_cols=result.currency_cols, percent_cols=result.percent_cols,
            already_percent_cols=result.already_percent_cols,
        )
        st.download_button(
            f"Download full {noun} pack",
            data=pack_bytes,
            file_name=f"{download_filename_prefix}_full_pack.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key=f"gavstyle_fullpack_{control_key}",
        )
    except Exception as exc:
        st.caption(f"Full pack download unavailable: {type(exc).__name__}: {exc}")

    # --- 4. red investigation dataframe(s) - Q2: kept separate ----------
    for i, (label, rdf) in enumerate(result.red_frames or []):
        header_label = f"{noun} {label.lower()} requiring investigation" if label.lower() != "check" else f"{noun} checks requiring investigation"
        st.markdown(f"##### {header_label} ({len(rdf):,})" if isinstance(rdf, pd.DataFrame) else f"##### {header_label}")
        if isinstance(rdf, pd.DataFrame) and not rdf.empty:
            disp = _prepare_display_df(rdf, result)
            try:
                st.dataframe(_solid_style(disp, RED_BG), width="stretch", hide_index=True)
            except Exception:
                st.dataframe(disp, width="stretch", hide_index=True)
            st.download_button(
                f"Download {label}",
                data=disp.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"{download_filename_prefix}_{label.lower().replace(' ', '_')}.csv",
                mime="text/csv",
                key=f"gavstyle_red_{control_key}_{i}",
            )
        else:
            st.caption(f"No {label.lower()} rows for the selected date.")

    # --- 5. green OK dataframe -------------------------------------------
    st.markdown(f"##### {noun} checks OK ({len(result.green_df):,})" if isinstance(result.green_df, pd.DataFrame) else f"##### {noun} checks OK")
    if isinstance(result.green_df, pd.DataFrame) and not result.green_df.empty:
        disp_green = _prepare_display_df(result.green_df, result)
        try:
            st.dataframe(_solid_style(disp_green, GREEN_BG), width="stretch", hide_index=True)
        except Exception:
            st.dataframe(disp_green, width="stretch", hide_index=True)
    else:
        st.caption("No OK rows for the selected date.")

    # --- 6. neutral excluded dataframe -----------------------------------
    st.markdown(
        f"##### {noun} excluded ({len(result.excluded_df):,})" if isinstance(result.excluded_df, pd.DataFrame) else f"##### {noun} excluded"
    )
    if isinstance(result.excluded_df, pd.DataFrame) and not result.excluded_df.empty:
        disp_excl = _prepare_display_df(result.excluded_df, result)
        try:
            st.dataframe(_solid_style(disp_excl, NEUTRAL_BG), width="stretch", hide_index=True)
        except Exception:
            st.dataframe(disp_excl, width="stretch", hide_index=True)
        st.caption("Excluded rows are outside the tested population (see Exclusion Reason). "
                   "They are NOT part of the Check/Ok invariant below, but ARE retained in the full pack (Q1).")
    else:
        st.caption("No excluded rows for the selected date.")

    # --- 7. invariant ------------------------------------------------------
    if result.invariant_ok:
        st.success("Invariant holds: " + str(result.invariant_detail))
    else:
        st.error("Invariant FAILED: " + str(result.invariant_detail))


__all__ = [
    "GAV_STYLE_VERSION",
    "STATUS_CHECK", "STATUS_OK", "STATUS_EXCLUDED",
    "COMMENT_COL", "USERNAME_COL",
    "GavStyleResult",
    "compute_invariant",
    "apply_number_formatting",
    "add_scope_column",
    "add_annotation_columns",
    "build_full_pack_df",
    "build_full_pack_bytes",
    "render_gav_style_section",
]


if __name__ == "__main__":
    print(f"[{GAV_STYLE_VERSION}] gav_style self-test")
    green = pd.DataFrame({"Portfolio code": ["M1AAA", "M1BBB"], "Value": [1.0, 2.5], "Pct": [0.01, 0.02],
                          "In Test population": [True, True], "Exclusion Reason": ["", ""]})
    red = pd.DataFrame({"Portfolio code": ["M1CCC"], "Value": [99.123], "Pct": [0.05],
                        "In Test population": [True], "Exclusion Reason": [""]})
    excluded = pd.DataFrame({"Portfolio code": ["M1TRE"], "Value": [0.0], "Pct": [0.0],
                             "In Test population": [False], "Exclusion Reason": ["Treasury"]})
    full = build_full_pack_df(green, [("Check", red)], excluded)
    assert set(full["Population Status"]) == {"Ok", "Check", "Excluded"}

    # v360 formatting checks
    fmt = apply_number_formatting(full, currency_cols=["Value"], percent_cols=["Pct"])
    assert fmt.loc[fmt["Portfolio code"] == "M1CCC", "Value"].iloc[0] == "$99.12"
    assert fmt.loc[fmt["Portfolio code"] == "M1AAA", "Pct"].iloc[0] == "1.00%"
    print("  $/% formatting OK:", fmt[["Portfolio code", "Value", "Pct"]].to_string(index=False))

    # v361: already_percent_cols - value stored AS percent (e.g. 25.0 -> "25.00%"),
    # confirming NO double x100 scaling (the Advisor Return Check bug fix).
    already_pct = pd.DataFrame({"Portfolio code": ["M1AAA", "M1BBB"], "Tolerance": [25.0, 0.0]})
    fmt2 = apply_number_formatting(already_pct, already_percent_cols=["Tolerance"])
    assert fmt2.loc[fmt2["Portfolio code"] == "M1AAA", "Tolerance"].iloc[0] == "25.00%"
    assert fmt2.loc[fmt2["Portfolio code"] == "M1BBB", "Tolerance"].iloc[0] == "0.00%"
    print("  already_percent_cols OK (no double x100 scaling):", fmt2.to_string(index=False))

    scoped = add_scope_column(full, "In Test population", "Test")
    assert scoped.loc[scoped["Portfolio code"] == "M1TRE", "Test scope"].iloc[0] == "Excluded: Treasury"
    assert scoped.loc[scoped["Portfolio code"] == "M1AAA", "Test scope"].iloc[0] == "Included"
    print("  scope column OK")

    annotated = add_annotation_columns(full)
    assert COMMENT_COL in annotated.columns and USERNAME_COL in annotated.columns
    print("  Human in the Loop comment / Username columns OK")

    ok, detail = compute_invariant(population=3, red_counts=[1], green_count=2)
    assert ok, detail
    pack = build_full_pack_bytes(full, currency_cols=["Value"], percent_cols=["Pct"])
    assert len(pack) > 0
    print("  OK - v2.0 full pack built with $/% formatting, invariant holds, single-tab workbook produced")
