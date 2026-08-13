# -*- coding: utf-8 -*-
"""Static Data workbook helpers for BNP Control App / ARC replacement.

Purpose
-------
Loads a workbook named "Static Data.xlsx" from the same folder as the app/helper
files, validates the expected configuration sheets, and exposes small helpers
for paths, thresholds, source report config and BNP ingestion config.

This module intentionally contains no Streamlit code.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

import pandas as pd

STATIC_DATA_FILENAME = "Static Data.xlsx"
# v356 FIX (false-alarm "Static Data workbook - Error"): source_file_keywords,
# excluded_filename_tokens and header_contracts were intentionally moved into code in
# v307 (see this module's SOURCE_FILE_KEYWORDS / EXCLUDED_FILENAME_TOKENS /
# HEADER_CONTRACTS constants below, and the workbook's own read_me sheet). The BNP
# ingestion path uses those code constants, NOT the workbook sheets. But the validator
# still LISTED them as required, so their (correct) absence flagged the whole workbook
# as "Error" and set RunValidationState degraded. They are removed from the required
# set here - no data is missing; this only stops the stale required-sheet check firing.
# Retained for reference so it is obvious they are code-owned, not lost:
CODE_OWNED_SHEETS = ["source_file_keywords", "excluded_filename_tokens", "header_contracts"]
REQUIRED_SHEETS = [
    "paths",
    "date_folder_rules",
    "folder_month_aliases",
    "source_reports",
    "thresholds",
]

REQUIRED_COLUMNS = {
    "paths": ["ConfigKey", "ConfigValue", "Active"],
    "date_folder_rules": ["RuleName", "RootConfigKey", "Level1Format", "Level2Format", "Active"],
    "folder_month_aliases": ["MonthNumber", "Alias", "Active"],
    "source_reports": ["ReportKey", "SourceGroup", "RootConfigKey", "DateFolderRule", "FileName", "Required", "Active"],
    "thresholds": ["ThresholdKey", "ThresholdValue", "Active"],
}

TRUE_VALUES = {"y", "yes", "true", "1", "active"}
FALSE_VALUES = {"n", "no", "false", "0", "inactive"}


def _normalise_token(value: object) -> str:
    """Normalise text for comparisons while preserving business values elsewhere."""
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _active_series(df: pd.DataFrame) -> pd.Series:
    if df is None or df.empty or "Active" not in df.columns:
        return pd.Series([True] * (0 if df is None else len(df)), index=(df.index if isinstance(df, pd.DataFrame) else None))
    return df["Active"].astype(str).str.strip().str.lower().isin(TRUE_VALUES)


def _clean_df(df: pd.DataFrame) -> pd.DataFrame:
    if df is None:
        return pd.DataFrame()
    out = df.copy()
    out = out.dropna(how="all")
    out.columns = [str(c).strip() for c in out.columns]
    # Drop fully blank columns that pandas might name Unnamed: x
    blank_cols = []
    for c in out.columns:
        if str(c).lower().startswith("unnamed") and out[c].isna().all():
            blank_cols.append(c)
    if blank_cols:
        out = out.drop(columns=blank_cols)
    for c in out.columns:
        if out[c].dtype == object:
            out[c] = out[c].map(lambda x: "" if pd.isna(x) else str(x).strip())
    return out.reset_index(drop=True)


def _module_dir(app_file_path: Optional[str] = None) -> Path:
    # v373: STATIC_DATA_DIR environment variable override. Checked FIRST so
    # Static Data.xlsx can live in a separate /config folder from the .py
    # files (which may move into /python) without any other code change.
    # Falls back to the ORIGINAL behaviour (app_file_path, then __file__,
    # then cwd) if the variable is unset or does not point at a real,
    # existing directory - so this is a no-op until Launch_Latest.bat
    # actually sets it.
    override = os.environ.get("STATIC_DATA_DIR", "").strip()
    if override:
        try:
            candidate = Path(override).resolve()
            if candidate.exists() and candidate.is_dir():
                return candidate
        except Exception:
            pass
    if app_file_path:
        try:
            return Path(app_file_path).resolve().parent
        except Exception:
            pass
    try:
        return Path(__file__).resolve().parent
    except Exception:
        return Path.cwd()


def find_static_data_workbook(app_file_path: Optional[str] = None, filename: str = STATIC_DATA_FILENAME) -> str:
    """Return the expected Static Data workbook path next to the app/helper files."""
    return str(_module_dir(app_file_path) / filename)


def load_static_data(path: Optional[str] = None, app_file_path: Optional[str] = None) -> Dict[str, object]:
    """Load and validate the Static Data workbook.

    Returns a bundle with one dataframe per configured sheet plus standard
    metadata, validation and exception dataframes.
    """
    static_file = str(path or find_static_data_workbook(app_file_path))
    meta_rows: List[Dict[str, object]] = []
    validation_rows: List[Dict[str, object]] = []
    exception_rows: List[Dict[str, object]] = []
    tables: Dict[str, pd.DataFrame] = {}

    if not os.path.exists(static_file):
        exception_rows.append({"Severity": "Error", "Check": "StaticDataWorkbook", "Detail": f"File not found: {static_file}"})
        return {
            "static_file": static_file,
            "tables": tables,
            "static_meta_df": pd.DataFrame(meta_rows),
            "static_validation_df": pd.DataFrame(validation_rows),
            "static_exception_df": pd.DataFrame(exception_rows),
        }

    try:
        xl = pd.ExcelFile(static_file, engine="openpyxl")
        sheet_names = list(xl.sheet_names)
    except Exception as exc:
        exception_rows.append({"Severity": "Error", "Check": "StaticDataWorkbookOpen", "Detail": f"{type(exc).__name__}: {exc}"})
        return {
            "static_file": static_file,
            "tables": tables,
            "static_meta_df": pd.DataFrame(meta_rows),
            "static_validation_df": pd.DataFrame(validation_rows),
            "static_exception_df": pd.DataFrame(exception_rows),
        }

    for sheet in REQUIRED_SHEETS:
        exists = sheet in sheet_names
        validation_rows.append({"Sheet": sheet, "Check": "SheetExists", "Status": "PASS" if exists else "FAIL", "Detail": "" if exists else "Missing required sheet"})
        if not exists:
            exception_rows.append({"Severity": "Error", "Check": "MissingSheet", "Detail": sheet})
            continue
        try:
            df = _clean_df(pd.read_excel(static_file, sheet_name=sheet, engine="openpyxl"))
            tables[sheet] = df
            meta_rows.append({
                "Sheet": sheet,
                "Loaded": True,
                "Rows": int(len(df)),
                "Columns": int(len(df.columns)),
                "ColumnsList": " | ".join(map(str, df.columns)),
                "Error": "",
            })
            required_cols = REQUIRED_COLUMNS.get(sheet, [])
            missing_cols = [c for c in required_cols if c not in df.columns]
            validation_rows.append({
                "Sheet": sheet,
                "Check": "RequiredColumns",
                "Status": "PASS" if not missing_cols else "FAIL",
                "Detail": "" if not missing_cols else "Missing: " + ", ".join(missing_cols),
            })
            if missing_cols:
                exception_rows.append({"Severity": "Error", "Check": "MissingColumns", "Detail": f"{sheet}: {', '.join(missing_cols)}"})
            if "Active" in df.columns:
                active_count = int(_active_series(df).sum())
                validation_rows.append({"Sheet": sheet, "Check": "ActiveRows", "Status": "INFO", "Detail": str(active_count)})
        except Exception as exc:
            meta_rows.append({"Sheet": sheet, "Loaded": False, "Rows": 0, "Columns": 0, "ColumnsList": "", "Error": f"{type(exc).__name__}: {exc}"})
            exception_rows.append({"Severity": "Error", "Check": "LoadSheet", "Detail": f"{sheet}: {type(exc).__name__}: {exc}"})

    # Business-key checks
    for sheet, key_col in [("paths", "ConfigKey"), ("date_folder_rules", "RuleName"), ("source_reports", "ReportKey"), ("thresholds", "ThresholdKey")]:
        df = tables.get(sheet, pd.DataFrame())
        if not df.empty and key_col in df.columns:
            active = df.loc[_active_series(df)].copy()
            dupes = active[active[key_col].astype(str).str.strip().duplicated(keep=False)]
            validation_rows.append({
                "Sheet": sheet,
                "Check": f"UniqueActive{key_col}",
                "Status": "PASS" if dupes.empty else "FAIL",
                "Detail": "" if dupes.empty else "Duplicates: " + ", ".join(sorted(set(dupes[key_col].astype(str))))
            })
            if not dupes.empty:
                exception_rows.append({"Severity": "Error", "Check": "DuplicateActiveKey", "Detail": f"{sheet}.{key_col}: {', '.join(sorted(set(dupes[key_col].astype(str))))}"})

    bundle = {
        "static_file": static_file,
        "tables": tables,
        "static_meta_df": pd.DataFrame(meta_rows),
        "static_validation_df": pd.DataFrame(validation_rows),
        "static_exception_df": pd.DataFrame(exception_rows),
    }
    # Convenience top-level aliases
    for k, v in tables.items():
        bundle[k] = v
    return bundle


def get_active_table(static_bundle: Dict[str, object], sheet_name: str) -> pd.DataFrame:
    tables = static_bundle.get("tables", {}) if isinstance(static_bundle, dict) else {}
    df = tables.get(sheet_name, pd.DataFrame()) if isinstance(tables, dict) else pd.DataFrame()
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame()
    if "Active" in df.columns:
        return df.loc[_active_series(df)].copy().reset_index(drop=True)
    return df.copy().reset_index(drop=True)


def get_config_value(static_bundle: Dict[str, object], key: str, default: Any = None) -> Any:
    paths = get_active_table(static_bundle, "paths")
    if paths.empty or "ConfigKey" not in paths.columns or "ConfigValue" not in paths.columns:
        return default
    key_norm = _normalise_token(key)
    m = paths.loc[paths["ConfigKey"].map(_normalise_token).eq(key_norm)]
    if m.empty:
        return default
    val = m.iloc[0].get("ConfigValue", default)
    return default if pd.isna(val) or str(val).strip() == "" else val


def get_threshold_value(static_bundle: Dict[str, object], key: str, default: Any = None) -> Any:
    thresholds = get_active_table(static_bundle, "thresholds")
    if thresholds.empty or "ThresholdKey" not in thresholds.columns or "ThresholdValue" not in thresholds.columns:
        return default
    key_norm = _normalise_token(key)
    m = thresholds.loc[thresholds["ThresholdKey"].map(_normalise_token).eq(key_norm)]
    if m.empty:
        return default
    val = m.iloc[0].get("ThresholdValue", default)
    return default if pd.isna(val) or str(val).strip() == "" else val


def build_ingestion_config(static_bundle: Dict[str, object], source_group: str = "BNP") -> Dict[str, object]:
    """Build arguments compatible with bnp_helpers_ingestion.configure_ingestion."""
    group_norm = _normalise_token(source_group)

    keywords = get_active_table(static_bundle, "source_file_keywords")
    if not keywords.empty and "SourceGroup" in keywords.columns:
        keywords = keywords.loc[keywords["SourceGroup"].map(_normalise_token).eq(group_norm)].copy()
    required = []
    optional = []
    for _, r in keywords.iterrows():
        kw = str(r.get("Keyword", "")).strip()
        if not kw:
            continue
        is_required = str(r.get("Required", "")).strip().lower() in TRUE_VALUES
        (required if is_required else optional).append(kw)

    excluded = get_active_table(static_bundle, "excluded_filename_tokens")
    if not excluded.empty and "SourceGroup" in excluded.columns:
        excluded = excluded.loc[excluded["SourceGroup"].map(_normalise_token).eq(group_norm)].copy()
    excluded_tokens = [str(v).strip() for v in excluded.get("Token", pd.Series(dtype="object")).tolist() if str(v).strip()]

    hc = get_active_table(static_bundle, "header_contracts")
    if not hc.empty and "SourceGroup" in hc.columns:
        hc = hc.loc[hc["SourceGroup"].map(_normalise_token).eq(group_norm)].copy()
    header_contracts: Dict[str, Dict[str, object]] = {}
    if not hc.empty:
        for keyword, g in hc.groupby("Keyword", dropna=False):
            groups = []
            try:
                sorted_groups = sorted(pd.to_numeric(g["RequiredGroupNo"], errors="coerce").dropna().astype(int).unique().tolist())
            except Exception:
                sorted_groups = []
            for group_no in sorted_groups:
                vals = g.loc[pd.to_numeric(g["RequiredGroupNo"], errors="coerce").eq(group_no), "AcceptedColumnName"].astype(str).str.strip()
                groups.append([v for v in vals.tolist() if v])
            if groups:
                header_contracts[str(keyword).strip()] = {"required_groups": groups}

    return {
        "header_contracts": header_contracts,
        "excluded_filename_tokens": excluded_tokens,
        "required_file_keywords": required,
        "optional_file_keywords": optional,
    }




# ===================================================================
# v315/v322 - BM Mapping reader (benchmark names by Portfolio code/Hiport)
# Data lives in this workbook's 'bm_mapping' sheet. Display/reference-data only.
# ===================================================================
BM_MAPPING_CHECK_LABEL = "Check BM Mapping"


def _bm_norm_key(v) -> str:
    return "".join(ch for ch in str(v or "").upper().strip() if ch.isalnum())


def build_bm_lookup(static_bundle: Dict[str, object]) -> Dict[str, Dict[str, str]]:
    """Return {hiport_norm: {'name':..., 'code':...}} from the bm_mapping sheet."""
    df = get_active_table(static_bundle, "bm_mapping")
    out: Dict[str, Dict[str, str]] = {}
    if not isinstance(df, pd.DataFrame) or df.empty:
        return out
    cols = {str(c).strip().lower(): c for c in df.columns}
    pc = cols.get("portfolio code") or cols.get("portfoliocode")
    nm = cols.get("benchmark name")
    cd = cols.get("benchmark code")
    if not pc:
        return out
    for _, r in df.iterrows():
        k = _bm_norm_key(r[pc])
        if k:
            out.setdefault(k, {"name": str(r[nm]).strip() if nm else "",
                               "code": str(r[cd]).strip() if cd else ""})
    return out


def attach_benchmark_name(portfolio_df: pd.DataFrame, static_bundle: Dict[str, object],
                          *, portfolio_code_col: str = "Portfolio code") -> pd.DataFrame:
    """Add 'Benchmark Name' (+ 'Benchmark Name Code') to portfolio_df, keyed on
    Portfolio code (Hiport). Where a Hiport is not in the mapping the name is set
    to 'Check BM Mapping'. Display/reference-data only - no calculation column is
    changed. Safe no-op if the sheet is absent."""
    if not isinstance(portfolio_df, pd.DataFrame) or portfolio_df.empty or portfolio_code_col not in portfolio_df.columns:
        return portfolio_df
    lookup = build_bm_lookup(static_bundle)
    if not lookup:
        return portfolio_df
    df = portfolio_df.copy()
    keys = df[portfolio_code_col].map(_bm_norm_key)
    df["Benchmark Name"] = keys.map(lambda k: lookup.get(k, {}).get("name", "") or BM_MAPPING_CHECK_LABEL)
    df["Benchmark Name Code"] = keys.map(lambda k: lookup.get(k, {}).get("code", ""))
    return df


def build_bm_quality_flags(portfolio_df: pd.DataFrame) -> pd.DataFrame:
    """Rows whose Benchmark Name resolved to 'Check BM Mapping' (data-quality)."""
    if not isinstance(portfolio_df, pd.DataFrame) or portfolio_df.empty or "Benchmark Name" not in portfolio_df.columns:
        return pd.DataFrame()
    bad = portfolio_df[portfolio_df["Benchmark Name"].astype(str).str.strip() == BM_MAPPING_CHECK_LABEL]
    keep = [c for c in ["Portfolio code", "External portfolio reference", "Portfolio Name", "Benchmark Name"] if c in bad.columns]
    return bad[keep].copy() if not bad.empty else pd.DataFrame()


# ===================================================================
# v326 - Excluded-from-BNP-reports population filter reader
# Reads the 'excluded_from_bnp_reports' sheet (added v325) and returns the
# PortfolioCodes to drop from the BNP report population. Config-driven, so the
# exclusion list changes WITHOUT a code deploy. Display/reference-data only here;
# the app applies the list at bundle-prep (A2).
# ===================================================================

EXCLUDED_BNP_REPORTS_SHEET = "excluded_from_bnp_reports"


def _norm_portfolio_code(v) -> str:
    "Normalise a Portfolio code for matching (uppercase, alphanumerics only)."
    return "".join(ch for ch in str(v or "").upper().strip() if ch.isalnum())


def load_excluded_bnp_report_codes(static_bundle: Dict[str, object],
                                   *, active_only: bool = True) -> Dict[str, object]:
    """Return the BNP-report exclusion set from Static Data.

    Reads the 'excluded_from_bnp_reports' sheet and returns a dict:
        {
          "codes":      ["M2STT2", "M2STT4", "M7MLCH"],   # as written
          "codes_norm": {"M2STT2", "M2STT4", "M7MLCH"},   # normalised for joins
          "evidence_df": <the source rows, Active-filtered>,
          "status": "OK" | "No sheet" | "Empty",
        }
    Safe: returns an empty set (never raises) if the sheet is absent/empty, so a
    missing sheet simply means 'exclude nothing' rather than breaking the load.
    """
    empty = {"codes": [], "codes_norm": set(), "evidence_df": pd.DataFrame(), "status": "No sheet"}
    # Active-aware read; get_active_table already filters Active='Y' when present.
    df = get_active_table(static_bundle, EXCLUDED_BNP_REPORTS_SHEET) if active_only else None
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        # fall back to the raw table (e.g. a sheet with no Active column)
        tables = static_bundle.get("tables", {}) if isinstance(static_bundle, dict) else {}
        df = tables.get(EXCLUDED_BNP_REPORTS_SHEET, pd.DataFrame()) if isinstance(tables, dict) else pd.DataFrame()
    if not isinstance(df, pd.DataFrame) or df.empty:
        # load_static_data only materialises the REQUIRED_SHEETS, so this
        # config-only sheet may not be in the bundle. Read it DIRECTLY from the
        # workbook file recorded on the bundle (self-sufficient; no dependency on
        # the loader's sheet list).
        static_file = str(static_bundle.get("static_file", "")) if isinstance(static_bundle, dict) else ""
        if not static_file:
            try:
                static_file = find_static_data_workbook()
            except Exception:
                static_file = ""
        if static_file and os.path.exists(static_file):
            try:
                raw = pd.read_excel(static_file, sheet_name=EXCLUDED_BNP_REPORTS_SHEET, engine="openpyxl")
                df = _clean_df(raw)
                if active_only and isinstance(df, pd.DataFrame) and "Active" in df.columns:
                    df = df.loc[_active_series(df)].copy().reset_index(drop=True)
            except Exception:
                df = pd.DataFrame()
        if not isinstance(df, pd.DataFrame) or df.empty:
            return empty
    cols = {str(c).strip().lower(): c for c in df.columns}
    code_col = cols.get("portfoliocode") or cols.get("portfolio code") or cols.get("portfolio")
    if not code_col:
        return {"codes": [], "codes_norm": set(), "evidence_df": df.copy(), "status": "No PortfolioCode column"}
    codes = [str(v).strip() for v in df[code_col].tolist() if str(v).strip()]
    # de-dup, preserve order
    seen, ordered = set(), []
    for c in codes:
        k = _norm_portfolio_code(c)
        if k and k not in seen:
            seen.add(k)
            ordered.append(c)
    return {
        "codes": ordered,
        "codes_norm": {_norm_portfolio_code(c) for c in ordered},
        "evidence_df": df.copy(),
        "status": "OK" if ordered else "Empty",
    }


__all__ = [
    "build_bm_lookup", "attach_benchmark_name", "build_bm_quality_flags",
    "load_excluded_bnp_report_codes", "EXCLUDED_BNP_REPORTS_SHEET",
    "STATIC_DATA_FILENAME",
    "find_static_data_workbook",
    "load_static_data",
    "get_active_table",
    "get_config_value",
    "get_threshold_value",
    "build_ingestion_config",
]



# ===== restored module constants (annotated assignments dropped in a merge) =====
_CANONICAL_MONTHS = [
    (1, "Jan", "January"), (2, "Feb", "February"), (3, "Mar", "March"),
    (4, "Apr", "April"), (5, "May", "May"), (6, "Jun", "June"),
    (7, "Jul", "July"), (8, "Aug", "August"), (9, "Sep", "September"),
    (10, "Oct", "October"), (11, "Nov", "November"), (12, "Dec", "December"),
]

DATE_FOLDER_RULES = {
    "tableau_month_day": {"root_config_key": "tableau_root", "level1_format": "%b %Y",
        "level2_format": "%d %b", "preferred_match_mode": "exact_then_alias",
        "fallback_match_mode": "scan_children_by_date", "example_path": r"Jul 2026\15 Jul"},
    "bnp_year_month_day": {"root_config_key": "bnp_reports_root", "level1_format": "%Y\\%m %b",
        "level2_format": "%d %b", "preferred_match_mode": "exact_then_alias",
        "fallback_match_mode": "scan_children_by_date", "example_path": r"2026\07 Jul\15 Jul"},
}

SOURCE_FILE_KEYWORDS = [
    {"source_group": "BNP", "keyword": "DDetailedReturn", "alias": "dd", "required": True},
    {"source_group": "BNP", "keyword": "DAssetTypeReturn", "alias": "dat", "required": False},
    {"source_group": "BNP", "keyword": "DAssetReturn", "alias": "dar", "required": False},
    {"source_group": "BNP", "keyword": "TransactionListing", "alias": "txn", "required": False},
    {"source_group": "BNP", "keyword": "BenchmarkStatic", "alias": "bmk", "required": False},
]

EXCLUDED_FILENAME_TOKENS = [
    {"source_group": "BNP", "token": "unverified"},
]

HEADER_CONTRACTS = [
    {"source_group": "BNP", "keyword": "DDetailedReturn", "group_no": 1,
     "accepted": ["portfolio code", "portfoliocode", "portfolio"]},
    {"source_group": "BNP", "keyword": "DAssetTypeReturn", "group_no": 1,
     "accepted": ["portfolio code", "portfoliocode"]},
    {"source_group": "BNP", "keyword": "DAssetTypeReturn", "group_no": 2,
     "accepted": ["asset type", "assettypename"]},
    {"source_group": "BNP", "keyword": "BenchmarkStatic", "group_no": 1, "accepted": ["portfolio code"]},
    {"source_group": "BNP", "keyword": "BenchmarkStatic", "group_no": 2, "accepted": ["benchmark code", "benchmark"]},
]


def _build_month_aliases_restore():
    out = {}
    def add(alias, num, short):
        out[alias.strip().lower()] = (num, short)
    for num, short, long in _CANONICAL_MONTHS:
        for v in {short, long, short.upper(), long.upper(), short + ".", long + ".",
                  f"{num:02d} {short}", f"{num:02d} {long}", f"{num} {short}", f"{num} {long}"}:
            add(v, num, short)
    return out

MONTH_ALIASES = _build_month_aliases_restore()

DEFAULT_FILTERS = {
    "valuation t": {
        "INCLUDE": {"GLGroupName": ["AUD UNLISTED TRUSTS", "AUD UNLISTED EQUITY",
                                     "UNLIST INTL EQUITIES", "UNLIST INTL TRUST"]},
        "EXCLUDE": {"PortfolioCode": ["M2STT2", "M2STT4"]},
    },
    "gav check": {"INCLUDE": {"Check": ["Check"]}},
    "advisor return check": {
        "EXCLUDE": {"Class": ["Currency Overlay", "Derivative Overlay", "Treasury"]},
        "INCLUDE": {"Tolerance Check": ["OUT"]},
    },
    "unison fails sf": {"EXCLUDE": {"Element": ["2A", "4A", "2D", "4D", "2M", "4M", "2S", "4S"]}},
}
# ===== end restored constants =====


# ===== merged from bnp_static_data_code_contracts =====
CODE_CONTRACTS_VERSION = "v307"

# v363: removed the duplicate _build_month_aliases() builder that was merged in from
# bnp_static_data_code_contracts - it built the exact same alias table as
# _build_month_aliases_restore() above (which is the one actually assigned to
# MONTH_ALIASES / used by resolve_month()) and was never called anywhere in the
# codebase. Confirmed no references before removal.

def resolve_month(token: str) -> Tuple[int, str]:
    key = str(token).strip().lower()
    if key not in MONTH_ALIASES:
        raise KeyError(f"Unknown month folder token: {token!r}")
    return MONTH_ALIASES[key]

def get_date_folder_rule(rule_name: str) -> Dict[str, str]:
    if rule_name not in DATE_FOLDER_RULES:
        raise KeyError(f"Unknown date folder rule: {rule_name!r}")
    return dict(DATE_FOLDER_RULES[rule_name])

def bnp_required_keywords() -> List[str]:
    return [r["keyword"] for r in SOURCE_FILE_KEYWORDS if r["required"]]

def bnp_keyword_alias_map() -> Dict[str, str]:
    return {r["keyword"]: r["alias"] for r in SOURCE_FILE_KEYWORDS}

def excluded_tokens(source_group: str = "BNP") -> List[str]:
    return [r["token"].lower() for r in EXCLUDED_FILENAME_TOKENS if r["source_group"] == source_group]

def is_excluded_filename(filename: str, source_group: str = "BNP") -> bool:
    name = str(filename).lower()
    return any(tok in name for tok in excluded_tokens(source_group))

def header_contract_for(keyword: str) -> Dict[int, List[str]]:
    out: Dict[int, List[str]] = {}
    for row in HEADER_CONTRACTS:
        if row["keyword"] == keyword:
            out.setdefault(int(row["group_no"]), []).extend([c.lower() for c in row["accepted"]])
    return out

def validate_headers(keyword: str, incoming_columns: List[str]) -> Tuple[bool, List[int]]:
    contract = header_contract_for(keyword)
    incoming = {str(c).strip().lower() for c in incoming_columns}
    missing = [gno for gno, accepted in contract.items() if not (incoming & set(accepted))]
    return (len(missing) == 0, sorted(missing))

# ===== merged from bnp_helpers_mapping_filters =====
MAPPING_FILTERS_VERSION = "v316"

# v326 FIX: the merged mapping_filters section referenced `_get_active_table`,
# which was never aliased -> NameError, so load_mapping_filters silently fell back
# to DEFAULT_FILTERS instead of the workbook. Alias it to the real accessor so the
# Advisor Return Check EXCLUDE Class list (and UUT population filters) are truly
# config-driven from Static Data 'mapping_filters'.
_get_active_table = get_active_table


def _load_table(static_bundle: Dict[str, object]) -> pd.DataFrame:
    df = pd.DataFrame()
    if static_bundle is not None and callable(_get_active_table):
        try:
            df = _get_active_table(static_bundle, "mapping_filters")
        except Exception:
            df = pd.DataFrame()
    if (not isinstance(df, pd.DataFrame) or df.empty) and isinstance(static_bundle, dict):
        tables = static_bundle.get("tables", {})
        if isinstance(tables, dict):
            df = tables.get("mapping_filters", pd.DataFrame())
        if (not isinstance(df, pd.DataFrame) or df.empty) and isinstance(static_bundle.get("mapping_filters"), pd.DataFrame):
            df = static_bundle["mapping_filters"]
    return df if isinstance(df, pd.DataFrame) else pd.DataFrame()

def load_mapping_filters(static_bundle: Dict[str, object]) -> Dict[str, Dict[str, Dict[str, List[str]]]]:
    """Return {section_lower: {'INCLUDE'|'EXCLUDE': {Column: [values]}}}.
    Falls back to DEFAULT_FILTERS if the sheet is missing/empty."""
    df = _load_table(static_bundle)
    if df.empty:
        return {k: {d: {c: list(v) for c, v in cols.items()} for d, cols in dirs.items()}
                for k, dirs in DEFAULT_FILTERS.items()}
    cols = {str(c).strip().lower(): c for c in df.columns}
    sc, dc, cc, vc = (cols.get("section"), cols.get("direction"), cols.get("column"), cols.get("value"))
    if not (sc and dc and cc and vc):
        return dict(DEFAULT_FILTERS)
    out: Dict[str, Dict[str, Dict[str, List[str]]]] = {}
    for _, r in df.iterrows():
        section = str(r[sc]).strip().lower()
        direction = str(r[dc]).strip().upper()
        column = str(r[cc]).strip()
        value = str(r[vc]).strip()
        if not section or not direction or not column or value == "":
            continue
        out.setdefault(section, {}).setdefault(direction, {}).setdefault(column, [])
        if value not in out[section][direction][column]:
            out[section][direction][column].append(value)
    return out or dict(DEFAULT_FILTERS)

def get_filter(static_bundle: Dict[str, object], section: str,
               direction: str, column: Optional[str] = None) -> List[str]:
    """Return the value list for a (section, direction[, column]).
    e.g. get_filter(sb, 'Advisor Return Check', 'EXCLUDE', 'Class')
         -> ['Currency Overlay','Derivative Overlay','Treasury']"""
    filt = load_mapping_filters(static_bundle)
    sec = filt.get(section.strip().lower(), {})
    dirmap = sec.get(direction.strip().upper(), {})
    if column is not None:
        return list(dirmap.get(column, []))
    # no column specified -> flatten all columns for that direction
    out: List[str] = []
    for vals in dirmap.values():
        out.extend(vals)
    return out

def advisor_return_check_excluded_classes(static_bundle: Dict[str, object]) -> List[str]:
    """v311.1 population exclusion (Class not in overlay/treasury)."""
    return get_filter(static_bundle, "Advisor Return Check", "EXCLUDE", "Class")

def uut_included_glgroups(static_bundle: Dict[str, object]) -> List[str]:
    """v311.2 UUT population - included GLGroupName values (Valuation T)."""
    return get_filter(static_bundle, "Valuation T", "INCLUDE", "GLGroupName")

def uut_excluded_portfolio_codes(static_bundle: Dict[str, object]) -> List[str]:
    """v311.2 UUT population - excluded Portfolio codes (Valuation T)."""
    return get_filter(static_bundle, "Valuation T", "EXCLUDE", "PortfolioCode")
