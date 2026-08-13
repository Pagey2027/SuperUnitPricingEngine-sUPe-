# -*- coding: utf-8 -*-
"""Pure column normalisation and resolution helpers extracted from the BNP Control App."""

from __future__ import annotations

import os
import re
import hashlib
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

_COL_INDEX_ATTR = "_normalized_col_index"
_NORM_COLS_ATTR = "_normalized_column_pairs"

# ============================================================
# v346: SHARED CACHED EXCEL READER (FX + Error Risk network reads)
# ------------------------------------------------------------
# The FX workbook (.xlsx) and Error Risk workbook (BP Impact Tool.xlsb) live on a G:/
# network share, one file per date. Parsing them over SMB (openpyxl / pyxlsb) is the
# dominant remaining cold-load cost. This shared reader:
#   * caches each parsed (path, sheet, header) result IN-PROCESS by file signature
#     (size, mtime), so repeat reads within a session are free; and
#   * PERSISTS each parsed sheet to a local PICKLE cache folder keyed by the same
#     signature (v351: pickle replaces Parquet), so re-opening a date already loaded
#     (even after an app restart) reads the pickle in milliseconds instead of
#     re-parsing the network workbook.
# Engine selection is fixed: pyxlsb for .xlsb, openpyxl for .xlsx (v351: the optional
# python-calamine fast engine was removed - no measurable gain here and it carried
# dtype-inference risk). Leaf module (no bnp imports) so both error_risk and
# exchange_rates can import it without any circular dependency.
# ============================================================
_EXCEL_MEM_CACHE: Dict[str, pd.DataFrame] = {}
_EXCEL_CACHE_DIR: Dict[str, str] = {"dir": ""}
_EXCEL_CACHE_STATS: Dict[str, int] = {"parses": 0, "mem_hits": 0, "pickle_hits": 0, "pickle_writes": 0}
_HEADER_UNSET = object()  # sentinel: caller did not specify header (use pandas default)


def set_excel_cache_dir(path: str) -> None:
    """Point the persisted (pickle) Excel cache at a local folder. Created if absent."""
    try:
        p = str(path or "").strip()
        if p:
            os.makedirs(p, exist_ok=True)
            _EXCEL_CACHE_DIR["dir"] = p
    except Exception:
        _EXCEL_CACHE_DIR["dir"] = ""


def set_excel_fast_engine(on: bool) -> None:
    """v351: calamine removed - this is now a harmless no-op kept only for backward
    compatibility with any external caller. The default engines (pyxlsb/.xlsb,
    openpyxl/.xlsx) are always used."""
    return None


def excel_cache_stats() -> Dict[str, int]:
    """Counts so the app can report reads saved: parses (network), mem_hits,
    pickle_hits, pickle_writes."""
    return dict(_EXCEL_CACHE_STATS)


def clear_excel_cache(drop_persisted: bool = False, **_legacy) -> None:
    """Clear the in-process Excel cache. If drop_persisted, also delete the on-disk
    pickle cache files (used on a forced source refresh). (**_legacy accepts the old
    drop_parquet kwarg harmlessly.)"""
    if not drop_persisted and _legacy.get("drop_parquet"):
        drop_persisted = True
    try:
        _EXCEL_MEM_CACHE.clear()
        for k in _EXCEL_CACHE_STATS:
            _EXCEL_CACHE_STATS[k] = 0
    except Exception:
        pass
    if drop_persisted:
        d = _EXCEL_CACHE_DIR.get("dir") or ""
        if d and os.path.isdir(d):
            try:
                for fn in os.listdir(d):
                    if fn.startswith("xlcache_") and fn.endswith(".pkl"):
                        try:
                            os.remove(os.path.join(d, fn))
                        except Exception:
                            pass
            except Exception:
                pass


def _excel_file_signature(resolved: str) -> Tuple[int, int]:
    try:
        stt = os.stat(resolved)
        return (int(stt.st_size), int(stt.st_mtime))
    except Exception:
        return (0, 0)


def _excel_cache_key(resolved: str, sheet_name: Any, header: Any, sig: Tuple[int, int]) -> str:
    # stable header token (the _HEADER_UNSET sentinel's repr varies per process, which
    # would break cross-restart Parquet hits - normalise it to a fixed string).
    if header is _HEADER_UNSET:
        htok = "unset"
    elif header is None:
        htok = "none"
    else:
        htok = str(header)
    raw = f"{resolved}|{sheet_name}|{htok}|{sig[0]}|{sig[1]}"
    return hashlib.md5(raw.encode("utf-8", "replace")).hexdigest()


def _excel_pickle_path(key: str) -> str:
    d = _EXCEL_CACHE_DIR.get("dir") or ""
    if not d:
        return ""
    return os.path.join(d, f"xlcache_{key}.pkl")


def _read_excel_engine(path: str, sheet_name: Any, header: Any) -> pd.DataFrame:
    """Do the actual parse: pyxlsb for .xlsb and openpyxl for .xlsx/.xlsm (v351: the
    calamine fast-engine path was removed - no measurable gain here and it carried
    dtype-inference risk). `header` may be an int, None (explicit no-header raw read -
    required by the FX detector), or the _HEADER_UNSET sentinel (omit -> pandas
    default header=0)."""
    suffix = os.path.splitext(str(path))[1].lower()
    engines: List[Optional[str]] = ["pyxlsb"] if suffix == ".xlsb" else ["openpyxl", None]
    last_err: Optional[Exception] = None
    for eng in engines:
        try:
            kwargs = {"sheet_name": sheet_name}
            if header is not _HEADER_UNSET:
                kwargs["header"] = header  # pass through int OR None explicitly
            if eng:
                return pd.read_excel(path, engine=eng, **kwargs)
            return pd.read_excel(path, **kwargs)
        except Exception as exc:
            last_err = exc
    raise last_err or RuntimeError("Unable to read workbook")


def read_excel_cached(path: str, sheet_name: Any = 0, header: Any = _HEADER_UNSET,
                      *, resolver=None) -> pd.DataFrame:
    """Cached Excel read (single source of truth for FX + Error Risk).

    Returns the parsed sheet as a DataFrame, reading the network workbook AT MOST ONCE
    per (file version, sheet, header): in-process cache first, then local Parquet, else
    parse the network file and populate both caches. `resolver`, if given, maps the raw
    path to a resolved path (e.g. G:/ <-> UNC). On any cache error it falls back to a
    direct parse so behaviour is never worse than before."""
    raw_path = str(path or "")
    resolved = raw_path
    try:
        if callable(resolver):
            r = resolver(raw_path)
            if r:
                resolved = str(r)
    except Exception:
        resolved = raw_path
    if not resolved or not os.path.exists(resolved):
        return _read_excel_engine(resolved or raw_path, sheet_name, header)

    sig = _excel_file_signature(resolved)
    key = _excel_cache_key(resolved, sheet_name, header, sig)

    # 1) in-process memory cache
    hit = _EXCEL_MEM_CACHE.get(key)
    if isinstance(hit, pd.DataFrame):
        _EXCEL_CACHE_STATS["mem_hits"] = _EXCEL_CACHE_STATS.get("mem_hits", 0) + 1
        return hit.copy()

    # 2) persisted pickle cache (v351: pickle replaces parquet)
    pk = _excel_pickle_path(key)
    if pk and os.path.exists(pk):
        try:
            df = pd.read_pickle(pk)
            if isinstance(df, pd.DataFrame):
                _EXCEL_MEM_CACHE[key] = df
                _EXCEL_CACHE_STATS["pickle_hits"] = _EXCEL_CACHE_STATS.get("pickle_hits", 0) + 1
                return df.copy()
        except Exception:
            pass  # corrupt/unavailable -> reparse

    # 3) parse the network workbook (the expensive path) and populate caches
    df = _read_excel_engine(resolved, sheet_name, header)
    _EXCEL_CACHE_STATS["parses"] = _EXCEL_CACHE_STATS.get("parses", 0) + 1
    try:
        _EXCEL_MEM_CACHE[key] = df
    except Exception:
        pass
    if pk:
        try:
            df.to_pickle(pk)
            _EXCEL_CACHE_STATS["pickle_writes"] = _EXCEL_CACHE_STATS.get("pickle_writes", 0) + 1
        except Exception:
            pass  # pickle optional; never fail the read on a cache-write error
    return df.copy()

COLUMN_ALIASES = {
    "portfolio_code": ["Portfolio code", "Portfolio", "portfolio"],
    "portfolio_name": ["Portfolio Name", "portfolio name", "name"],
    "trust_sector": ["Trust/Sector", "trust sector", "trust", "sector"],
    "portfolio_type": ["Portfolio Type", "portfoliotype"],
    "external_portfolio_reference": ["External portfolio reference", "external reference", "external portfolio"],
    "status": ["Status"],
    "comment": ["Comment", "Comments"],
    "benchmark_code_exact": [
        "benchmark code", "benchmarkcode",
        "benchmark id", "benchmarkid",
        "index code", "indexcode",
        "bmk code", "bmkcode",
    ],
    "benchmark_code_fallback": ["benchmark", "index", "bmk"],
    "fdv_current_value": [
        "FDV Valuation(Current Day)",
        "FDV Valuation Current Day",
        "FDVCurrentValuation",
        "FDVCurrentDayValuation",
        "FDV Valuation - Current Day",
        "Valuation(Current Day)",
        "Valuation Current Day",
    ],
    "asset_type_code": ["Asset Type Code", "AssetTypeCode", "Driver Code", "Asset Code"],
    "asset_type_desc": [
        "Asset Type Description", "AssetTypeDescription", "Asset Type Name", "AssetTypeName", "Asset Type",
    ],
    "fdv_prev": [
        "FDV Valuation Prev_Day",
        "FDV Valuation Prev Day",
        "FDV Valuation(Previous Day)",
        "FDV Valuation Previous Day",
        "Valuation Prev_Day",
        "Valuation Prev Day",
        "Valuation(Previous Day)",
        "Valuation Previous Day",
    ],
    "fdv_curr": [
        "FDV Valuation Curr_Day",
        "FDV Valuation Curr Day",
        "FDV Valuation(Current Day)",
        "FDV Valuation Current Day",
        "Valuation Curr_Day",
        "Valuation Curr Day",
        "Valuation(Current Day)",
        "Valuation Current Day",
    ],
    "cashflow": ["Cashflow", "Cash Flow", "FDV Cashflow"],
    "actual_vs_benchmark": ["Actual vs Benchmark", "actual vs benchmark", "variance"],
    "actual_return": ["Actual Return", "actual return"],
    "benchmark_return": ["Benchmark Return", "benchmark return"],
    "over_under": ["Over/Under", "over under", "overunder", "Original Over/Under", "Source Original Over/Under"],
    "tolerance": ["Tolerance", "tolerance"],
    "excess_contribution": ["Excess Contribution", "ExcessContribution", "Excess contribution"],
    "transactions": ["Transactions", "All Transactions", "Transaction Amount"],
    "control_break": ["Transaction-aware Control Break", "Control Break", "Original Over/Under", "Over/Under"],
}

def _normalise_col_token(x: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(x).strip().lower())
def _build_col_lookup(df: Optional[pd.DataFrame]) -> Tuple[Dict[str, List[str]], List[Tuple[str, str]]]:
    if df is None:
        return {}, []
    norm_map: Dict[str, List[str]] = {}
    norm_cols: List[Tuple[str, str]] = []
    for col in df.columns:
        norm_col = _normalise_col_token(col)
        norm_cols.append((col, norm_col))
        norm_map.setdefault(norm_col, []).append(col)
    return norm_map, norm_cols
def _get_col_lookup(df: Optional[pd.DataFrame]) -> Tuple[Dict[str, List[str]], List[Tuple[str, str]]]:
    if df is None:
        return {}, []
    attrs = getattr(df, "attrs", None)
    if isinstance(attrs, dict):
        norm_map = attrs.get(_COL_INDEX_ATTR)
        norm_cols = attrs.get(_NORM_COLS_ATTR)
        if isinstance(norm_map, dict) and isinstance(norm_cols, list):
            return norm_map, norm_cols
    norm_map, norm_cols = _build_col_lookup(df)
    if isinstance(attrs, dict):
        attrs[_COL_INDEX_ATTR] = norm_map
        attrs[_NORM_COLS_ATTR] = norm_cols
    return norm_map, norm_cols
def _prime_dataframe_col_index(df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    if df is None:
        return df
    _get_col_lookup(df)
    return df
def find_exact_normalized_col(df: Optional[pd.DataFrame], keywords: List[str]) -> Optional[str]:
    if df is None:
        return None
    norm_map, _ = _get_col_lookup(df)
    for key in keywords:
        norm_key = _normalise_col_token(key)
        matches = norm_map.get(norm_key, [])
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            return None
    return None
def find_col(df: Optional[pd.DataFrame], keywords: List[str]) -> Optional[str]:
    """Match columns using normalised tokens and keyword-first priority.

    This makes CamelCase / snake_case / spaced headings resolve consistently and
    prevents a broad keyword (for example 'benchmark') from winning ahead of a
    more specific target like 'benchmark code'.
    """
    if df is None:
        return None
    _, norm_cols = _get_col_lookup(df)
    norm_keys = [_normalise_col_token(k) for k in keywords if str(k).strip()]

    for key in norm_keys:
        for col, norm_col in norm_cols:
            if norm_col == key:
                return col

    for key in norm_keys:
        for col, norm_col in norm_cols:
            if norm_col.startswith(key):
                return col

    for key in norm_keys:
        for col, norm_col in norm_cols:
            if key and key in norm_col:
                return col
    return None
def resolve_col(
    df: Optional[pd.DataFrame],
    exact_aliases: List[str],
    fallback_aliases: Optional[List[str]] = None,
) -> Optional[str]:
    if df is None:
        return None
    fallback_aliases = fallback_aliases or exact_aliases
    return find_exact_normalized_col(df, exact_aliases) or find_col(df, fallback_aliases)
def resolve_driver_label_col(df: Optional[pd.DataFrame]) -> Optional[str]:
    if df is None:
        return None
    return (
        find_col(df, [
            "asset type name", "assettypename",
            "asset type description", "assettypedescription",
            "asset type desc", "assettypedesc",
            "asset group name", "assetgroupname",
            "asset driver name", "assetdrivername",
            "asset type label", "assettypelabel",
            "asset type"
        ]) or
        find_col(df, ["asset group", "driver"]) or
        find_col(df, ["asset type code", "assettypecode", "asset code", "driver code"])
    )
def normalise_join_key_series(s: pd.Series) -> pd.Series:
    return s.astype(str).str.strip().str.upper().str.replace(r"\s+", "", regex=True)
def resolve_benchmark_code_col(df: Optional[pd.DataFrame]) -> Optional[str]:
    if df is None:
        return None
    return resolve_col(
        df,
        COLUMN_ALIASES["benchmark_code_exact"],
        COLUMN_ALIASES["benchmark_code_fallback"],
    )
def resolve_fdv_current_value_col(df: Optional[pd.DataFrame]) -> Optional[str]:
    if df is None:
        return None
    return resolve_col(df, COLUMN_ALIASES["fdv_current_value"])


__all__ = [
    "COLUMN_ALIASES",
    "_normalise_col_token",
    "_prime_dataframe_col_index",
    "find_exact_normalized_col",
    "find_col",
    "resolve_col",
    "resolve_driver_label_col",
    "normalise_join_key_series",
    "resolve_benchmark_code_col",
    "resolve_fdv_current_value_col",
]
from typing import Optional


# ===== merged from bnp_helpers_formatting =====
def _percent_string_1dp(value: object) -> str:
    num = pd.to_numeric(value, errors='coerce')
    if pd.isna(num):
        return ""
    return f"{float(num):.2%}"

def _percent_string_2dp(value):
    v = pd.to_numeric(value, errors="coerce")
    if pd.isna(v):
        return ""
    return f"{float(v) * 100:.2f}%"

def _excel_currency_string(value: object) -> str:
    num = pd.to_numeric(value, errors='coerce')
    if pd.isna(num):
        return ""
    num = float(num)
    if num < 0:
        return f"(${abs(num):,.2f})"
    return f"${num:,.2f}"

def _decimal_string(value: object, dp: int = 2) -> str:
    num = pd.to_numeric(value, errors='coerce')
    if pd.isna(num):
        return ""
    return f"{float(num):,.{dp}f}"

def _date_string_yyyy_mm_dd(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    s = str(value).strip()
    if s == "":
        return ""
    try:
        dt = pd.to_datetime(value, errors="coerce")
        if pd.isna(dt):
            return s
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return s

def _clean_mojibake_text(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    s = str(value)
    replacements = {
        "–": "–",
        "â€“": "–",
        "â€”": "—",
        "â€˜": "‘",
        "â€™": "’",
        "â€œ": "“",
        "â€": "”",
    }
    for bad, good in replacements.items():
        s = s.replace(bad, good)
    return s

# ===== merged from bnp_helpers_numeric =====
def _coerce_numeric_like(series: pd.Series) -> pd.Series:
    """Coerce numeric-like text safely, including percentage strings.

    Handles values such as ``-5.9716%``, ``1,234.56`` and ``(123.45)``.
    The percent sign is stripped but the numeric magnitude is preserved, so a
    value like ``-5.9716%`` becomes ``-5.9716`` and can still be scaled by the
    caller as required.
    """
    if series is None:
        return pd.Series(dtype='float64')
    s = series.astype(str).str.strip()
    s = s.str.replace(',', '', regex=False)
    s = s.str.replace('%', '', regex=False)
    s = s.str.replace('$', '', regex=False)
    s = s.str.replace(r'^\((.*)\)$', r'-\1', regex=True)
    s = s.replace({'': pd.NA, 'nan': pd.NA, 'None': pd.NA, '<NA>': pd.NA, 'N/A': pd.NA})
    return pd.to_numeric(s, errors='coerce')

def num(df, col):
    """Safely coerce a DataFrame column or Series to numeric.

    If ``col`` is None or missing from ``df`` a zero-filled Series aligned to
    ``df.index`` is returned.
    """
    if df is None:
        return pd.Series(dtype='float64')
    if isinstance(col, pd.Series):
        return _coerce_numeric_like(col).fillna(0.0)
    if col is None or col not in getattr(df, 'columns', []):
        return pd.Series([0.0] * len(df), index=df.index, dtype='float64')
    return _coerce_numeric_like(df[col]).fillna(0.0)

def _coerce_mixed_object_series_to_string(s: pd.Series) -> pd.Series:
    if s is None:
        return s
    if str(getattr(s, "dtype", "")) != "object":
        return s
    non_null = s.dropna()
    if non_null.empty:
        return s.astype("string")
    type_names = {type(v).__name__ for v in non_null.tolist()}
    if len(type_names) <= 1:
        return s
    return s.map(lambda v: "" if pd.isna(v) else str(v)).astype("string")

def make_arrow_safe(df: Optional[pd.DataFrame]) -> pd.DataFrame:
    if df is None:
        return pd.DataFrame()
    out = df.copy()
    for col in out.columns:
        try:
            out[col] = _coerce_mixed_object_series_to_string(out[col])
        except Exception:
            out[col] = out[col].map(lambda v: "" if pd.isna(v) else str(v)).astype("string")
    return out
