# -*- coding: utf-8 -*-
"""Error Risk source helper for BNP Control App.

v306.13.9: loads Error Risk Report from BP Impact Tool.xlsb rather than from
the ARC workbook. The source path and sheet name are controlled by Static Data.xlsx:
- paths.bp_impact_tool_workbook
- reference_sources.error_risk_report / SheetName = Error Risk Report
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List

import pandas as pd
from dataclasses import dataclass, field

TRUE_VALUES = {"y", "yes", "true", "1", "active"}


def _active(df: pd.DataFrame) -> pd.Series:
    if df is None or df.empty or "Active" not in df.columns:
        return pd.Series([True] * (0 if df is None else len(df)), index=(df.index if isinstance(df, pd.DataFrame) else None))
    return df["Active"].astype(str).str.strip().str.lower().isin(TRUE_VALUES)


def _table(static_bundle: Dict[str, Any], name: str) -> pd.DataFrame:
    tables = static_bundle.get("tables", {}) if isinstance(static_bundle, dict) else {}
    df = tables.get(name, pd.DataFrame()) if isinstance(tables, dict) else pd.DataFrame()
    if not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame()
    return df.loc[_active(df)].copy().reset_index(drop=True)


def _config(static_bundle: Dict[str, Any], key: str, default: str = "") -> str:
    paths = _table(static_bundle, "paths")
    if paths.empty or "ConfigKey" not in paths.columns or "ConfigValue" not in paths.columns:
        return default
    m = paths.loc[paths["ConfigKey"].astype(str).str.strip().str.lower().eq(str(key).strip().lower())]
    if m.empty:
        return default
    val = m.iloc[0].get("ConfigValue", default)
    return default if pd.isna(val) or str(val).strip() == "" else str(val).strip()


def _root_variants(path: str) -> List[str]:
    p = str(path or "").strip()
    if not p:
        return []
    variants = [p]
    bs = chr(92)
    if p.upper().startswith("G:" + bs):
        variants.append(bs + bs + "hq.local" + bs + "Corp" + bs + p[3:].lstrip(bs))
    elif p.lower().startswith((bs + bs + "hq.local" + bs + "corp" + bs).lower()):
        variants.append("G:" + bs + p[len(bs + bs + "hq.local" + bs + "Corp" + bs):])
    out, seen = [], set()
    for v in variants:
        k = v.lower()
        if k not in seen:
            seen.add(k); out.append(v)
    return out


def _reference_row(static_bundle: Dict[str, Any], source_key: str = "error_risk_report") -> Dict[str, Any]:
    refs = _table(static_bundle, "reference_sources")
    if refs.empty:
        return {"SourceKey": source_key, "PathConfigKey": "bp_impact_tool_workbook", "SheetName": "Error Risk Report", "Required": "Y"}
    m = refs.loc[refs.get("SourceKey", pd.Series(dtype="object")).astype(str).str.strip().str.lower().eq(source_key.lower())]
    if m.empty:
        return {"SourceKey": source_key, "PathConfigKey": "bp_impact_tool_workbook", "SheetName": "Error Risk Report", "Required": "Y"}
    return m.iloc[0].to_dict()


# v346: route Error Risk (BP Impact Tool.xlsb, G:/ network) through the shared cached
# Excel reader so the network workbook is parsed at most once per file version, then
# served from the in-process + Parquet cache. Guarded import keeps this module usable
# even if the shared helper is unavailable (falls back to the original engine path).
try:
    from bnp_helpers_columns import read_excel_cached as _read_excel_cached_v346
except Exception:
    _read_excel_cached_v346 = None


def _read_excel_flexible(path: str, sheet_name: str) -> Tuple[pd.DataFrame, str]:
    if callable(_read_excel_cached_v346):
        try:
            df = _read_excel_cached_v346(path, sheet_name=sheet_name, header=0)
            return df, "cached"
        except Exception:
            pass  # fall through to the original direct-parse path
    suffix = Path(path).suffix.lower()
    engines = ["pyxlsb"] if suffix == ".xlsb" else ["openpyxl", None]
    last_error = None
    for engine in engines:
        try:
            if engine:
                return pd.read_excel(path, sheet_name=sheet_name, engine=engine), engine
            return pd.read_excel(path, sheet_name=sheet_name), "default"
        except Exception as exc:
            last_error = exc
    raise last_error or RuntimeError("Unable to read workbook")


def _clean_headers(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.dropna(how="all").copy()
    out.columns = [str(c).strip() for c in out.columns]
    for c in out.columns:
        if out[c].dtype == object:
            out[c] = out[c].map(lambda x: "" if pd.isna(x) else str(x).strip())
    return out.reset_index(drop=True)


def _find_col(df: pd.DataFrame, candidates: List[str]) -> Optional[str]:
    norm = {str(c).strip().lower().replace(" ", "").replace("_", ""): c for c in df.columns}
    for cand in candidates:
        key = str(cand).strip().lower().replace(" ", "").replace("_", "")
        if key in norm:
            return norm[key]
    for c in df.columns:
        low = str(c).lower()
        if all(part.lower() in low for part in candidates[0].split()):
            return c
    return None


def _normalise_error_risk_columns(df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame]:
    diag = []
    out = df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()
    if out.empty:
        return out, pd.DataFrame([{"Check": "error_df", "Result": "Empty"}])
    ratio_col = _find_col(out, ["Error Risk Ratio", "ErrorRiskRatio", "ERR", "Risk Ratio"])
    if ratio_col:
        raw = pd.to_numeric(out[ratio_col], errors="coerce")
        non_null = raw.dropna()
        divisor = 1.0
        # If this is a large workbook style value (e.g. 300 for 3%), normalise to 0.03.
        if not non_null.empty and float(non_null.abs().median()) > 10:
            divisor = 10000.0
        norm = raw / divisor
        if "ARC Error Risk Ratio" not in out.columns:
            out["ARC Error Risk Ratio"] = norm
        if "ARC Error Risk Ratio Raw" not in out.columns:
            out["ARC Error Risk Ratio Raw"] = raw
        if "ARC Error Risk Ratio Pct" not in out.columns:
            out["ARC Error Risk Ratio Pct"] = norm
        diag.append({"Check": "Error Risk Ratio column", "Result": "Found", "Detail": ratio_col, "DivisorApplied": divisor})
    else:
        diag.append({"Check": "Error Risk Ratio column", "Result": "Missing", "Detail": "No ratio-style column resolved", "DivisorApplied": ""})
    return out, pd.DataFrame(diag)


def prepare_error_risk_source(static_bundle: Dict[str, Any], run_date: object = None, timing_callback=None) -> Dict[str, Any]:
    started = time.perf_counter()
    rows = []
    exc = []
    ref = _reference_row(static_bundle)
    path_key = str(ref.get("PathConfigKey", "bp_impact_tool_workbook") or "bp_impact_tool_workbook")
    sheet = str(ref.get("SheetName", "Error Risk Report") or "Error Risk Report")
    configured_path = _config(static_bundle, path_key, "")
    resolved_path = ""
    for p in _root_variants(configured_path):
        if os.path.exists(p):
            resolved_path = p; break
    if not resolved_path:
        exc.append({"Severity": "Error", "Check": "BPImpactToolPath", "Detail": f"File not found: {configured_path}"})
        return {"status": "Error", "source_file": configured_path, "source_sheet": sheet, "error_df": pd.DataFrame(), "error_risk_meta_df": pd.DataFrame(rows), "error_risk_diagnostic_df": pd.DataFrame(), "error_risk_exception_df": pd.DataFrame(exc), "error_risk_timing_df": pd.DataFrame([{"Phase": "prepare_error_risk_source", "ElapsedSeconds": round(time.perf_counter()-started,4), "Status": "Error"}])}
    try:
        df, engine = _read_excel_flexible(resolved_path, sheet)
        df = _clean_headers(df)
        df, diag = _normalise_error_risk_columns(df)
        rows.append({"SourceKey": ref.get("SourceKey", "error_risk_report"), "Path": resolved_path, "SheetName": sheet, "Engine": engine, "Loaded": True, "Rows": int(len(df)), "Columns": int(len(df.columns)), "Error": ""})
        status = "OK" if not df.empty else "Empty"
    except Exception as e:
        df = pd.DataFrame(); diag = pd.DataFrame()
        status = "Error"
        msg = f"{type(e).__name__}: {e}"
        rows.append({"SourceKey": ref.get("SourceKey", "error_risk_report"), "Path": resolved_path, "SheetName": sheet, "Engine": "", "Loaded": False, "Rows": 0, "Columns": 0, "Error": msg})
        exc.append({"Severity": "Error", "Check": "LoadErrorRiskReport", "Detail": msg})
    timing = pd.DataFrame([{"Phase": "prepare_error_risk_source", "ElapsedSeconds": round(time.perf_counter()-started,4), "Status": status}])
    if callable(timing_callback):
        try: timing_callback("prepare_error_risk_source", float(timing.iloc[0]["ElapsedSeconds"]), status)
        except Exception: pass
    return {"status": status, "source_file": resolved_path or configured_path, "source_sheet": sheet, "error_df": df, "error_risk_meta_df": pd.DataFrame(rows), "error_risk_diagnostic_df": diag, "error_risk_exception_df": pd.DataFrame(exc), "error_risk_timing_df": timing}


# ===================================================================
# v307 - Hot/Cold ENRICHMENT / classifier (merged from
# bnp_helpers_error_risk_enrichment). The loader above reads the BP Impact
# Error Risk source; the code below matches OUT portfolios to it and classifies
# Hot / Cold, with the invariant No BP Impact row + Cold + Hot == OUT.
# ===================================================================

ERROR_RISK_ENRICHMENT_VERSION = "v307"
COL_MATCH_KEY = "BP Impact match key"
COL_MATCHED = "BP Impact matched?"
COL_MATCH_BASIS = "BP Impact match basis"
COL_RATIO = "BP Impact Error Risk Ratio"
COL_RATIO_RAW = "BP Impact Error Risk Ratio (raw)"
COL_HOTCOLD = "Hot / Cold"
COL_UNMATCHED_REASON = "BP Impact unmatched reason"
COL_ERROR_SOURCE = "Error Risk Source"
CLASS_HOT = "Hot"; CLASS_COLD = "Cold"; CLASS_NO_BP = "No BP Impact row"; CLASS_NONE = ""

@dataclass
class ErrorRiskEnrichmentResult:
    portfolio_df: pd.DataFrame
    diagnostics: Dict[str, Any] = field(default_factory=dict)
    invariant_ok: bool = True
    invariant_detail: str = ""
    unmatched_sample: pd.DataFrame = field(default_factory=pd.DataFrame)

def _norm_key(series: pd.Series) -> pd.Series:
    s = series.astype("string").fillna("").str.upper().str.strip()
    return s.str.replace(r"[^A-Z0-9]", "", regex=True)
def _first_token(series: pd.Series) -> pd.Series:
    return series.astype("string").fillna("").str.strip().str.split().str[0].fillna("")
def _to_num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")

def enrich_portfolio_error_risk(portfolio_df, error_df, *, out_flag_col, deviation_pp_col,
        external_ref_col=None, portfolio_name_col=None, advisor_col_in_error="Advisor",
        ratio_col_in_error="Error Risk Ratio",
        error_source_label="BP Impact Tool Error Risk Report", assert_invariant=True):
    df = portfolio_df.copy(); diagnostics: Dict[str, Any] = {"version": ERROR_RISK_ENRICHMENT_VERSION}
    if out_flag_col not in df.columns:
        raise KeyError(f"out_flag_col {out_flag_col!r} not in portfolio_df")
    out_mask = df[out_flag_col].fillna(False).astype(bool)
    out_count = int(out_mask.sum()); diagnostics["out_count"] = out_count
    have_source = isinstance(error_df, pd.DataFrame) and not error_df.empty
    ratio_lookup: Dict[str, float] = {}
    if have_source:
        e = error_df.copy()
        if advisor_col_in_error not in e.columns or ratio_col_in_error not in e.columns:
            cl = {str(c).strip().lower(): c for c in e.columns}
            adv = cl.get("advisor", advisor_col_in_error); rat = cl.get("error risk ratio", ratio_col_in_error)
        else:
            adv, rat = advisor_col_in_error, ratio_col_in_error
        e["_adv_key"] = _norm_key(e[adv]); e["_ratio"] = _to_num(e[rat])
        e = e.dropna(subset=["_ratio"]); ratio_lookup = e.groupby("_adv_key")["_ratio"].last().to_dict()
    diagnostics["error_source_rows"] = len(ratio_lookup); diagnostics["error_source_present"] = bool(have_source)
    df[COL_ERROR_SOURCE] = error_source_label
    ext_key = _norm_key(df[external_ref_col]) if external_ref_col and external_ref_col in df.columns else pd.Series("", index=df.index, dtype="object")
    name_token_key = _norm_key(_first_token(df[portfolio_name_col])) if portfolio_name_col and portfolio_name_col in df.columns else pd.Series("", index=df.index, dtype="object")
    match_key = pd.Series("", index=df.index, dtype="object"); match_basis = pd.Series("", index=df.index, dtype="object")
    matched = pd.Series(False, index=df.index); ratio = pd.Series(pd.NA, index=df.index, dtype="Float64")
    def _apply_basis(candidate, basis_label):
        eligible = out_mask & (~matched) & candidate.ne("")
        hit = eligible & candidate.map(lambda k: k in ratio_lookup)
        match_key.loc[hit] = candidate.loc[hit]; match_basis.loc[hit] = basis_label
        matched.loc[hit] = True; ratio.loc[hit] = candidate.loc[hit].map(ratio_lookup).astype("Float64")
    if have_source:
        _apply_basis(ext_key, "External portfolio reference -> Advisor")
        _apply_basis(name_token_key, "Portfolio Name first token (fallback)")
    df[COL_MATCH_KEY] = match_key; df[COL_MATCH_BASIS] = match_basis; df[COL_MATCHED] = matched
    df[COL_RATIO_RAW] = ratio; df[COL_RATIO] = ratio
    dev_pp = _to_num(df[deviation_pp_col]).abs()
    hotcold = pd.Series(CLASS_NONE, index=df.index, dtype="object")
    unmatched_reason = pd.Series("", index=df.index, dtype="object")
    out_unmatched = out_mask & (~matched); out_matched = out_mask & matched
    hotcold.loc[out_unmatched] = CLASS_NO_BP
    unmatched_reason.loc[out_unmatched] = "Advisor key not found in BP Impact Error Risk source"
    ratio_num = _to_num(df[COL_RATIO])
    hotcold.loc[out_matched & (dev_pp > ratio_num)] = CLASS_HOT
    hotcold.loc[out_matched & (dev_pp <= ratio_num)] = CLASS_COLD
    df[COL_HOTCOLD] = hotcold; df[COL_UNMATCHED_REASON] = unmatched_reason
    n_nobp = int((hotcold == CLASS_NO_BP).sum()); n_cold = int((hotcold == CLASS_COLD).sum()); n_hot = int((hotcold == CLASS_HOT).sum())
    total = n_nobp + n_cold + n_hot; invariant_ok = (total == out_count)
    invariant_detail = f"No BP Impact row ({n_nobp}) + Cold ({n_cold}) + Hot ({n_hot}) = {total}; OUT = {out_count}; {'OK' if invariant_ok else 'MISMATCH'}"
    diagnostics.update(no_bp_impact_row=n_nobp, cold=n_cold, hot=n_hot, matched=int(matched.sum()),
        matched_by_external_ref=int((match_basis == "External portfolio reference -> Advisor").sum()),
        matched_by_name_token=int((match_basis == "Portfolio Name first token (fallback)").sum()),
        invariant_ok=invariant_ok, invariant_detail=invariant_detail)
    if assert_invariant and not invariant_ok:
        raise AssertionError("Error-risk classification invariant failed: " + invariant_detail)
    cols = [c for c in [external_ref_col, portfolio_name_col, COL_MATCH_KEY, deviation_pp_col, out_flag_col] if c and c in df.columns]
    return ErrorRiskEnrichmentResult(portfolio_df=df, diagnostics=diagnostics, invariant_ok=invariant_ok,
        invariant_detail=invariant_detail, unmatched_sample=df.loc[out_unmatched, cols].head(50).copy())

def compute_hotcold_invariant(portfolio_df, *, out_flag_col=None, hotcold_col="Hot / Cold",
        no_source_labels=("No BP Impact row", "No Error Risk row", "No ARC match")):
    """Read-only invariant check on an ALREADY-classified frame. Never raises."""
    if not isinstance(portfolio_df, pd.DataFrame) or portfolio_df.empty or hotcold_col not in portfolio_df.columns:
        return {"invariant_ok": True, "detail": "No classified portfolio rows to check.",
                "out_count": 0, "no_source": 0, "cold": 0, "hot": 0}
    hc = portfolio_df[hotcold_col].astype(str).str.strip()
    no_src = {str(x).strip() for x in no_source_labels}
    if out_flag_col and out_flag_col in portfolio_df.columns:
        out_mask = portfolio_df[out_flag_col].fillna(False).astype(bool)
    elif "Within Tolerance" in portfolio_df.columns:
        out_mask = ~portfolio_df["Within Tolerance"].fillna(False).astype(bool)
    else:
        out_mask = hc.isin(no_src | {CLASS_COLD, CLASS_HOT})
    n_out = int(out_mask.sum()); n_ns = int((out_mask & hc.isin(no_src)).sum())
    n_c = int((out_mask & hc.eq(CLASS_COLD)).sum()); n_h = int((out_mask & hc.eq(CLASS_HOT)).sum())
    total = n_ns + n_c + n_h; ok = (total == n_out)
    return {"invariant_ok": ok, "detail": f"No source ({n_ns}) + Cold ({n_c}) + Hot ({n_h}) = {total}; OUT = {n_out}; {'OK' if ok else 'MISMATCH'}",
            "out_count": n_out, "no_source": n_ns, "cold": n_c, "hot": n_h}


__all__ = [
    "prepare_error_risk_source",
    "enrich_portfolio_error_risk",
    "compute_hotcold_invariant",
    "ErrorRiskEnrichmentResult",
    "COL_MATCH_KEY", "COL_MATCHED", "COL_MATCH_BASIS", "COL_RATIO",
    "COL_RATIO_RAW", "COL_HOTCOLD", "COL_UNMATCHED_REASON", "COL_ERROR_SOURCE",
    "CLASS_HOT", "CLASS_COLD", "CLASS_NO_BP", "CLASS_NONE",
    "ERROR_RISK_ENRICHMENT_VERSION",
]


if __name__ == "__main__":
    import pandas as _pd
    print("[merged error_risk] loader + classifier self-test")
    # classifier smoke test (loader needs a live workbook, skipped here)
    portfolio = _pd.DataFrame({
        "Portfolio code": ["M1CU35","M1NAFI","M1XX"],
        "External portfolio reference": ["ACU35PUA","NSIFXPUA","NOPE"],
        "Portfolio Name": ["a","b","c"],
        "Deviation pp": [0.90,0.20,0.50],
        "OUT flag": [True,True,True]})
    error = _pd.DataFrame({"Advisor":["ACU35PUA","NSIFXPUA"],"Error Risk Ratio":[0.50,0.77]})
    res = enrich_portfolio_error_risk(portfolio, error, out_flag_col="OUT flag",
        deviation_pp_col="Deviation pp", external_ref_col="External portfolio reference",
        portfolio_name_col="Portfolio Name")
    print("  invariant:", res.invariant_detail)
    inv = compute_hotcold_invariant(res.portfolio_df, out_flag_col="OUT flag")
    assert res.invariant_ok and inv["invariant_ok"], "invariant failed"
    print("  prepare_error_risk_source present:", callable(prepare_error_risk_source))
    print("  OK - merged module: loader + classifier both present, invariant holds")
