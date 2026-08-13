# -*- coding: utf-8 -*-
"""
bnp_helpers_price_integrity.py  (v314 - Price integrity: Stale + Material Movement)

Replicates the legacy workbook price-integrity controls:

  1. STALE PRICE (workbook UUT Return col Q: Stale if a Daily-priced security's
     price date did not advance). BNP now provides a dedicated DStalePrice report
     with per-security staleness metrics, so v313 surfaces that report and flags:
         Stale = Un-priced(Business_Days) > expected_bd(Price Freq calendar days)
         where expected_bd = max(1, round(freq_cal * 5/7))
     e.g. freq 90 (quarterly) & 147 bd unpriced -> Stale; freq 90 & 23 bd -> OK;
          freq 1 (daily) & >1 bd -> Stale.

  2. MATERIAL PRICE MOVEMENT (workbook UUT Return col R:
         IF(OR(return>1%, return<-0.5%), "Check", "Ok")).
     Computed from the two-day DetailedValuationFDV price return per security
         return = CurrentPrice(T) / PreviousPrice(T-1) - 1
     flagged against configurable up/down thresholds (workbook default +1% / -0.5%).
     v314: the POPULATION this materiality test is scoped to no longer comes from
     the hard-coded AssetSubClassName UUT-scope rules (bnp_helpers_uut.resolve_uut_scope,
     which is UNCHANGED and continues to drive the Advisor-UUT Check). Instead:
         include = DetailedValuationFDV['GLGroupName'] normalised in
                   {AUD UNLISTED TRUSTS, AUD UNLISTED EQUITY, UNLIST INTL EQUITIES,
                    UNLIST INTL TRUST}
         exclude = PortfolioCode in {M2STT2, M2STT4}
     See resolve_material_movement_scope(). Price calculation and thresholds are
     unchanged; no minimum-weight/market-value filter is applied. The output
     retains GLGroupName / 'In material-movement population' / inclusion /
     exclusion reason columns for auditability.

DATA CONTRACTS (verified on real 2026-07-31 extracts)
  DStalePrice CSV: 2 preamble lines then header. Key columns by NAME:
     Portfolio, External Portfolio Reference, Security Code, Security Name,
     Category Name, Pricing Source, Price, Last Price Date,
     Un-priced for (Business_Days), Price Freq(Calendar days), Commentary,
     Market Value (Portfolio), Weight.
  DetailedValuationFDV: PortfolioCode idx3, SecurityCode idx7,
     LocalMarketPrice idx24, GLGroupName (by NAME, v314) - grouped by filename
     date token, T vs T-1.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import csv, os, glob, re
import pandas as pd

PRICE_INTEGRITY_VERSION = "v363"
# v314: UUT Material Price MVT population rule changed. It no longer derives from
# the hard-coded AssetSubClassName UUT-scope rules in bnp_helpers_uut.resolve_uut_scope
# (that function, and the Advisor-UUT Check that consumes it, are UNCHANGED). Instead
# the material-movement population is driven by DetailedValuationFDV['GLGroupName']:
#     include = normalised GLGroupName in {AUD UNLISTED TRUSTS, AUD UNLISTED EQUITY,
#                                           UNLIST INTL EQUITIES, UNLIST INTL TRUST}
#     exclude = PortfolioCode in {M2STT2, M2STT4}
# Price calculation (Current Price / Previous Price - 1) and the exception
# thresholds (>+1% / <-0.5%) are unchanged; no minimum-weight/market-value filter
# is applied. See resolve_material_movement_scope() / build_material_movement_check().

# v345: consume the shared single-source-of-truth FDV frame so price-integrity no
# longer re-scans the FDV files over G:/ (it previously read them TWICE more - once
# for stale, once for material movement). Guarded fallback to the legacy reader.
try:
    from bnp_helpers_fdv_enrichment import load_fdv_frame as _shared_load_fdv_frame_v345
except Exception:
    _shared_load_fdv_frame_v345 = None

# v363: read the Material Movement include/exclude population from Static Data
# 'mapping_filters' -> 'Valuation T' (the SAME sheet rows already used by
# bnp_helpers_static_data.uut_included_glgroups()/uut_excluded_portfolio_codes()
# for the UUT look-through population), instead of maintaining a separate
# hard-coded copy of the identical values here. The MATERIAL_MOVEMENT_* module
# constants below are RETAINED as a safe fallback only (used if Static Data is
# unavailable or the mapping_filters rows are empty) - no values changed.
try:
    from bnp_helpers_static_data import get_filter as _get_mapping_filter_v363
except Exception:
    _get_mapping_filter_v363 = None


def _num_series_v345(s: pd.Series) -> pd.Series:
    """Vectorised equivalent of _num: strip commas/$/space, treat (x) as -x, coerce."""
    txt = (s.astype(str)
             .str.replace(",", "", regex=False)
             .str.replace("$", "", regex=False)
             .str.strip())
    neg = txt.str.startswith("(") & txt.str.endswith(")")
    txt = txt.mask(neg, "-" + txt.str.slice(1, -1))
    return pd.to_numeric(txt, errors="coerce")

MATERIAL_UP_THRESHOLD = 0.01     # workbook: return > 1%
MATERIAL_DOWN_THRESHOLD = -0.005  # workbook: return < -0.5%

FDV_PORT_IDX = 3
FDV_SEC_IDX = 7
FDV_PRICE_IDX = 24
FDV_WEIGHT_IDX = 59   # Portfolio%TotalMV
MATERIAL_MIN_WEIGHT_PCT = 1.0  # only flag material moves on holdings >= 1% of the portfolio
_DATE_RE = re.compile(r"(?:FDV|DStalePrice)_[A-Za-z0-9]+-(\d{6})-", re.IGNORECASE)

# ---------------------------------------------------------------------------
# v314 - GLGroupName-based material-movement population (UUT Material Price MVT
# ONLY). This is intentionally SEPARATE from bnp_helpers_uut.resolve_uut_scope()
# / load_uut_scope_from_fdv(), which remain AssetSubClassName-based and continue
# to drive the Advisor-UUT Check unchanged (resolve_uut_scope() is a shared
# helper also consumed by bnp_helpers_uut's corrected Advisor-UUT render and by
# bnp_helpers_reconciliation_export's Advisor-UUT export frame, so it is not
# safe to repoint it to GLGroupName without silently changing Advisor-UUT
# results). Exact, case-insensitive, trimmed matching only - no partial/fuzzy
# matching of either the GLGroupName label or the excluded PortfolioCode.
# ---------------------------------------------------------------------------
MATERIAL_MOVEMENT_INCLUDE_GL_GROUPS = {
    "AUD UNLISTED TRUSTS",
    "AUD UNLISTED EQUITY",
    "UNLIST INTL EQUITIES",
    "UNLIST INTL TRUST",
}
MATERIAL_MOVEMENT_EXCLUDED_PORTFOLIO_CODES = {"M2STT2", "M2STT4"}


def _norm_gl_group_v314(value: object) -> str:
    "Safe trim + case-insensitive normalisation (collapses internal whitespace runs); no partial/fuzzy matching."
    return " ".join(str(value or "").strip().upper().split())


def _norm_portfolio_code_v314(value: object) -> str:
    "Safe trim + case-insensitive normalisation of a PortfolioCode for exact exclusion matching."
    return str(value or "").strip().upper()


def _load_fdv_gl_group_rows_v314(path_or_paths: Any) -> pd.DataFrame:
    """Load PortfolioCode / SecurityCode / GLGroupName rows for the v314
    material-movement population rule. Prefers the shared, single-network-read
    FDV frame (bnp_helpers_fdv_enrichment.load_fdv_frame); falls back to a
    direct named-column read of the raw FDV CSV(s) if the shared frame is
    unavailable or does not (yet) expose GLGroupName."""
    cols = ["PortfolioCode", "SecurityCode", "GLGroupName"]
    if callable(_shared_load_fdv_frame_v345):
        frame = _shared_load_fdv_frame_v345(path_or_paths)
        if isinstance(frame, pd.DataFrame) and not frame.empty and "GLGroupName" in frame.columns:
            return pd.DataFrame({
                "PortfolioCode": frame.get("PortfolioCode", "").astype(str).str.strip(),
                "SecurityCode": frame.get("SecurityCode", "").astype(str).str.strip(),
                "GLGroupName": frame.get("GLGroupName", "").astype(str),
            }).reset_index(drop=True)
    paths = path_or_paths if isinstance(path_or_paths, (list, tuple)) else [path_or_paths]
    frames = []
    for path in paths:
        resolved = _first_existing(path) or path
        if not resolved or not os.path.exists(resolved):
            continue
        try:
            raw = pd.read_csv(
                resolved, dtype=str, encoding="latin-1",
                usecols=lambda c: c in cols,
                keep_default_na=False, na_filter=False, low_memory=False,
            )
            for c in cols:
                if c not in raw.columns:
                    raw[c] = ""
            frames.append(raw[cols])
        except Exception:
            continue
    if not frames:
        return pd.DataFrame(columns=cols)
    return pd.concat(frames, ignore_index=True)


def _resolve_material_movement_include_groups_v363(static_bundle: Optional[Dict[str, object]]) -> set:
    """v363: prefer Static Data mapping_filters['Valuation T']['INCLUDE']['GLGroupName'];
    fall back to the hard-coded MATERIAL_MOVEMENT_INCLUDE_GL_GROUPS if Static Data is
    unavailable or the sheet rows are empty."""
    if static_bundle is not None and callable(_get_mapping_filter_v363):
        try:
            vals = _get_mapping_filter_v363(static_bundle, "Valuation T", "INCLUDE", "GLGroupName")
            norm = {_norm_gl_group_v314(v) for v in (vals or []) if str(v or "").strip()}
            if norm:
                return norm
        except Exception:
            pass
    return set(MATERIAL_MOVEMENT_INCLUDE_GL_GROUPS)


def _resolve_material_movement_excluded_codes_v363(static_bundle: Optional[Dict[str, object]]) -> set:
    """v363: prefer Static Data mapping_filters['Valuation T']['EXCLUDE']['PortfolioCode'];
    fall back to the hard-coded MATERIAL_MOVEMENT_EXCLUDED_PORTFOLIO_CODES if Static Data
    is unavailable or the sheet rows are empty."""
    if static_bundle is not None and callable(_get_mapping_filter_v363):
        try:
            vals = _get_mapping_filter_v363(static_bundle, "Valuation T", "EXCLUDE", "PortfolioCode")
            norm = {_norm_portfolio_code_v314(v) for v in (vals or []) if str(v or "").strip()}
            if norm:
                return norm
        except Exception:
            pass
    return set(MATERIAL_MOVEMENT_EXCLUDED_PORTFOLIO_CODES)


def resolve_material_movement_scope(fdv_paths: Any, static_bundle: Optional[Dict[str, object]] = None) -> Dict[str, Any]:
    """v314: build the UUT Material Price MVT population from
    DetailedValuationFDV['GLGroupName'], NOT from resolve_uut_scope()'s
    AssetSubClassName rules (that function is untouched and continues to serve
    the Advisor-UUT Check).

    Effective rule (v363: sourced from Static Data 'mapping_filters' -> 'Valuation T'
    when available - the SAME sheet rows used by the UUT look-through population -
    with the module constants below retained as a fallback only):
        include = GLGroupName in {AUD UNLISTED TRUSTS, AUD UNLISTED EQUITY,
                                   UNLIST INTL EQUITIES, UNLIST INTL TRUST}
        exclude = PortfolioCode in {M2STT2, M2STT4}

    Returns a dict with:
      'pairs'   - set of (PortfolioCode, SecurityCode) tuples IN the population
      'rows_df' - one row per distinct (PortfolioCode, SecurityCode, GLGroupName)
                  with audit columns: 'In material-movement population',
                  'Population inclusion reason', 'Population exclusion reason'
      'source'  - provenance tag for diagnostics
    """
    audit_cols = [
        "PortfolioCode", "SecurityCode", "GLGroupName",
        "In material-movement population",
        "Population inclusion reason", "Population exclusion reason",
    ]
    rows = _load_fdv_gl_group_rows_v314(fdv_paths)
    if rows is None or not isinstance(rows, pd.DataFrame) or rows.empty:
        return {"pairs": set(), "rows_df": pd.DataFrame(columns=audit_cols), "source": "gl_group_name"}

    include_groups = _resolve_material_movement_include_groups_v363(static_bundle)
    excluded_codes = _resolve_material_movement_excluded_codes_v363(static_bundle)

    out = rows.drop_duplicates(["PortfolioCode", "SecurityCode", "GLGroupName"]).copy()
    gl_norm = out["GLGroupName"].map(_norm_gl_group_v314)
    port_norm = out["PortfolioCode"].map(_norm_portfolio_code_v314)
    included_by_gl = gl_norm.isin(include_groups)
    excluded_by_portfolio = port_norm.isin(excluded_codes)

    out["In material-movement population"] = included_by_gl & ~excluded_by_portfolio
    out["Population inclusion reason"] = out["GLGroupName"].astype(str).apply(
        lambda v: f"GLGroupName = '{v}'"
    )
    out.loc[~included_by_gl, "Population inclusion reason"] = "GLGroupName not in scope"
    out["Population exclusion reason"] = ""
    out.loc[excluded_by_portfolio, "Population exclusion reason"] = out.loc[
        excluded_by_portfolio, "PortfolioCode"
    ].astype(str).apply(lambda v: f"PortfolioCode excluded ({v})")

    pairs = set(map(
        tuple,
        out.loc[out["In material-movement population"], ["PortfolioCode", "SecurityCode"]]
        .drop_duplicates().to_numpy().tolist(),
    ))
    return {"pairs": pairs, "rows_df": out[audit_cols].copy(), "source": "gl_group_name"}


def _num(x) -> Optional[float]:
    s = str(x).replace(",", "").replace("$", "").strip()
    if s in ("", "nan", "None"):
        return None
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        return float(s)
    except Exception:
        return None


def _first_existing(path: str) -> str:
    p = str(path or "").strip()
    if not p:
        return ""
    bs = chr(92); cands = [p]
    if p.upper().startswith("G:" + bs):
        cands.append(bs + bs + "hq.local" + bs + "Corp" + bs + p[3:].lstrip(bs))
    for c in cands:
        if c and os.path.exists(c):
            return c
    return p if os.path.exists(p) else ""


def _expected_business_days(freq_cal: Optional[float]) -> float:
    if freq_cal is None or freq_cal <= 0:
        return 1.0
    return max(1.0, round(float(freq_cal) * 5.0 / 7.0))


# ---------------------------------------------------------------------------
# 1. Stale Price - from the BNP DStalePrice report
# ---------------------------------------------------------------------------
def load_stale_price_report(path_or_paths: Any) -> pd.DataFrame:
    """Load one or more DStalePrice CSVs (2 preamble lines then header)."""
    paths = path_or_paths if isinstance(path_or_paths, (list, tuple)) else [path_or_paths]
    frames = []
    for path in paths:
        resolved = _first_existing(path) or path
        if not resolved or not os.path.exists(resolved):
            continue
        try:
            df = pd.read_csv(resolved, skiprows=2, encoding="latin-1", dtype=str, index_col=False)
            df.columns = [str(c).strip() for c in df.columns]
            frames.append(df)
        except Exception:
            continue
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def build_stale_price_check(stale_report: pd.DataFrame) -> pd.DataFrame:
    """Flag stale prices where un-priced business days exceed the frequency."""
    if not isinstance(stale_report, pd.DataFrame) or stale_report.empty:
        return pd.DataFrame()
    df = stale_report.copy()

    def find(cands):
        norm = {str(c).strip().lower(): c for c in df.columns}
        for cand in cands:
            if cand.lower() in norm:
                return norm[cand.lower()]
        return None

    c_port = find(["Portfolio"])
    c_ext = find(["External Portfolio Reference"])
    c_sec = find(["Security Code"])
    c_name = find(["Security Name"])
    c_src = find(["Pricing Source"])
    c_lastdt = find(["Last Price Date"])
    c_unpriced = find(["Un-priced for (Business_Days)"])
    c_freq = find(["Price Freq(Calendar days)"])
    c_comm = find(["Commentary"])
    c_wt = find(["Weight"])
    c_mv = find(["Market Value (Portfolio)"])

    df["Un-priced (bd)"] = df[c_unpriced].map(_num) if c_unpriced else None
    df["Price Freq (cal)"] = df[c_freq].map(_num) if c_freq else None
    df["Expected (bd)"] = df["Price Freq (cal)"].map(_expected_business_days)
    up = pd.to_numeric(df["Un-priced (bd)"], errors="coerce")
    exp = pd.to_numeric(df["Expected (bd)"], errors="coerce")
    df["Stale Price Check"] = "Ok"
    df.loc[up.notna() & exp.notna() & (up > exp), "Stale Price Check"] = "Stale"

    out_cols = {c_port: "Portfolio", c_ext: "External portfolio reference",
                c_sec: "Security Code", c_name: "Security Name", c_src: "Pricing Source",
                c_lastdt: "Last Price Date", c_comm: "Commentary", c_wt: "Weight",
                c_mv: "Market Value"}
    keep = {v: df[k] for k, v in out_cols.items() if k}
    out = pd.DataFrame(keep)
    out["Un-priced (bd)"] = df["Un-priced (bd)"]
    out["Price Freq (cal)"] = df["Price Freq (cal)"]
    out["Expected (bd)"] = df["Expected (bd)"]
    out["Stale Price Check"] = df["Stale Price Check"]
    return out


def build_stale_price_full(stale_report: pd.DataFrame) -> pd.DataFrame:
    """GAV-style population builder (v1.0): the FULL DStalePrice report tagged
    with 'Stale Price Check' in {'Check' (stale), 'Ok' (evaluated, not stale),
    'Excluded' (could not be evaluated - Un-priced or Price Freq missing)}.
    Same calculation as build_stale_price_check(); the only change is that rows
    which previously defaulted to 'Ok' when they had no evaluable Un-priced/
    Price Freq data are now correctly tagged 'Excluded' with a reason, so the
    population/investigation/OK/excluded template can be applied faithfully
    (a row that was never actually tested must not silently count as a pass).
    """
    base = build_stale_price_check(stale_report)
    if not isinstance(base, pd.DataFrame) or base.empty:
        return pd.DataFrame()
    out = base.copy()
    up = pd.to_numeric(out.get("Un-priced (bd)"), errors="coerce")
    exp = pd.to_numeric(out.get("Expected (bd)"), errors="coerce")
    evaluable = up.notna() & exp.notna()
    out["Exclusion Reason"] = ""
    out.loc[~evaluable, "Exclusion Reason"] = "Un-priced (business days) or Price Freq (calendar days) unavailable in the DStalePrice report row"
    # v360: paired "In <Control> population" boolean, mirroring GAV Check.
    out["In Stale Price Check population"] = evaluable
    # Rename "Stale" -> "Check" for GAV-style consistency; keep the original
    # legacy label too for anyone downstream still matching on "Stale".
    out["Stale Price Check (legacy label)"] = out["Stale Price Check"]
    out["Stale Price Check"] = out["Stale Price Check"].replace({"Stale": "Check"})
    out.loc[~evaluable, "Stale Price Check"] = "Excluded"
    # v360: standardised "Check" column alongside the branded column name.
    out["Check"] = out["Stale Price Check"]
    return out


def build_stale_price_gav_style(bundle: Dict[str, object]):
    """GAV-style wrapper for Stale Price Check: population/investigation
    (red)/OK (green)/excluded (neutral) + single-tab full pack + invariant.
    Returns a bnp_helpers_gav_style.GavStyleResult."""
    from bnp_helpers_gav_style import GavStyleResult, compute_invariant

    sp = _collect(bundle, "stale_price_files", "DStalePrice")
    if not sp:
        return GavStyleResult(status="No DStalePrice report available for the selected date")
    report = load_stale_price_report(sp)
    if report.empty:
        return GavStyleResult(status="DStalePrice report resolved but contained no rows")
    full = build_stale_price_full(report)
    if full.empty:
        return GavStyleResult(status="No stale-price rows produced from the DStalePrice report")

    green_df = full[full["Stale Price Check"] == "Ok"].copy()
    red_df = full[full["Stale Price Check"] == "Check"].copy()
    excluded_df = full[full["Stale Price Check"] == "Excluded"].copy()
    population_count = int(len(green_df) + len(red_df))

    ok, detail = compute_invariant(population_count, [len(red_df)], len(green_df))

    return GavStyleResult(
        red_frames=[("Check", red_df)],
        green_df=green_df,
        excluded_df=excluded_df,
        full_df=full,
        population_metrics=[
            ("Stale Price population", population_count),
            ("Stale Price checks", int(len(red_df))),
            ("Stale Price OK", int(len(green_df))),
            ("Excluded (unevaluable)", int(len(excluded_df))),
        ],
        invariant_ok=ok,
        invariant_detail=detail,
        status="OK",
        currency_cols=["Market Value"],
        percent_cols=["Weight"],
        population_bool_col="In Stale Price Check population",
        control_noun="Stale Price Check",
    )


def render_stale_price_gav_style(st, bundle: Dict[str, object]) -> None:
    from bnp_helpers_gav_style import render_gav_style_section
    result = build_stale_price_gav_style(bundle)
    if isinstance(bundle, dict):
        bundle["stale_price_gav_style_result"] = result
    render_gav_style_section(
        st,
        control_key="stale_price",
        title="Stale Price Check",
        purpose=("BNP DStalePrice report rows flagged where un-priced business days exceed the expected pricing "
                 "frequency (expected_bd = round(freq_cal * 5/7)). Rows that could not be evaluated (missing "
                 "un-priced or price-frequency data) are excluded from the Check/Ok test but retained for audit."),
        result=result,
        download_filename_prefix="stale_price_check",
    )


# ---------------------------------------------------------------------------
# 2. Material Price Movement - from the two-day FDV price return
# ---------------------------------------------------------------------------
def _date_token(path: str) -> str:
    m = _DATE_RE.search(os.path.basename(str(path)))
    if not m:
        return ""
    d = m.group(1)
    return d[4:6] + d[2:4] + d[0:2]  # YYMMDD


def _load_fdv_prices_legacy(path_or_paths: Any, with_weight: bool = False) -> pd.DataFrame:
    """Original row-by-row reader, retained as a fallback."""
    paths = path_or_paths if isinstance(path_or_paths, (list, tuple)) else [path_or_paths]
    recs = []
    need = FDV_WEIGHT_IDX if with_weight else FDV_PRICE_IDX
    for path in paths:
        resolved = _first_existing(path) or path
        if not resolved or not os.path.exists(resolved):
            continue
        try:
            with open(resolved, encoding="latin-1", newline="") as f:
                r = csv.reader(f); next(r, None)
                for row in r:
                    if len(row) <= need:
                        continue
                    rec = {"PortfolioCode": str(row[FDV_PORT_IDX]).strip(),
                           "SecurityCode": str(row[FDV_SEC_IDX]).strip(),
                           "Price": _num(row[FDV_PRICE_IDX])}
                    if with_weight:
                        rec["Weight %"] = _num(row[FDV_WEIGHT_IDX])
                    recs.append(rec)
        except Exception:
            continue
    cols = ["PortfolioCode", "SecurityCode", "Price"] + (["Weight %"] if with_weight else [])
    return pd.DataFrame(recs, columns=cols)


def _load_fdv_prices(path_or_paths: Any, with_weight: bool = False) -> pd.DataFrame:
    """v345: derive prices from the SHARED FDV frame (single network read per file,
    vectorised) instead of re-scanning. Output is identical: PortfolioCode,
    SecurityCode, Price (LocalMarketPrice), and optionally Weight % (Portfolio%TotalMV).
    Falls back to the legacy reader if the shared helper is absent."""
    if not callable(_shared_load_fdv_frame_v345):
        return _load_fdv_prices_legacy(path_or_paths, with_weight=with_weight)
    frame = _shared_load_fdv_frame_v345(path_or_paths)
    cols = ["PortfolioCode", "SecurityCode", "Price"] + (["Weight %"] if with_weight else [])
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return pd.DataFrame(columns=cols)
    data = {
        "PortfolioCode": frame.get("PortfolioCode", "").astype(str).str.strip(),
        "SecurityCode": frame.get("SecurityCode", "").astype(str).str.strip(),
        "Price": _num_series_v345(frame.get("LocalMarketPrice", "")),
    }
    if with_weight:
        data["Weight %"] = _num_series_v345(frame.get("Portfolio%TotalMV", ""))
    return pd.DataFrame(data, columns=cols).reset_index(drop=True)


def build_material_movement_check(fdv_t: Any, fdv_t1: Any,
                                  up_threshold: float = MATERIAL_UP_THRESHOLD,
                                  down_threshold: float = MATERIAL_DOWN_THRESHOLD,
                                  min_weight_pct: float = 0.0,
                                  population_scope: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
    """Flag material two-day price moves on the UUT Material Price MVT population (v314).

    v314 CHANGE: the material-movement population no longer derives from the
    hard-coded AssetSubClassName UUT-scope rules (bnp_helpers_uut.resolve_uut_scope,
    which is UNCHANGED and continues to drive the Advisor-UUT Check). Instead it
    is driven by `population_scope` (see resolve_material_movement_scope()):
        include = DetailedValuationFDV['GLGroupName'] normalised in
                  {AUD UNLISTED TRUSTS, AUD UNLISTED EQUITY, UNLIST INTL EQUITIES,
                   UNLIST INTL TRUST}
        exclude = PortfolioCode in {M2STT2, M2STT4}
    The price calculation (Current Price / Previous Price - 1) and the exception
    thresholds (>+1% / <-0.5%) are UNCHANGED. `min_weight_pct` remains an optional
    secondary filter, default 0 = no minimum-weight/market-value filter applied.
    For auditability the output retains GLGroupName, 'In material-movement
    population', 'Population inclusion reason' and 'Population exclusion reason'
    so every row is traceable to the new population rule.
    """
    t = _load_fdv_prices(fdv_t, with_weight=True); t1 = _load_fdv_prices(fdv_t1)
    if t.empty or t1.empty:
        return pd.DataFrame()
    prev = t1.drop_duplicates(["PortfolioCode", "SecurityCode"]).rename(columns={"Price": "Previous Price"})
    df = t.merge(prev, on=["PortfolioCode", "SecurityCode"], how="left").rename(columns={"Price": "Current Price"})
    df["Current Price"] = pd.to_numeric(df["Current Price"], errors="coerce")
    df["Previous Price"] = pd.to_numeric(df["Previous Price"], errors="coerce")
    df["Weight %"] = pd.to_numeric(df.get("Weight %"), errors="coerce")
    good = df["Current Price"].notna() & df["Previous Price"].notna() & (df["Previous Price"] != 0)
    df["Price Return"] = pd.NA
    df.loc[good, "Price Return"] = df.loc[good, "Current Price"] / df.loc[good, "Previous Price"] - 1
    ret = pd.to_numeric(df["Price Return"], errors="coerce")
    wt = df["Weight %"].abs()
    material = ret.notna() & ((ret > up_threshold) | (ret < down_threshold))

    # v314: attach the GLGroupName-based population rule (replaces the prior
    # AssetSubClassName UUT-scope isin() filter). Joined on (PortfolioCode,
    # SecurityCode) so the same security can be correctly scoped per-holding.
    pop_rows = population_scope.get("rows_df") if isinstance(population_scope, dict) else None
    if isinstance(pop_rows, pd.DataFrame) and not pop_rows.empty:
        pop_df = pop_rows.drop_duplicates(["PortfolioCode", "SecurityCode"])
        df = df.merge(pop_df, on=["PortfolioCode", "SecurityCode"], how="left")
        df["In material-movement population"] = df["In material-movement population"].fillna(False).astype(bool)
        df["GLGroupName"] = df["GLGroupName"].fillna("")
        df["Population inclusion reason"] = df["Population inclusion reason"].fillna("No FDV GLGroupName row matched")
        df["Population exclusion reason"] = df["Population exclusion reason"].fillna("")
        in_scope = df["In material-movement population"]
    else:
        # No population scope resolved (e.g. GLGroupName unavailable this run) -
        # fail safe to an EMPTY population rather than silently reverting to the
        # legacy AssetSubClassName rule or flagging the whole (unscoped) book.
        df["GLGroupName"] = ""
        df["In material-movement population"] = False
        df["Population inclusion reason"] = "Population scope unavailable"
        df["Population exclusion reason"] = ""
        in_scope = pd.Series(False, index=df.index)

    meaningful = (wt.notna() & (wt >= float(min_weight_pct))) if (min_weight_pct and min_weight_pct > 0) else pd.Series(True, index=df.index)
    df["Materiality Check"] = "Ok"
    df.loc[material & in_scope & meaningful, "Materiality Check"] = "Check"
    out = df[df["Materiality Check"] == "Check"].copy()
    return out.sort_values("Weight %", ascending=False) if not out.empty else out


def build_material_movement_full(fdv_t: Any, fdv_t1: Any,
                                 up_threshold: float = MATERIAL_UP_THRESHOLD,
                                 down_threshold: float = MATERIAL_DOWN_THRESHOLD,
                                 min_weight_pct: float = 0.0,
                                 population_scope: Optional[Dict[str, Any]] = None) -> pd.DataFrame:
    """GAV-style population builder (v1.0): returns EVERY (PortfolioCode,
    SecurityCode) row from the two-day FDV price return - both IN the v314
    GLGroupName population and OUT of it - tagged with a single 'Materiality
    Check' status of 'Check' / 'Ok' / 'Excluded'. This is the same calculation
    as build_material_movement_check() (identical price/threshold logic,
    identical population rule), just WITHOUT the final filter to only the
    flagged rows - so it can drive the GAV-style population/investigation/OK/
    excluded template (UUT Material Price MVT panel).
    """
    t = _load_fdv_prices(fdv_t, with_weight=True); t1 = _load_fdv_prices(fdv_t1)
    if t.empty or t1.empty:
        return pd.DataFrame()
    prev = t1.drop_duplicates(["PortfolioCode", "SecurityCode"]).rename(columns={"Price": "Previous Price"})
    df = t.merge(prev, on=["PortfolioCode", "SecurityCode"], how="left").rename(columns={"Price": "Current Price"})
    df["Current Price"] = pd.to_numeric(df["Current Price"], errors="coerce")
    df["Previous Price"] = pd.to_numeric(df["Previous Price"], errors="coerce")
    df["Weight %"] = pd.to_numeric(df.get("Weight %"), errors="coerce")
    good = df["Current Price"].notna() & df["Previous Price"].notna() & (df["Previous Price"] != 0)
    df["Price Return"] = pd.NA
    df.loc[good, "Price Return"] = df.loc[good, "Current Price"] / df.loc[good, "Previous Price"] - 1
    ret = pd.to_numeric(df["Price Return"], errors="coerce")
    wt = df["Weight %"].abs()
    material = ret.notna() & ((ret > up_threshold) | (ret < down_threshold))

    pop_rows = population_scope.get("rows_df") if isinstance(population_scope, dict) else None
    if isinstance(pop_rows, pd.DataFrame) and not pop_rows.empty:
        pop_df = pop_rows.drop_duplicates(["PortfolioCode", "SecurityCode"])
        df = df.merge(pop_df, on=["PortfolioCode", "SecurityCode"], how="left")
        df["In material-movement population"] = df["In material-movement population"].fillna(False).astype(bool)
        df["GLGroupName"] = df["GLGroupName"].fillna("")
        df["Population inclusion reason"] = df["Population inclusion reason"].fillna("No FDV GLGroupName row matched")
        df["Population exclusion reason"] = df["Population exclusion reason"].fillna("")
        in_scope = df["In material-movement population"]
    else:
        df["GLGroupName"] = ""
        df["In material-movement population"] = False
        df["Population inclusion reason"] = "Population scope unavailable"
        df["Population exclusion reason"] = "Population scope unavailable"
        in_scope = pd.Series(False, index=df.index)

    meaningful = (wt.notna() & (wt >= float(min_weight_pct))) if (min_weight_pct and min_weight_pct > 0) else pd.Series(True, index=df.index)
    df["Materiality Check"] = "Excluded"
    df.loc[in_scope & meaningful & ~material, "Materiality Check"] = "Ok"
    df.loc[in_scope & meaningful & material, "Materiality Check"] = "Check"
    # in-scope but filtered out by min_weight_pct (rare; default 0 = never happens)
    df.loc[in_scope & ~meaningful, "Materiality Check"] = "Excluded"
    df.loc[in_scope & ~meaningful, "Population exclusion reason"] = df.loc[in_scope & ~meaningful, "Population exclusion reason"].where(
        df.loc[in_scope & ~meaningful, "Population exclusion reason"].astype(str).str.strip().ne(""),
        f"Below minimum weight threshold ({min_weight_pct}%)"
    )
    # v360: paired "In <Control> population" boolean + standardised "Check" column.
    df["In UUT Material Price MVT population"] = (in_scope & meaningful)
    df["Exclusion Reason"] = df["Population exclusion reason"].where(
        df["Population exclusion reason"].astype(str).str.strip().ne(""), df["Population inclusion reason"]
    )
    df.loc[df["In UUT Material Price MVT population"], "Exclusion Reason"] = ""
    df["Check"] = df["Materiality Check"]
    return df.sort_values(["Materiality Check", "Weight %"], ascending=[True, False]).reset_index(drop=True)


def build_uut_material_mvt_gav_style(bundle: Dict[str, object]):
    """GAV-style wrapper for UUT Material Price MVT: population/investigation
    (red)/OK (green)/excluded (neutral) + single-tab full pack + invariant.
    Returns a bnp_helpers_gav_style.GavStyleResult."""
    from bnp_helpers_gav_style import GavStyleResult, compute_invariant

    diag: Dict[str, Any] = {}
    fdv = (bundle.get("fdv_files") if isinstance(bundle, dict) else None) or _collect(bundle, "fdv_files", "DetailedValuationFDV")
    if not fdv:
        return GavStyleResult(status="No DetailedValuationFDV files available for the selected date", diag=diag)

    by_date: Dict[str, List[str]] = {}
    for p in fdv:
        tok = _date_token(p)
        if tok:
            by_date.setdefault(tok, []).append(p)
    dates = sorted(by_date.keys(), reverse=True)
    if len(dates) < 2:
        return GavStyleResult(status=f"Only one FDV date available ({dates[0] if dates else '?'}) - "
                                      f"material movement needs T and T-1", diag=diag)
    fdv_t, fdv_t1 = by_date[dates[0]], by_date[dates[1]]
    try:
        population_scope = resolve_material_movement_scope(fdv)
    except Exception as exc:
        return GavStyleResult(status=f"Population scope error: {type(exc).__name__}: {exc}", diag=diag)

    full = build_material_movement_full(fdv_t, fdv_t1, population_scope=population_scope)
    if full.empty:
        return GavStyleResult(status="No FDV price rows available to evaluate", diag=diag)

    green_df = full[full["Materiality Check"] == "Ok"].copy()
    red_df = full[full["Materiality Check"] == "Check"].copy()
    excluded_df = full[full["Materiality Check"] == "Excluded"].copy()
    population_count = int(len(green_df) + len(red_df))

    ok, detail = compute_invariant(population_count, [len(red_df)], len(green_df))
    full_pack = full.copy()

    return GavStyleResult(
        red_frames=[("Check", red_df)],
        green_df=green_df,
        excluded_df=excluded_df,
        full_df=full_pack,
        population_metrics=[
            ("MVT population", population_count),
            ("MVT checks", int(len(red_df))),
            ("MVT OK", int(len(green_df))),
            ("Excluded (GLGroupName/M2STT2+M2STT4)", int(len(excluded_df))),
        ],
        invariant_ok=ok,
        invariant_detail=detail,
        status="OK",
        diag={"fdv_t": dates[0], "fdv_t1": dates[1], **diag},
        currency_cols=["Current Price", "Previous Price"],
        percent_cols=["Weight %", "Price Return"],
        population_bool_col="In UUT Material Price MVT population",
        control_noun="UUT Material Price MVT",
    )


def render_uut_material_mvt_gav_style(st, bundle: Dict[str, object]) -> None:
    from bnp_helpers_gav_style import render_gav_style_section
    result = build_uut_material_mvt_gav_style(bundle)
    if isinstance(bundle, dict):
        bundle["uut_material_mvt_gav_style_result"] = result
    render_gav_style_section(
        st,
        control_key="uut_material_mvt",
        title="UUT Material Price MVT",
        purpose=("Two-day DetailedValuationFDV price movements, scoped to GLGroupName in {AUD Unlisted Trusts, "
                 "AUD Unlisted Equity, Unlist Intl Equities, Unlist Intl Trust}, excluding PortfolioCode M2STT2 / "
                 "M2STT4. Flagged where price return is greater than +1% or less than -0.5%."),
        result=result,
        download_filename_prefix="uut_material_price_mvt",
    )


# ---------------------------------------------------------------------------
@dataclass
class PriceIntegrityResult:
    stale_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    material_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    summary: Dict[str, Any] = field(default_factory=dict)
    status: str = "OK"
    diag: Dict[str, Any] = field(default_factory=dict)


def _collect(bundle: Dict[str, object], key: str, keyword: str) -> List[str]:
    out = []
    if not isinstance(bundle, dict):
        return out
    v = bundle.get(key)
    if isinstance(v, (list, tuple)):
        out += [str(p) for p in v]
    folder = str(bundle.get("folder") or "")
    if folder and os.path.isdir(folder):
        out += glob.glob(os.path.join(folder, f"*{keyword}*.csv"))
    meta = bundle.get("file_meta_df")
    if isinstance(meta, pd.DataFrame) and not meta.empty:
        for c in meta.columns:
            for val in meta[c].astype(str).tolist():
                if keyword in val and val.lower().endswith(".csv"):
                    out.append(val)
    seen, res = set(), []
    for p in out:
        rp = _first_existing(p)
        if rp and rp not in seen:
            seen.add(rp); res.append(rp)
    return res


def build_price_integrity(bundle: Dict[str, object],
                          stale_paths: Any = None, fdv_files: Any = None) -> PriceIntegrityResult:
    diag = {}
    sp = stale_paths or _collect(bundle, "stale_price_files", "DStalePrice")
    stale_report = load_stale_price_report(sp) if sp else pd.DataFrame()
    stale = build_stale_price_check(stale_report) if not stale_report.empty else pd.DataFrame()
    diag["stale_report_rows"] = int(len(stale_report))

    fdv = fdv_files or (bundle.get("fdv_files") if isinstance(bundle, dict) else None) or _collect(bundle, "fdv_files", "DetailedValuationFDV")
    material = pd.DataFrame()
    population_scope = None
    if fdv:
        # v314: material-movement population is now GLGroupName-based (see
        # resolve_material_movement_scope). This is DELIBERATELY separate from
        # bnp_helpers_uut.resolve_uut_scope() (AssetSubClassName-based), which is
        # untouched and continues to drive the Advisor-UUT Check.
        try:
            _static_bundle = bundle.get("static_data") if isinstance(bundle, dict) else None
            population_scope = resolve_material_movement_scope(fdv, static_bundle=_static_bundle)
            diag["material_movement_population_source"] = population_scope.get("source", "")
            diag["material_movement_population_pairs_in_scope"] = int(len(population_scope.get("pairs") or []))
        except Exception as _e:
            population_scope = None
            diag["material_movement_population_error"] = str(_e)
        by_date = {}
        for p in fdv:
            tok = _date_token(p)
            if tok:
                by_date.setdefault(tok, []).append(p)
        dates = sorted(by_date.keys(), reverse=True)
        if len(dates) >= 2:
            material = build_material_movement_check(by_date[dates[0]], by_date[dates[1]],
                                                     population_scope=population_scope)
            diag["fdv_t"] = dates[0]; diag["fdv_t1"] = dates[1]
    summary = {
        "stale_report_rows": int(len(stale)),
        "stale_flagged": int((stale.get("Stale Price Check") == "Stale").sum()) if not stale.empty else 0,
        "material_movements": int(len(material)) if not material.empty else 0,
        "material_movement_population_pairs_in_scope": int(len(population_scope.get("pairs") or [])) if population_scope else 0,
    }
    status = "OK" if (not stale.empty or not material.empty) else "No price-integrity sources"
    return PriceIntegrityResult(stale, material, summary, status, diag)


def render_price_integrity_section(st, bundle: Dict[str, object]) -> None:
    try:
        res = build_price_integrity(bundle)
        st.markdown("**Price integrity (v314)** - Stale Price (BNP DStalePrice report) "
                    "and Material Price Movement (two-day FDV price return, GLGroupName population).")
        if res.status != "OK":
            st.warning(f"Price integrity unavailable: {res.status}. Diagnostic: {res.diag}")
            return
        if isinstance(bundle, dict):
            bundle["stale_price_df"] = res.stale_df
            bundle["material_movement_df"] = res.material_df
            bundle["price_integrity_summary"] = res.summary
        s = res.summary
        c1, c2, c3 = st.columns(3)
        c1.metric("Stale-report rows", s.get("stale_report_rows", 0))
        c2.metric("Stale flagged", s.get("stale_flagged", 0))
        c3.metric("Material movements", s.get("material_movements", 0))

        st.markdown("*Stale prices* (un-priced beyond the pricing frequency):")
        sf = res.stale_df[res.stale_df["Stale Price Check"] == "Stale"].copy() if not res.stale_df.empty else pd.DataFrame()
        st.dataframe(sf, width="stretch", hide_index=True)
        st.download_button("Download stale prices", sf.to_csv(index=False).encode("utf-8"),
                           "stale_prices_last_run.csv", "text/csv", key="pi_stale_dl")

        st.markdown(f"*Material price movements* (>{MATERIAL_UP_THRESHOLD:.0%} or <{MATERIAL_DOWN_THRESHOLD:.1%}):")
        st.dataframe(res.material_df, width="stretch", hide_index=True)
        st.download_button("Download material movements", res.material_df.to_csv(index=False).encode("utf-8"),
                           "material_movements_last_run.csv", "text/csv", key="pi_material_dl")

        with st.expander("Full stale-price report (all rows)", expanded=False):
            st.dataframe(res.stale_df, width="stretch", hide_index=True)
    except Exception:
        pass


if __name__ == "__main__":
    print(f"[{PRICE_INTEGRITY_VERSION}] price integrity self-test")
    up = "/mnt/user-data/uploads"
    stale = glob.glob(os.path.join(up, "*DStalePrice*.csv"))
    fdv = glob.glob(os.path.join(up, "*DetailedValuationFDV*.csv"))
    if stale:
        rep = load_stale_price_report(stale)
        chk = build_stale_price_check(rep)
        n_stale = int((chk["Stale Price Check"] == "Stale").sum())
        print(f"  stale report rows: {len(rep)} | flagged Stale: {n_stale}")
        # spot-check the profiled cases
        for sec, exp in [("AMPCSITE", "Ok"), ("AUSBALEU", "Ok")]:
            row = chk[chk["Security Code"] == sec]
            if not row.empty:
                r = row.iloc[0]
                print(f"    {sec}: unpriced={r['Un-priced (bd)']} freq={r['Price Freq (cal)']} "
                      f"expected={r['Expected (bd)']} -> {r['Stale Price Check']}")
        assert n_stale > 0, "expected some stale flags"
    if len(fdv) >= 2:
        by = {}
        for p in fdv:
            m = _DATE_RE.search(os.path.basename(p))
            if m:
                d = m.group(1); by.setdefault(d[4:6]+d[2:4]+d[0:2], []).append(p)
        ds = sorted(by, reverse=True)
        if len(ds) >= 2:
            pop_scope = resolve_material_movement_scope(fdv)
            print(f"  material-movement population pairs in scope (GLGroupName rule): {len(pop_scope.get('pairs') or [])}")
            mat = build_material_movement_check(by[ds[0]], by[ds[1]], population_scope=pop_scope)
            print(f"  material movements flagged: {len(mat)}")
            if not mat.empty:
                cols = ["PortfolioCode", "SecurityCode", "GLGroupName", "Current Price", "Previous Price",
                        "Price Return", "In material-movement population"]
                print(mat[[c for c in cols if c in mat.columns]].head(4).to_string(index=False))
                assert bool(mat["In material-movement population"].all()), "flagged rows must all be in the v314 population"
                excluded_hit = mat["PortfolioCode"].astype(str).str.strip().str.upper().isin(MATERIAL_MOVEMENT_EXCLUDED_PORTFOLIO_CODES)
                assert not bool(excluded_hit.any()), "M2STT2/M2STT4 must never appear in the flagged output"
    print("  OK - v314 validated (GLGroupName population + M2STT2/M2STT4 exclusion) on real DStalePrice + FDV")
