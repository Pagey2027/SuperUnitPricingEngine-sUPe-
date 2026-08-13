# -*- coding: utf-8 -*-
"""Processing-core helpers extracted from the BNP Control App.

This module intentionally contains no Streamlit bootstrap code. The main app
configures the module with runtime dependencies (folder/date helpers, file
loading function, and cache/version constants) and then calls process_day().
"""

from __future__ import annotations

from typing import Dict, List, Optional

import time

import pandas as pd

from bnp_helpers_columns import (
    find_col,
    normalise_join_key_series,
    resolve_benchmark_code_col,
    resolve_driver_label_col,
    resolve_fdv_current_value_col,
)

from bnp_helpers_columns import num

CACHE_VERSION = ""
REQUIRED_FILE_KEYWORDS: List[str] = []
parse_date_from_path = None
folder_fingerprint = None
load_day_files = None
_string_series = None
_safe_series = None
apply_fdv_exclusion = None
HELPER_VERSION = "v304.3.2"

_RUNTIME_DEPENDENCIES = {
    "parse_date_from_path": "parse_date_from_path",
    "folder_fingerprint": "folder_fingerprint",
    "load_day_files": "load_day_files",
    "_string_series": "_string_series",
    "_safe_series": "_safe_series",
    "apply_fdv_exclusion": "apply_fdv_exclusion",
}


def _validate_processing_configuration() -> None:
    missing = [name for name in _RUNTIME_DEPENDENCIES if globals().get(name) is None]
    if missing:
        raise RuntimeError(
            "Processing helpers are not fully configured. Missing runtime dependencies: "
            + ", ".join(sorted(missing))
        )


def configure_processing(
    *,
    cache_version: str,
    required_file_keywords: List[str],
    parse_date_from_path_fn,
    folder_fingerprint_fn,
    load_day_files_fn,
    string_series_fn,
    safe_series_fn,
    apply_fdv_exclusion_fn,
):
    global CACHE_VERSION, REQUIRED_FILE_KEYWORDS
    global parse_date_from_path, folder_fingerprint, load_day_files
    global _string_series, _safe_series, apply_fdv_exclusion
    CACHE_VERSION = cache_version
    REQUIRED_FILE_KEYWORDS = list(required_file_keywords or [])
    parse_date_from_path = parse_date_from_path_fn
    folder_fingerprint = folder_fingerprint_fn
    load_day_files = load_day_files_fn
    _string_series = string_series_fn
    _safe_series = safe_series_fn
    apply_fdv_exclusion = apply_fdv_exclusion_fn

def _init_process_day_context(
    folder: str,
    progress_label: str,
    exclude_below_current_value: float,
    folder_fingerprint_override: Optional[str] = None,
) -> Dict[str, object]:
    fingerprint_value = str(folder_fingerprint_override or "").strip()
    if not fingerprint_value:
        fingerprint_value = folder_fingerprint(folder)
    return {
        "folder": folder,
        "progress_label": progress_label,
        "exclude_below_current_value": float(exclude_below_current_value or 0.0),
        "run_date": parse_date_from_path(folder),
        "fingerprint": fingerprint_value,
        "fingerprint_source": "override" if str(folder_fingerprint_override or "").strip() else "computed",
        "diagnostics": [],
        "exceptions": [],
    }
def _make_process_day_progress_updater(progress_bar=None, status_text=None, summary_text=None):
    def update_day_progress(percent: int, status: Optional[str] = None, summary: Optional[str] = None, message_type: str = "info"):
        bounded = max(0, min(100, int(percent)))
        if progress_bar is not None:
            progress_bar.progress(bounded)
        if status_text is not None and status is not None:
            if message_type == "success":
                status_text.success(status)
            elif message_type == "warning":
                status_text.warning(status)
            elif message_type == "error":
                status_text.error(status)
            else:
                status_text.info(status)
        if summary_text is not None and summary is not None:
            summary_text.caption(summary)

    return update_day_progress
def _make_process_day_recorders(ctx: Dict[str, object]):
    def add_diag(metric, value, status="INFO", detail=""):
        ctx["diagnostics"].append({
            "RunDate": ctx["run_date"],
            "SourceFolder": ctx["folder"],
            "FolderFingerprint": ctx["fingerprint"],
            "Metric": "" if pd.isna(metric) else str(metric),
            "Value": "" if pd.isna(value) else str(value),
            "Status": "" if pd.isna(status) else str(status),
            "Detail": "" if pd.isna(detail) else str(detail),
            "CacheVersion": CACHE_VERSION,
        })

    def add_exc(category, message, severity="Warning"):
        ctx["exceptions"].append({
            "RunDate": ctx["run_date"],
            "SourceFolder": ctx["folder"],
            "FolderFingerprint": ctx["fingerprint"],
            "Category": category,
            "Severity": severity,
            "Message": message,
            "CacheVersion": CACHE_VERSION,
        })

    return add_diag, add_exc
def _resolve_process_day_sources(
    folder: str,
    loaded_files: Optional[Dict[str, object]],
    progress_callback=None,
    progress_label: str = "Daily processing",
) -> Dict[str, object]:
    loaded = loaded_files or load_day_files(folder, progress_callback=progress_callback, progress_label=progress_label)
    file_meta_df = loaded.get("file_meta_df", pd.DataFrame())
    if file_meta_df is None:
        file_meta_df = pd.DataFrame()
    return {
        "loaded": loaded,
        "dd": loaded.get("dd"),
        "dat": loaded.get("dat"),
        "dar": loaded.get("dar"),
        "bmk": loaded.get("bmk"),
        "file_meta_df": file_meta_df,
    }
def _build_process_day_summary(
    run_date: object,
    folder: str,
    fingerprint: str,
    exceptions: List[Dict[str, object]],
    add_diag,
    total_portfolios: int,
    out_portfolios: int,
    pct_out: float,
    ddetailed_out_portfolios: int,
    control_break_out_portfolios: int,
    control_break_within_portfolios: int,
    ddetailed_out_reclassified_within: int,
    ddetailed_within_reclassified_out: int,
    benchmark_recon_total: float,
    benchmark_recon_pass: bool,
    driver_recon_total: float,
    driver_recon_pass: bool,
    recon_diff_benchmark: float,
    recon_diff_driver: float,
    exclude_threshold: float,
    excluded_portfolios_below_threshold: int,
    base_processing_success: bool,
) -> pd.DataFrame:
    error_count = sum(str(x.get("Severity", "")).strip().lower() == "error" for x in exceptions)
    warning_count = sum(str(x.get("Severity", "")).strip().lower() == "warning" for x in exceptions)
    if not base_processing_success or error_count > 0:
        run_validation_state = "FAIL"
        diag_status = "FAIL"
    elif warning_count > 0:
        run_validation_state = "DEGRADED"
        diag_status = "WARN"
    else:
        run_validation_state = "PASS"
        diag_status = "PASS"
    add_diag(
        "RunValidationState",
        run_validation_state,
        diag_status,
        f"Errors={int(error_count)}; Warnings={int(warning_count)}; BaseProcessingSuccess={bool(base_processing_success)}",
    )
    return pd.DataFrame([{
        "RunDate": run_date,
        "SourceFolder": folder,
        "FolderFingerprint": fingerprint,
        "TotalPortfolios": int(total_portfolios),
        "OutPortfolios": int(out_portfolios),
        "PctOut": float(pct_out),
        "DDetailedReturnOutPortfolios": int(ddetailed_out_portfolios),
        "ControlBreakOutPortfolios": int(control_break_out_portfolios),
        "ControlBreakWithinPortfolios": int(control_break_within_portfolios),
        "DDetailedOutReclassifiedWithin": int(ddetailed_out_reclassified_within),
        "DDetailedWithinReclassifiedOut": int(ddetailed_within_reclassified_out),
        "BenchmarkReconTotal": float(benchmark_recon_total),
        "BenchmarkReconPass": bool(benchmark_recon_pass),
        "DriverReconTotal": float(driver_recon_total),
        "DriverReconPass": bool(driver_recon_pass),
        "ReconDifferenceBenchmark": float(recon_diff_benchmark),
        "ReconDifferenceDriver": float(recon_diff_driver),
        "ExcludeThreshold": float(exclude_threshold),
        "ExcludedPortfoliosBelowThreshold": int(excluded_portfolios_below_threshold),
        "BaseProcessingSuccess": bool(base_processing_success),
        "RunValidationState": run_validation_state,
        "ErrorCount": int(error_count),
        "WarningCount": int(warning_count),
        "CacheVersion": CACHE_VERSION,
    }])
def _validate_process_day_inputs(
    run_date: object,
    folder: str,
    fingerprint: str,
    progress_label: str,
    exclude_below_current_value: float,
    update_day_progress,
    add_diag,
    add_exc,
    exceptions: List[Dict[str, object]],
    dd: Optional[pd.DataFrame],
    file_meta_df: pd.DataFrame,
    diagnostics: List[Dict[str, object]],
) -> Dict[str, object]:
    update_day_progress(55, status=f"{progress_label}: validating file readiness", summary="Checking required and optional source files")
    if not file_meta_df.empty:
        for _, r in file_meta_df.iterrows():
            metric = f"File.{r['Keyword']}"
            if bool(r.get("Loaded", False)):
                add_diag(metric, "Loaded", "PASS", f"Rows={r.get('Rows', 0)}; Cols={r.get('Columns', 0)}; LoadedFiles={r.get('LoadedFiles', 0)}; ExcludedCount={r.get('ExcludedCount', 0)}; HeaderStrategy={r.get('HeaderStrategy', '')}; HeaderValidation={r.get('HeaderValidation', '')}")
            else:
                if r['Keyword'] in REQUIRED_FILE_KEYWORDS:
                    add_diag(metric, "Missing", "FAIL", str(r.get("Error", "")))
                    add_exc("MissingRequiredFile", f"{r['Keyword']}: {r.get('Error', '')}", "Error")
                else:
                    add_diag(metric, "MissingOptional", "WARN", str(r.get("Error", "")))
                    add_exc("MissingOptionalFile", f"{r['Keyword']}: {r.get('Error', '')}", "Warning")

    if dd is None or dd.empty:
        update_day_progress(100, status=f"{progress_label}: failed - required DDetailedReturn unavailable", summary="Base processing stopped because the required DDetailedReturn file could not be loaded or failed header validation", message_type="error")
        return {
            "early_result": {
                "summary_df": _build_process_day_summary(
                    run_date=run_date,
                    folder=folder,
                    fingerprint=fingerprint,
                    exceptions=exceptions,
                    add_diag=add_diag,
                    total_portfolios=0,
                    out_portfolios=0,
                    pct_out=0.0,
                    benchmark_recon_total=0.0,
                    benchmark_recon_pass=False,
                    driver_recon_total=0.0,
                    driver_recon_pass=False,
                    recon_diff_benchmark=0.0,
                    recon_diff_driver=0.0,
                    exclude_threshold=float(exclude_below_current_value or 0.0),
                    excluded_portfolios_below_threshold=0,
                    base_processing_success=False,
                ),
                "portfolio_df": pd.DataFrame(),
                "driver_df": pd.DataFrame(),
                "benchmark_df": pd.DataFrame(),
                "diagnostic_df": pd.DataFrame(diagnostics),
                "exception_df": pd.DataFrame(exceptions),
                "file_meta_df": file_meta_df.assign(RunDate=run_date, SourceFolder=folder, FolderFingerprint=fingerprint, CacheVersion=CACHE_VERSION) if not file_meta_df.empty else pd.DataFrame(),
            }
        }

    update_day_progress(65, status=f"{progress_label}: identifying core columns", summary="Resolving status, portfolio, return and tolerance fields")
    status_col = find_col(dd, ["status"])
    portfolio_col = find_col(dd, ["portfoliocode", "portfolio code"]) or find_col(dd, ["portfolio"])
    actual_col = find_col(dd, ["actual", "portfolio return", "portfolio performance"])
    benchmark_ret_col = find_col(dd, ["benchmark return", "benchmark return %", "benchmarkreturn"])
    # v235: for control-break retesting, prefer the transaction-aware Over/Under field.
    # Actual vs Benchmark is still derived separately from Actual Return minus Benchmark Return.
    # Using Actual vs Benchmark here double-counted transaction impacts for portfolios such as M1CU01.
    control_break_col = find_col(dd, ["Over/Under", "over under", "overunder", "Original Over/Under", "Source Original Over/Under"])
    deviation_col = control_break_col or find_col(dd, ["actual vs benchmark", "difference", "deviation", "active"])
    tolerance_col = find_col(dd, ["tolerance", "tol", "limit"])
    current_fdv_valuation_col = resolve_fdv_current_value_col(dd)

    add_diag("Column.Status", status_col or "", "PASS" if status_col else "WARN")
    add_diag("Column.Portfolio", portfolio_col or "", "PASS" if portfolio_col else "FAIL")
    add_diag("Column.PortfolioSelected", portfolio_col or "", "PASS" if portfolio_col else "FAIL")
    add_diag("Column.Actual", actual_col or "", "PASS" if actual_col else "WARN")
    add_diag("Column.BenchmarkReturn", benchmark_ret_col or "", "PASS" if benchmark_ret_col else "WARN")
    add_diag("Column.Deviation", deviation_col or "", "PASS" if deviation_col else "WARN")
    add_diag("Column.ControlBreakSource", control_break_col or deviation_col or "", "PASS" if (control_break_col or deviation_col) else "WARN")
    add_diag("Column.Tolerance", tolerance_col or "", "PASS" if tolerance_col else "WARN")
    add_diag("Column.FDVCurrentValuation", current_fdv_valuation_col or "", "PASS" if current_fdv_valuation_col else "WARN")

    if portfolio_col is None:
        add_exc("MissingRequiredColumn", "Portfolio column not found in DDetailedReturn", "Error")
        update_day_progress(100, status=f"{progress_label}: failed - required portfolio column missing", summary="Base processing stopped because DDetailedReturn could not be mapped to a required portfolio column", message_type="error")
        return {
            "early_result": {
                "summary_df": _build_process_day_summary(
                    run_date=run_date,
                    folder=folder,
                    fingerprint=fingerprint,
                    exceptions=exceptions,
                    add_diag=add_diag,
                    total_portfolios=0,
                    out_portfolios=0,
                    pct_out=0.0,
                    benchmark_recon_total=0.0,
                    benchmark_recon_pass=False,
                    driver_recon_total=0.0,
                    driver_recon_pass=False,
                    recon_diff_benchmark=0.0,
                    recon_diff_driver=0.0,
                    exclude_threshold=float(exclude_below_current_value or 0.0),
                    excluded_portfolios_below_threshold=0,
                    base_processing_success=False,
                ),
                "portfolio_df": pd.DataFrame(),
                "driver_df": pd.DataFrame(),
                "benchmark_df": pd.DataFrame(),
                "diagnostic_df": pd.DataFrame(diagnostics),
                "exception_df": pd.DataFrame(exceptions),
                "file_meta_df": file_meta_df.assign(RunDate=run_date, SourceFolder=folder, FolderFingerprint=fingerprint, CacheVersion=CACHE_VERSION) if not file_meta_df.empty else pd.DataFrame(),
            }
        }

    return {
        "early_result": None,
        "status_col": status_col,
        "portfolio_col": portfolio_col,
        "actual_col": actual_col,
        "benchmark_ret_col": benchmark_ret_col,
        "deviation_col": deviation_col,
        "tolerance_col": tolerance_col,
        "current_fdv_valuation_col": current_fdv_valuation_col,
    }

CONTROL_BREAK_SOURCE_MATCH_TOLERANCE_PP = 0.01  # percentage points for source-vs-DAssetReturn integrity comparison


def _resolve_dassetreturn_excess_by_portfolio(dar: Optional[pd.DataFrame]) -> pd.DataFrame:
    """Return one row per portfolio with summed DAssetReturn Excess Contribution."""
    empty = pd.DataFrame(columns=["Portfolio", "DAssetReturn Excess Contribution Total", "DAssetReturn Excess Contribution Rows"])
    if dar is None or not isinstance(dar, pd.DataFrame) or dar.empty:
        return empty
    port_col = find_col(dar, ["Portfolio", "Portfolio code", "PortfolioCode", "portfolio", "portfolio code"])
    excess_col = find_col(dar, ["Excess Contribution", "ExcessContribution", "Excess contribution"])
    if port_col is None or excess_col is None:
        return empty
    tmp = dar[[port_col, excess_col]].copy()
    tmp["Portfolio"] = _string_series(tmp, port_col).str.strip()
    tmp = tmp[tmp["Portfolio"] != ""].copy()
    if tmp.empty:
        return empty
    tmp["_excess_contribution_num"] = num(tmp, excess_col)
    return (
        tmp.groupby("Portfolio", dropna=False)
        .agg(**{
            "DAssetReturn Excess Contribution Total": ("_excess_contribution_num", "sum"),
            "DAssetReturn Excess Contribution Rows": ("_excess_contribution_num", "count"),
        })
        .reset_index()
    )


def _resolve_dassetreturn_contribution_by_portfolio(dar: Optional[pd.DataFrame]) -> pd.DataFrame:
    """v357: return one row per portfolio with summed DAssetReturn 'Asset to Portfolio
    Contributions'. This is the B side of the Actual-Return control-break integrity
    check (the portfolio's Actual Return should reconcile to the sum of its asset-level
    contributions to that return)."""
    empty = pd.DataFrame(columns=["Portfolio", "DAssetReturn Asset to Portfolio Contribution Total", "DAssetReturn Asset to Portfolio Contribution Rows"])
    if dar is None or not isinstance(dar, pd.DataFrame) or dar.empty:
        return empty
    port_col = find_col(dar, ["Portfolio", "Portfolio code", "PortfolioCode", "portfolio", "portfolio code"])
    contrib_col = find_col(dar, ["Asset to Portfolio Contributions", "Asset to Portfolio Contribution", "AssetToPortfolioContributions", "AssetToPortfolioContribution", "Asset to portfolio contributions", "Asset to portfolio contribution"])
    if port_col is None or contrib_col is None:
        return empty
    tmp = dar[[port_col, contrib_col]].copy()
    tmp["Portfolio"] = _string_series(tmp, port_col).str.strip()
    tmp = tmp[tmp["Portfolio"] != ""].copy()
    if tmp.empty:
        return empty
    tmp["_contribution_num"] = num(tmp, contrib_col)
    return (
        tmp.groupby("Portfolio", dropna=False)
        .agg(**{
            "DAssetReturn Asset to Portfolio Contribution Total": ("_contribution_num", "sum"),
            "DAssetReturn Asset to Portfolio Contribution Rows": ("_contribution_num", "count"),
        })
        .reset_index()
    )


def _derive_transaction_aware_control_break_columns(
    all_df: pd.DataFrame,
    *,
    dar: Optional[pd.DataFrame],
    portfolio_col: str,
    status_col: Optional[str],
    actual_col: Optional[str],
    benchmark_ret_col: Optional[str],
    deviation_col: Optional[str],
    tolerance_col: Optional[str],
    add_diag,
    add_exc,
) -> pd.DataFrame:
    """Add audit bridge columns comparing DDetailedReturn status to transaction-aware control break."""
    out = all_df.copy()
    out["Portfolio"] = _string_series(out, portfolio_col).str.strip()
    out["DDetailedReturn Status"] = _string_series(out, status_col).str.strip() if status_col is not None else ""
    out["DDetailedReturn OUT Flag"] = out["DDetailedReturn Status"].astype(str).str.upper().str.strip().eq("OUT")

    out["Actual Return Num"] = num(out, actual_col) if actual_col is not None else pd.Series(float("nan"), index=out.index, dtype="float64")
    out["Benchmark Return Num"] = num(out, benchmark_ret_col) if benchmark_ret_col is not None else pd.Series(float("nan"), index=out.index, dtype="float64")
    out["Source Original Over/Under"] = num(out, deviation_col) if deviation_col is not None else pd.Series(float("nan"), index=out.index, dtype="float64")
    out["Reported DDetailedReturn over/under"] = out["Source Original Over/Under"]
    if actual_col is not None and benchmark_ret_col is not None:
        out["Calculated over/under"] = out["Actual Return Num"] - out["Benchmark Return Num"]
    else:
        out["Calculated over/under"] = pd.Series(float("nan"), index=out.index, dtype="float64")
    out["Gross Actual-Benchmark Break"] = out["Calculated over/under"].where(out["Calculated over/under"].notna(), out["Source Original Over/Under"])
    out["Reported vs Calculated over/under Difference"] = out["Reported DDetailedReturn over/under"] - out["Calculated over/under"]
    out["Abs Reported vs Calculated over/under Difference"] = out["Reported vs Calculated over/under Difference"].abs()
    out["Tolerance Num"] = num(out, tolerance_col) if tolerance_col is not None else pd.Series(float("nan"), index=out.index, dtype="float64")

    dar_excess = _resolve_dassetreturn_excess_by_portfolio(dar)
    if not dar_excess.empty:
        out = out.merge(dar_excess, on="Portfolio", how="left")
    else:
        out["DAssetReturn Excess Contribution Total"] = pd.Series(float("nan"), index=out.index, dtype="float64")
        out["DAssetReturn Excess Contribution Rows"] = 0
    out["DAssetReturn Excess Contribution Total"] = pd.to_numeric(out["DAssetReturn Excess Contribution Total"], errors="coerce")
    out["DAssetReturn Excess Contribution Rows"] = pd.to_numeric(out["DAssetReturn Excess Contribution Rows"], errors="coerce").fillna(0).astype(int)

    # v357: Actual-Return source-integrity reconciliation (replaces the excess basis for
    # the surfaced control-break warning). A = DDetailedReturn Actual Return (already
    # parsed as 'Actual Return Num'); B = summed DAssetReturn 'Asset to Portfolio
    # Contributions'. Both are in percentage points. |A - B| > 1bp = source mismatch.
    dar_contrib = _resolve_dassetreturn_contribution_by_portfolio(dar)
    if not dar_contrib.empty:
        out = out.merge(dar_contrib, on="Portfolio", how="left")
    else:
        out["DAssetReturn Asset to Portfolio Contribution Total"] = pd.Series(float("nan"), index=out.index, dtype="float64")
        out["DAssetReturn Asset to Portfolio Contribution Rows"] = 0
    out["DAssetReturn Asset to Portfolio Contribution Total"] = pd.to_numeric(out["DAssetReturn Asset to Portfolio Contribution Total"], errors="coerce")
    out["DAssetReturn Asset to Portfolio Contribution Rows"] = pd.to_numeric(out["DAssetReturn Asset to Portfolio Contribution Rows"], errors="coerce").fillna(0).astype(int)
    out["DDetailedReturn Actual Return"] = out["Actual Return Num"]
    out["Actual Return vs DAssetReturn Contribution Difference"] = out["Actual Return Num"] - out["DAssetReturn Asset to Portfolio Contribution Total"]
    out["Abs Actual Return vs DAssetReturn Contribution Difference"] = out["Actual Return vs DAssetReturn Contribution Difference"].abs()

    out["Source vs DAssetReturn Excess Difference"] = out["Source Original Over/Under"] - out["DAssetReturn Excess Contribution Total"]
    out["Abs Source vs DAssetReturn Excess Difference"] = out["Source vs DAssetReturn Excess Difference"].abs()
    out["Calculated over/under vs DAssetReturn Excess Difference"] = out["Calculated over/under"] - out["DAssetReturn Excess Contribution Total"]
    out["Abs Calculated over/under vs DAssetReturn Excess Difference"] = out["Calculated over/under vs DAssetReturn Excess Difference"].abs()
    # v237 diagnostic only: display-rounded comparison; raw match status remains based on the raw difference above.
    out["Source Over/Under Rounded 2dp"] = out["Source Original Over/Under"].round(2)
    out["DAssetReturn Excess Rounded 2dp"] = out["DAssetReturn Excess Contribution Total"].round(2)
    out["Rounded Display Difference 2dp"] = out["Source Over/Under Rounded 2dp"] - out["DAssetReturn Excess Rounded 2dp"]
    out["Abs Rounded Display Difference 2dp"] = out["Rounded Display Difference 2dp"].abs()
    # Retained excess-basis status for audit (v357: no longer the surfaced warning).
    both_excess = out["Source Original Over/Under"].notna() & out["DAssetReturn Excess Contribution Total"].notna()
    out["Source vs DAssetReturn Excess Match Status"] = "Not compared"
    out.loc[both_excess & (out["Abs Source vs DAssetReturn Excess Difference"] <= CONTROL_BREAK_SOURCE_MATCH_TOLERANCE_PP), "Source vs DAssetReturn Excess Match Status"] = "Matched"
    out.loc[both_excess & (out["Abs Source vs DAssetReturn Excess Difference"] > CONTROL_BREAK_SOURCE_MATCH_TOLERANCE_PP), "Source vs DAssetReturn Excess Match Status"] = "Mismatch"
    out.loc[out["Source Original Over/Under"].notna() & out["DAssetReturn Excess Contribution Total"].isna(), "Source vs DAssetReturn Excess Match Status"] = "No DAssetReturn excess total"
    out.loc[out["Source Original Over/Under"].isna() & out["DAssetReturn Excess Contribution Total"].notna(), "Source vs DAssetReturn Excess Match Status"] = "No source Over/Under"

    # v357: PRIMARY source-integrity status = DDetailedReturn Actual Return vs summed
    # DAssetReturn Asset-to-Portfolio Contributions, at 1bp. Drives the warning + count.
    both_available = out["Actual Return Num"].notna() & out["DAssetReturn Asset to Portfolio Contribution Total"].notna()
    out["Source vs DAssetReturn Match Status"] = "Not compared"
    out.loc[both_available & (out["Abs Actual Return vs DAssetReturn Contribution Difference"] <= CONTROL_BREAK_SOURCE_MATCH_TOLERANCE_PP), "Source vs DAssetReturn Match Status"] = "Matched"
    out.loc[both_available & (out["Abs Actual Return vs DAssetReturn Contribution Difference"] > CONTROL_BREAK_SOURCE_MATCH_TOLERANCE_PP), "Source vs DAssetReturn Match Status"] = "Mismatch"
    out.loc[out["Actual Return Num"].notna() & out["DAssetReturn Asset to Portfolio Contribution Total"].isna(), "Source vs DAssetReturn Match Status"] = "No DAssetReturn contribution total"
    out.loc[out["Actual Return Num"].isna() & out["DAssetReturn Asset to Portfolio Contribution Total"].notna(), "Source vs DAssetReturn Match Status"] = "No Actual Return"

    out["Transaction-aware Control Break"] = out["Calculated over/under"]
    out["Control Break Basis"] = "Calculated over/under"
    missing_calc = out["Transaction-aware Control Break"].isna()
    out.loc[missing_calc, "Transaction-aware Control Break"] = out.loc[missing_calc, "DAssetReturn Excess Contribution Total"]
    out.loc[missing_calc & out["DAssetReturn Excess Contribution Total"].notna(), "Control Break Basis"] = "Fallback: DAssetReturn Excess Contribution total"
    still_missing = out["Transaction-aware Control Break"].isna()
    out.loc[still_missing, "Transaction-aware Control Break"] = out.loc[still_missing, "Source Original Over/Under"]
    out.loc[still_missing & out["Source Original Over/Under"].notna(), "Control Break Basis"] = "Fallback: reported DDetailedReturn over/under"
    out.loc[out["Transaction-aware Control Break"].isna(), "Control Break Basis"] = "No control-break basis available"

    out["Transaction Adjustment Implied"] = out["Gross Actual-Benchmark Break"] - out["Transaction-aware Control Break"]
    out["Transaction-aware Outside Tolerance"] = (out["Transaction-aware Control Break"].abs() - out["Tolerance Num"].abs()).clip(lower=0)
    out.loc[out["Tolerance Num"].isna(), "Transaction-aware Outside Tolerance"] = pd.NA
    out["OUT - Control Break Flag"] = out["Transaction-aware Outside Tolerance"].fillna(0).gt(0)
    out["Control Break Status"] = out["OUT - Control Break Flag"].map({True: "OUT - Control Break", False: "Within - Control Break"})
    out.loc[out["Transaction-aware Control Break"].isna(), "Control Break Status"] = "Unknown - missing control break"
    out.loc[out["Tolerance Num"].isna(), "Control Break Status"] = "Unknown - missing tolerance"

    out["Control Break Reclassification"] = "No change"
    out.loc[out["DDetailedReturn OUT Flag"] & ~out["OUT - Control Break Flag"], "Control Break Reclassification"] = "DDetailed OUT -> Control Within"
    out.loc[~out["DDetailedReturn OUT Flag"] & out["OUT - Control Break Flag"], "Control Break Reclassification"] = "DDetailed Within -> Control OUT"
    out["Control Break Diagnostic Note"] = ""
    out.loc[out["Source vs DAssetReturn Match Status"].eq("Mismatch"), "Control Break Diagnostic Note"] = "DDetailedReturn Actual Return and summed DAssetReturn Asset-to-Portfolio Contributions differ beyond tolerance"
    out.loc[out["Control Break Basis"].str.startswith("Fallback", na=False), "Control Break Diagnostic Note"] = "Control break used fallback basis"
    out.loc[out["Control Break Basis"].eq("No control-break basis available"), "Control Break Diagnostic Note"] = "No usable control-break basis"
    out.loc[out["Tolerance Num"].isna(), "Control Break Diagnostic Note"] = "Tolerance missing"

    add_diag("ControlBreak.SourceDAssetReturnMatchTolerancePP", CONTROL_BREAK_SOURCE_MATCH_TOLERANCE_PP, "INFO")
    add_diag("ControlBreak.DDetailedOutCount", int(out["DDetailedReturn OUT Flag"].sum()), "PASS")
    add_diag("ControlBreak.OutCount", int(out["OUT - Control Break Flag"].sum()), "PASS")
    mismatch_count = int(out["Source vs DAssetReturn Match Status"].eq("Mismatch").sum())
    add_diag("ControlBreak.SourceDAssetReturnMismatchCount", mismatch_count, "WARN" if mismatch_count else "PASS")
    if mismatch_count:
        add_exc("ControlBreakSourceMismatch", f"{mismatch_count} portfolio(s) where DDetailedReturn Actual Return and summed DAssetReturn Asset-to-Portfolio Contributions differ beyond tolerance", "Warning")
    return out

def _build_process_day_portfolio_df(
    dd: pd.DataFrame,
    dar: Optional[pd.DataFrame],
    portfolio_col: str,
    status_col: Optional[str],
    actual_col: Optional[str],
    benchmark_ret_col: Optional[str],
    deviation_col: Optional[str],
    tolerance_col: Optional[str],
    current_fdv_valuation_col: Optional[str],
    run_date: object,
    folder: str,
    fingerprint: str,
    progress_label: str,
    exclude_below_current_value: float,
    update_day_progress,
    add_diag,
    add_exc,
) -> Dict[str, object]:
    all_df = dd.copy()
    all_df["Portfolio"] = _string_series(all_df, portfolio_col).str.strip()
    all_df = all_df[all_df["Portfolio"] != ""].copy()
    all_df = all_df.drop_duplicates(subset=["Portfolio"], keep="first")
    all_count = int(len(all_df))

    if status_col is None:
        add_exc("MissingStatus", "Status column not found - DDetailedReturn OUT flag cannot be audited", "Warning")
    if tolerance_col is None:
        add_exc("MissingTolerance", "Tolerance column not found - transaction-aware control-break status unavailable", "Warning")
    if deviation_col is None and actual_col is None and benchmark_ret_col is None:
        add_exc("MissingDeviation", "Source Over/Under and Actual/Benchmark columns could not be identified", "Warning")

    all_control_df = _derive_transaction_aware_control_break_columns(
        all_df,
        dar=dar,
        portfolio_col=portfolio_col,
        status_col=status_col,
        actual_col=actual_col,
        benchmark_ret_col=benchmark_ret_col,
        deviation_col=deviation_col,
        tolerance_col=tolerance_col,
        add_diag=add_diag,
        add_exc=add_exc,
    )

    ddetailed_out_count = int(all_control_df["DDetailedReturn OUT Flag"].sum())
    control_break_out_count_pre_exclusion = int(all_control_df["OUT - Control Break Flag"].sum())
    ddetailed_out_reclassified_within = int((all_control_df["DDetailedReturn OUT Flag"] & ~all_control_df["OUT - Control Break Flag"]).sum())
    ddetailed_within_reclassified_out = int((~all_control_df["DDetailedReturn OUT Flag"] & all_control_df["OUT - Control Break Flag"]).sum())

    threshold_value = float(exclude_below_current_value or 0.0)
    excluded_portfolio_count = 0
    excluded_non_numeric_count = 0
    control_out_df = all_control_df.loc[all_control_df["OUT - Control Break Flag"]].copy()
    if threshold_value > 0:
        control_out_df, excluded_portfolio_count, excluded_non_numeric_count = apply_fdv_exclusion(control_out_df, threshold_value, current_fdv_valuation_col)
        add_diag("FDVExclusion.Threshold", threshold_value, "INFO")
        add_diag("FDVExclusion.ExcludedCount", excluded_portfolio_count, "WARN" if excluded_portfolio_count else "PASS")
        if excluded_non_numeric_count:
            add_exc("FDVExclusionNonNumeric", f"{excluded_non_numeric_count} row(s) had non-numeric FDV values and were retained", "Warning")

    control_break_out_count = int(len(control_out_df))
    pct_out = (control_break_out_count / all_count) if all_count else 0.0
    add_diag("Base.TotalPortfolioCount", all_count, "PASS")
    add_diag("Base.DDetailedReturnOutCount", ddetailed_out_count, "PASS")
    add_diag("Base.ControlBreakOutCountBeforeExclusion", control_break_out_count_pre_exclusion, "PASS")
    add_diag("Base.ControlBreakOutCount", control_break_out_count, "PASS")
    add_diag("Base.PctOut", float(pct_out), "PASS")
    add_diag("Base.DDetailedOutReclassifiedWithin", ddetailed_out_reclassified_within, "INFO")
    add_diag("Base.DDetailedWithinReclassifiedOut", ddetailed_within_reclassified_out, "INFO")

    update_day_progress(75, status=f"{progress_label}: building transaction-aware portfolio detail", summary=f"OUT - Control Break population identified: {int(control_break_out_count):,} portfolios; DDetailedReturn OUT: {int(ddetailed_out_count):,}")

    for frame in (all_control_df, control_out_df):
        frame["RunDate"] = run_date
        frame["SourceFolder"] = folder
        frame["FolderFingerprint"] = fingerprint
        frame["CacheVersion"] = CACHE_VERSION
        frame["Portfolio"] = _string_series(frame, "Portfolio").str.strip()
        frame["CurrentFDVValueNum"] = num(frame, current_fdv_valuation_col)
        frame["deviation_num"] = frame["Transaction-aware Control Break"]
        frame["tol_num"] = frame["Tolerance Num"]
        tol_safe = frame["tol_num"].abs().where(frame["tol_num"].abs() > 0, float("nan"))
        frame["sev_ratio"] = frame["deviation_num"].abs() / tol_safe

    return {
        "portfolio_df": control_out_df,
        "control_break_audit_df": all_control_df,
        "all_count": all_count,
        "out_count": control_break_out_count,
        "pct_out": pct_out,
        "excluded_portfolio_count": excluded_portfolio_count,
        "threshold_value": threshold_value,
        "ddetailed_out_count": ddetailed_out_count,
        "control_break_out_count": control_break_out_count,
        "control_break_within_count": int(all_count - control_break_out_count),
        "ddetailed_out_reclassified_within": ddetailed_out_reclassified_within,
        "ddetailed_within_reclassified_out": ddetailed_within_reclassified_out,
    }
def _empty_benchmark_recon_df() -> pd.DataFrame:
    """Return an empty benchmark reconciliation frame with the canonical schema."""
    return pd.DataFrame(columns=[
        "RunDate",
        "SourceFolder",
        "FolderFingerprint",
        "BenchmarkCode",
        "OutPortfolioCount",
        "ReconciliationTotal",
        "CacheVersion",
    ])
def _empty_driver_recon_df() -> pd.DataFrame:
    """Return an empty driver reconciliation frame with the canonical schema."""
    return pd.DataFrame(columns=[
        "RunDate",
        "SourceFolder",
        "FolderFingerprint",
        "Asset Type",
        "WeightedOutPortfolioCount",
        "ReconciliationTotal",
        "CacheVersion",
    ])
def _attach_run_metadata(
    df: pd.DataFrame,
    run_date: object,
    folder: str,
    fingerprint: str,
) -> pd.DataFrame:
    """Attach standard run metadata columns to a non-empty frame."""
    if df is None or df.empty:
        return pd.DataFrame()
    return df.assign(
        RunDate=run_date,
        SourceFolder=folder,
        FolderFingerprint=fingerprint,
        CacheVersion=CACHE_VERSION,
    )



def _prepare_portkey_frame(
    df: Optional[pd.DataFrame],
    source_col: Optional[str],
    *,
    output_name: str = "Portfolio",
    extra_cols: Optional[List[str]] = None,
) -> pd.DataFrame:
    """Standardise portfolio-key dataframe prep for joins/grouping.

    This helper centralises the repeated pattern of:
    - selecting only the relevant columns
    - coercing string columns consistently
    - building a normalised join key
    - dropping blank keys
    """
    extra_cols = [c for c in (extra_cols or []) if c]
    base_columns = [source_col] if source_col else []
    selected_cols: List[str] = []
    for col in base_columns + extra_cols:
        if col and col in getattr(df, "columns", []) and col not in selected_cols:
            selected_cols.append(col)
    empty_columns = [output_name, "portkey"] + [c for c in extra_cols if c != source_col]
    if df is None or df.empty or source_col is None or source_col not in getattr(df, "columns", []):
        return pd.DataFrame(columns=empty_columns)

    out = df[selected_cols].copy()
    out[output_name] = _string_series(out, source_col).str.strip()
    out["portkey"] = normalise_join_key_series(out[output_name])
    for col in extra_cols:
        if col in out.columns and col != source_col:
            out[col] = _string_series(out, col).str.strip()
    out = out[out["portkey"].replace("", pd.NA).notna()].copy()
    return out


def _prepare_unique_portkey_frame(
    df: Optional[pd.DataFrame],
    source_col: Optional[str],
    *,
    output_name: str = "Portfolio",
    extra_cols: Optional[List[str]] = None,
    keep: str = "first",
) -> pd.DataFrame:
    out = _prepare_portkey_frame(df, source_col, output_name=output_name, extra_cols=extra_cols)
    if out.empty:
        return out
    return out.drop_duplicates(subset=["portkey"], keep=keep).reset_index(drop=True)
def _evaluate_reconciliation_total(
    label: str,
    recon_total: float,
    expected_total: float,
    add_diag,
    add_exc,
) -> bool:
    """Record reconciliation diagnostics and return whether the totals match."""
    recon_pass = abs(float(recon_total) - float(expected_total)) < 1e-9
    add_diag(f"{label}ReconTotal", recon_total, "PASS" if recon_pass else "FAIL")
    if not recon_pass:
        add_exc(
            f"{label}Reconciliation",
            f"{label} total {recon_total} does not match OUT count {expected_total}",
            "Error",
        )
    return recon_pass
def _build_process_day_benchmark_df(
    portfolio_df: pd.DataFrame,
    bmk: Optional[pd.DataFrame],
    run_date: object,
    folder: str,
    fingerprint: str,
    out_count: int,
    progress_label: str,
    update_day_progress,
    add_diag,
    add_exc,
) -> Dict[str, object]:
    update_day_progress(85, status=f"{progress_label}: reconciling benchmarks", summary="Joining OUT portfolios to BenchmarkStatic and testing benchmark reconciliation")
    benchmark_df = _empty_benchmark_recon_df()
    benchmark_recon_total = 0.0
    benchmark_recon_pass = False
    portfolio_out = portfolio_df.copy()
    if bmk is not None and not bmk.empty:
        bmk_portfolio_code_col = find_col(bmk, ["portfoliocode", "portfolio code", "portfolio"])
        bmk_code_col = resolve_benchmark_code_col(bmk)
        add_diag("Column.BenchmarkPortfolioCodeSelected", bmk_portfolio_code_col or "", "PASS" if bmk_portfolio_code_col else "FAIL")
        add_diag("Column.BenchmarkCodeSelected", bmk_code_col or "", "PASS" if bmk_code_col else "FAIL")
        if bmk_portfolio_code_col is not None and bmk_code_col is not None:
            tmp = pd.DataFrame({"Portfolio": _string_series(portfolio_out, "Portfolio").str.strip()})
            tmp["portkey"] = normalise_join_key_series(tmp["Portfolio"])
            tmp = tmp[tmp["portkey"].replace("", pd.NA).notna()].drop_duplicates(subset=["portkey"]).reset_index(drop=True)
            map_df = bmk[[bmk_portfolio_code_col, bmk_code_col]].dropna().drop_duplicates().copy()
            map_df["portkey"] = normalise_join_key_series(_string_series(map_df, bmk_portfolio_code_col))
            map_df = map_df[map_df["portkey"].replace("", pd.NA).notna()].copy()
            map_df = map_df[["portkey", bmk_code_col]].drop_duplicates(subset=["portkey"], keep="first")
            joined = tmp.merge(map_df, on="portkey", how="left")
            joined = joined.rename(columns={bmk_code_col: "BenchmarkCode"})
            portfolio_out["portkey"] = normalise_join_key_series(_string_series(portfolio_out, "Portfolio"))
            portfolio_out = portfolio_out.merge(joined[["portkey", "BenchmarkCode"]].drop_duplicates(), on="portkey", how="left")
            matched_count = int(joined["BenchmarkCode"].notna().sum())
            unmatched_count = int(joined["BenchmarkCode"].isna().sum())
            add_diag("BenchmarkJoin.MatchedCount", matched_count, "PASS" if matched_count else "WARN")
            add_diag("BenchmarkJoin.UnmatchedCount", unmatched_count, "WARN" if unmatched_count else "PASS")
            benchmark_df = joined.groupby("BenchmarkCode", dropna=False).size().reset_index(name="OutPortfolioCount")
            benchmark_recon_total = float(pd.to_numeric(benchmark_df["OutPortfolioCount"], errors="coerce").sum())
            benchmark_df["ReconciliationTotal"] = benchmark_recon_total
            benchmark_df = _attach_run_metadata(benchmark_df, run_date, folder, fingerprint)
            benchmark_recon_pass = _evaluate_reconciliation_total("Benchmark", benchmark_recon_total, out_count, add_diag, add_exc)
            if unmatched_count:
                add_exc("BenchmarkJoinUnmatched", f"{unmatched_count} OUT portfolios did not match BenchmarkStatic PortfolioCode", "Warning")
        else:
            add_exc("BenchmarkMapping", "Benchmark mapping columns not fully identified", "Warning")
    else:
        add_exc("MissingBenchmarkStatic", "BenchmarkStatic unavailable - benchmark reconciliation skipped", "Warning")

    if "portkey" in portfolio_out.columns:
        portfolio_out = portfolio_out.drop(columns=["portkey"])

    return {
        "portfolio_df": portfolio_out,
        "benchmark_df": benchmark_df,
        "benchmark_recon_total": benchmark_recon_total,
        "benchmark_recon_pass": benchmark_recon_pass,
    }
def _build_process_day_driver_df(
    portfolio_df: pd.DataFrame,
    dat: Optional[pd.DataFrame],
    run_date: object,
    folder: str,
    fingerprint: str,
    out_count: int,
    progress_label: str,
    update_day_progress,
    add_diag,
    add_exc,
) -> Dict[str, object]:
    update_day_progress(95, status=f"{progress_label}: reconciling drivers", summary="Allocating OUT portfolios across asset drivers on a weighted basis")
    driver_df = _empty_driver_recon_df()
    driver_recon_total = 0.0
    driver_recon_pass = False
    portfolio_out = portfolio_df.copy()
    if dat is not None and not dat.empty:
        dat_port_col = find_col(dat, ["portfolio code", "portfoliocode", "portfolio"])
        driver_col = resolve_driver_label_col(dat)
        if dat_port_col is not None and driver_col is not None:
            tmp = dat[[dat_port_col, driver_col]].copy()
            tmp = tmp.dropna(subset=[dat_port_col, driver_col]).copy()
            tmp[dat_port_col] = tmp[dat_port_col].astype(str).str.strip()
            tmp[driver_col] = tmp[driver_col].astype(str).str.strip()
            out_ports = set(portfolio_out["Portfolio"].astype(str).str.strip().unique().tolist())
            tmp = tmp[tmp[dat_port_col].isin(out_ports)].drop_duplicates()
            if not tmp.empty:
                driver_port_map = (
                    tmp.groupby(dat_port_col)[driver_col]
                    .agg(lambda s: " | ".join(sorted({str(v).strip() for v in s if str(v).strip()})))
                    .reset_index()
                    .rename(columns={dat_port_col: "Portfolio", driver_col: "Driver"})
                )
                portfolio_out = portfolio_out.merge(driver_port_map, on="Portfolio", how="left")
                n_per_port = tmp.groupby(dat_port_col)[driver_col].nunique().rename("n_drivers")
                tmp = tmp.merge(n_per_port, left_on=dat_port_col, right_index=True, how="left")
                tmp["n_drivers"] = pd.to_numeric(tmp["n_drivers"], errors="coerce")
                tmp["Weight"] = 1.0 / tmp["n_drivers"].replace(0, pd.NA)
                driver_df = tmp.groupby(driver_col, dropna=False)["Weight"].sum().reset_index().rename(columns={driver_col: "Asset Type", "Weight": "WeightedOutPortfolioCount"})
                driver_recon_total = float(pd.to_numeric(driver_df["WeightedOutPortfolioCount"], errors="coerce").sum())
                driver_df["ReconciliationTotal"] = driver_recon_total
                driver_df = _attach_run_metadata(driver_df, run_date, folder, fingerprint)
                driver_recon_pass = _evaluate_reconciliation_total("Driver", driver_recon_total, out_count, add_diag, add_exc)
            else:
                add_exc("DriverAttribution", "No asset type rows matched OUT population for the day", "Warning")
        else:
            add_exc("DriverMapping", "Driver mapping columns not fully identified", "Warning")
    else:
        add_exc("MissingDAssetTypeReturn", "DAssetTypeReturn unavailable - driver reconciliation skipped", "Warning")

    return {
        "portfolio_df": portfolio_out,
        "driver_df": driver_df,
        "driver_recon_total": driver_recon_total,
        "driver_recon_pass": driver_recon_pass,
    }
def _package_process_day_result(
    run_date: object,
    folder: str,
    fingerprint: str,
    summary_df: pd.DataFrame,
    portfolio_df: pd.DataFrame,
    driver_df: pd.DataFrame,
    benchmark_df: pd.DataFrame,
    control_break_audit_df: Optional[pd.DataFrame],
    diagnostics: List[Dict[str, object]],
    exceptions: List[Dict[str, object]],
    file_meta_df: pd.DataFrame,
    process_timing_rows: Optional[List[Dict[str, object]]] = None,
) -> Dict[str, pd.DataFrame]:
    """Package the canonical process_day result payload without changing schema."""
    diagnostic_df = pd.DataFrame(diagnostics)
    exception_df = pd.DataFrame(exceptions)
    process_day_timing_df = pd.DataFrame(process_timing_rows or [])
    file_meta_with_metadata = _attach_run_metadata(file_meta_df, run_date, folder, fingerprint)
    return {
        "summary_df": summary_df,
        "portfolio_df": portfolio_df,
        "driver_df": driver_df,
        "benchmark_df": benchmark_df,
        "control_break_audit_df": control_break_audit_df if isinstance(control_break_audit_df, pd.DataFrame) else pd.DataFrame(),
        "diagnostic_df": diagnostic_df,
        "exception_df": exception_df,
        "file_meta_df": file_meta_with_metadata,
        "process_day_timing_df": process_day_timing_df,
    }
def process_day(
    folder: str,
    progress_bar=None,
    status_text=None,
    summary_text=None,
    progress_label: str = "Daily processing",
    exclude_below_current_value: float = 0.0,
    loaded_files: Optional[Dict[str, object]] = None,
    folder_fingerprint_override: Optional[str] = None,
) -> Dict[str, pd.DataFrame]:
    """Canonical day-level processor used by daily mode and trend history."""
    process_timing_rows: List[Dict[str, object]] = []
    process_total_started = time.perf_counter()

    # v304.3.2: first timing row captures context creation and folder fingerprint handling.
    context_started = time.perf_counter()
    ctx = _init_process_day_context(
        folder,
        progress_label,
        exclude_below_current_value,
        folder_fingerprint_override=folder_fingerprint_override,
    )
    # [removed] diagnostic timing-frame generation (process_day init).

    run_date = ctx["run_date"]
    fingerprint = ctx["fingerprint"]
    diagnostics = ctx["diagnostics"]
    exceptions = ctx["exceptions"]

    def _record_process_timing(step: str, started_at: float, status: str = "Done", detail: str = "") -> None:
        # [removed] diagnostic timing-frame generation. process_day_timing_df is
        # returned empty; no initial-load display depends on it.
        return None

    update_day_progress = _make_process_day_progress_updater(progress_bar, status_text, summary_text)
    add_diag, add_exc = _make_process_day_recorders(ctx)

    update_day_progress(0, status=f"{progress_label}: preparing selected day", summary=f"Folder: {folder}")
    step_started = time.perf_counter()
    source_bundle = _resolve_process_day_sources(
        folder=folder,
        loaded_files=loaded_files,
        progress_callback=update_day_progress,
        progress_label=progress_label,
    )
    dd = source_bundle["dd"]
    dat = source_bundle["dat"]
    dar = source_bundle.get("dar")
    bmk = source_bundle["bmk"]
    file_meta_df = source_bundle["file_meta_df"]
    _record_process_timing("process_day: resolve/load source bundle", step_started)

    step_started = time.perf_counter()
    validation_bundle = _validate_process_day_inputs(
        run_date=run_date,
        folder=folder,
        fingerprint=fingerprint,
        progress_label=progress_label,
        exclude_below_current_value=exclude_below_current_value,
        update_day_progress=update_day_progress,
        add_diag=add_diag,
        add_exc=add_exc,
        exceptions=exceptions,
        dd=dd,
        file_meta_df=file_meta_df,
        diagnostics=diagnostics,
    )
    _record_process_timing("process_day: validate inputs and resolve columns", step_started)
    if validation_bundle["early_result"] is not None:
        early_result = validation_bundle["early_result"]
        if isinstance(early_result, dict):
            early_result["process_day_timing_df"] = pd.DataFrame(process_timing_rows)
        return early_result

    status_col = validation_bundle["status_col"]
    portfolio_col = validation_bundle["portfolio_col"]
    actual_col = validation_bundle["actual_col"]
    benchmark_ret_col = validation_bundle["benchmark_ret_col"]
    deviation_col = validation_bundle["deviation_col"]
    tolerance_col = validation_bundle["tolerance_col"]
    current_fdv_valuation_col = validation_bundle["current_fdv_valuation_col"]

    step_started = time.perf_counter()
    portfolio_bundle = _build_process_day_portfolio_df(
        dd=dd,
        dar=dar,
        portfolio_col=portfolio_col,
        status_col=status_col,
        actual_col=actual_col,
        benchmark_ret_col=benchmark_ret_col,
        deviation_col=deviation_col,
        tolerance_col=tolerance_col,
        current_fdv_valuation_col=current_fdv_valuation_col,
        run_date=run_date,
        folder=folder,
        fingerprint=fingerprint,
        progress_label=progress_label,
        exclude_below_current_value=exclude_below_current_value,
        update_day_progress=update_day_progress,
        add_diag=add_diag,
        add_exc=add_exc,
    )
    portfolio_df = portfolio_bundle["portfolio_df"]
    all_count = portfolio_bundle["all_count"]
    out_count = portfolio_bundle["out_count"]
    pct_out = portfolio_bundle["pct_out"]
    excluded_portfolio_count = portfolio_bundle["excluded_portfolio_count"]
    threshold_value = portfolio_bundle["threshold_value"]
    control_break_audit_df = portfolio_bundle.get("control_break_audit_df", pd.DataFrame())
    ddetailed_out_count = portfolio_bundle.get("ddetailed_out_count", out_count)
    control_break_out_count = portfolio_bundle.get("control_break_out_count", out_count)
    control_break_within_count = portfolio_bundle.get("control_break_within_count", max(0, int(all_count) - int(out_count)))
    ddetailed_out_reclassified_within = portfolio_bundle.get("ddetailed_out_reclassified_within", 0)
    ddetailed_within_reclassified_out = portfolio_bundle.get("ddetailed_within_reclassified_out", 0)
    _record_process_timing("process_day: build portfolio/control-break output", step_started, detail=f"rows={len(portfolio_df) if isinstance(portfolio_df, pd.DataFrame) else 0}")

    step_started = time.perf_counter()
    benchmark_bundle = _build_process_day_benchmark_df(
        portfolio_df=portfolio_df,
        bmk=bmk,
        run_date=run_date,
        folder=folder,
        fingerprint=fingerprint,
        out_count=int(out_count),
        progress_label=progress_label,
        update_day_progress=update_day_progress,
        add_diag=add_diag,
        add_exc=add_exc,
    )
    portfolio_df = benchmark_bundle["portfolio_df"]
    benchmark_df = benchmark_bundle["benchmark_df"]
    benchmark_recon_total = benchmark_bundle["benchmark_recon_total"]
    benchmark_recon_pass = benchmark_bundle["benchmark_recon_pass"]
    _record_process_timing("process_day: build benchmark mapping/reconciliation", step_started, detail=f"rows={len(benchmark_df) if isinstance(benchmark_df, pd.DataFrame) else 0}")

    step_started = time.perf_counter()
    driver_bundle = _build_process_day_driver_df(
        portfolio_df=portfolio_df,
        dat=dat,
        run_date=run_date,
        folder=folder,
        fingerprint=fingerprint,
        out_count=int(out_count),
        progress_label=progress_label,
        update_day_progress=update_day_progress,
        add_diag=add_diag,
        add_exc=add_exc,
    )
    portfolio_df = driver_bundle["portfolio_df"]
    driver_df = driver_bundle["driver_df"]
    driver_recon_total = driver_bundle["driver_recon_total"]
    driver_recon_pass = driver_bundle["driver_recon_pass"]
    _record_process_timing("process_day: build driver reconciliation", step_started, detail=f"rows={len(driver_df) if isinstance(driver_df, pd.DataFrame) else 0}")

    step_started = time.perf_counter()
    summary_df = _build_process_day_summary(
        run_date=run_date,
        folder=folder,
        fingerprint=fingerprint,
        exceptions=exceptions,
        add_diag=add_diag,
        total_portfolios=int(all_count),
        out_portfolios=int(out_count),
        pct_out=float(pct_out),
        ddetailed_out_portfolios=int(ddetailed_out_count),
        control_break_out_portfolios=int(control_break_out_count),
        control_break_within_portfolios=int(control_break_within_count),
        ddetailed_out_reclassified_within=int(ddetailed_out_reclassified_within),
        ddetailed_within_reclassified_out=int(ddetailed_within_reclassified_out),
        benchmark_recon_total=float(benchmark_recon_total),
        benchmark_recon_pass=bool(benchmark_recon_pass),
        driver_recon_total=float(driver_recon_total),
        driver_recon_pass=bool(driver_recon_pass),
        recon_diff_benchmark=float(benchmark_recon_total - float(out_count)),
        recon_diff_driver=float(driver_recon_total - float(out_count)),
        exclude_threshold=float(threshold_value),
        excluded_portfolios_below_threshold=int(excluded_portfolio_count),
        base_processing_success=True,
    )
    _record_process_timing("process_day: build summary", step_started, detail=f"rows={len(summary_df) if isinstance(summary_df, pd.DataFrame) else 0}")
    _record_process_timing("process_day: total", process_total_started)

    update_day_progress(100, status=f"{progress_label}: complete", summary=f"OUT - Control Break portfolios: {int(out_count):,} | DDetailedReturn OUT: {int(ddetailed_out_count):,} | Benchmark recon: {'PASS' if benchmark_recon_pass else 'FAIL'} | Driver recon: {'PASS' if driver_recon_pass else 'FAIL'}", message_type="success")
    return _package_process_day_result(
        run_date=run_date,
        folder=folder,
        fingerprint=fingerprint,
        summary_df=summary_df,
        portfolio_df=portfolio_df,
        driver_df=driver_df,
        benchmark_df=benchmark_df,
        control_break_audit_df=control_break_audit_df,
        diagnostics=diagnostics,
        exceptions=exceptions,
        file_meta_df=file_meta_df,
        process_timing_rows=process_timing_rows,
    )


__all__ = [
    "HELPER_VERSION",
    "configure_processing",
    "process_day",
]
