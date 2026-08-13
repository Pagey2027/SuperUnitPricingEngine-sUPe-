# -*- coding: utf-8 -*-
"""Tableau / Unison BO CSV ingestion helpers for BNP Control App.

Loads the daily Tableau CSVs configured in Static Data.xlsx:
- Acc Balance.csv
- Daily Price - By Statutory Fund.csv
- Daily Price - By Trust Product.csv

The helper is deliberately Streamlit-free and returns dataframes plus diagnostics.
"""
from __future__ import annotations

import csv
import os
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

import pandas as pd

try:
    from bnp_helpers_static_data import load_static_data, get_active_table, get_config_value
except Exception:  # allow standalone import in diagnostic tooling
    load_static_data = None
    get_active_table = None
    get_config_value = None

TRUE_VALUES = {"y", "yes", "true", "1", "active"}


def _normalise_text(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _month_alias_lookup(static_bundle: Dict[str, object]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    if get_active_table is None:
        return out
    aliases = get_active_table(static_bundle, "folder_month_aliases")
    if aliases.empty:
        return out
    for _, r in aliases.iterrows():
        alias = _normalise_text(r.get("Alias", ""))
        month = pd.to_numeric(r.get("MonthNumber"), errors="coerce")
        if alias and pd.notna(month):
            out[alias] = int(month)
    return out


def _root_variants(root: str) -> List[str]:
    root = str(root or "").strip()
    if not root:
        return []
    variants = [root]
    bs = chr(92)
    try:
        if root.upper().startswith("G:" + bs):
            tail = root[3:].lstrip(bs)
            variants.append(bs + bs + "hq.local" + bs + "Corp" + bs + tail)
        elif root.lower().startswith((bs + bs + "hq.local" + bs + "corp" + bs).lower()):
            tail = root[len(bs + bs + "hq.local" + bs + "Corp" + bs):]
            variants.append("G:" + bs + tail)
    except Exception:
        pass
    out = []
    seen = set()
    for v in variants:
        key = os.path.abspath(v).lower()
        if key not in seen:
            seen.add(key)
            out.append(v)
    return out


def _safe_isdir(path: str) -> bool:
    try:
        return bool(path and os.path.isdir(path))
    except Exception:
        return False


def _safe_exists(path: str) -> bool:
    try:
        return bool(path and os.path.exists(path))
    except Exception:
        return False


def _safe_listdir(path: str, limit: int = 100) -> List[str]:
    try:
        if not _safe_isdir(path):
            return []
        return sorted(os.listdir(path))[:limit]
    except Exception:
        return []


def _format_path_part(dt: pd.Timestamp, fmt: str) -> str:
    # Support nested levels using backslashes in the format, e.g. %Y\%m %b
    parts = []
    for part in re.split(r"[\\/]+", str(fmt or "")):
        if part:
            parts.append(dt.strftime(part))
    return os.path.join(*parts) if parts else ""


def _extract_month_year_score(name: str, target: pd.Timestamp, aliases: Dict[str, int]) -> int:
    raw = str(name or "").strip()
    norm = _normalise_text(raw)
    year_ok = str(int(target.year)) in raw or str(int(target.year)) in norm
    if not year_ok:
        return 0
    # Try aliases and canonical strftime tokens.
    target_month = int(target.month)
    for token, month in aliases.items():
        if month == target_month and token and token in norm:
            return 100
    # Fallback to Python month spellings.
    candidates = {target.strftime("%b"), target.strftime("%B"), target.strftime("%m %b"), target.strftime("%-m %b") if hasattr(target, 'strftime') else ""}
    for c in candidates:
        if c and _normalise_text(c) in norm:
            return 90
    return 0


def _extract_day_month_score(name: str, target: pd.Timestamp, aliases: Dict[str, int]) -> int:
    raw = str(name or "").strip()
    norm = _normalise_text(raw)
    day = int(target.day)
    day_tokens = {str(day), f"{day:02d}"}
    day_ok = any(re.search(rf"(^|[^0-9]){re.escape(d)}([^0-9]|$)", raw) for d in day_tokens)
    if not day_ok:
        # For normalised tokens, 15jul becomes 15jul; require startswith day number.
        day_ok = any(norm.startswith(d) for d in day_tokens)
    if not day_ok:
        return 0
    target_month = int(target.month)
    for token, month in aliases.items():
        if month == target_month and token and token in norm:
            return 100
    candidates = {target.strftime("%b"), target.strftime("%B"), target.strftime("%m %b"), target.strftime("%-m %b") if hasattr(target, 'strftime') else ""}
    for c in candidates:
        if c and _normalise_text(c) in norm:
            return 90
    return 0


def _select_unique_best(candidates: List[Dict[str, object]]) -> Tuple[str, str]:
    if not candidates:
        return "", "No candidates"
    ordered = sorted(candidates, key=lambda r: (int(r.get("Score", 0)), str(r.get("Path", ""))), reverse=True)
    best = ordered[0]
    best_score = int(best.get("Score", 0))
    tied = [r for r in ordered if int(r.get("Score", 0)) == best_score]
    if best_score <= 0:
        return "", "No positive-score candidate"
    if len(tied) > 1:
        return "", "Ambiguous candidates tied: " + " | ".join(str(r.get("Path", "")) for r in tied[:10])
    return str(best.get("Path", "")), str(best.get("Reason", "Selected best candidate"))


def resolve_date_folder(root: str, rule_row: pd.Series, run_date: object, static_bundle: Dict[str, object]) -> Tuple[str, pd.DataFrame]:
    """Resolve expected date folder with exact path first, then controlled alias scan."""
    dt = pd.to_datetime(run_date, errors="coerce")
    diag: List[Dict[str, object]] = []
    if pd.isna(dt):
        return "", pd.DataFrame([{"Stage": "ResolveDateFolder", "Result": "Invalid run date", "Detail": str(run_date)}])
    dt = pd.Timestamp(dt).normalize()
    aliases = _month_alias_lookup(static_bundle)
    level1_fmt = str(rule_row.get("Level1Format", "") or "").strip()
    level2_fmt = str(rule_row.get("Level2Format", "") or "").strip()
    rule_name = str(rule_row.get("RuleName", "") or "")
    expected_rel = os.path.join(_format_path_part(dt, level1_fmt), _format_path_part(dt, level2_fmt))

    for rv in _root_variants(root):
        expected = os.path.join(rv, expected_rel)
        diag.append({"RuleName": rule_name, "Stage": "ExactPath", "ExpectedPath": expected, "Path": expected, "Score": 999, "Exists": _safe_isdir(expected), "Selected": False, "Reason": "Exact expected path"})
        if _safe_isdir(expected):
            diag[-1]["Selected"] = True
            return expected, pd.DataFrame(diag)

    # Fallback scan: find month folder then day folder.
    month_candidates: List[Dict[str, object]] = []
    root_used = ""
    for rv in _root_variants(root):
        if not _safe_isdir(rv):
            diag.append({"RuleName": rule_name, "Stage": "RootMissing", "Path": rv, "Score": 0, "Exists": False, "Selected": False, "Reason": "Root not accessible"})
            continue
        root_used = rv
        for child in _safe_listdir(rv, limit=500):
            p = os.path.join(rv, child)
            if not _safe_isdir(p):
                continue
            score = _extract_month_year_score(child, dt, aliases)
            if score:
                month_candidates.append({"RuleName": rule_name, "Stage": "MonthAlias", "Path": p, "FolderName": child, "Score": score, "Exists": True, "Selected": False, "Reason": "Matched month/year by alias"})
        if month_candidates:
            break
    diag.extend(month_candidates)
    month_folder, month_reason = _select_unique_best(month_candidates)
    if not month_folder:
        diag.append({"RuleName": rule_name, "Stage": "MonthSelection", "Path": root_used or root, "Score": 0, "Exists": _safe_isdir(root_used or root), "Selected": False, "Reason": month_reason})
        return "", pd.DataFrame(diag)

    day_candidates: List[Dict[str, object]] = []
    for child in _safe_listdir(month_folder, limit=500):
        p = os.path.join(month_folder, child)
        if not _safe_isdir(p):
            continue
        score = _extract_day_month_score(child, dt, aliases)
        if score:
            day_candidates.append({"RuleName": rule_name, "Stage": "DayAlias", "Path": p, "FolderName": child, "Score": score, "Exists": True, "Selected": False, "Reason": "Matched day/month by alias"})
    diag.extend(day_candidates)
    day_folder, day_reason = _select_unique_best(day_candidates)
    if not day_folder:
        diag.append({"RuleName": rule_name, "Stage": "DaySelection", "Path": month_folder, "Score": 0, "Exists": _safe_isdir(month_folder), "Selected": False, "Reason": day_reason})
        return "", pd.DataFrame(diag)

    for d in diag:
        if str(d.get("Path")) == day_folder:
            d["Selected"] = True
    return day_folder, pd.DataFrame(diag)


def _try_read_text(path: str, encodings=("utf-8-sig", "utf-8", "cp1252", "latin1")) -> Tuple[str, str]:
    for enc in encodings:
        try:
            with open(path, "r", encoding=enc, errors="strict") as f:
                return f.read(65536), enc
        except Exception:
            continue
    with open(path, "r", encoding="latin1", errors="replace") as f:
        return f.read(65536), "latin1+replace"


def _sniff_delimiter(sample_text: str) -> str:
    try:
        dialect = csv.Sniffer().sniff(sample_text, delimiters=[",", ";", "\t", "|", "^", "~"])
        return dialect.delimiter
    except Exception:
        return ","


def _read_csv_flexible(path: str) -> Tuple[pd.DataFrame, Dict[str, object]]:
    meta: Dict[str, object] = {"Path": path, "Encoding": "", "Delimiter": "", "Rows": 0, "Columns": 0, "Error": ""}
    try:
        sample, enc = _try_read_text(path)
        delim = _sniff_delimiter(sample)
        meta["Encoding"] = enc
        meta["Delimiter"] = delim
        df = pd.read_csv(path, encoding=enc.replace("+replace", ""), sep=delim, dtype=str, engine="python")
        df = df.dropna(how="all")
        df.columns = [str(c).strip() for c in df.columns]
        meta["Rows"] = int(len(df))
        meta["Columns"] = int(len(df.columns))
        return df.reset_index(drop=True), meta
    except Exception as exc:
        meta["Error"] = f"{type(exc).__name__}: {exc}"
        return pd.DataFrame(), meta


def _file_stat(path: str) -> Dict[str, object]:
    try:
        st = os.stat(path)
        return {"FileSizeBytes": int(st.st_size), "ModifiedTime": pd.to_datetime(st.st_mtime, unit="s")}
    except Exception:
        return {"FileSizeBytes": 0, "ModifiedTime": pd.NaT}


def prepare_tableau_sources(run_date: object, static_bundle: Optional[Dict[str, object]] = None, static_data_path: Optional[str] = None, timing_callback=None) -> Dict[str, object]:
    """Load configured Tableau/Unison BO CSVs for a run date."""
    started_total = time.perf_counter()
    if static_bundle is None:
        if load_static_data is None:
            raise RuntimeError("bnp_helpers_static_data.load_static_data is not available")
        static_bundle = load_static_data(static_data_path)

    meta_rows: List[Dict[str, object]] = []
    exc_rows: List[Dict[str, object]] = []
    diag_frames: List[pd.DataFrame] = []
    out: Dict[str, object] = {
        "tableau_folder": "",
        "acc_balance_df": pd.DataFrame(),
        "tableau_price_sf_df": pd.DataFrame(),
        "tableau_price_trust_df": pd.DataFrame(),
    }

    reports = get_active_table(static_bundle, "source_reports") if get_active_table is not None else pd.DataFrame()
    reports = reports.loc[reports.get("SourceGroup", pd.Series(dtype="object")).astype(str).str.strip().str.lower().eq("tableau")].copy() if not reports.empty else reports
    rules = get_active_table(static_bundle, "date_folder_rules") if get_active_table is not None else pd.DataFrame()

    if reports.empty:
        exc_rows.append({"Severity": "Error", "Check": "TableauReports", "Detail": "No active Tableau reports configured in source_reports"})
    else:
        for _, report in reports.iterrows():
            report_key = str(report.get("ReportKey", "")).strip()
            file_name = str(report.get("FileName", "")).strip()
            root_key = str(report.get("RootConfigKey", "tableau_root")).strip()
            rule_name = str(report.get("DateFolderRule", "tableau_month_day")).strip()
            required = str(report.get("Required", "Y")).strip().lower() in TRUE_VALUES
            root = get_config_value(static_bundle, root_key, "") if get_config_value is not None else ""
            rule_match = rules.loc[rules.get("RuleName", pd.Series(dtype="object")).astype(str).str.strip().eq(rule_name)].copy() if not rules.empty else pd.DataFrame()
            if rule_match.empty:
                exc_rows.append({"Severity": "Error" if required else "Warning", "Check": "DateFolderRule", "Detail": f"{report_key}: rule not found: {rule_name}"})
                folder = ""
                folder_diag = pd.DataFrame()
            else:
                folder, folder_diag = resolve_date_folder(root, rule_match.iloc[0], run_date, static_bundle)
                if not folder and required:
                    exc_rows.append({"Severity": "Error", "Check": "ResolveTableauFolder", "Detail": f"{report_key}: could not resolve folder for rule {rule_name}"})
            if isinstance(folder_diag, pd.DataFrame) and not folder_diag.empty:
                folder_diag = folder_diag.copy()
                folder_diag["ReportKey"] = report_key
                diag_frames.append(folder_diag)
            if folder and not out["tableau_folder"]:
                out["tableau_folder"] = folder
            expected_path = os.path.join(folder, file_name) if folder else ""
            loaded = False
            df = pd.DataFrame()
            err = ""
            enc = ""
            delim = ""
            rows = 0
            cols = 0
            stat = {"FileSizeBytes": 0, "ModifiedTime": pd.NaT}
            if expected_path and _safe_exists(expected_path):
                df, file_meta = _read_csv_flexible(expected_path)
                err = str(file_meta.get("Error", ""))
                enc = str(file_meta.get("Encoding", ""))
                delim = str(file_meta.get("Delimiter", ""))
                rows = int(file_meta.get("Rows", 0) or 0)
                cols = int(file_meta.get("Columns", 0) or 0)
                loaded = err == "" and isinstance(df, pd.DataFrame) and not df.empty
                stat = _file_stat(expected_path)
            else:
                err = "File not found"
            if not loaded and required:
                exc_rows.append({"Severity": "Error", "Check": "LoadTableauCsv", "Detail": f"{report_key}: {err}; path={expected_path}"})
            meta_rows.append({
                "ReportKey": report_key,
                "FileName": file_name,
                "ExpectedPath": expected_path,
                "ResolvedPath": expected_path if loaded else "",
                "Loaded": bool(loaded),
                "Rows": rows,
                "Columns": cols,
                "Encoding": enc,
                "Delimiter": delim,
                "Required": required,
                "Error": err,
                **stat,
            })
            # Canonical output names.
            if report_key == "acc_balance":
                out["acc_balance_df"] = df
            elif report_key == "tableau_price_sf":
                out["tableau_price_sf_df"] = df
            elif report_key == "tableau_price_trust":
                out["tableau_price_trust_df"] = df
            else:
                out[f"{report_key}_df"] = df

    out["tableau_file_meta_df"] = pd.DataFrame(meta_rows)
    out["tableau_diagnostic_df"] = pd.concat(diag_frames, ignore_index=True, sort=False) if diag_frames else pd.DataFrame()
    out["tableau_exception_df"] = pd.DataFrame(exc_rows)
    out["tableau_timing_df"] = pd.DataFrame([{"Phase": "prepare_tableau_sources", "ElapsedSeconds": round(time.perf_counter() - started_total, 4), "Status": "Done"}])
    if timing_callback is not None:
        try:
            timing_callback("prepare_tableau_sources", time.perf_counter() - started_total, "Done")
        except Exception:
            pass
    return out


__all__ = ["prepare_tableau_sources", "resolve_date_folder"]
