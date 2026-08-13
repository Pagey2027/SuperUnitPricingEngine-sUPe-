# -*- coding: utf-8 -*-
"""
bnp_helpers_reconciliation_export.py

v315 - ARC-named "Download selected date" workbook (single day).
v316 - Manual, ad-hoc BACKFILL reconciliation (multi-day) folded into THIS module
       (kept here rather than a new file so the helper count stays at 20).

--------------------------------------------------------------------------------
v315 (single day)
--------------------------------------------------------------------------------
One button -> one .xlsx whose TABS ARE NAMED EXACTLY LIKE THE ARC WORKBOOK sheets
they reconcile to, so the FAO team can open a single file and compare app vs ARC
tab-for-tab. A front "Recon Summary" tab lists every control with its exception
count, RAG status and the ARC sheet it maps to (driven by the ARC Parity Matrix).
READ-ONLY: every frame is read from the dashboard bundle exactly as the check
panels placed it. (Button relabelled from "Download everything" -> "Download
selected date" in v316.)

--------------------------------------------------------------------------------
v316 (multi-day backfill) - MANUAL / AD-HOC
--------------------------------------------------------------------------------
A button in the SAME "Reconciliation export" section, sitting beneath the single-
day button. It walks a user-chosen date range (default 1 Apr 2026 -> today),
per BUSINESS day:
  * resolves that day's BNP folder via the app's scan_folders() (original
    locations), and that day's ARC workbook via the app's _find_arc_workbook_for_date()
    (the same subfolder range the app already searches),
  * builds the day bundle headlessly (_prepare_out_dashboard_bundle) and runs the
    check builders to populate the check frames,
  * writes ONE ledger row per check: date | check | app_value | arc_value | diff |
    pass_fail | app_version | run_at.
Design decisions (confirmed):
  * NOTHING runs on load - only inside the "Run backfill" button click.
  * The coverage HEATMAP is written INSIDE the .xlsx (conditional green/amber/red),
    NOT rendered in the app. The panel only shows a small status line + progress +
    a download button.
  * VERSION-AWARE AUTO-REFRESH: each stored day is stamped with app_version. On a
    run, a stored day whose app_version is OLDER than the current build is
    recomputed and overwritten automatically (newer app always wins); a day at the
    current version is skipped (unless the user ticks "force recompute").
  * Persistence lives under the app's CACHE_DIR (pickle per day), so a backfill is
    idempotent/resumable.
App access is via a LAZY `import bnp_control_app` inside the functions (the app is
already imported and running when the panel renders), so this module needs no
app-side edit and creates no circular import at load time.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, date, timedelta
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple
import os
import re

import pandas as pd

RECON_EXPORT_VERSION = "v316.4"

STATUS_OK = "Ok"
STATUS_CHECK = "Check"
STATUS_NA = "n/a"


# ===========================================================================
# v315 - single-day ARC-named workbook
# ===========================================================================
@dataclass
class ExportSpec:
    bundle_key: str
    arc_sheet: str          # target tab name (ARC-mirrored)
    label: str              # friendly control name for the summary tab
    note: str = ""          # optional note shown when the frame is absent


EXPORT_SPECS: List[ExportSpec] = [
    ExportSpec("universe_missing_from_bnp_df", "Central Mapping List",       "Portfolios - missing from BNP", "mapped/expected but absent in BNP today"),
    ExportSpec("universe_unmapped_in_bnp_df",  "CML - unmapped in BNP",      "Portfolios - unmapped in BNP",  "present in BNP today, not in the mapping"),
    ExportSpec("gav_check_df",                 "GAV Check - SF & Trust",     "GAV Check",                     "Checked population only; Treasury excluded"),
    ExportSpec("gav_treasury_excluded_df",    "GAV Treasury Excluded",      "GAV Treasury excluded",          "Treasury rows retained separately; excluded from checks and totals"),
    ExportSpec("gav_full_df",                 "GAV Full Pack",              "GAV full evidence pack",         "All portfolios with Class, scope and exclusion comment"),
    ExportSpec("return_check_df",              "Unison vs BNP return check", "Advisor Return Check",          "Unison vs BNP recon + OUT (Unison vs Benchmark)"),
    ExportSpec("advisor_uut_df",               "Advisor-UUT Check",          "Advisor-UUT look-through",      "weighted underlying return vs Unison; |variance| > tol"),
    ExportSpec("uut_holdings_df",              "UUT Return",                 "UUT underlying holdings",       "per-holding weighted price returns"),
    ExportSpec("clearing_check_df",            "Investment & Cash Clearing", "Investment & Cash Clearing",    "|Movement| > $1 (End Balance retained alongside)"),
    ExportSpec("negative_nav_df",              "Negative NAV",               "Negative NAV",                  "NAV(9018) < 0 excl. Currency Overlay"),
    ExportSpec("liquidity_df",                 "Acc Balance - Liquidity",    "Liquidity %",                   "Current Account FDV / NAV"),
    ExportSpec("stale_price_df",               "Stale Price Check",          "Stale Price",                   "un-priced beyond pricing frequency"),
    ExportSpec("material_movement_df",         "UUT Material Price MVT",     "Material Price Movement",       ">1% / <-0.5% on the current app material-movement population"),
    ExportSpec("sf_status_df",                 "SF Checklist",               "SF Status Dashboard",           "NULIS sign-off rows"),
    ExportSpec("trust_status_df",              "Trusts Checklist",           "Trust Status Dashboard",        "MLCI sign-off rows"),
    ExportSpec("portfolio_df",                 "DDetailed return",           "Portfolio detail (all)",        "full per-portfolio result set"),
]


def _df(bundle: Dict[str, object], key: str) -> pd.DataFrame:
    v = bundle.get(key) if isinstance(bundle, dict) else None
    return v.copy() if isinstance(v, pd.DataFrame) else pd.DataFrame()


def _universe_frames(bundle: Dict[str, object]) -> Dict[str, pd.DataFrame]:
    out = {"universe_missing_from_bnp_df": pd.DataFrame(),
           "universe_unmapped_in_bnp_df": pd.DataFrame()}
    if not isinstance(bundle, dict):
        return out
    for k in out:
        v = bundle.get(k)
        if isinstance(v, pd.DataFrame) and not v.empty:
            out[k] = v.copy()
    recon = bundle.get("_universe_reconciliation_v308")
    for attr, key in (("missing_from_bnp_df", "universe_missing_from_bnp_df"),
                      ("unmapped_in_bnp_df", "universe_unmapped_in_bnp_df")):
        if out[key].empty:
            v = getattr(recon, attr, None) if recon is not None else None
            if isinstance(v, pd.DataFrame):
                out[key] = v.copy()
    return out


def _excel_safe_sheet_name(name: str, used: set) -> str:
    raw = str(name or "Sheet").strip() or "Sheet"
    for bad in ("\\", "/", "*", "?", ":", "[", "]"):
        raw = raw.replace(bad, " ")
    raw = " ".join(raw.split())[:31] or "Sheet"
    base = raw
    i = 2
    while raw.lower() in used:
        suffix = f" ({i})"
        raw = (base[: 31 - len(suffix)]).rstrip() + suffix
        i += 1
    used.add(raw.lower())
    return raw


def _clean_for_excel(df: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(df, pd.DataFrame) or df.empty:
        return df if isinstance(df, pd.DataFrame) else pd.DataFrame()
    out = df.copy()
    if out.columns.duplicated().any():
        out = out.loc[:, ~pd.Index(out.columns).duplicated()].copy()
    for col in out.columns:
        if out[col].dtype == object:
            out[col] = out[col].map(lambda v: "" if pd.isna(v) else v)
    return out


def _count_exceptions(key: str, df: pd.DataFrame) -> Optional[int]:
    """Best-effort exception count per known check frame. None = not applicable."""
    if not isinstance(df, pd.DataFrame) or df.empty:
        return None

    def _where(col, value):
        if col not in df.columns:
            return None
        s = df[col].astype(str).str.strip()
        if isinstance(value, (list, tuple, set)):
            return int(s.isin([str(x) for x in value]).sum())
        return int((s == str(value)).sum())

    if key == "gav_check_df":
        return _where("Check", "Check")
    if key == "return_check_df":
        n = _where("Return recon Check", "Check")
        return n if n is not None else 0
    if key == "advisor_uut_df":
        return _where("Breach", "Check")
    if key == "clearing_check_df":
        return _where("Check", "Check")
    if key == "negative_nav_df":
        return _where("Negative NAV flag", ["True", "TRUE", "1"])
    if key == "stale_price_df":
        return _where("Stale Price Check", "Stale")
    if key == "material_movement_df":
        return int(len(df))
    if key in ("universe_missing_from_bnp_df", "universe_unmapped_in_bnp_df"):
        return int(len(df))
    if key in ("sf_status_df", "trust_status_df"):
        return _where("Outcome", "Check")
    return None


# ---------------------------------------------------------------------------
# v318 - distinguish "ran, 0 exceptions (Ok)" from "genuinely not run"
# ---------------------------------------------------------------------------
# Previously build_recon_summary collapsed BOTH an empty frame and an absent
# frame to "Not run this session", so a check that RAN and found ZERO (e.g. CML -
# unmapped in BNP after the v326 exclusion cleared it to 0) looked identical to a
# check that never executed (SF/Trust sign-off checklists in a headless export).
# These helpers split the two states by whether the frame was actually PRODUCED
# on the bundle (present as a DataFrame - even empty - or, for universe frames,
# available on the reconciliation object) rather than by whether it has rows.

# Checks that carry exception semantics (an integer breach count). Everything
# else is informational/population-only (Status = n/a when produced).
_EXCEPTION_CHECK_KEYS = {
    "gav_check_df", "return_check_df", "advisor_uut_df", "clearing_check_df",
    "negative_nav_df", "stale_price_df", "material_movement_df",
    "universe_missing_from_bnp_df", "universe_unmapped_in_bnp_df",
    "sf_status_df", "trust_status_df",
}


def _frame_was_produced(bundle: Dict[str, object], key: str) -> bool:
    """True when the check actually executed this session (frame present on the
    bundle, even if empty), vs never run (key absent). Universe frames may live on
    the v308 reconciliation object rather than the bundle key."""
    if not isinstance(bundle, dict):
        return False
    if isinstance(bundle.get(key), pd.DataFrame):
        return True
    if key in ("universe_missing_from_bnp_df", "universe_unmapped_in_bnp_df"):
        recon = bundle.get("_universe_reconciliation_v308")
        attr = "missing_from_bnp_df" if "missing" in key else "unmapped_in_bnp_df"
        if recon is not None and isinstance(getattr(recon, attr, None), pd.DataFrame):
            return True
    return False


def build_recon_summary(bundle: Dict[str, object],
                        frames: Dict[str, pd.DataFrame],
                        arc_names: Dict[str, str]) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    for spec in EXPORT_SPECS:
        key = spec.bundle_key
        df = frames.get(key, pd.DataFrame())
        has_rows = isinstance(df, pd.DataFrame) and not df.empty
        population = int(len(df)) if isinstance(df, pd.DataFrame) else 0
        # v319: the corrected Advisor-UUT frame keeps every row and tags
        # 'In UUT population' (out-of-scope rows carry Breach='Excluded (not UUT/PE)',
        # never 'Check'). Report the SCOPED population (UUT/PE subset), not the whole
        # book, so the summary reads e.g. "~3 / ~100" and matches the section + tab.
        if key == "advisor_uut_df" and has_rows and "In UUT population" in df.columns:
            population = int(pd.Series(df["In UUT population"]).astype("boolean").fillna(False).sum())
        if key == "gav_check_df" and has_rows and "In GAV Check population" in df.columns:
            population = int(pd.Series(df["In GAV Check population"]).astype("boolean").fillna(False).sum())
        produced = _frame_was_produced(bundle, key)

        if not produced:
            # never executed this session (e.g. SF/Trust sign-off not run headless)
            status = "Not run this session"
            exc_str = ""
            pop_str = ""
        elif key not in _EXCEPTION_CHECK_KEYS:
            # produced, informational/population-only control (no breach semantics)
            status = STATUS_NA
            exc_str = ""
            pop_str = f"{population:,}"
        else:
            # produced exception check: empty frame => it RAN and found ZERO -> Ok,
            # not "Not run". _count_exceptions returns None on an empty frame, so
            # treat produced+empty as 0.
            exceptions = _count_exceptions(key, df) if has_rows else 0
            if exceptions is None:
                exceptions = 0
            status = STATUS_CHECK if exceptions > 0 else STATUS_OK
            exc_str = f"{int(exceptions):,}"
            pop_str = f"{population:,}"

        rows.append({
            "Control": spec.label,
            "ARC sheet": arc_names.get(key, spec.arc_sheet),
            "App tab": arc_names.get(key, spec.arc_sheet),
            "Exceptions": exc_str,
            "Population": pop_str,
            "Status": status,
            "Note": spec.note,
        })
    return pd.DataFrame(rows, columns=["Control", "ARC sheet", "App tab",
                                       "Exceptions", "Population", "Status", "Note"])


# ---------------------------------------------------------------------------
# v319 (Option 1) - reconcile the Advisor-UUT tab AND summary to the CORRECTED
# (v311.1) frame. The raw v311 core tests the whole book price-only vs Unison
# (~173/325 over-flags). apply_v311_1 narrows to the true UUT/PE population
# (v311.2), excludes overlay/cash/derivative classes (v316), scales Unison to
# decimal and adds a Tax Effect; it KEEPS every row, tagging 'In UUT population'
# (out-of-scope rows carry Breach='Excluded (not UUT/PE)', never 'Check').
def _advisor_uut_corrected_frame(bundle: Dict[str, object]) -> pd.DataFrame:
    if not isinstance(bundle, dict):
        return pd.DataFrame()
    pre = bundle.get("advisor_uut_df_v311_1")
    if isinstance(pre, pd.DataFrame) and not pre.empty:
        return pre.copy()
    raw = bundle.get("advisor_uut_df")
    if not isinstance(raw, pd.DataFrame) or raw.empty:
        return raw.copy() if isinstance(raw, pd.DataFrame) else pd.DataFrame()
    try:
        from bnp_helpers_uut import (
            apply_v311_1, resolve_uut_scope, _resolve_central_mapping_path,
        )
    except Exception:
        return raw.copy()
    uut_portfolios = None
    fdv_all_portfolios = None
    try:
        scope = resolve_uut_scope(bundle, fdv_paths=bundle.get("fdv_files"))
        uut_portfolios = scope.get("portfolios") or None
        fdv_all_portfolios = scope.get("all_portfolios") or None
    except Exception:
        pass
    excluded_classes = None
    try:
        from bnp_helpers_static_data import advisor_return_check_excluded_classes as _excl
        _ec = _excl(bundle.get("static_data"))
        if _ec:
            excluded_classes = {str(x).strip().lower() for x in _ec}
    except Exception:
        pass
    # v324 FIX: this export/warm-up path previously called apply_v311_1 WITHOUT
    # income, so the workbook-faithful DAssetReturn income was only applied when a
    # user opened the Advisor-UUT panel interactively. The eager warm-up stashes
    # advisor_uut_df_v311_1 from HERE, so the export used an income-less frame -
    # which is why wiring income in changed nothing. Compute income_by_code (sourced
    # from the parsed bundle['dar'] frame + gav_check_df + uut_holdings_df) and pass
    # it, so the warm-up + export both apply it.
    income_by_code = None
    try:
        from bnp_helpers_uut import build_uut_income_by_code as _uut_income
        income_by_code = _uut_income(bundle) or None
    except Exception:
        income_by_code = None
    try:
        cm_path = _resolve_central_mapping_path(bundle)
        out = apply_v311_1(raw, cm_path if cm_path else None,
                           income_by_code=income_by_code,
                           uut_portfolios=uut_portfolios,
                           fdv_all_portfolios=fdv_all_portfolios,
                           excluded_classes=excluded_classes)
        if isinstance(out, pd.DataFrame) and not out.empty:
            bundle["advisor_uut_df_v311_1"] = out
            return out.copy()
    except Exception:
        pass
    return raw.copy()


def _collect_frames(bundle: Dict[str, object]) -> Dict[str, pd.DataFrame]:
    frames: Dict[str, pd.DataFrame] = {}
    uni = _universe_frames(bundle)
    for spec in EXPORT_SPECS:
        if spec.bundle_key in uni:
            frames[spec.bundle_key] = uni[spec.bundle_key]
        else:
            frames[spec.bundle_key] = _df(bundle, spec.bundle_key)
    # v319 (Option 1): publish the CORRECTED Advisor-UUT frame so the exported tab
    # AND the summary both read the scoped/tax-adjusted numbers, matching the app UI.
    corrected = _advisor_uut_corrected_frame(bundle)
    if isinstance(corrected, pd.DataFrame) and not corrected.empty:
        frames["advisor_uut_df"] = corrected
    return frames


def _parity_frame() -> pd.DataFrame:
    try:
        from bnp_helpers_parity import build_parity_dataframe
        return build_parity_dataframe()
    except Exception:
        return pd.DataFrame()


def build_reconciliation_workbook_bytes(bundle: Dict[str, object],
                                        run_date_label: str = "") -> Tuple[bytes, pd.DataFrame]:
    """Build the single-day ARC-named workbook. Returns (xlsx_bytes, summary_df)."""
    frames = _collect_frames(bundle)
    used: set = set()
    arc_names: Dict[str, str] = {}
    for spec in EXPORT_SPECS:
        arc_names[spec.bundle_key] = _excel_safe_sheet_name(spec.arc_sheet, used)

    summary = build_recon_summary(bundle, frames, arc_names)

    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        summary_sheet = _excel_safe_sheet_name("Recon Summary", set())
        _clean_for_excel(summary).to_excel(writer, sheet_name=summary_sheet, index=False)
        parity = _parity_frame()
        if isinstance(parity, pd.DataFrame) and not parity.empty:
            pname = _excel_safe_sheet_name("Parity Matrix", used | {summary_sheet.lower()})
            _clean_for_excel(parity).to_excel(writer, sheet_name=pname, index=False)
        for spec in EXPORT_SPECS:
            df = frames.get(spec.bundle_key, pd.DataFrame())
            sheet = arc_names[spec.bundle_key]
            if isinstance(df, pd.DataFrame) and not df.empty:
                _clean_for_excel(df).to_excel(writer, sheet_name=sheet, index=False)
            else:
                placeholder = pd.DataFrame(
                    [{"Status": "Not run this session",
                      "Detail": spec.note or "Open the matching section to populate this tab."}]
                )
                placeholder.to_excel(writer, sheet_name=sheet, index=False)
        _freeze_and_widen(writer.book)

    return output.getvalue(), summary


def _freeze_and_widen(wb) -> None:
    try:
        for ws in wb.worksheets:
            ws.freeze_panes = "A2"
            for column_cells in ws.columns:
                try:
                    letter = column_cells[0].column_letter
                    max_len = max(len(str(c.value or "")) for c in column_cells[:200])
                    ws.column_dimensions[letter].width = min(max(max_len + 2, 10), 60)
                except Exception:
                    pass
    except Exception:
        pass


# ===========================================================================
# v316 - multi-day backfill
# ===========================================================================
BACKFILL_START_DEFAULT = date(2026, 4, 1)   # big-picture: reconcile back to 1 Apr 2026

# Ledger schema (one row per check per day).
LEDGER_COLUMNS = ["date", "check", "app_value", "arc_value", "diff",
                  "pass_fail", "app_version", "run_at"]

PASS = "PASS"
FAIL = "FAIL"
APP_ONLY = "APP-ONLY"      # app value computed, no ARC comparator resolved
NO_ARC = "NO ARC FILE"     # business day but no ARC workbook found
ERROR = "ERROR"            # the day (or a check) blew up
NOT_RUN = "NOT RUN"        # check frame not produced this run

# Per-check ARC sheet(s) + candidate flag columns / values, anchored to the
# workbook_sheet names in the parity matrix / the ARC workbook tab list. Used to
# derive arc_value (an exception count) best-effort. If a sheet/column cannot be
# resolved the check is recorded APP-ONLY rather than fabricating a number.
ARC_FLAG_SPECS: Dict[str, Dict[str, Any]] = {
    "gav_check_df":          {"sheets": ["GAV Check - SF", "GAV Check - Trust", "GAV Check"],
                              "flag_cols": ["Check", "N"], "flag_values": {"check"}},
    "return_check_df":       {"sheets": ["Unison Fail - SF", "Unison Fail - Trust",
                                          "Advisor Return Check - SF", "Advisor Return Check - Trust",
                                          "Unison vs BNP return check"],
                              "flag_cols": ["Return recon Check", "AA", "Check"], "flag_values": {"check"}},
    "advisor_uut_df":        {"sheets": ["Advisor-UUT Return Check", "Advisor-UUT Check"],
                              "flag_cols": ["Breach", "Check"], "flag_values": {"check", "breach"}},
    "clearing_check_df":     {"sheets": ["Investment & Cash Clearing", "Investment Clearing", "Cash Clearing"],
                              "flag_cols": ["Check"], "flag_values": {"check"}},
    "negative_nav_df":       {"sheets": ["Unison vs BNP return check"],
                              "flag_cols": ["Negative NAV flag", "Negative NAV"], "flag_values": {"true", "check"}},
    "stale_price_df":        {"sheets": ["Stale Price Check"],
                              "flag_cols": ["Stale Price Check", "Stale", "Check"], "flag_values": {"stale", "check"}},
    "material_movement_df":  {"sheets": ["UUT Material Price MVT"],
                              "flag_cols": ["Check", "Material"], "flag_values": {"check"}, "count_all_rows": True},
    "universe_missing_from_bnp_df": {"sheets": ["Central Mapping List"],
                              "flag_cols": ["Missing from BNP", "Present today", "A"],
                              "flag_values": {"false", "missing", "no"}},
}


# --- app version parsing / comparison ---------------------------------------
def _parse_app_version(s: object) -> Tuple[int, ...]:
    """Extract a comparable (major, minor, patch, ...) tuple from an APP_PYTHON_VERSION
    string like 'v357.1 (ARC replacement - 3-group dashboard)'. Returns () if unparseable."""
    m = re.search(r"v?(\d+(?:\.\d+)*)", str(s or ""), flags=re.IGNORECASE)
    if not m:
        return tuple()
    try:
        return tuple(int(p) for p in m.group(1).split("."))
    except Exception:
        return tuple()


def _current_is_newer(current: object, stored: object) -> bool:
    """True when `current` app version is strictly newer than `stored` (so the stored
    day should be recomputed). Unparseable/blank stored -> treat as older (refresh)."""
    c = _parse_app_version(current)
    s = _parse_app_version(stored)
    if not s:
        return True
    if not c:
        return False
    return c > s


# --- persistence (pickle per day, under the app CACHE_DIR) ------------------
def _backfill_cache_dir() -> str:
    base = ""
    try:
        import bnp_control_app as _app
        base = str(getattr(_app, "CACHE_DIR", "") or "")
    except Exception:
        base = ""
    if not base:
        base = os.path.join(os.getcwd(), "trend_cache")
    d = os.path.join(base, "recon_backfill")
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        pass
    return d


def _day_pickle_path(d: date) -> str:
    return os.path.join(_backfill_cache_dir(), f"{d.isoformat()}.pkl")


def _load_stored_day(d: date) -> pd.DataFrame:
    p = _day_pickle_path(d)
    try:
        if os.path.exists(p):
            df = pd.read_pickle(p)
            if isinstance(df, pd.DataFrame):
                return df
    except Exception:
        pass
    return pd.DataFrame(columns=LEDGER_COLUMNS)


def _persist_day(d: date, rows_df: pd.DataFrame) -> None:
    try:
        rows_df.to_pickle(_day_pickle_path(d))
    except Exception:
        pass


def _stored_day_version(d: date) -> object:
    df = _load_stored_day(d)
    if isinstance(df, pd.DataFrame) and not df.empty and "app_version" in df.columns:
        vals = [v for v in df["app_version"].tolist() if str(v).strip()]
        if vals:
            return vals[0]
    return None


# --- app access (lazy) ------------------------------------------------------
def _app_current_version() -> str:
    try:
        import bnp_control_app as _app
        return str(getattr(_app, "APP_PYTHON_VERSION", "") or "")
    except Exception:
        return ""


def _bnp_folder_for_date(d: date) -> str:
    """Resolve the BNP source folder for a date using the app's scan_folders()."""
    try:
        import bnp_control_app as _app
        pairs = _app.scan_folders(getattr(_app, "ROOT_FOLDER", ""), force_refresh=False)
        for dd, folder in (pairs or []):
            try:
                if pd.to_datetime(dd).date() == d:
                    return str(folder)
            except Exception:
                continue
    except Exception:
        pass
    return ""


def _arc_path_for_date(d: date) -> str:
    """Resolve the ARC workbook for a date using the app's finder (subfolder range)."""
    try:
        import bnp_control_app as _app
        arc_file, _loc = _app._find_arc_workbook_for_date(d)
        return str(arc_file or "")
    except Exception:
        return ""


def _build_day_bundle(folder: str) -> Dict[str, object]:
    """Headlessly build the dashboard bundle for a folder (full fidelity), then
    populate the check frames by running the builders directly."""
    import bnp_control_app as _app
    try:
        settings = _app.load_sidebar_settings()
    except Exception:
        settings = {}
    tiny_upper = float(settings.get("mv_tiny_upper_bound", 100.0)) if isinstance(settings, dict) else 100.0
    fx_tol = float(settings.get("fx_line_match_tolerance_dollar", 100.0)) if isinstance(settings, dict) else 100.0
    ca_pct = float(settings.get("current_account_dominance_threshold_pct", 80.0)) if isinstance(settings, dict) else 80.0
    bundle = _app._prepare_out_dashboard_bundle(
        folder, tiny_upper, progress_callback=None, fx_timing_callback=None,
        force_source_refresh=False, force_process_refresh=False,
        fx_line_match_tolerance_dollar=fx_tol,
        current_account_dominance_threshold_pct=ca_pct,
    )
    if not isinstance(bundle, dict):
        bundle = {}
    _populate_check_frames(bundle)
    return bundle


# ---------------------------------------------------------------------------
# Per-check builders (idempotent) + shared eager warm-up
# ---------------------------------------------------------------------------
# Each _build_* helper is guarded and IDEMPOTENT: it skips work when the frame is
# already present on the bundle (so the live app can call the shared warm-up at
# load without recomputing anything a render already produced, and repeat calls
# are no-ops). These are the SINGLE source of truth used by BOTH the headless
# backfill (_populate_check_frames) and the live-app eager warm-up
# (ensure_all_check_frames), so what is exported is guaranteed identical to what
# the on-screen panels show.

def _already(bundle: Dict[str, object], *keys: str) -> bool:
    return all(isinstance(bundle.get(k), pd.DataFrame) for k in keys)


def _build_universe_frames(bundle: Dict[str, object]) -> None:
    if _frame_was_produced(bundle, "universe_missing_from_bnp_df") and \
       _frame_was_produced(bundle, "universe_unmapped_in_bnp_df"):
        return
    try:
        from bnp_helpers_universe import load_universe, reconcile_universe
        pf = bundle.get("portfolio_df", pd.DataFrame())
        uni = load_universe(bundle.get("static_data"))
        full_universe = getattr(uni, "universe_df", pd.DataFrame())
        recon = reconcile_universe(full_universe, pf, expected_source="Unison Active Advisors", full_universe_df=full_universe)
        bundle["_universe_reconciliation_v308"] = recon
        bundle["universe_missing_from_bnp_df"] = getattr(recon, "missing_from_bnp_df", pd.DataFrame())
        bundle["universe_unmapped_in_bnp_df"] = getattr(recon, "unmapped_in_bnp_df", pd.DataFrame())
    except Exception:
        pass


def _build_gav_frame(bundle: Dict[str, object]) -> None:
    if _already(bundle, "gav_check_df") and not bundle["gav_check_df"].empty:
        return
    try:
        from bnp_helpers_gav import build_gav_check, enrich_portfolio_class_from_mapping, resolve_acc_balance_source
        pf = enrich_portfolio_class_from_mapping(bundle.get("portfolio_df", pd.DataFrame()), bundle)
        acc = resolve_acc_balance_source(bundle)
        res = build_gav_check(pf, acc, bundle.get("dar", pd.DataFrame()))
        bundle["gav_check_df"] = getattr(res, "gav_df", pd.DataFrame())
        bundle["gav_full_df"] = getattr(res, "full_df", pd.DataFrame())
        bundle["gav_treasury_excluded_df"] = getattr(res, "treasury_excluded_df", pd.DataFrame())
        bundle["gav_check_summary"] = getattr(res, "summary", {})
    except Exception:
        pass


def _build_return_frame(bundle: Dict[str, object]) -> None:
    if _already(bundle, "return_check_df") and not bundle["return_check_df"].empty:
        return
    try:
        from bnp_helpers_return_check import build_return_check
        pf = bundle.get("portfolio_df", pd.DataFrame())
        res = build_return_check(pf, bundle)
        bundle["return_check_df"] = getattr(res, "return_df", pd.DataFrame())
        bundle["return_check_summary"] = getattr(res, "summary", {})
    except Exception:
        pass


def _build_uut_frame(bundle: Dict[str, object]) -> None:
    # If the Option 1 corrected-UUT swap (_advisor_uut_corrected_frame) is present
    # in this build, publish the CORRECTED frame; otherwise publish the raw v311
    # frame. Guarded so it works with or without Option 1.
    def _swap_corrected():
        fn = globals().get("_advisor_uut_corrected_frame")
        if callable(fn):
            try:
                corrected = fn(bundle)
                if isinstance(corrected, pd.DataFrame) and not corrected.empty:
                    bundle["advisor_uut_df"] = corrected
            except Exception:
                pass
    if _already(bundle, "advisor_uut_df") and not bundle["advisor_uut_df"].empty:
        _swap_corrected()
        return
    try:
        from bnp_helpers_uut import build_advisor_uut_check
        pf = bundle.get("portfolio_df", pd.DataFrame())
        res = build_advisor_uut_check(pf, bundle)
        bundle["advisor_uut_df"] = getattr(res, "advisor_uut_df", pd.DataFrame())
        bundle["uut_holdings_df"] = getattr(res, "holdings_df", pd.DataFrame())
        _swap_corrected()
    except Exception:
        pass


def _build_ancillary_frames(bundle: Dict[str, object]) -> None:
    if _already(bundle, "clearing_check_df", "negative_nav_df", "liquidity_df"):
        return
    try:
        from bnp_helpers_ancillary import build_ancillary_checks, _find_acc_balance
        acc = _find_acc_balance(bundle)
        res = build_ancillary_checks(bundle, acc)
        bundle["clearing_check_df"] = getattr(res, "clearing_df", pd.DataFrame())
        bundle["negative_nav_df"] = getattr(res, "negative_nav_df", pd.DataFrame())
        bundle["liquidity_df"] = getattr(res, "liquidity_df", pd.DataFrame())
    except Exception:
        pass


def _build_price_integrity_frames(bundle: Dict[str, object]) -> None:
    if _already(bundle, "stale_price_df", "material_movement_df"):
        return
    try:
        from bnp_helpers_price_integrity import build_price_integrity
        res = build_price_integrity(bundle)
        bundle["stale_price_df"] = getattr(res, "stale_df", pd.DataFrame())
        bundle["material_movement_df"] = getattr(res, "material_df", pd.DataFrame())
    except Exception:
        pass


def _build_outputs_frames(bundle: Dict[str, object]) -> None:
    if _already(bundle, "sf_status_df", "trust_status_df"):
        return
    try:
        from bnp_helpers_outputs import build_outputs
        res = build_outputs(bundle)
        bundle["sf_status_df"] = getattr(res, "sf_status_df", pd.DataFrame())
        bundle["trust_status_df"] = getattr(res, "trust_status_df", pd.DataFrame())
    except Exception:
        pass


def ensure_all_check_frames(bundle: Dict[str, object], *, parallel: bool = True,
                            max_workers: int = 4) -> Dict[str, object]:
    """EAGER warm-up: build every Portfolio Numbers check frame ONCE and stash it
    on the bundle, so (a) the reconciliation export is complete/current the moment
    load finishes and (b) each sub-section renders from cache with no recompute.

    Ordering respects the one real dependency: universe + GAV are built FIRST
    (the return-check NAV=0 gate reads gav_check_df), then the remaining
    independent checks fan out. The independent builders write to DISTINCT bundle
    keys, so running them on threads is safe (CPython dict item-assignment is
    atomic and there are no shared-key writes); the cost is network/file I/O, which
    releases the GIL, so wall-time collapses toward the slowest single check rather
    than their sum. Fully guarded and idempotent - safe to call on every rerun.
    """
    if not isinstance(bundle, dict):
        return bundle
    # Phase 1 - dependencies first (sequential).
    _build_universe_frames(bundle)
    _build_gav_frame(bundle)
    # Phase 2 - independent checks (parallel where available).
    independent = [
        _build_return_frame,
        _build_uut_frame,
        _build_ancillary_frames,
        _build_price_integrity_frames,
        _build_outputs_frames,
    ]
    ran_parallel = False
    if parallel:
        try:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=max(1, int(max_workers))) as ex:
                futures = [ex.submit(fn, bundle) for fn in independent]
                for fut in futures:
                    try:
                        fut.result()
                    except Exception:
                        pass
            ran_parallel = True
        except Exception:
            ran_parallel = False
    if not ran_parallel:
        for fn in independent:
            try:
                fn(bundle)
            except Exception:
                pass
    bundle["_all_check_frames_ready"] = True
    return bundle


def _populate_check_frames(bundle: Dict[str, object]) -> None:
    """Headless builder for the backfill: run every check builder on this day's
    isolated bundle. Delegates to the shared idempotent builders so the backfill
    and the live app produce identical frames. Sequential (the backfill already
    parallelises across DAYS)."""
    if not isinstance(bundle, dict):
        return
    ensure_all_check_frames(bundle, parallel=False)


# --- ARC comparator (best-effort exception count from the ARC workbook) -----
def _load_arc_sheet(arc_path: str, sheet: str) -> pd.DataFrame:
    try:
        import bnp_control_app as _app
        df, _meta = _app._load_excel_sheet_normalised(arc_path, sheet)
        return df if isinstance(df, pd.DataFrame) else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def _arc_exception_count(bundle_key: str, arc_path: str) -> Optional[int]:
    """Best-effort exception count for a check from the ARC workbook. None when the
    sheet/flag column cannot be resolved (caller records APP-ONLY, not a fake 0)."""
    spec = ARC_FLAG_SPECS.get(bundle_key)
    if not spec or not arc_path:
        return None
    for sheet in spec.get("sheets", []):
        df = _load_arc_sheet(arc_path, sheet)
        if not isinstance(df, pd.DataFrame) or df.empty:
            continue
        if spec.get("count_all_rows"):
            return int(len(df))
        cols_norm = {re.sub(r"[^a-z0-9]", "", str(c).lower()): c for c in df.columns}
        flag_values = {str(v).lower() for v in spec.get("flag_values", set())}
        for cand in spec.get("flag_cols", []):
            key = re.sub(r"[^a-z0-9]", "", str(cand).lower())
            col = cols_norm.get(key)
            if col is not None:
                s = df[col].astype(str).str.strip().str.lower()
                return int(s.isin(flag_values).sum())
    return None


# --- one day's ledger rows --------------------------------------------------
def _day_ledger_rows(d: date, app_version: str) -> pd.DataFrame:
    run_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    arc_path = _arc_path_for_date(d)
    folder = _bnp_folder_for_date(d)

    checks = [(s.bundle_key, s.label) for s in EXPORT_SPECS
              if s.bundle_key in ARC_FLAG_SPECS or s.bundle_key in (
                  "gav_check_df", "return_check_df", "advisor_uut_df",
                  "clearing_check_df", "negative_nav_df", "stale_price_df",
                  "material_movement_df", "universe_missing_from_bnp_df")]

    if not folder:
        rows = [{"date": d.isoformat(), "check": lbl, "app_value": "", "arc_value": "",
                 "diff": "", "pass_fail": "NO BNP FOLDER", "app_version": app_version,
                 "run_at": run_at} for _k, lbl in checks]
        return pd.DataFrame(rows, columns=LEDGER_COLUMNS)

    try:
        bundle = _build_day_bundle(folder)
    except Exception as exc:
        rows = [{"date": d.isoformat(), "check": lbl, "app_value": "", "arc_value": "",
                 "diff": "", "pass_fail": f"{ERROR}: {type(exc).__name__}",
                 "app_version": app_version, "run_at": run_at} for _k, lbl in checks]
        return pd.DataFrame(rows, columns=LEDGER_COLUMNS)

    rows: List[Dict[str, Any]] = []
    for key, label in checks:
        try:
            app_v = _count_exceptions(key, bundle.get(key, pd.DataFrame()))
            if app_v is None:
                rows.append({"date": d.isoformat(), "check": label, "app_value": "",
                             "arc_value": "", "diff": "", "pass_fail": NOT_RUN,
                             "app_version": app_version, "run_at": run_at})
                continue
            if not arc_path:
                arc_v = None
                pf = NO_ARC
            else:
                arc_v = _arc_exception_count(key, arc_path)
                if arc_v is None:
                    pf = APP_ONLY
                else:
                    pf = PASS if int(app_v) == int(arc_v) else FAIL
            rows.append({
                "date": d.isoformat(), "check": label,
                "app_value": int(app_v),
                "arc_value": ("" if arc_v is None else int(arc_v)),
                "diff": ("" if arc_v is None else int(app_v) - int(arc_v)),
                "pass_fail": pf, "app_version": app_version, "run_at": run_at,
            })
        except Exception as exc:
            rows.append({"date": d.isoformat(), "check": label, "app_value": "",
                         "arc_value": "", "diff": "", "pass_fail": f"{ERROR}: {type(exc).__name__}",
                         "app_version": app_version, "run_at": run_at})
    return pd.DataFrame(rows, columns=LEDGER_COLUMNS)


# --- the backfill runner ----------------------------------------------------
def run_backfill(start: date, end: date, *, force: bool = False,
                 progress_cb=None, app_version: Optional[str] = None) -> pd.DataFrame:
    """Walk business days start..end. For each day: skip if already stored at the
    current app version (unless force); otherwise (re)compute and overwrite. A stored
    day at an OLDER app version is always recomputed. Returns the full ledger."""
    app_version = app_version or _app_current_version()
    days: List[date] = []
    d = start
    while d <= end:
        if d.weekday() < 5:  # Mon-Fri
            days.append(d)
        d += timedelta(days=1)

    all_frames: List[pd.DataFrame] = []
    total = max(1, len(days))
    for i, day in enumerate(days, start=1):
        if callable(progress_cb):
            try:
                progress_cb(i, total, day)
            except Exception:
                pass
        stored = _load_stored_day(day)
        stored_ok = isinstance(stored, pd.DataFrame) and not stored.empty
        if stored_ok and not force and not _current_is_newer(app_version, _stored_day_version(day)):
            all_frames.append(stored)   # up-to-date -> reuse
            continue
        rows = _day_ledger_rows(day, app_version)
        _persist_day(day, rows)
        all_frames.append(rows)

    if not all_frames:
        return pd.DataFrame(columns=LEDGER_COLUMNS)
    return pd.concat(all_frames, ignore_index=True)


# --- coverage heatmap + ledger workbook -------------------------------------
def _pass_fail_fill(token: str):
    from openpyxl.styles import PatternFill
    t = str(token or "").upper()
    if t.startswith(PASS):
        rgb = "C6EFCE"   # green
    elif t.startswith(FAIL):
        rgb = "FFC7CE"   # red
    elif t.startswith(ERROR):
        rgb = "F4CCCC"   # dark-ish red
    elif t in (NO_ARC, APP_ONLY, NOT_RUN, "NO BNP FOLDER"):
        rgb = "FFEB9C"   # amber
    else:
        rgb = "FFFFFF"
    return PatternFill(start_color=rgb, end_color=rgb, fill_type="solid")


def build_backfill_workbook_bytes(ledger: pd.DataFrame) -> bytes:
    """Build the multi-day workbook: Coverage Heatmap (conditional colours) + Ledger +
    Summary. The heatmap is a date x check grid of pass/fail tokens with green/amber/
    red fills - written to the FILE, never rendered in the app."""
    led = ledger.copy() if isinstance(ledger, pd.DataFrame) else pd.DataFrame(columns=LEDGER_COLUMNS)
    for c in LEDGER_COLUMNS:
        if c not in led.columns:
            led[c] = ""

    # pivot date x check -> pass_fail token (last run wins per date/check)
    if not led.empty:
        piv = (led.assign(_o=range(len(led)))
                  .sort_values("_o")
                  .drop_duplicates(subset=["date", "check"], keep="last")
                  .pivot(index="date", columns="check", values="pass_fail")
                  .fillna(""))
        piv = piv.sort_index()
    else:
        piv = pd.DataFrame()

    # Summary: per-check first-fail date + % green
    summary_rows: List[Dict[str, Any]] = []
    if not led.empty:
        for chk, grp in led.groupby("check"):
            pfs = grp["pass_fail"].astype(str)
            n = int(len(grp))
            green = int(pfs.str.upper().str.startswith(PASS).sum())
            fails = grp[pfs.str.upper().str.startswith(FAIL)]["date"].tolist()
            summary_rows.append({
                "Check": chk,
                "Days": n,
                "PASS": green,
                "FAIL": int(pfs.str.upper().str.startswith(FAIL).sum()),
                "Amber/Other": n - green - int(pfs.str.upper().str.startswith(FAIL).sum()),
                "% green": (round(100.0 * green / n, 1) if n else 0.0),
                "First FAIL date": (min(fails) if fails else ""),
            })
    summary_df = pd.DataFrame(summary_rows)

    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        # 1) Coverage Heatmap
        hm_name = "Coverage Heatmap"
        if piv.empty:
            pd.DataFrame([{"Coverage": "No ledger rows for the selected range."}]).to_excel(
                writer, sheet_name=hm_name, index=False)
        else:
            piv_out = piv.reset_index().rename(columns={"index": "date"})
            piv_out.to_excel(writer, sheet_name=hm_name, index=False)
            ws = writer.sheets[hm_name]
            # colour each data cell (skip header row + the date column)
            n_rows, n_cols = piv.shape
            for r in range(n_rows):
                for c in range(n_cols):
                    cell = ws.cell(row=r + 2, column=c + 2)  # +2: header + date col
                    cell.fill = _pass_fail_fill(str(cell.value or ""))
        # 2) Ledger
        _clean_for_excel(led[LEDGER_COLUMNS]).to_excel(writer, sheet_name="Ledger", index=False)
        # 3) Summary
        if not summary_df.empty:
            _clean_for_excel(summary_df).to_excel(writer, sheet_name="Summary", index=False)
        _freeze_and_widen(writer.book)

    return output.getvalue()


# ===========================================================================
# Streamlit renderers
# ===========================================================================
def render_reconciliation_export(st, bundle: Dict[str, object]) -> None:
    """Reconciliation export section: single-day download (v315, renamed) followed by
    the multi-day backfill panel (v316)."""
    _render_single_day(st, bundle)
    try:
        st.divider()
    except Exception:
        pass
    render_backfill_panel(st, bundle)


def _render_single_day(st, bundle: Dict[str, object]) -> None:
    try:
        run_date_label = str(bundle.get("selected_date_label", "")) if isinstance(bundle, dict) else ""
        xlsx_bytes, summary = build_reconciliation_workbook_bytes(bundle, run_date_label)

        st.markdown("**Reconciliation export (v315)** - one workbook, tabs named "
                    "exactly like the ARC sheets, so the team can validate app vs "
                    "ARC tab-for-tab.")
        has_check = (not summary.empty) and (summary["Status"] == STATUS_CHECK).any()
        (st.warning if has_check else st.success)(
            "CHECK - one or more controls have exceptions" if has_check
            else "OK - all populated controls within tolerance"
        )
        st.dataframe(summary, width="stretch", hide_index=True)

        stamp = (run_date_label or datetime.now().strftime("%Y-%m-%d")).replace("/", "-").replace(" ", "_")
        st.download_button(
            "Download selected date",   # v316: relabelled from "Download everything"
            data=xlsx_bytes,
            file_name=f"BNP_ARC_reconciliation_{stamp}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="v315_recon_export_dl",
        )
        st.caption("Each tab mirrors an ARC sheet name. Tabs marked 'Not run this "
                   "session' populate once you open the matching section (or run a "
                   "full pass) before exporting.")
    except Exception as exc:
        try:
            st.error(f"Single-date export could not be built: {type(exc).__name__}: {exc}")
        except Exception:
            pass


def render_backfill_panel(st, bundle: Dict[str, object]) -> None:
    """Manual, ad-hoc multi-day backfill. Nothing runs until 'Run backfill' is clicked.
    Output is a downloadable workbook (Coverage Heatmap + Ledger + Summary); the heatmap
    is NOT rendered in the app."""
    try:
        cur_ver = _app_current_version()
        st.markdown("**Backfill reconciliation (v316)** - app vs ARC across a date "
                    "range. Runs only when you click **Run backfill**. Output is a "
                    "workbook with a colour-coded coverage heatmap - nothing heavy is "
                    "drawn in the app.")

        today = date.today()
        c1, c2 = st.columns(2)
        with c1:
            start = st.date_input("From", value=BACKFILL_START_DEFAULT, key="v316_backfill_from")
        with c2:
            end = st.date_input("To", value=today, key="v316_backfill_to")
        force = st.checkbox(
            "Force recompute (ignore stored days at the current version)",
            value=False, key="v316_backfill_force",
            help=("Off: days already reconciled under the CURRENT app version are reused; "
                  "days stored under an OLDER version are always recomputed (newer app "
                  "wins). On: every day in range is recomputed and overwritten."),
        )
        if st.button("Run backfill now", key="v316_backfill_run"):
            try:
                s = pd.to_datetime(start).date()
                e = pd.to_datetime(end).date()
            except Exception:
                st.error("Please choose a valid From/To date.")
                return
            if s > e:
                st.error("'From' must be on or before 'To'.")
                return

            bar = st.progress(0.0)
            note = st.empty()

            def _cb(i, total, day):
                try:
                    bar.progress(min(1.0, i / max(1, total)))
                    note.caption(f"Day {i} of {total}: {day.isoformat()}")
                except Exception:
                    pass

            with st.spinner("Running backfill reconciliation..."):
                ledger = run_backfill(s, e, force=bool(force), progress_cb=_cb, app_version=cur_ver)

            try:
                bar.progress(1.0)
            except Exception:
                pass

            if ledger is None or ledger.empty:
                st.warning("No business days produced ledger rows for the selected range.")
                return

            # brief, non-heatmap status only
            pf = ledger["pass_fail"].astype(str)
            n = int(len(ledger))
            n_pass = int(pf.str.upper().str.startswith(PASS).sum())
            n_fail = int(pf.str.upper().str.startswith(FAIL).sum())
            (st.warning if n_fail else st.success)(
                f"Backfill complete: {n:,} check-days | {n_pass:,} PASS | {n_fail:,} FAIL "
                f"| {n - n_pass - n_fail:,} amber/other. Open the workbook's "
                f"'Coverage Heatmap' tab for the green/amber/red grid."
            )

            xlsx = build_backfill_workbook_bytes(ledger)
            stamp = f"{s.isoformat()}_to_{e.isoformat()}"
            st.download_button(
                "Download backfill workbook (heatmap + ledger)",
                data=xlsx,
                file_name=f"BNP_ARC_backfill_{stamp}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="v316_backfill_dl",
            )
    except Exception as exc:
        try:
            st.error(f"Backfill panel error: {type(exc).__name__}: {exc}")
        except Exception:
            pass


__all__ = [
    "RECON_EXPORT_VERSION",
    "EXPORT_SPECS",
    "build_recon_summary",
    "build_reconciliation_workbook_bytes",
    "render_reconciliation_export",
    "ensure_all_check_frames",
    # v316
    "run_backfill",
    "build_backfill_workbook_bytes",
    "render_backfill_panel",
    "LEDGER_COLUMNS",
]


if __name__ == "__main__":
    import openpyxl  # noqa
    # ---- self-test 1: single-day workbook (v315 parity) ----
    bundle = {
        "selected_date_label": "2026-08-05",
        "gav_check_df": pd.DataFrame({"Portfolio code": [f"M1{i:03d}" for i in range(194)],
                                      "Check": ["Ok"] * 191 + ["Check"] * 3}),
        "return_check_df": pd.DataFrame({"Portfolio code": [f"M1{i:03d}" for i in range(194)],
                                         "Return recon Check": ["Ok"] * 176 + ["Check"] * 18}),
        "advisor_uut_df": pd.DataFrame({"Breach": ["Ok"] * 17 + ["Check"] * 12}),
        "clearing_check_df": pd.DataFrame({"Check": ["Check"] * 189 + ["Ok"] * 807}),
        "negative_nav_df": pd.DataFrame({"Negative NAV flag": [True] * 3 + [False] * 280}),
        "stale_price_df": pd.DataFrame({"Stale Price Check": ["Stale"] * 380 + ["Ok"] * 1370}),
        "material_movement_df": pd.DataFrame({"x": range(5)}),
    }
    xb, summ = build_reconciliation_workbook_bytes(bundle, "2026-08-05")
    wb = openpyxl.load_workbook(BytesIO(xb))
    assert "Recon Summary" in wb.sheetnames
    print("[single-day] sheets:", len(wb.sheetnames), "| button label = 'Download selected date'")

    # ---- self-test 2: version compare ----
    assert _current_is_newer("v357.1 (x)", "v314") is True
    assert _current_is_newer("v314", "v357.1") is False
    assert _current_is_newer("v316", "v316") is False
    assert _current_is_newer("v316", None) is True
    print("[version] compare OK")

    # ---- self-test 3: heatmap workbook from a synthetic ledger ----
    led = pd.DataFrame([
        {"date": "2026-04-01", "check": "GAV Check", "app_value": 3, "arc_value": 3, "diff": 0, "pass_fail": "PASS", "app_version": "v357.1", "run_at": "x"},
        {"date": "2026-04-01", "check": "Advisor Return Check", "app_value": 18, "arc_value": 17, "diff": 1, "pass_fail": "FAIL", "app_version": "v357.1", "run_at": "x"},
        {"date": "2026-04-01", "check": "Stale Price", "app_value": 380, "arc_value": "", "diff": "", "pass_fail": "APP-ONLY", "app_version": "v357.1", "run_at": "x"},
        {"date": "2026-04-02", "check": "GAV Check", "app_value": 2, "arc_value": 2, "diff": 0, "pass_fail": "PASS", "app_version": "v357.1", "run_at": "x"},
        {"date": "2026-04-02", "check": "Advisor Return Check", "app_value": 10, "arc_value": 10, "diff": 0, "pass_fail": "PASS", "app_version": "v357.1", "run_at": "x"},
        {"date": "2026-04-02", "check": "Stale Price", "app_value": 12, "arc_value": "", "diff": "", "pass_fail": "NO ARC FILE", "app_version": "v357.1", "run_at": "x"},
    ], columns=LEDGER_COLUMNS)
    bx = build_backfill_workbook_bytes(led)
    wb2 = openpyxl.load_workbook(BytesIO(bx))
    assert "Coverage Heatmap" in wb2.sheetnames and "Ledger" in wb2.sheetnames and "Summary" in wb2.sheetnames
    ws = wb2["Coverage Heatmap"]
    # header row 1; first data cell is B2; confirm a fill was applied (not default None)
    filled = sum(1 for row in ws.iter_rows(min_row=2, min_col=2)
                 for c in row if c.fill is not None and c.fill.fill_type == "solid")
    assert filled >= 4, f"expected coloured heatmap cells, got {filled}"
    print(f"[heatmap] Coverage Heatmap/Ledger/Summary built; {filled} coloured cells")

    # ---- self-test 4: run_backfill loop (business days + skip/force), stubs ----
    import bnp_helpers_reconciliation_export as _self
    _self._current_is_newer = lambda cur, stored: True  # force recompute path deterministically

    def _fake_rows(d, ver):
        return pd.DataFrame([{"date": d.isoformat(), "check": "GAV Check", "app_value": 1,
                              "arc_value": 1, "diff": 0, "pass_fail": "PASS",
                              "app_version": ver, "run_at": "x"}], columns=LEDGER_COLUMNS)
    _self._day_ledger_rows = _fake_rows
    _self._persist_day = lambda d, df: None
    _self._load_stored_day = lambda d: pd.DataFrame(columns=LEDGER_COLUMNS)

    ledger = _self.run_backfill(date(2026, 4, 1), date(2026, 4, 7), force=True, app_version="v357.1")
    # 1-7 Apr 2026: Wed..Tue -> business days = Apr 1,2,3,6,7 = 5 days
    assert ledger["date"].nunique() == 5, ledger["date"].unique().tolist()
    print("[runner] business-day loop OK ->", sorted(ledger["date"].unique().tolist()))

    print("\nALL SELF-TESTS PASSED")
