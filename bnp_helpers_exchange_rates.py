# -*- coding: utf-8 -*-
"""Exchange-rate workbook helpers for BNP Control App.

v306.13.7.6c repair:
- restores this helper as a clean module-level implementation;
- prefers left-most External/Externals folders such as "04 Externals - Day 3 Indexation";
- keeps the original recursive day/month search behaviour as fallback;
- emits timing labels compatible with the BNP Control App timing collector.
"""
from __future__ import annotations

import os
import re
import time
from typing import Dict, List, Optional, Tuple

import pandas as pd

# v346: route the FX workbook per-sheet reads (G:/ network, openpyxl) through the
# shared cached Excel reader so the same sheet isn't re-parsed by the header detector
# and the extractor, and repeat FX loads within a session are free. Guarded import
# keeps the module usable if the helper is unavailable (falls back to direct read).
try:
    from bnp_helpers_columns import read_excel_cached as _read_excel_cached_v346
except Exception:
    _read_excel_cached_v346 = None


def _fx_read_sheet_v346(path: str, sheet_name, header=None) -> pd.DataFrame:
    """Cached per-sheet FX read (header=None raw by default, as the detector needs).
    Falls back to the original openpyxl read on any issue."""
    if callable(_read_excel_cached_v346):
        try:
            return _read_excel_cached_v346(path, sheet_name=sheet_name, header=header)
        except Exception:
            pass
    return pd.read_excel(path, sheet_name=sheet_name, header=header, engine="openpyxl")

# v353: DIRECT read of the known "External Indices" FX sheet (see _extract_exchange_
# rate_rows_direct). Replaces the open-all-sheets + score-every-sheet resolver on the
# happy path; the full scan is retained as a guarded fallback. Parity verified on the
# live workbook (37 Exchange Rates rows, identical columns/values). No behaviour change.
EXCHANGE_RATES_VERSION = "v353"
EXCHANGE_RATES_ROOT_FOLDER = ""
_MONTH_ABBR = {1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun", 7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"}
_DAY_ABBR = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}
_VALID_EXTS = (".xlsx", ".xlsm", ".xls")
_FILE_PREFIX = "internal securities master list"
_FILE_CONTAINS = "review international indices"
_HEADER_HINTS = ["index", "index sector", "code"]
_EXCHANGE_SECTOR_VALUE = "exchangerates"
_PREFERRED_COMPARE_CODES = ["USD", "EUR", "GBP", "JPY", "NZD", "CAD", "CNY", "HKD", "SGD", "CHF"]
_EXTERNALS_LEFTMOST_RE = re.compile(r"^\s*\d{0,2}\s*externals?\b", re.IGNORECASE)


def configure_exchange_rates(*, exchange_rates_root_folder: str) -> None:
    global EXCHANGE_RATES_ROOT_FOLDER
    EXCHANGE_RATES_ROOT_FOLDER = str(exchange_rates_root_folder or "").strip()


# v356: per-date FX workbook PATH cache. The residual ~2.3s "FX workbook" cost that
# did NOT drop on revisit was the os.walk discovery of the "04 Externals*" subtree on
# G:/ (find_internal_securities_master_for_date), which re-ran on every load. Once the
# workbook path for a date is resolved it does not change within a session, so we memo
# it keyed by (root, run_date). A cache hit skips the whole network walk (the resolved
# path is re-validated with os.path.exists, so a moved/renamed workbook naturally
# misses and re-discovers). The v346 per-sheet read cache already handles the parse;
# this removes the discovery walk - the last uncached piece.
_FX_WORKBOOK_PATH_CACHE: Dict[str, str] = {}


def clear_fx_workbook_path_cache() -> None:
    "Drop the per-date FX workbook path cache (app calls this on a forced refresh)."
    try:
        _FX_WORKBOOK_PATH_CACHE.clear()
    except Exception:
        pass


def _fx_workbook_path_cache_key(run_date: object) -> str:
    dt = _coerce_run_date(run_date)
    return f"{EXCHANGE_RATES_ROOT_FOLDER}||{dt.date() if dt is not None else run_date}"


def _normalise_col_token(x: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(x).strip().lower())


def _cell_clean(x: object) -> str:
    return ("" if x is None else str(x)).strip()


def _coerce_run_date(run_date: object) -> Optional[pd.Timestamp]:
    if run_date is None:
        return None
    try:
        if pd.isna(run_date):
            return None
    except Exception:
        pass
    dt = pd.to_datetime(run_date, errors="coerce")
    if pd.isna(dt):
        return None
    return pd.Timestamp(dt).normalize()




def _expected_month_folder(root_folder: str, run_date: object) -> str:
    dt = _coerce_run_date(run_date)
    if dt is None:
        return ""
    return os.path.join(str(root_folder or ""), f"{int(dt.year)}", f"{int(dt.month):02d} {_MONTH_ABBR.get(int(dt.month), dt.strftime('%b'))}")


def _expected_day_folder(root_folder: str, run_date: object) -> str:
    dt = _coerce_run_date(run_date)
    if dt is None:
        return ""
    month_folder = _expected_month_folder(root_folder, run_date)
    if not month_folder:
        return ""
    return os.path.join(month_folder, f"{int(dt.day):02d} {_DAY_ABBR.get(int(dt.dayofweek), dt.strftime('%a'))}")


def _safe_exists(path: str) -> bool:
    try:
        return bool(path and os.path.exists(path))
    except Exception:
        return False


def _safe_isdir(path: str) -> bool:
    try:
        return bool(path and os.path.isdir(path))
    except Exception:
        return False


def _safe_listdir(path: str, limit: int = 20) -> str:
    try:
        if not _safe_isdir(path):
            return ""
        return " | ".join(sorted(os.listdir(path))[:limit])
    except Exception as exc:
        return f"Error: {type(exc).__name__}: {exc}"


def _path_repr_info(label: str, path: str) -> List[Dict[str, object]]:
    return [
        {"Check": f"{label}", "Result": path or ""},
        {"Check": f"{label} repr", "Result": repr(path or "")},
        {"Check": f"{label} exists", "Result": "Yes" if _safe_exists(path) else "No"},
        {"Check": f"{label} isdir", "Result": "Yes" if _safe_isdir(path) else "No"},
        {"Check": f"{label} listing", "Result": _safe_listdir(path)},
    ]


def _nearest_existing_ancestor(path: str) -> str:
    cur = str(path or "").strip()
    tried = set()
    while cur and cur not in tried:
        tried.add(cur)
        if _safe_exists(cur):
            return cur
        parent = os.path.dirname(cur)
        if not parent or parent == cur:
            break
        cur = parent
    return ""






def probe_exchange_rate_filesystem(run_date: object) -> pd.DataFrame:
    rows: List[Dict[str, object]] = []
    rows.append({"Check": "Configured exchange-rate root", "Result": EXCHANGE_RATES_ROOT_FOLDER})
    rows.append({"Check": "Configured exchange-rate root repr", "Result": repr(EXCHANGE_RATES_ROOT_FOLDER)})
    roots = _root_variants(EXCHANGE_RATES_ROOT_FOLDER)
    rows.append({"Check": "Configured root variants", "Result": " | ".join(roots)})
    dt = _coerce_run_date(run_date)
    rows.append({"Check": "Resolved run date", "Result": "" if dt is None else str(dt.date())})
    for root in roots:
        month = _expected_month_folder(root, run_date)
        day = _expected_day_folder(root, run_date)
        rows.extend(_path_repr_info("Expected month folder", month))
        rows.extend(_path_repr_info("Expected day folder", day))
        if _safe_isdir(day):
            preferred = _preferred_search_roots(day)
            rows.append({"Check": "Preferred FX search roots", "Result": " | ".join(preferred)})
    return pd.DataFrame(rows)


def _score_candidate(path: str, run_date: object, expected_day_folder: str) -> Tuple[int, int, int, int, str]:
    dt = _coerce_run_date(run_date)
    name = os.path.basename(path).lower()
    parent = os.path.dirname(path).lower().replace(chr(92), "/")
    score_prefix = 1 if name.startswith(_FILE_PREFIX) else 0
    score_contains = 1 if _FILE_CONTAINS in name else 0
    score_run_date = 0
    if dt is not None:
        if dt.strftime("%Y%m%d") in name:
            score_run_date = 3
        elif dt.strftime("%d.%m.%Y") in name:
            score_run_date = 2
    score_day_path = 0
    try:
        if expected_day_folder and os.path.abspath(path).lower().startswith(os.path.abspath(expected_day_folder).lower()):
            score_day_path = 2
    except Exception:
        pass
    score_benchmarks = 1 if "/benchmarks/" in parent else 0
    return (score_run_date, score_day_path, score_prefix + score_contains, score_benchmarks, name)


def find_internal_securities_master_for_date(run_date: object, timing_callback=None) -> Tuple[str, str, List[Dict[str, object]]]:
    diagnostics: List[Dict[str, object]] = []

    def _emit(label: str, start: float, status: str = "Done") -> None:
        if timing_callback is None:
            return
        try:
            timing_callback(label, time.perf_counter() - start, status)
        except Exception:
            pass

    # v356: fast path - reuse the previously-resolved workbook path for this date and
    # skip the os.walk discovery entirely. Re-validated with os.path.exists so a
    # moved/renamed file misses and falls through to full discovery.
    _cache_key = _fx_workbook_path_cache_key(run_date)
    _cached = _FX_WORKBOOK_PATH_CACHE.get(_cache_key)
    if _cached and _safe_exists(_cached):
        diagnostics.append({"Check": "FX workbook path cache", "Result": "hit (v356)", "Path": _cached})
        return _cached, "Workbook resolved (path cache)", diagnostics

    roots = _root_variants(EXCHANGE_RATES_ROOT_FOLDER)
    diagnostics.append({"Check": "FX helper patch", "Result": "v306.13.7.6c_helper_repair_active; v306.13.7.6c_hotfix3_unc_repr; v306.13.7.6c_hotfix1_unc_string"})
    diagnostics.append({"Check": "Configured root variants", "Result": " | ".join(roots)})
    all_candidates: List[str] = []
    all_benchmark_dirs: List[str] = []
    last_expected_day = ""
    for root in roots:
        start = time.perf_counter()
        diagnostics.extend(_path_repr_info("Root", root))
        _emit(f"FX find: check root {root}", start, "Done")
        expected_day = _expected_day_folder(root, run_date)
        expected_month = _expected_month_folder(root, run_date)
        last_expected_day = expected_day or last_expected_day
        search_roots: List[str] = []
        if _safe_isdir(expected_day):
            search_roots.append(expected_day)
        if _safe_isdir(expected_month) and expected_month not in search_roots:
            search_roots.append(expected_month)
        if not search_roots:
            ancestor = _nearest_existing_ancestor(expected_day or expected_month or root)
            if ancestor:
                search_roots.append(ancestor)
        for search_root in search_roots:
            scan_start = time.perf_counter()
            candidates, benchmark_dirs = _collect_candidates(search_root)
            all_candidates.extend(candidates)
            all_benchmark_dirs.extend(benchmark_dirs)
            preferred_roots = _preferred_search_roots(search_root)
            diagnostics.append({
                "Check": "FX helper search root",
                "Result": search_root,
                "PreferredRoots": " | ".join(preferred_roots),
                "Candidates": len(candidates),
                "BenchmarkDirs": len(benchmark_dirs),
            })
            _emit(f"FX find: scan day folder {root}", scan_start, "Done")
    # Deduplicate candidates.
    unique_candidates: List[str] = []
    seen = set()
    for path in all_candidates:
        key = os.path.abspath(path).lower()
        if key not in seen:
            unique_candidates.append(path)
            seen.add(key)
    diagnostics.append({"Check": "FX candidate count", "Result": len(unique_candidates)})
    diagnostics.append({"Check": "FX benchmark dir count", "Result": len(set(map(str.lower, all_benchmark_dirs)))})
    if not unique_candidates:
        return "", "No Internal Securities Master List workbook found", diagnostics
    scored = sorted(unique_candidates, key=lambda p: _score_candidate(p, run_date, last_expected_day), reverse=True)
    selected = scored[0]
    diagnostics.append({"Check": "Selected workbook", "Result": selected})
    diagnostics.append({"Check": "Selected workbook score", "Result": str(_score_candidate(selected, run_date, last_expected_day))})
    # v356: memo the resolved path for this date so subsequent loads skip the walk.
    try:
        if selected:
            _FX_WORKBOOK_PATH_CACHE[_cache_key] = selected
    except Exception:
        pass
    return selected, "Workbook resolved", diagnostics


def _header_names_from_row(row: pd.Series) -> List[str]:
    names: List[str] = []
    seen: Dict[str, int] = {}
    for idx, value in enumerate(row.tolist()):
        text = _cell_clean(value) or f"Column_{idx + 1}"
        base = text
        count = seen.get(base, 0)
        if count:
            text = f"{base}_{count + 1}"
        seen[base] = count + 1
        names.append(text)
    return names


def _sheet_preview(df: pd.DataFrame, max_rows: int = 80) -> List[str]:
    vals: List[str] = []
    try:
        top = df.head(max_rows)
        for value in top.astype(str).fillna("").to_numpy().flatten().tolist():
            token = _normalise_col_token(value)
            if token:
                vals.append(token)
    except Exception:
        pass
    return vals


def _inspect_exchange_rate_workbook(path: str) -> Dict[str, object]:
    info: Dict[str, object] = {"workbook_file": path or "", "sheet_names": [], "workbook_open_error": ""}
    if not path or not os.path.exists(path):
        info["workbook_open_error"] = "Workbook path missing"
        return info
    try:
        xl = pd.ExcelFile(path, engine="openpyxl")
        info["sheet_names"] = list(xl.sheet_names)
    except Exception as exc:
        info["workbook_open_error"] = f"{type(exc).__name__}: {exc}"
    return info


def _find_exchange_rate_sheet(path: str) -> Tuple[str, Dict[str, object]]:
    meta: Dict[str, object] = {"selected_sheet": "", "selected_header_row": None, "sheet_tests": [], "error": ""}
    try:
        xl = pd.ExcelFile(path, engine="openpyxl")
    except Exception as exc:
        meta["error"] = f"{type(exc).__name__}: {exc}"
        return "", meta
    best_sheet = ""
    best_header_row = None
    best_score = (-1, -1, -1)
    for sheet_name in xl.sheet_names:
        try:
            raw = _fx_read_sheet_v346(path, sheet_name=sheet_name, header=None)
            preview_tokens = _sheet_preview(raw)
            header_hits = 0
            exchange_hits = sum(1 for t in preview_tokens if t == _EXCHANGE_SECTOR_VALUE)
            header_row = None
            for idx in range(min(len(raw), 80)):
                row_tokens = [_normalise_col_token(v) for v in raw.iloc[idx].tolist() if _cell_clean(v)]
                row_set = set(row_tokens)
                row_hits = sum(1 for hint in _HEADER_HINTS if _normalise_col_token(hint) in row_set)
                if row_hits >= 2 and header_row is None:
                    header_row = idx
                header_hits = max(header_hits, row_hits)
            score = (header_hits, exchange_hits, 1 if "externalindices" in _normalise_col_token(sheet_name) else 0)
            meta["sheet_tests"].append({"Sheet": sheet_name, "HeaderHits": int(header_hits), "ExchangeSectorHits": int(exchange_hits), "DetectedHeaderRow": "" if header_row is None else int(header_row)})
            if header_row is not None and score > best_score:
                best_score = score
                best_sheet = sheet_name
                best_header_row = header_row
        except Exception as exc:
            meta["sheet_tests"].append({"Sheet": sheet_name, "HeaderHits": 0, "ExchangeSectorHits": 0, "DetectedHeaderRow": "", "Error": f"{type(exc).__name__}: {exc}"})
    meta["selected_sheet"] = best_sheet
    meta["selected_header_row"] = best_header_row
    return best_sheet, meta


# v353: the FX workbook's exchange-rate sheet is ALWAYS "External Indices" (confirmed
# against the live file; format is fixed). The prior path opened the workbook, listed
# ALL ~10 sheets and read EVERY sheet with header=None to *score* which one held the
# rates - the dominant residual FX cost that did not cache on revisit. This goes DIRECT
# to the known sheet: read ONLY "External Indices" (one cached per-sheet read), find its
# header row, and extract. Falls back to the full scan only if the known sheet is
# absent or the direct read yields nothing, so behaviour can never be worse.
_FX_KNOWN_EXCHANGE_SHEET = "External Indices"


def _fx_build_exchange_df_from_raw(raw: pd.DataFrame, header_row: int, meta: Dict[str, object]) -> Tuple[pd.DataFrame, Dict[str, object]]:
    """Shared extractor: given a raw header=None sheet and its header row, build the
    Exchange Rates dataframe. Identical logic on the direct and scan paths (parity)."""
    if header_row is None or int(header_row) >= len(raw):
        meta["error"] = "Header row unresolved"
        return pd.DataFrame(), meta
    header_row = int(header_row)
    headers = _header_names_from_row(raw.iloc[header_row])
    data = raw.iloc[header_row + 1:].copy().reset_index(drop=True)
    if data.empty:
        meta["error"] = "No data rows beneath detected header"
        return pd.DataFrame(), meta
    data.columns = headers
    data = data[~data.apply(lambda r: all(_cell_clean(v) == "" for v in r.tolist()), axis=1)].copy()
    meta["row_count"] = int(len(data))
    meta["column_count"] = int(len(data.columns))
    index_sector_col = ""
    for col in data.columns:
        if _normalise_col_token(col) in {"indexsector", "sector", "indexgroup", "group"}:
            index_sector_col = col
            break
    meta["index_sector_col"] = index_sector_col
    if not index_sector_col:
        meta["status"] = "Header resolved but Index Sector column not found"
        return pd.DataFrame(), meta
    sector_norm = data[index_sector_col].astype(str).map(_normalise_col_token)
    exchange_df = data[sector_norm == _EXCHANGE_SECTOR_VALUE].copy().reset_index(drop=True)
    keep_cols = [c for c in exchange_df.columns if not _normalise_col_token(c).startswith("column") or exchange_df[c].astype(str).str.strip().ne("").any()]
    if keep_cols:
        exchange_df = exchange_df[keep_cols].copy()
    meta["exchange_rate_rows"] = int(len(exchange_df))
    meta["status"] = "Exchange rates extracted" if not exchange_df.empty else "Exchange-rate sheet resolved but no Exchange Rates rows found"
    return exchange_df, meta


def _extract_exchange_rate_rows_direct(path: str) -> Tuple[pd.DataFrame, Dict[str, object]]:
    """v353 fast path: read ONLY the known 'External Indices' sheet, find its header row
    within that single sheet, and extract. No workbook-wide sheet enumeration/scoring."""
    meta: Dict[str, object] = {"sheet_used": _FX_KNOWN_EXCHANGE_SHEET, "header_row": None,
                               "status": "No exchange-rate sheet resolved", "row_count": 0,
                               "column_count": 0, "exchange_rate_rows": 0, "index_sector_col": "",
                               "error": "", "resolution": "direct (v353)"}
    try:
        raw = _fx_read_sheet_v346(path, sheet_name=_FX_KNOWN_EXCHANGE_SHEET, header=None)
    except Exception as exc:
        # sheet not present / unreadable -> signal caller to fall back to the scan
        meta["error"] = f"direct read failed: {type(exc).__name__}: {exc}"
        return pd.DataFrame(), meta
    if not isinstance(raw, pd.DataFrame) or raw.empty:
        meta["error"] = "External Indices sheet empty/unavailable"
        return pd.DataFrame(), meta
    # locate the header row within this one sheet (>=2 header hints, incl. Index Sector)
    header_row = None
    for idx in range(min(len(raw), 80)):
        row_set = {_normalise_col_token(v) for v in raw.iloc[idx].tolist() if _cell_clean(v)}
        row_hits = sum(1 for hint in _HEADER_HINTS if _normalise_col_token(hint) in row_set)
        if row_hits >= 2:
            header_row = idx
            break
    if header_row is None:
        meta["error"] = "Header row not found on External Indices"
        return pd.DataFrame(), meta
    meta["header_row"] = int(header_row)
    return _fx_build_exchange_df_from_raw(raw, header_row, meta)


def _extract_exchange_rate_rows(path: str) -> Tuple[pd.DataFrame, Dict[str, object]]:
    # v353: try the DIRECT known-sheet read first; only fall back to the full
    # scan-all-sheets resolver if the known sheet is absent or yields no rates.
    try:
        direct_df, direct_meta = _extract_exchange_rate_rows_direct(path)
        if isinstance(direct_df, pd.DataFrame) and not direct_df.empty:
            return direct_df, direct_meta
    except Exception:
        pass
    selected_sheet, find_meta = _find_exchange_rate_sheet(path)
    meta: Dict[str, object] = {"sheet_used": selected_sheet, "header_row": find_meta.get("selected_header_row"), "status": "No exchange-rate sheet resolved", "row_count": 0, "column_count": 0, "exchange_rate_rows": 0, "index_sector_col": "", "error": "", "sheet_tests": find_meta.get("sheet_tests", []), "resolution": "scan fallback (v353)"}
    if not selected_sheet:
        meta["error"] = find_meta.get("error", "")
        return pd.DataFrame(), meta
    try:
        raw = _fx_read_sheet_v346(path, sheet_name=selected_sheet, header=None)
        header_row = meta.get("header_row")
        if header_row is None or int(header_row) >= len(raw):
            meta["error"] = "Header row unresolved"
            return pd.DataFrame(), meta
        header_row = int(header_row)
        headers = _header_names_from_row(raw.iloc[header_row])
        data = raw.iloc[header_row + 1:].copy().reset_index(drop=True)
        if data.empty:
            meta["error"] = "No data rows beneath detected header"
            return pd.DataFrame(), meta
        data.columns = headers
        data = data[~data.apply(lambda r: all(_cell_clean(v) == "" for v in r.tolist()), axis=1)].copy()
        meta["row_count"] = int(len(data))
        meta["column_count"] = int(len(data.columns))
        index_sector_col = ""
        for col in data.columns:
            if _normalise_col_token(col) in {"indexsector", "sector", "indexgroup", "group"}:
                index_sector_col = col
                break
        meta["index_sector_col"] = index_sector_col
        if not index_sector_col:
            meta["status"] = "Header resolved but Index Sector column not found"
            return pd.DataFrame(), meta
        sector_norm = data[index_sector_col].astype(str).map(_normalise_col_token)
        exchange_df = data[sector_norm == _EXCHANGE_SECTOR_VALUE].copy().reset_index(drop=True)
        keep_cols = [c for c in exchange_df.columns if not _normalise_col_token(c).startswith("column") or exchange_df[c].astype(str).str.strip().ne("").any()]
        if keep_cols:
            exchange_df = exchange_df[keep_cols].copy()
        meta["exchange_rate_rows"] = int(len(exchange_df))
        meta["status"] = "Exchange rates extracted" if not exchange_df.empty else "Exchange-rate sheet resolved but no Exchange Rates rows found"
        return exchange_df, meta
    except Exception as exc:
        meta["error"] = f"{type(exc).__name__}: {exc}"
        meta["status"] = "Exchange-rate extraction failed"
        return pd.DataFrame(), meta


def build_exchange_rate_summary(exchange_rate_df: Optional[pd.DataFrame], source_file: str = "", sheet_used: str = "") -> pd.DataFrame:
    rows: List[Dict[str, object]] = []
    df = exchange_rate_df if isinstance(exchange_rate_df, pd.DataFrame) else pd.DataFrame()
    rows.append({"Measure": "Status", "Value": "Exchange rates extracted" if not df.empty else "No exchange-rate rows available"})
    rows.append({"Measure": "Workbook", "Value": source_file or ""})
    rows.append({"Measure": "Sheet used", "Value": sheet_used or ""})
    rows.append({"Measure": "FX rows", "Value": int(len(df)) if not df.empty else 0})
    if not df.empty:
        if "Source" in df.columns:
            sources = sorted({str(v).strip() for v in df["Source"].astype(str).tolist() if str(v).strip()})
            rows.append({"Measure": "Sources", "Value": ", ".join(sources)})
        if "Code" in df.columns:
            rows.append({"Measure": "Currency code preview", "Value": ", ".join(df["Code"].astype(str).head(10).tolist())})
    return pd.DataFrame(rows)


def build_exchange_rate_comparison(exchange_rate_df: Optional[pd.DataFrame]) -> Tuple[pd.DataFrame, pd.DataFrame]:
    df = exchange_rate_df if isinstance(exchange_rate_df, pd.DataFrame) else pd.DataFrame()
    if df.empty:
        return pd.DataFrame(columns=["Measure", "Value"]), pd.DataFrame()
    code_col = None
    for col in df.columns:
        if _normalise_col_token(col) in {"code", "currency", "ccy"}:
            code_col = col
            break
    if not code_col:
        return pd.DataFrame([{"Measure": "Preferred currency codes found", "Value": 0}]), pd.DataFrame()
    detail = df[df[code_col].astype(str).str.upper().isin(_PREFERRED_COMPARE_CODES)].copy()
    summary = pd.DataFrame([
        {"Measure": "Preferred currency codes found", "Value": int(len(detail))},
        {"Measure": "Preferred currency code list", "Value": ", ".join(detail[code_col].astype(str).head(20).tolist())},
    ])
    return summary, detail


def prepare_exchange_rate_source(run_date: object, timing_callback=None) -> Dict[str, object]:
    """Prepare independent FX source bundle and optionally emit sub-timings."""
    def _emit(label: str, started_at: float, status: str = "Done") -> None:
        if timing_callback is None:
            return
        try:
            timing_callback(label, time.perf_counter() - started_at, status)
        except Exception:
            pass

    started = time.perf_counter()
    workbook, resolve_status, diagnostics = find_internal_securities_master_for_date(run_date, timing_callback=timing_callback)
    _emit("FX find: total workbook resolve", started, "Done" if workbook else resolve_status)

    inspect_started = time.perf_counter()
    workbook_info = _inspect_exchange_rate_workbook(workbook)
    exchange_df, extract_meta = _extract_exchange_rate_rows(workbook)
    _emit("FX workbook: open/detect/extract rows", inspect_started, extract_meta.get("status", "Done"))

    table_started = time.perf_counter()
    summary_df = build_exchange_rate_summary(exchange_df, source_file=workbook, sheet_used=str(extract_meta.get("sheet_used", "")))
    comparison_summary_df, comparison_detail_df = build_exchange_rate_comparison(exchange_df)
    _emit("FX diagnostics: build output tables", table_started, "Done")

    status = str(extract_meta.get("status", "")) or resolve_status
    diagnostics_df = pd.DataFrame(diagnostics + [{"Check": "Extraction status", "Result": status}, {"Check": "Helper patch", "Result": "v306.13.7.6c_helper_repair_active; v306.13.7.6c_hotfix3_unc_repr; v306.13.7.6c_hotfix1_unc_string"}])
    return {
        "status": status,
        "source_file": workbook,
        "workbook_file": workbook,
        "sheet_used": extract_meta.get("sheet_used", ""),
        "exchange_rate_df": exchange_df,
        "exchange_rates_df": exchange_df,
        "fx_df": exchange_df,
        "summary_df": summary_df,
        "comparison_summary_df": comparison_summary_df,
        "comparison_detail_df": comparison_detail_df,
        "diagnostics_df": diagnostics_df,
        "workbook_info": workbook_info,
        "extract_meta": extract_meta,
        "resolve_status": resolve_status,
    }


__all__ = [
    "configure_exchange_rates",
    "clear_fx_workbook_path_cache",
    "find_internal_securities_master_for_date",
    "prepare_exchange_rate_source",
    "probe_exchange_rate_filesystem",
    "build_exchange_rate_summary",
    "build_exchange_rate_comparison",
]


# ========================================================
# v306.13.7.6d FX discovery hotfix
# - Search only the UNC root variant (\\hq.local\Corp\...)
# - Within the expected day folder, search only an exact left-most child folder named "04 Externals"
# - Do not search suffix variants like "04 Externals - Day 3 Indexation"
# - Do not fall back to broad recursive day/month scans from the FX helper
# ========================================================

def _fx76d_unc_only_root(root_folder: str) -> str:
    root = str(root_folder or "").strip()
    if not root:
        return ""
    bs = chr(92)
    unc_prefix = bs + bs + "hq.local" + bs + "Corp" + bs
    if root.upper().startswith("G:" + bs):
        tail = root[3:].lstrip(bs)
        return unc_prefix + tail
    if root.lower().startswith(unc_prefix.lower()):
        return root
    return root




def _fx76d_is_exact_04_externals_name(name: str) -> bool:
    try:
        return re.match(r"^\s*04\s+externals\s*$", str(name or ""), flags=re.IGNORECASE) is not None
    except Exception:
        return False





FX_DISCOVERY_HOTFIX_VERSION = "v306.13.7.6d_unc_only_exact_04_externals"


# ========================================================
# v306.13.7.6e FX discovery hotfix
# - Search only the UNC root variant (\\hq.local\Corp\...)
# - Within the expected day folder, search only left-most folders whose name starts with "04 Externals"
# - Includes folders such as "04 Externals - Day 5 Indexation" and "04 Externals - Day 6 Indexation"
# - Does not match folders where "04 Externals" appears later in the name
# - Does not fall back to broad recursive day/month scans from the FX helper
# ========================================================

def _fx76e_unc_only_root(root_folder: str) -> str:
    root = str(root_folder or "").strip()
    if not root:
        return ""
    bs = chr(92)
    unc_prefix = bs + bs + "hq.local" + bs + "Corp" + bs
    if root.upper().startswith("G:" + bs):
        tail = root[3:].lstrip(bs)
        return unc_prefix + tail
    if root.lower().startswith(unc_prefix.lower()):
        return root
    return root


def _root_variants(root_folder: str) -> List[str]:
    root = _fx76e_unc_only_root(root_folder)
    return [root] if root else []


def _fx76e_is_leftmost_04_externals_name(name: str) -> bool:
    try:
        return re.match(r"^\s*04\s+externals\b", str(name or ""), flags=re.IGNORECASE) is not None
    except Exception:
        return False


def _preferred_search_roots(search_root: str) -> List[str]:
    """Return only left-most '04 Externals*' search roots.

    Matches:
    - 04 Externals
    - 04 Externals - Day 5 Indexation
    - 04 Externals - Day 6 Indexation

    Does not return broad search_root fallback.
    """
    if not _safe_isdir(search_root):
        return []
    try:
        if _fx76e_is_leftmost_04_externals_name(os.path.basename(search_root)):
            return [search_root]
    except Exception:
        pass
    matches: List[str] = []
    try:
        for name in sorted(os.listdir(search_root)):
            candidate = os.path.join(search_root, name)
            if _safe_isdir(candidate) and _fx76e_is_leftmost_04_externals_name(name):
                matches.append(candidate)
    except Exception:
        return []
    return matches


def _collect_candidates(search_root: str) -> Tuple[List[str], List[str]]:
    """Collect FX workbook candidates only under left-most '04 Externals*' folders."""
    candidates: List[str] = []
    benchmark_dirs: List[str] = []
    roots = _preferred_search_roots(search_root)
    if not roots:
        return candidates, benchmark_dirs
    seen_candidates = set()
    seen_benchmarks = set()
    for root_to_scan in roots:
        try:
            for root, _, files in os.walk(root_to_scan):
                if os.path.basename(root).strip().lower() == "benchmarks":
                    bkey = os.path.abspath(root).lower()
                    if bkey not in seen_benchmarks:
                        benchmark_dirs.append(root)
                        seen_benchmarks.add(bkey)
                for file_name in files:
                    lower_name = file_name.lower().strip()
                    if lower_name.startswith(_FILE_PREFIX) and lower_name.endswith(_VALID_EXTS):
                        path = os.path.join(root, file_name)
                        ckey = os.path.abspath(path).lower()
                        if ckey not in seen_candidates:
                            candidates.append(path)
                            seen_candidates.add(ckey)
        except Exception:
            pass
    return candidates, benchmark_dirs

FX_DISCOVERY_HOTFIX_VERSION = "v306.13.7.6e_unc_only_leftmost_04_externals"

