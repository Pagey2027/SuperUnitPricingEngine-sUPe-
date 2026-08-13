# -*- coding: utf-8 -*-
"""
bnp_helpers_return_check.py  (v310 - Advisor Return Check core)

PURPOSE
-------
Computes the ACTUAL Advisor Return Check on the Unison (production) basis,
replicating the legacy workbook "Unison vs BNP return check" columns:

    Q   Unison Return          = SUMIF(Tableau Trust Element, advisor, Movement)
                                + SUMIF(Tableau SF Element, advisor, Movement)
    V   BNP Return             = DDetailedReturn Actual Return
    W   Benchmark              = DDetailedReturn Benchmark Return
    Z   Variance (Unison-BNP)  = Unison Return - BNP Return           (recon)
    AA  Return recon Check     = IF(|Z| > 0.02%, "Check", "Ok")
    AB  Unison vs Benchmark    = Unison Return - Benchmark
    AC  Tolerance              = DDetailedReturn Tolerance
    AD  Tolerance Check (OUT)  = IF(|AB| >= tolerance, "OUT", "OK")   <-- PRIMARY OUT

WHAT CHANGES (agreed): this is the FIRST version that changes the OUT basis.
    * NEW primary OUT = |Unison Return - Benchmark| >= Tolerance   (production vs
      benchmark - a genuine two-system control).
    * The app's existing BNP-internal OUT (Within Tolerance / Status Normalised,
      i.e. |BNP Actual - Benchmark| vs Tolerance) is RETAINED as a reconciliation
      column so the change is auditable side-by-side before sign-off.
    * Benchmark NAME (workbook col AE / BM Mapping) is DEFERRED per agreement.

KEYS / DATA CONTRACTS (verified on real 2026-07-31 ILFMAY extracts)
    * Unison Return join key = advisor code (portfolio_df["External portfolio
      reference"], first token, normalised) -> Tableau "Element".
      Proven: 194/194 trust portfolios matched the Trust price file.
    * Tableau price files are UTF-16 / TAB / single header row:
        Trust : Element = col D (idx3), Movement = col H (idx7)
        SF    : Element = col E (idx4), Movement = col I (idx8)
      (The app's generic CSV reader cannot read UTF-16, so - as with Acc Balance
      in v309.1 - this module resolves the file path and reads it directly.)
    * Benchmark / Tolerance / Actual / Status come from DDetailedReturn (bundle
      ["dd"]); all values parsed to PERCENT units with the same _pct() parser as
      Unison Return, so the comparison is scale-consistent.

Return-recon tolerance (0.02%) is read from Static Data thresholds
(return_recon_tolerance_pct, added v307), echoed on screen for audit.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import csv, io, os
import pandas as pd

RETURN_CHECK_VERSION = "v310"

TRUST_ELEMENT_IDX = 3
TRUST_MOVEMENT_IDX = 7
SF_ELEMENT_IDX = 4
SF_MOVEMENT_IDX = 8
DEFAULT_RETURN_RECON_TOLERANCE_PCT = 0.02  # workbook col AA

try:
    from bnp_helpers_columns import normalise_join_key_series as _norm_join
except Exception:
    def _norm_join(s: pd.Series) -> pd.Series:
        return s.astype(str).str.strip().str.upper().str.replace(r"\s+", "", regex=True)

try:
    from bnp_helpers_static_data import get_threshold_value as _get_threshold_value, get_config_value as _get_config_value
except Exception:
    _get_threshold_value = None
    _get_config_value = None


def _pct(x) -> Optional[float]:
    """Parse a percentage/number string to a float in PERCENT units.

    "0.0137%" -> 0.0137 ; "0.0200" -> 0.0200 ; "$20.27" -> 20.27 ; "(0.5)" -> -0.5
    """
    s = str(x).replace("%", "").replace("$", "").replace(",", "").strip()
    if s in ("", "nan", "None"):
        return None
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        return float(s)
    except Exception:
        return None


def _norm_token(v: object) -> str:
    t = str(v or "").strip()
    first = t.split()[0] if t else ""
    return "".join(ch for ch in first.upper() if ch.isalnum())


def _root_variants(path: str) -> List[str]:
    p = str(path or "").strip()
    if not p:
        return []
    bs = chr(92); variants = [p]
    if p.upper().startswith("G:" + bs):
        variants.append(bs + bs + "hq.local" + bs + "Corp" + bs + p[3:].lstrip(bs))
    elif p.lower().startswith((bs + bs + "hq.local" + bs + "corp" + bs).lower()):
        variants.append("G:" + bs + p[len(bs + bs + "hq.local" + bs + "Corp" + bs):])
    out, seen = [], set()
    for v in variants:
        if v.lower() not in seen:
            seen.add(v.lower()); out.append(v)
    return out


def _first_existing(path: str) -> str:
    for c in _root_variants(path):
        if c and os.path.exists(c):
            return c
    return ""


# ---------------------------------------------------------------------------
# Unison Return from Tableau price files (UTF-16 aware)
# ---------------------------------------------------------------------------
def load_tableau_price_movements(path: str, element_idx: int, movement_idx: int) -> Dict[str, float]:
    """Return {advisor_norm: summed Movement (percent)} from a Tableau price CSV."""
    resolved = _first_existing(path) or path
    rows: List[List[str]] = []
    for enc in ("utf-16", "utf-16-le", "utf-8-sig", "utf-8", "latin-1"):
        try:
            with io.open(resolved, encoding=enc) as f:
                cand = list(csv.reader(f, delimiter="\t"))
            if cand and max((len(r) for r in cand[:5]), default=0) > 3:
                rows = cand
                break
        except Exception:
            continue
    out: Dict[str, float] = {}
    if not rows:
        return out
    for r in rows[1:]:  # single header row
        if len(r) <= max(element_idx, movement_idx):
            continue
        k = _norm_token(r[element_idx])
        v = _pct(r[movement_idx])
        if k and v is not None:
            out[k] = out.get(k, 0.0) + v
    return out


def _resolve_tableau_price_path(bundle: Dict[str, object], report_key: str, filename_hint: str) -> str:
    """Resolve a Tableau price file path from bundle metadata (v309.1 pattern)."""
    if not isinstance(bundle, dict):
        return ""
    tb = bundle.get("tableau") if isinstance(bundle.get("tableau"), dict) else {}
    for meta in (bundle.get("tableau_file_meta_df"), tb.get("tableau_file_meta_df") if isinstance(tb, dict) else None):
        if isinstance(meta, pd.DataFrame) and not meta.empty and "ReportKey" in meta.columns:
            row = meta[meta["ReportKey"].astype(str).str.strip().str.lower() == report_key]
            if not row.empty:
                for col in ("ResolvedPath", "ExpectedPath"):
                    if col in row.columns:
                        p = _first_existing(str(row.iloc[0][col] or "").strip())
                        if p:
                            return p
    folder = bundle.get("tableau_folder") or (tb.get("tableau_folder") if isinstance(tb, dict) else "")
    if folder:
        p = _first_existing(os.path.join(str(folder), filename_hint))
        if p:
            return p
    return ""


def build_unison_return_map(bundle: Dict[str, object],
                            trust_path: Optional[str] = None,
                            sf_path: Optional[str] = None) -> Tuple[Dict[str, float], Dict[str, str], Dict[str, Any]]:
    """Return (advisor_norm -> Unison Return %, advisor_norm -> basis, diag)."""
    tp = trust_path or _resolve_tableau_price_path(bundle, "tableau_price_trust", "Daily Price - By Trust Product.csv")
    sp = sf_path or _resolve_tableau_price_path(bundle, "tableau_price_sf", "Daily Price - By Statutory Fund.csv")
    trust = load_tableau_price_movements(tp, TRUST_ELEMENT_IDX, TRUST_MOVEMENT_IDX) if tp else {}
    sf = load_tableau_price_movements(sp, SF_ELEMENT_IDX, SF_MOVEMENT_IDX) if sp else {}
    uni: Dict[str, float] = {}
    basis: Dict[str, str] = {}
    for k, v in trust.items():
        uni[k] = v; basis[k] = "Trust"
    for k, v in sf.items():
        if k not in uni:
            uni[k] = v; basis[k] = "SF"
    diag = {"trust_path": tp, "sf_path": sp, "trust_rows": len(trust), "sf_rows": len(sf), "unison_keys": len(uni)}
    return uni, basis, diag


# ---------------------------------------------------------------------------
# BNP return fields (Benchmark / Tolerance / Actual / Status) from DDetailedReturn
# ---------------------------------------------------------------------------
def _resolve_dd_columns(dd: pd.DataFrame) -> Dict[str, Optional[str]]:
    def find(cands):
        norm = {str(c).strip().lower().replace(" ", "").replace("_", ""): c for c in dd.columns}
        for cand in cands:
            k = cand.strip().lower().replace(" ", "").replace("_", "")
            if k in norm:
                return norm[k]
        return None
    return {
        "portfolio": find(["Portfolio code", "PortfolioCode", "Portfolio"]),
        "external": find(["External portfolio reference", "ExternalPortfolioReference", "External reference"]),
        "benchmark": find(["Benchmark Return", "BenchmarkReturn"]),
        "tolerance": find(["Tolerance"]),
        "actual": find(["Actual Return", "ActualReturn"]),
        "status": find(["Status"]),
    }


def build_bnp_return_fields(bundle: Dict[str, object]) -> pd.DataFrame:
    """Per-portfolio Benchmark/Tolerance/Actual/BNP Status from bundle['dd'].

    Returns columns: Hiport norm, Advisor norm, Benchmark %, Tolerance %,
    BNP Return %, BNP Status. All numeric fields in PERCENT units.
    """
    dd = bundle.get("dd") if isinstance(bundle, dict) else None
    if not isinstance(dd, pd.DataFrame) or dd.empty:
        return pd.DataFrame(columns=["Hiport norm", "Advisor norm", "Benchmark", "Tolerance", "BNP Return", "BNP Status"])
    cols = _resolve_dd_columns(dd)
    if not cols["portfolio"]:
        return pd.DataFrame(columns=["Hiport norm", "Advisor norm", "Benchmark", "Tolerance", "BNP Return", "BNP Status"])
    out = pd.DataFrame()
    out["Hiport norm"] = _norm_join(dd[cols["portfolio"]])
    out["Advisor norm"] = dd[cols["external"]].map(_norm_token) if cols["external"] else ""
    out["Benchmark"] = dd[cols["benchmark"]].map(_pct) if cols["benchmark"] else None
    out["Tolerance"] = dd[cols["tolerance"]].map(_pct) if cols["tolerance"] else None
    out["BNP Return"] = dd[cols["actual"]].map(_pct) if cols["actual"] else None
    out["BNP Status"] = dd[cols["status"]].astype(str).str.strip().str.upper() if cols["status"] else ""
    return out.drop_duplicates(subset=["Hiport norm"], keep="first").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Return Check
# ---------------------------------------------------------------------------
@dataclass
class ReturnCheckResult:
    return_df: pd.DataFrame
    summary: Dict[str, Any] = field(default_factory=dict)
    recon_tolerance_pct: float = DEFAULT_RETURN_RECON_TOLERANCE_PCT
    status: str = "OK"
    diag: Dict[str, Any] = field(default_factory=dict)


def build_return_check(portfolio_df: pd.DataFrame, bundle: Dict[str, object],
                       *, recon_tolerance_pct: float = DEFAULT_RETURN_RECON_TOLERANCE_PCT,
                       portfolio_code_col: str = "Portfolio code",
                       advisor_col: str = "External portfolio reference") -> ReturnCheckResult:
    if not isinstance(portfolio_df, pd.DataFrame) or portfolio_df.empty or portfolio_code_col not in portfolio_df.columns:
        return ReturnCheckResult(pd.DataFrame(), {}, recon_tolerance_pct, "No portfolio_df")

    uni_map, uni_basis, uni_diag = build_unison_return_map(bundle)
    if not uni_map:
        return ReturnCheckResult(pd.DataFrame(), {}, recon_tolerance_pct, "No Unison prices", diag=uni_diag)

    df = portfolio_df.copy()
    df["_hiport_norm"] = df["Portfolio code norm"].astype(str) if "Portfolio code norm" in df.columns else _norm_join(df[portfolio_code_col])
    df["_advisor_norm"] = df[advisor_col].map(_norm_token) if advisor_col in df.columns else ""

    keep = [c for c in [portfolio_code_col, advisor_col, "Portfolio Name", "Class"] if c in df.columns]
    base = df[keep + ["_hiport_norm", "_advisor_norm"]].copy()

    # --- BNP fields: PREFER portfolio_df's already-parsed columns (always present,
    #     production-correct) and fall back to bundle['dd'] only if absent. ---
    have_pf_cols = all(c in df.columns for c in ["Benchmark Return Num", "Tolerance Num", "Actual Return Num"])
    bnp_source = ""
    if have_pf_cols:
        bnp_source = "portfolio_df parsed columns"
        base["Benchmark"] = pd.to_numeric(df["Benchmark Return Num"], errors="coerce")
        base["Tolerance"] = pd.to_numeric(df["Tolerance Num"], errors="coerce")
        base["BNP Return"] = pd.to_numeric(df["Actual Return Num"], errors="coerce")
        if "BNP Status" not in base.columns:
            base["BNP Status"] = ""
    else:
        bnp_source = "bundle['dd']"
        bnp = build_bnp_return_fields(bundle)
        if bnp.empty:
            return ReturnCheckResult(pd.DataFrame(), {}, recon_tolerance_pct,
                                     "No BNP return fields (portfolio_df lacks parsed columns and no 'dd' in bundle)", diag=uni_diag)
        base = base.merge(bnp, left_on="_hiport_norm", right_on="Hiport norm", how="left").drop(columns=["Hiport norm"], errors="ignore")
        if "Advisor norm" in base.columns:
            need = base["_advisor_norm"].astype(str).str.len().eq(0)
            base.loc[need, "_advisor_norm"] = base.loc[need, "Advisor norm"].fillna("")
        base = base.drop(columns=["Advisor norm"], errors="ignore")
    uni_diag["bnp_source"] = bnp_source

    # Unison Return keyed on advisor (parsed in PERCENT units).
    base["Unison Return (pct)"] = base["_advisor_norm"].map(lambda k: uni_map.get(k))
    base["Unison basis"] = base["_advisor_norm"].map(lambda k: uni_basis.get(k, ""))

    for c in ["Benchmark", "Tolerance", "BNP Return", "Unison Return (pct)"]:
        base[c] = pd.to_numeric(base[c], errors="coerce")

    # --- Scale-align Unison Return to the app's BNP Return scale. Unison and BNP
    #     Actual are the SAME quantity from two systems (they agree closely), so
    #     the ratio of their medians reveals the app's scale (percent vs decimal).
    #     This makes v310 correct whatever scale portfolio_df uses. ---
    scale = 1.0
    m = base[base["Unison Return (pct)"].notna() & base["BNP Return"].notna()]
    if len(m) >= 5:
        um = float(m["Unison Return (pct)"].abs().median())
        bm = float(m["BNP Return"].abs().median())
        if um > 0 and bm > 0:
            r = bm / um
            # Snap to the nearest sensible factor (1 or 1/100) to avoid noise.
            scale = 0.01 if r < 0.2 else (1.0 if r < 5 else 1.0)
    uni_diag["unison_scale_factor"] = scale
    base["Unison Return"] = base["Unison Return (pct)"] * scale
    base = base.drop(columns=["Unison Return (pct)"], errors="ignore")

    # Core calculations (all percent units).
    base["Unison vs Benchmark"] = base["Unison Return"] - base["Benchmark"]
    base["Variance (Unison-BNP)"] = base["Unison Return"] - base["BNP Return"]

    # PRIMARY OUT (Unison basis).
    have_out_inputs = base["Unison Return"].notna() & base["Benchmark"].notna() & base["Tolerance"].notna()
    base["OUT (Unison basis)"] = pd.NA
    base.loc[have_out_inputs, "OUT (Unison basis)"] = base.loc[have_out_inputs, "Unison vs Benchmark"].abs() >= base.loc[have_out_inputs, "Tolerance"].abs()

    # OLD OUT (BNP-internal), retained for reconciliation.
    if "Within Tolerance" in df.columns:
        base["OUT (BNP-internal)"] = ~df["Within Tolerance"].reindex(base.index).fillna(True).astype(bool)
    elif "BNP Status" in base.columns:
        base["OUT (BNP-internal)"] = base["BNP Status"].astype(str).str.upper().eq("OUT")
    else:
        base["OUT (BNP-internal)"] = pd.NA

    # Return reconciliation check (Unison vs BNP return).
    tol_recon = float(recon_tolerance_pct)
    base["Return recon Check"] = ""
    rv = base["Variance (Unison-BNP)"]
    base.loc[rv.notna() & (rv.abs() > tol_recon), "Return recon Check"] = "Check"
    base.loc[rv.notna() & (rv.abs() <= tol_recon), "Return recon Check"] = "Ok"

    # v326: classify each recon breach as a BNP SIGN-FLIP (BNP displays the opposite
    # sign; magnitudes agree once corrected) vs a TRUE ANOMALY. Sign-flip when the
    # signs are opposite AND |Unison + BNP| <= the same recon tolerance (i.e. the
    # returns actually agree). Everything else that breaches is a true anomaly.
    _u = pd.to_numeric(base["Unison Return"], errors="coerce")
    _b = pd.to_numeric(base["BNP Return"], errors="coerce")
    _opp = _u.notna() & _b.notna() & ((_u > 0) & (_b < 0) | (_u < 0) & (_b > 0))
    _sumabs = (_u + _b).abs()
    _is_check = base["Return recon Check"].eq("Check")
    base["Unison + BNP"] = (_u + _b)
    base["Recon breach type"] = ""
    base.loc[_is_check & _opp & (_sumabs <= tol_recon), "Recon breach type"] = "Sign flip (BNP convention)"
    base.loc[_is_check & ~(_opp & (_sumabs <= tol_recon)), "Recon breach type"] = "True anomaly"

    # OUT reclassification (audit of the basis change).
    def _reclass(r):
        a, b = r["OUT (Unison basis)"], r["OUT (BNP-internal)"]
        if pd.isna(a) or pd.isna(b):
            return "Not comparable"
        if a and not b:
            return "BNP Within -> Unison OUT"
        if b and not a:
            return "BNP OUT -> Unison Within"
        return "No change"
    base["OUT Reclassification"] = base.apply(_reclass, axis=1)

    base["Unison matched?"] = base["Unison Return"].notna()
    base = base.drop(columns=["_hiport_norm", "_advisor_norm"], errors="ignore")

    # -----------------------------------------------------------------------
    # v326 (B/C-2) - ADDITIVE workbook-scoped OUT. The raw Unison-basis OUT above
    # tests EVERY portfolio; the ARC workbook did not. Two workbook rules are
    # applied here as a SEPARATE, reason-coded column so the raw OUT is retained
    # and the reclassification is auditable side-by-side (mirrors the v310 OUT
    # reclassification pattern):
    #   (B) Class exclusion  - overlay/treasury classes are outside the Advisor
    #       Return Check population (Static Data mapping_filters 'Advisor Return
    #       Check' EXCLUDE Class). Config-driven; workbook-exact.
    #   (C) NAV=0 gate       - workbook AD=IF(I<>0, ..., "OK"): a zero-NAV line is
    #       forced OK. NAV (Unison NAV, Acc Balance 9018) is read from the GAV
    #       check frame on the bundle when available.
    # Gated by Static Data thresholds 'workbook_scoped_out_enabled' (default on).
    # If disabled, the workbook-scoped OUT simply mirrors the raw OUT.
    # -----------------------------------------------------------------------
    static_bundle_wb = bundle.get("static_data") if isinstance(bundle, dict) else None
    wb_enabled = _resolve_workbook_scoped_out_enabled(static_bundle_wb)
    excluded_classes = _resolve_excluded_classes(static_bundle_wb)
    nav_norm = _nav_by_portfolio_norm_from_bundle(bundle)

    raw_out = base["OUT (Unison basis)"]
    class_l = (base["Class"].astype(str).str.strip().str.lower()
               if "Class" in base.columns else pd.Series([""] * len(base), index=base.index))
    key_norm = _norm_join(base[portfolio_code_col]) if portfolio_code_col in base.columns else pd.Series([""] * len(base), index=base.index)
    nav_series = key_norm.map(lambda k: nav_norm.get(str(k))) if nav_norm else pd.Series([pd.NA] * len(base), index=base.index)
    nav_num = pd.to_numeric(nav_series, errors="coerce")

    excl_l = {str(c).strip().lower() for c in excluded_classes}
    is_excluded_class = class_l.isin(excl_l) if excl_l else pd.Series([False] * len(base), index=base.index)
    have_nav = nav_num.notna()
    is_zero_nav = have_nav & (nav_num.abs() <= 0.0)

    scoped = raw_out.copy()
    reason = pd.Series([""] * len(base), index=base.index, dtype="object")
    if wb_enabled:
        # class exclusion first (population), then NAV gate (workbook AD)
        scoped = scoped.where(~is_excluded_class, other=False)
        reason = reason.mask(is_excluded_class, class_l.map(lambda c: f"OK - excluded class ({c.title()})"))
        gate_nav = is_zero_nav & ~is_excluded_class
        scoped = scoped.where(~gate_nav, other=False)
        reason = reason.mask(gate_nav, "OK - zero NAV (workbook AD gate)")
        # everything else keeps the raw OUT; note where NAV was unavailable for the gate
        reason = reason.mask((reason == "") & raw_out.astype("boolean").fillna(False) & ~have_nav,
                             "OUT (NAV unavailable - class-only scope)")
        reason = reason.mask(reason == "", "Same as raw OUT")
    else:
        reason = pd.Series(["(workbook scope disabled)"] * len(base), index=base.index, dtype="object")

    base["OUT (workbook-scoped)"] = scoped
    base["OUT Scope Reason"] = reason
    base["Unison NAV"] = nav_num

    order = [c for c in [portfolio_code_col, advisor_col, "Portfolio Name", "Class",
                         "Unison Return", "BNP Return", "Benchmark", "Tolerance",
                         "Unison vs Benchmark", "OUT (Unison basis)", "OUT (workbook-scoped)",
                         "OUT Scope Reason", "Unison NAV", "OUT (BNP-internal)",
                         "OUT Reclassification", "Variance (Unison-BNP)", "Unison + BNP", "Return recon Check", "Recon breach type",
                         "Unison basis", "Unison matched?", "BNP Status"] if c in base.columns]
    base = base[order]

    n = len(base)
    out_uni = int(base["OUT (Unison basis)"].astype("boolean").fillna(False).astype(bool).sum())
    out_wb = int(base["OUT (workbook-scoped)"].astype("boolean").fillna(False).astype(bool).sum())
    out_bnp = int(base["OUT (BNP-internal)"].astype("boolean").fillna(False).astype(bool).sum())
    reclass = base["OUT Reclassification"].value_counts().to_dict()
    summary = {
        "portfolios": n,
        "unison_matched": int(base["Unison matched?"].sum()),
        "out_unison_basis": out_uni,
        "out_workbook_scoped": out_wb,
        "out_scoped_out_by_class": int(is_excluded_class.sum()) if wb_enabled else 0,
        "out_scoped_out_by_zero_nav": int((is_zero_nav & ~is_excluded_class).sum()) if wb_enabled else 0,
        "workbook_scope_enabled": bool(wb_enabled),
        "workbook_scope_nav_available": bool(nav_norm),
        "out_bnp_internal": out_bnp,
        "recon_checks": int((base["Return recon Check"] == "Check").sum()),
        "recon_true_anomalies": int((base["Recon breach type"] == "True anomaly").sum()),
        "recon_sign_flips": int((base["Recon breach type"] == "Sign flip (BNP convention)").sum()),
        "reclassified": int(n - reclass.get("No change", 0) - reclass.get("Not comparable", 0)),
        "recon_tolerance_pct": tol_recon,
    }
    return ReturnCheckResult(base, summary, tol_recon, "OK", uni_diag)


# ---------------------------------------------------------------------------
# v326 (B/C-2) helpers - workbook-scoped OUT config + inputs
# ---------------------------------------------------------------------------
DEFAULT_EXCLUDED_CLASSES = ["Currency Overlay", "Derivative Overlay", "Treasury"]


def _resolve_workbook_scoped_out_enabled(static_bundle) -> bool:
    "Read the workbook-scoped OUT feature flag from Static Data thresholds (default ON)."
    if static_bundle is not None and callable(_get_threshold_value):
        try:
            v = _get_threshold_value(static_bundle, "workbook_scoped_out_enabled", "Y")
            return str(v).strip().lower() in {"y", "yes", "true", "1", "on", "active"}
        except Exception:
            pass
    return True


def _resolve_excluded_classes(static_bundle):
    "Advisor Return Check EXCLUDE Class list from Static Data mapping_filters (config-driven)."
    try:
        from bnp_helpers_static_data import advisor_return_check_excluded_classes as _excl
        vals = _excl(static_bundle)
        if vals:
            return list(vals)
    except Exception:
        pass
    return list(DEFAULT_EXCLUDED_CLASSES)


def _nav_by_portfolio_norm_from_bundle(bundle) -> Dict[str, float]:
    "Return {Portfolio code norm -> Unison NAV} from the GAV check frame if present."
    out: Dict[str, float] = {}
    if not isinstance(bundle, dict):
        return out
    gav = bundle.get("gav_check_df")
    if not isinstance(gav, pd.DataFrame) or gav.empty:
        return out
    pcol = None
    for c in ("Portfolio code", "Portfolio", "PortfolioCode"):
        if c in gav.columns:
            pcol = c
            break
    ncol = None
    for c in ("Unison NAV", "Unison NAV ", "NAV"):
        if c in gav.columns:
            ncol = c
            break
    if not pcol or not ncol:
        return out
    keys = _norm_join(gav[pcol])
    vals = pd.to_numeric(gav[ncol], errors="coerce")
    for k, v in zip(keys.tolist(), vals.tolist()):
        k = str(k).strip()
        if k and k not in out and pd.notna(v):
            out[k] = float(v)
    return out


# ---------------------------------------------------------------------------
# v310.1 - Hot/Cold realignment to the Unison deviation
# ---------------------------------------------------------------------------
UNISON_VOT_COL = "Unison Volatility over Tolerance Num"
HOTCOLD_BEFORE_COL = "_hotcold_before_unison_v310_1"


def compute_unison_volatility_over_tolerance(portfolio_df: pd.DataFrame, bundle: Dict[str, object],
                                             *, portfolio_code_col: str = "Portfolio code",
                                             advisor_col: str = "External portfolio reference") -> Optional[pd.Series]:
    """Unison-basis 'Volatility over Tolerance', in the SAME units as the app's
    existing 'Volatility over Tolerance Num', so the authoritative classifier can
    consume it for Hot/Cold.

    v310.1 FIX (scale-correct): the whole VoT is computed in ONE self-consistent
    scale (percent, from the raw DDetailedReturn) and only then scaled to match
    the app's own 'Volatility over Tolerance Num' units (which are decimal). The
    earlier version mixed a percent 'Benchmark Return Num' with a decimal
    'Tolerance Decimal', producing a percent-scale VoT that the classifier then
    compared against a decimal Error Risk Ratio -> every OUT row became Hot.

    Method:
      * From dd raw (all percent): benchmark%, tolerance%, actual% per Hiport.
      * From Tableau: unison% per advisor.
      * bnp_vot_pct = max(|actual% - bench%| - tol%, 0)   (percent)
      * uni_vot_pct = max(|unison% - bench%| - tol%, 0)   (percent)
      * factor = the app's 'Volatility over Tolerance Num' / bnp_vot_pct, taken as
        a robust median over sizeable rows and SNAPPED to {1, 1e-2, 1e-4}. This is
        a VoT-to-VoT anchor, so the result lands in exactly the scale the
        classifier compares against the Error Risk Ratio.
      * Cross-check: predicted BNP VoT (bnp_vot_pct*factor) must reconcile with the
        app's 'Volatility over Tolerance Num'; if not, RETURN None (fail-safe:
        Hot/Cold stay on the BNP basis rather than risk corruption).
      * uni_vot_app = uni_vot_pct * factor.

    Returns a Series indexed like portfolio_df (NaN where no Unison match, so the
    classifier falls back to the BNP deviation for those rows), or None (fail-safe).
    """
    import math
    if not isinstance(portfolio_df, pd.DataFrame) or portfolio_df.empty:
        return None
    if "Volatility over Tolerance Num" not in portfolio_df.columns:
        return None  # need the app's own VoT to anchor the scale (fail-safe)
    dd = bundle.get("dd") if isinstance(bundle, dict) else None
    if not isinstance(dd, pd.DataFrame) or dd.empty:
        return None
    dc = _resolve_dd_columns(dd)
    if not (dc.get("portfolio") and dc.get("benchmark") and dc.get("tolerance") and dc.get("actual")):
        return None
    uni_map, _basis, _diag = build_unison_return_map(bundle)
    if not uni_map:
        return None

    df = portfolio_df
    # Per-Hiport PERCENT maps from dd raw (single, self-consistent scale).
    key = _norm_join(dd[dc["portfolio"]])
    def _dd_map(col):
        s = pd.Series(pd.Series(dd[col]).map(_pct).values, index=key.values)
        return s[~s.index.duplicated(keep="first")]
    bench_map = _dd_map(dc["benchmark"]); tol_map = _dd_map(dc["tolerance"]); act_map = _dd_map(dc["actual"])
    hip = _norm_join(df[portfolio_code_col]) if portfolio_code_col in df.columns else _norm_join(df[advisor_col])
    bench_pct = hip.map(bench_map)
    tol_pct = hip.map(tol_map).abs()
    actual_pct = hip.map(act_map)

    # Unison return (percent) by advisor.
    adv = df[advisor_col].map(_norm_token) if advisor_col in df.columns else pd.Series("", index=df.index)
    unison_pct = adv.map(lambda k: uni_map.get(k))

    # VoT in PERCENT for BOTH bases - identical formula, one scale.
    bnp_vot_pct = ((actual_pct - bench_pct).abs() - tol_pct).clip(lower=0.0)
    uni_vot_pct = ((unison_pct - bench_pct).abs() - tol_pct).clip(lower=0.0)

    # Scale to the app's 'Volatility over Tolerance Num' (decimal) via VoT-to-VoT.
    app_vot = pd.to_numeric(df["Volatility over Tolerance Num"], errors="coerce").abs()
    m = bnp_vot_pct.notna() & app_vot.notna() & (bnp_vot_pct > 0.02) & (app_vot > 0)
    if int(m.sum()) < 5:
        return None
    raw_factor = float((app_vot[m] / bnp_vot_pct[m]).median())
    if not (raw_factor > 0) or not math.isfinite(raw_factor):
        return None
    factor = min([1.0, 1e-2, 1e-4], key=lambda c: abs(math.log10(raw_factor) - math.log10(c)))

    # Cross-check: reconstructed BNP VoT must reconcile with the app's own VoT.
    predicted = bnp_vot_pct * factor
    rel = (predicted[m] - app_vot[m]).abs() / (app_vot[m].abs() + 1e-12)
    if float(rel.median()) > 0.5:
        return None  # scale does not reconcile -> keep BNP basis (fail-safe)

    uni_vot_app = (uni_vot_pct * factor).where(unison_pct.notna(), other=pd.NA)
    uni_vot_app.name = UNISON_VOT_COL
    return uni_vot_app


def attach_unison_volatility_column(bundle: Dict[str, object]) -> Dict[str, object]:
    """Write the Unison-basis VoT column onto bundle['portfolio_df'] and snapshot
    the current (BNP-basis) Hot/Cold so the reclassification can be reported.
    Fully guarded; on any problem the bundle is returned unchanged."""
    try:
        if not isinstance(bundle, dict):
            return bundle
        pf = bundle.get("portfolio_df")
        if not isinstance(pf, pd.DataFrame) or pf.empty:
            return bundle
        vot = compute_unison_volatility_over_tolerance(pf, bundle)
        if vot is None:
            bundle["hotcold_unison_realign_status"] = "skipped (inputs unavailable; Hot/Cold remain on BNP basis)"
            return bundle
        pf = pf.copy()
        if "Hot / Cold" in pf.columns:
            pf[HOTCOLD_BEFORE_COL] = pf["Hot / Cold"].astype(str)
        pf[UNISON_VOT_COL] = vot
        bundle["portfolio_df"] = pf
        bundle["hotcold_unison_realign_status"] = f"attached ({int(vot.notna().sum())} portfolios have a Unison deviation)"
    except Exception as exc:
        try:
            bundle["hotcold_unison_realign_status"] = f"error: {type(exc).__name__}: {exc}"
        except Exception:
            pass
    return bundle


def record_hotcold_reclassification(bundle: Dict[str, object]) -> Dict[str, object]:
    """After the classifier has re-run on the Unison deviation, compare the new
    Hot/Cold to the snapshot taken in attach_unison_volatility_column and store a
    before/after reconciliation dataframe + summary in the bundle."""
    try:
        if not isinstance(bundle, dict):
            return bundle
        pf = bundle.get("portfolio_df")
        if not isinstance(pf, pd.DataFrame) or pf.empty or HOTCOLD_BEFORE_COL not in pf.columns or "Hot / Cold" not in pf.columns:
            return bundle
        before = pf[HOTCOLD_BEFORE_COL].astype(str).str.strip()
        after = pf["Hot / Cold"].astype(str).str.strip()
        changed = before.ne(after)
        cols = [c for c in ["Portfolio code", "External portfolio reference", "Portfolio Name"] if c in pf.columns]
        recon = pf.loc[changed, cols].copy()
        recon["Hot/Cold (BNP basis)"] = before[changed].values
        recon["Hot/Cold (Unison basis)"] = after[changed].values
        if UNISON_VOT_COL in pf.columns:
            recon["Unison VoT"] = pf.loc[changed, UNISON_VOT_COL].values
        bundle["hotcold_reclassification_df"] = recon
        # invariant (unchanged counts): No source + Cold + Hot == OUT
        no_src = {"No BP Impact row", "No Error Risk row", "No ARC match"}
        out_mask = ~pf["Within Tolerance"].fillna(True).astype(bool) if "Within Tolerance" in pf.columns else after.isin(no_src | {"Cold", "Hot"})
        n_out = int(out_mask.sum())
        n_ns = int((out_mask & after.isin(no_src)).sum())
        n_cold = int((out_mask & after.eq("Cold")).sum())
        n_hot = int((out_mask & after.eq("Hot")).sum())
        bundle["hotcold_reclassification_summary"] = {
            "changed": int(changed.sum()),
            "bnp_to_hot": int((changed & after.eq("Hot")).sum()),
            "bnp_to_cold": int((changed & after.eq("Cold")).sum()),
            "out": n_out, "no_source": n_ns, "cold": n_cold, "hot": n_hot,
            "invariant_ok": bool(n_ns + n_cold + n_hot == n_out),
            "invariant_detail": f"No source ({n_ns}) + Cold ({n_cold}) + Hot ({n_hot}) = {n_ns+n_cold+n_hot}; OUT = {n_out}",
        }
        # tidy: drop the internal snapshot column so it doesn't leak into exports
        bundle["portfolio_df"] = pf.drop(columns=[HOTCOLD_BEFORE_COL], errors="ignore")
    except Exception:
        pass
    return bundle


def _resolve_recon_tolerance(static_bundle) -> float:
    if static_bundle is not None and callable(_get_threshold_value):
        try:
            return float(_get_threshold_value(static_bundle, "return_recon_tolerance_pct", DEFAULT_RETURN_RECON_TOLERANCE_PCT))
        except Exception:
            pass
    return DEFAULT_RETURN_RECON_TOLERANCE_PCT


def render_return_check_section(st, bundle: Dict[str, object]) -> None:
    """Render Portfolio Numbers -> Advisor Return Check (v310). Fully guarded."""
    try:
        portfolio_df = bundle.get("portfolio_df", pd.DataFrame()) if isinstance(bundle, dict) else pd.DataFrame()
        if not isinstance(portfolio_df, pd.DataFrame) or portfolio_df.empty:
            return
        static_bundle = bundle.get("static_data") if isinstance(bundle, dict) else None
        tol = _resolve_recon_tolerance(static_bundle)

        st.markdown("**Advisor Return Check - core (v310)**")
        st.caption("PRIMARY OUT = |Unison Return (Tableau price) - Benchmark| >= Tolerance. "
                   "The app's prior BNP-internal OUT is shown alongside as reconciliation. "
                   f"Return recon flags |Unison - BNP return| > {tol}% "
                   "(Static Data: return_recon_tolerance_pct). Benchmark name deferred.")

        res = build_return_check(portfolio_df, bundle, recon_tolerance_pct=tol)
        if res.status != "OK" or res.return_df.empty:
            st.warning(f"Return Check unavailable: {res.status}. "
                       f"(Unison prices need Tableau SF/Trust CSVs; benchmark/tolerance need DDetailedReturn.) "
                       f"Diagnostic: {res.diag}")
            return
        if isinstance(bundle, dict):
            bundle["return_check_df"] = res.return_df
            bundle["return_check_summary"] = res.summary

        s = res.summary
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Portfolios", s["portfolios"])
        c2.metric("Unison matched", s["unison_matched"])
        c3.metric("OUT (Unison)", s["out_unison_basis"])
        c4.metric("OUT (BNP old)", s["out_bnp_internal"])
        c5.metric("Reclassified", s["reclassified"])

        # v326 (B/C-2): workbook-scoped OUT - raw OUT minus overlay/treasury class
        # exclusions and zero-NAV lines (workbook AD gate). Shown alongside the raw
        # OUT so the difference is auditable; raw OUT is unchanged.
        if s.get("workbook_scope_enabled"):
            w1, w2, w3, w4 = st.columns(4)
            w1.metric("OUT (workbook-scoped)", s.get("out_workbook_scoped", 0),
                      delta=int(s.get("out_workbook_scoped", 0)) - int(s.get("out_unison_basis", 0)),
                      delta_color="off")
            w2.metric("Scoped OUT - by class", s.get("out_scoped_out_by_class", 0))
            w3.metric("Scoped OUT - by zero NAV", s.get("out_scoped_out_by_zero_nav", 0))
            w4.metric("NAV source", "GAV check (prep)" if s.get("workbook_scope_nav_available") else "unavailable")
            if not s.get("workbook_scope_nav_available"):
                st.caption("Zero-NAV gate is inactive this run because no Acc Balance source was resolved at "
                           "prep time (v327 computes GAV/NAV once at bundle prep so this normally always "
                           "fires). Class exclusions are always applied as the fail-safe.")
            _scoped_diff = res.return_df[
                res.return_df["OUT Scope Reason"].astype(str).str.startswith("OK - ")
            ].copy() if "OUT Scope Reason" in res.return_df.columns else pd.DataFrame()
            if not _scoped_diff.empty:
                with st.expander(f"Workbook-scoped OUT reclassifications ({len(_scoped_diff)}) - raw OUT set to OK by workbook rules", expanded=False):
                    st.dataframe(_scoped_diff, width="stretch", hide_index=True)
                    st.download_button("Download workbook-scoped OUT reclassifications",
                                       _scoped_diff.to_csv(index=False).encode("utf-8"),
                                       "return_check_workbook_scoped_out_last_run.csv", "text/csv",
                                       key="rc_wbscope_dl")

        st.markdown("**OUT basis reconciliation** - portfolios where the new Unison-basis OUT differs from the old BNP-internal OUT:")
        reclass = res.return_df[res.return_df["OUT Reclassification"].isin(["BNP Within -> Unison OUT", "BNP OUT -> Unison Within"])].copy()
        if reclass.empty:
            st.success("No reclassifications - Unison-basis OUT matches the prior BNP-internal OUT for all comparable portfolios.")
        else:
            st.dataframe(reclass, width="stretch", hide_index=True)
            st.download_button("Download OUT reclassifications", reclass.to_csv(index=False).encode("utf-8"),
                               "return_check_out_reclassification_last_run.csv", "text/csv", key="rc_reclass_dl")

        # v326: Recon sign-flip audit - separate true anomalies from BNP sign-flips.
        st.markdown("**Recon sign-flip audit** - BNP can display the opposite sign to Unison; "
                    "those are set aside so the TRUE return-recon anomalies stand out.")
        _breaches = res.return_df[res.return_df["Return recon Check"] == "Check"].copy()
        _true = _breaches[_breaches["Recon breach type"] == "True anomaly"].copy() if "Recon breach type" in _breaches.columns else _breaches
        _flips = _breaches[_breaches["Recon breach type"] == "Sign flip (BNP convention)"].copy() if "Recon breach type" in _breaches.columns else _breaches.iloc[0:0]
        _c1, _c2 = st.columns(2)
        _c1.metric("True anomalies", int(len(_true)))
        _c2.metric("Sign-flips (BNP convention)", int(len(_flips)))
        st.markdown(f"*True anomalies* - genuine |Unison - BNP| > {tol}% (action these):")
        st.dataframe(_true, width="stretch", hide_index=True)
        st.download_button("Download recon true anomalies", _true.to_csv(index=False).encode("utf-8"),
                           "recon_true_anomalies_last_run.csv", "text/csv", key="rc_true_dl")
        with st.expander("Sign-flips (BNP convention) - returns agree, BNP shows opposite sign", expanded=False):
            st.caption("Opposite signs but |Unison + BNP| is within tolerance - a BNP display convention, not a break.")
            st.dataframe(_flips, width="stretch", hide_index=True)
            st.download_button("Download recon sign-flips", _flips.to_csv(index=False).encode("utf-8"),
                               "recon_sign_flips_last_run.csv", "text/csv", key="rc_flip_dl")
        recon = _true
        st.dataframe(recon, width="stretch", hide_index=True)
        st.download_button("Download return recon breaches", recon.to_csv(index=False).encode("utf-8"),
                           "return_check_recon_breaches_last_run.csv", "text/csv", key="rc_recon_dl")

        with st.expander("Full Advisor Return Check evidence (all portfolios)", expanded=False):
            st.dataframe(res.return_df, width="stretch", hide_index=True)
            st.download_button("Download full Return Check", res.return_df.to_csv(index=False).encode("utf-8"),
                               "return_check_full_last_run.csv", "text/csv", key="rc_full_dl")

        # v310.1: Hot/Cold realignment reconciliation (severity on the Unison deviation).
        # GATED: only shown when the realignment actually applied this run (a
        # reclassification summary exists). When inputs are unavailable it is
        # skipped silently (no confusing "not applied" message).
        rsum_hc = bundle.get("hotcold_reclassification_summary") if isinstance(bundle, dict) else None
        recon_hc = bundle.get("hotcold_reclassification_df") if isinstance(bundle, dict) else None
        status_hc = bundle.get("hotcold_unison_realign_status") if isinstance(bundle, dict) else None
        if isinstance(rsum_hc, dict):
            st.markdown("**Hot/Cold realignment** - severity uses the same "
                        "Unison-vs-benchmark deviation as OUT.")
            _render_hotcold_reclass(st, rsum_hc, recon_hc, status_hc)
    except Exception:
        pass


def _render_hotcold_reclass(st, summary, recon_df, status) -> None:
    """Render the v310.1 Hot/Cold realignment reconciliation (severity change)."""
    try:
        if not isinstance(summary, dict):
            return  # gated upstream; nothing to show when realignment did not apply
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Severity changed", summary.get("changed", 0))
        c2.metric("-> Hot", summary.get("bnp_to_hot", 0))
        c3.metric("-> Cold", summary.get("bnp_to_cold", 0))
        c4.metric("OUT (unchanged)", summary.get("out", 0))
        if summary.get("invariant_ok", True):
            st.success("Invariant holds: " + str(summary.get("invariant_detail", "")))
        else:
            st.error("Invariant FAILED: " + str(summary.get("invariant_detail", "")))
        if isinstance(recon_df, pd.DataFrame) and not recon_df.empty:
            st.caption("Portfolios whose Hot/Cold severity changed when moved to the Unison deviation:")
            st.dataframe(recon_df, width="stretch", hide_index=True)
            st.download_button("Download Hot/Cold realignment", recon_df.to_csv(index=False).encode("utf-8"),
                               "hotcold_realignment_last_run.csv", "text/csv", key="hc_realign_dl")
        else:
            st.success("No severity changes - Hot/Cold is identical on the Unison and BNP bases for this date.")
    except Exception:
        pass


def build_advisor_return_gav_style(bundle: Dict[str, object]):
    """GAV-style wrapper for Advisor Return Check: population/investigation
    (red)/OK (green)/excluded (neutral) + single-tab full pack + invariant.

    Population = portfolios with a matched Unison price (genuinely testable).
    Investigation (red) = OUT (workbook-scoped) among the matched population.
    OK (green) = matched and not OUT (workbook-scoped) - this correctly
        includes portfolios forced OK by the workbook's class-exclusion / NAV=0
        gates (see 'OUT Scope Reason'), since those ARE tested, just resolved
        to OK by business rule.
    Excluded (neutral) = no Unison price matched this run (cannot be tested
        against the Unison basis at all) - retained with a reason.
    """
    from bnp_helpers_gav_style import GavStyleResult, compute_invariant

    portfolio_df = bundle.get("portfolio_df", pd.DataFrame()) if isinstance(bundle, dict) else pd.DataFrame()
    if not isinstance(portfolio_df, pd.DataFrame) or portfolio_df.empty:
        return GavStyleResult(status="No portfolio detail available for the selected day")
    static_bundle = bundle.get("static_data") if isinstance(bundle, dict) else None
    tol = _resolve_recon_tolerance(static_bundle)
    res = build_return_check(portfolio_df, bundle, recon_tolerance_pct=tol)
    if res.status != "OK":
        return GavStyleResult(status=res.status, diag=res.diag)
    df = res.return_df.copy()
    if df.empty or "Unison matched?" not in df.columns or "OUT (workbook-scoped)" not in df.columns:
        return GavStyleResult(status="Advisor Return Check produced no usable rows this run")

    matched = df["Unison matched?"].astype(bool)
    out_flag = df["OUT (workbook-scoped)"].astype("boolean").fillna(False).astype(bool)

    df = df.copy()
    df["Exclusion Reason"] = ""
    df.loc[~matched, "Exclusion Reason"] = "No Unison price matched this run (Tableau SF/Trust price file)"
    # v360: paired "In <Control> population" boolean + standardised "Check" column.
    df["In Advisor Return population"] = matched
    df["Check"] = "Excluded"
    df.loc[matched & ~out_flag, "Check"] = "Ok"
    df.loc[matched & out_flag, "Check"] = "Check"

    green_df = df[matched & ~out_flag].copy()
    red_df = df[matched & out_flag].copy()
    excluded_df = df[~matched].copy()
    population_count = int(len(green_df) + len(red_df))

    ok, detail = compute_invariant(population_count, [len(red_df)], len(green_df))

    return GavStyleResult(
        red_frames=[("Check (OUT)", red_df)],
        green_df=green_df,
        excluded_df=excluded_df,
        full_df=df,
        population_metrics=[
            ("Advisor Return population", population_count),
            ("Advisor Return checks (OUT)", int(len(red_df))),
            ("Advisor Return OK", int(len(green_df))),
            ("Excluded (no Unison price)", int(len(excluded_df))),
        ],
        invariant_ok=ok,
        invariant_detail=detail,
        status="OK",
        diag=res.diag,
        currency_cols=["Unison NAV"],
        # v361 FIX: these columns are ALREADY IN PERCENT UNITS (e.g. Tolerance =
        # 25.0 meaning 25%, confirmed from the raw advisor_return_check_check_
        # (out).csv export), NOT decimal - so they must use already_percent_cols
        # (no x100), never percent_cols (which would double-scale to 2500.00%).
        already_percent_cols=["Unison Return", "BNP Return", "Benchmark", "Tolerance",
                              "Unison vs Benchmark", "Variance (Unison-BNP)", "Unison + BNP"],
        population_bool_col="In Advisor Return population",
        # v361: renamed from "Advisor Return Check" to "Advisor Return" so labels
        # in dataframes/metrics/headers read "Advisor Return checks OK" etc.
        # rather than the awkward "Advisor Return Check checks OK".
        control_noun="Advisor Return",
    )


def render_advisor_return_gav_style(st, bundle: Dict[str, object]) -> None:
    from bnp_helpers_gav_style import render_gav_style_section
    result = build_advisor_return_gav_style(bundle)
    if isinstance(bundle, dict):
        bundle["advisor_return_gav_style_result"] = result
    render_gav_style_section(
        st, control_key="advisor_return", title="Advisor Return",
        purpose=("Unison Return (Tableau SF/Trust price) vs Benchmark, workbook-scoped OUT (class exclusion + "
                 "NAV=0 gate applied). Population is every portfolio with a matched Unison price this run; "
                 "portfolios with no Unison price match are excluded from the Check/Ok test but retained for audit."),
        result=result, download_filename_prefix="advisor_return_check",
    )


if __name__ == "__main__":
    print(f"[{RETURN_CHECK_VERSION}] Advisor Return Check self-test")
    real_trust = "/mnt/user-data/uploads/Daily Price - By Trust Product.csv"
    real_sf = "/mnt/user-data/uploads/Daily Price - By Statutory Fund.csv"
    real_dd = "/mnt/user-data/uploads/BNPPSS_INSGNAU01_DDetailedReturn_ILFMAY-310726-IRVR26073166ZHO_1_20260731233918.csv"
    if all(os.path.exists(p) for p in (real_trust, real_sf, real_dd)):
        # index_col=False: the file has a trailing comma (data has 1 more field
        # than the header), which would otherwise make pandas use the first
        # column as the index and shift every column by +1. The app's own BNP
        # parser handles this; here we force correct alignment for the test.
        dd = pd.read_csv(real_dd, skiprows=2, encoding="latin-1", index_col=False)
        dd.columns = [str(c).strip() for c in dd.columns]
        # Build a portfolio_df like the app's: Portfolio code = Hiport, External ref = advisor.
        cols = _resolve_dd_columns(dd)
        pf = pd.DataFrame({
            "Portfolio code": dd[cols["portfolio"]].astype(str).str.strip(),
            "External portfolio reference": dd[cols["external"]].astype(str).str.strip(),
            "Portfolio Name": dd[cols["portfolio"]].astype(str),
        })
        bundle = {
            "portfolio_df": pf,
            "dd": dd,
            "tableau_file_meta_df": pd.DataFrame([
                {"ReportKey": "tableau_price_trust", "ExpectedPath": real_trust, "ResolvedPath": real_trust},
                {"ReportKey": "tableau_price_sf", "ExpectedPath": real_sf, "ResolvedPath": real_sf},
            ]),
        }
        res = build_return_check(pf, bundle, recon_tolerance_pct=0.02)
        print("  status:", res.status, "| diag:", res.diag)
        print("  summary:", res.summary)
        rc = res.return_df[res.return_df["OUT Reclassification"].isin(["BNP Within -> Unison OUT", "BNP OUT -> Unison Within"])]
        print(f"  reclassifications: {len(rc)}")
        pd.set_option("display.width", 220); pd.set_option("display.max_columns", 30)
        show = res.return_df[res.return_df["Unison matched?"]].head(6)
        print(show[["Portfolio code", "External portfolio reference", "Unison Return", "BNP Return",
                    "Benchmark", "Tolerance", "Unison vs Benchmark", "OUT (Unison basis)", "OUT (BNP-internal)"]].to_string(index=False))
        assert res.summary["unison_matched"] > 150, "expected most trusts to match Unison prices"
        base_out_uni = res.summary["out_unison_basis"]
        print("  OK - real-data self-test (dd path) passed")

        # --- App-path test: portfolio_df carries the parsed Num columns. Verify
        #     the result matches the dd path, at BOTH percent and decimal scale. ---
        b = build_bnp_return_fields(bundle)  # correctly-aligned reference fields
        ref = pf.copy()
        ref["_h"] = _norm_join(ref["Portfolio code"])
        b2 = b.rename(columns={"Hiport norm": "_h"})
        ref = ref.merge(b2[["_h", "Benchmark", "Tolerance", "BNP Return", "BNP Status"]], on="_h", how="left")
        for scale_name, sf_scale in [("percent", 1.0), ("decimal", 0.01)]:
            pf2 = pf.copy()
            pf2["Benchmark Return Num"] = ref["Benchmark"] * sf_scale
            pf2["Tolerance Num"] = ref["Tolerance"] * sf_scale
            pf2["Actual Return Num"] = ref["BNP Return"] * sf_scale
            pf2["Within Tolerance"] = ~ref["BNP Status"].astype(str).str.upper().eq("OUT")
            bundle2 = dict(bundle); bundle2["portfolio_df"] = pf2
            r2 = build_return_check(pf2, bundle2, recon_tolerance_pct=0.02)
            print(f"  app-path [{scale_name}]: bnp_source={r2.diag.get('bnp_source')} "
                  f"scale={r2.diag.get('unison_scale_factor')} OUT(Unison)={r2.summary['out_unison_basis']} "
                  f"reclassified={r2.summary['reclassified']}")
            assert r2.summary["out_unison_basis"] == base_out_uni, \
                f"app-path {scale_name} OUT mismatch: {r2.summary['out_unison_basis']} vs {base_out_uni}"
        print("  OK - app-path self-test passed (percent & decimal scale both reconcile)")
    else:
        print("  (real files not present; skipping real-data test)")
