# -*- coding: utf-8 -*-
"""CSV/header ingestion helpers extracted from the BNP Control App v162."""

from __future__ import annotations

import csv
import os
import re
from typing import Dict, List, Optional, Tuple

import pandas as pd

from bnp_helpers_columns import _normalise_col_token, _prime_dataframe_col_index

HEADER_CONTRACTS: Dict[str, Dict[str, object]] = {}
EXCLUDED_FILENAME_TOKENS: List[str] = []
REQUIRED_FILE_KEYWORDS: List[str] = []
OPTIONAL_FILE_KEYWORDS: List[str] = []


def configure_ingestion(*, header_contracts: Dict[str, Dict[str, object]], excluded_filename_tokens: List[str], required_file_keywords: List[str], optional_file_keywords: List[str]) -> None:
    global HEADER_CONTRACTS, EXCLUDED_FILENAME_TOKENS, REQUIRED_FILE_KEYWORDS, OPTIONAL_FILE_KEYWORDS
    HEADER_CONTRACTS = dict(header_contracts or {})
    EXCLUDED_FILENAME_TOKENS = list(excluded_filename_tokens or [])
    REQUIRED_FILE_KEYWORDS = list(required_file_keywords or [])
    OPTIONAL_FILE_KEYWORDS = list(optional_file_keywords or [])

_STRICT_NUMERIC_RE = re.compile(r"""
    ^\s*
    (?P<sign>[+-]?)
    (?:(?P<int>\d{1,3}(?:,\d{3})+|\d+)(?P<frac>\.\d+)?|(?P<onlyfrac>\.\d+))
    (?P<exp>[eE][+-]?\d+)?
    \s*%?\s*$
""", re.X)





def _try_read_text(path, encodings=("utf-8-sig", "utf-8", "cp1252", "latin1")):
    for enc in encodings:
        try:
            with open(path, "r", encoding=enc, errors="strict") as f:
                return f.read(65536), enc
        except Exception:
            continue
    with open(path, "r", encoding="latin1", errors="replace") as f:
        return f.read(65536), "latin1+replace"

def _sniff_delimiter(sample_text):
    try:
        dialect = csv.Sniffer().sniff(sample_text, delimiters=[",", ";", "\t", "|", "^", "~"])
        return dialect.delimiter
    except Exception:
        return ","

def _robust_csv_to_df(path, delimiter, encoding):
    rows, max_width = [], 0
    with open(path, "r", encoding=encoding, errors="replace", newline="") as f:
        reader = csv.reader(f, delimiter=delimiter)
        for row in reader:
            row = ["" if v is None else str(v) for v in row]
            rows.append(row)
            max_width = max(max_width, len(row))
    if not rows:
        return pd.DataFrame()
    padded = [r + [""] * (max_width - len(r)) for r in rows]
    return pd.DataFrame(padded)

def _cell_clean(x):
    return ("" if x is None else str(x)).strip()

def _row_profile(row: pd.Series) -> Dict[str, int]:
    vals = [_cell_clean(v) for v in row.tolist()]
    nonempty = [v for v in vals if v != ""]
    alpha_like = sum(any(ch.isalpha() for ch in v) for v in nonempty)
    numeric_like = sum(pd.notna(pd.to_numeric(v, errors='coerce')) for v in nonempty)
    return {
        "nonempty": len(nonempty),
        "alpha_like": alpha_like,
        "numeric_like": numeric_like,
    }

def _detect_header_rows(raw: pd.DataFrame) -> List[int]:
    candidates = []
    top_n = min(len(raw), 10)
    for i in range(top_n):
        prof = _row_profile(raw.iloc[i])
        if prof["nonempty"] == 0:
            continue
        score = (prof["alpha_like"] * 2) + prof["nonempty"] - prof["numeric_like"]
        candidates.append((i, score, prof))
    if not candidates:
        return [0]
    candidates = sorted(candidates, key=lambda x: (-x[1], x[0]))
    base_idx = candidates[0][0]
    header_rows = [base_idx]
    for j in range(base_idx + 1, min(base_idx + 3, len(raw))):
        prof = _row_profile(raw.iloc[j])
        if prof["alpha_like"] >= 1 and prof["numeric_like"] <= max(1, prof["alpha_like"]):
            header_rows.append(j)
        else:
            break
    return header_rows[:3]

def _find_header_row_by_tokens(raw: pd.DataFrame, required_tokens: List[str], search_rows: int = 10) -> Optional[int]:
    required = {_normalise_col_token(t) for t in required_tokens if str(t).strip()}
    top_n = min(len(raw), search_rows)
    for i in range(top_n):
        row_tokens = {_normalise_col_token(v) for v in raw.iloc[i].tolist() if _cell_clean(v) != ""}
        if required.issubset(row_tokens):
            return i
    return None

def normalize_header(raw: pd.DataFrame, header_rows: List[int]) -> List[str]:
    header_parts = []
    for idx in header_rows:
        header_parts.append([_cell_clean(v) for v in raw.iloc[idx].tolist()])
    width = max(len(r) for r in header_parts) if header_parts else raw.shape[1]
    for r in header_parts:
        if len(r) < width:
            r += [""] * (width - len(r))

    headers, used = [], {}
    for c in range(width):
        bits = [r[c] for r in header_parts if r[c] != ""]
        name = " ".join(bits).strip() or f"Unnamed_{c+1}"
        name = re.sub(r"\s+", " ", name)
        if name in used:
            used[name] += 1
            name = f"{name}_{used[name]}"
        else:
            used[name] = 1
        headers.append(name)
    return headers

def _describe_header_contract(keyword: str) -> str:
    contract = HEADER_CONTRACTS.get(keyword, {})
    groups = contract.get("required_groups", [])
    if not groups:
        return ""
    parts = []
    for group in groups:
        parts.append(" | ".join(str(x) for x in group if str(x).strip()))
    return " ; ".join(parts)

def _header_contract_met(token_set: set, required_groups: List[List[str]]) -> bool:
    if not required_groups:
        return True
    normalised_tokens = {_normalise_col_token(x) for x in token_set if str(x).strip()}
    for group in required_groups:
        normalised_group = {_normalise_col_token(x) for x in group if str(x).strip()}
        if not (normalised_tokens & normalised_group):
            return False
    return True

def _select_header_rows_for_keyword(raw: pd.DataFrame, keyword: str) -> Tuple[List[int], str, str]:
    contract = HEADER_CONTRACTS.get(keyword, {})
    required_groups = contract.get("required_groups", [])
    top_n = min(len(raw), 10)

    if required_groups:
        for i in range(top_n):
            row_tokens = {_cell_clean(v) for v in raw.iloc[i].tolist() if _cell_clean(v) != ""}
            if _header_contract_met(row_tokens, required_groups):
                return [i], "contract_row", "PASS"

    header_rows = _detect_header_rows(raw)
    header_tokens = set(normalize_header(raw, header_rows))
    if _header_contract_met(header_tokens, required_groups):
        strategy = "heuristic" if not required_groups else "heuristic_validated"
        return header_rows, strategy, "PASS"

    if required_groups:
        single_rows = []
        for i in range(top_n):
            row_headers = normalize_header(raw, [i])
            if _header_contract_met(set(row_headers), required_groups):
                single_rows.append(i)
        if single_rows:
            return [single_rows[0]], "single_row_validated", "PASS"

        raise ValueError(
            f"Header validation failed for {keyword}. Required header groups not found: {_describe_header_contract(keyword)}"
        )

    return header_rows, "heuristic", "PASS"

def _should_exclude_report_file(path: str) -> bool:
    name = os.path.basename(path).lower()
    return any(token.lower() in name for token in EXCLUDED_FILENAME_TOKENS)

def load_csv_keyword(folder: str, keyword: str) -> Tuple[Optional[pd.DataFrame], Dict[str, object]]:
    meta = {
        "Keyword": keyword,
        "Loaded": False,
        "Path": "",
        "Rows": 0,
        "Columns": 0,
        "HeaderRows": "",
        "Encoding": "",
        "Delimiter": "",
        "Error": "",
        "MatchedFiles": 0,
        "LoadedFiles": 0,
        "ExcludedCount": 0,
        "ExcludedFiles": "",
        "LoadedPaths": "",
        "FileErrors": "",
        "HeaderStrategy": "",
        "HeaderValidation": "",
        "HeaderContract": _describe_header_contract(keyword),
    }
    try:
        matches = []
        for f in os.listdir(folder):
            if keyword.lower() in f.lower() and f.lower().endswith((".csv", ".txt")):
                matches.append(os.path.join(folder, f))
        matches = sorted(matches)
        meta["MatchedFiles"] = int(len(matches))
        if not matches:
            meta["Error"] = "File not found"
            return None, meta

        excluded = [p for p in matches if _should_exclude_report_file(p)]
        valid_paths = [p for p in matches if not _should_exclude_report_file(p)]
        meta["ExcludedCount"] = int(len(excluded))
        meta["ExcludedFiles"] = " | ".join(os.path.basename(p) for p in excluded)

        if not valid_paths:
            meta["Error"] = "All matching files excluded by filename rule"
            return None, meta

        frames: List[pd.DataFrame] = []
        loaded_paths: List[str] = []
        header_info: List[str] = []
        encodings: List[str] = []
        delimiters: List[str] = []
        file_errors: List[str] = []
        header_strategy_info: List[str] = []
        header_validation_info: List[str] = []

        for path in valid_paths:
            try:
                sample_text, enc = _try_read_text(path)
                delim = _sniff_delimiter(sample_text)
                raw = _robust_csv_to_df(path, delim, enc)
                if raw.empty:
                    file_errors.append(f"{os.path.basename(path)}: Empty file")
                    continue

                header_rows, header_strategy, header_validation = _select_header_rows_for_keyword(raw, keyword)
                cols = normalize_header(raw, header_rows)
                start_row = max(header_rows) + 1
                data = raw.iloc[start_row:].reset_index(drop=True).copy()
                if data.shape[1] < len(cols):
                    for _ in range(len(cols) - data.shape[1]):
                        data[data.shape[1]] = ""
                elif data.shape[1] > len(cols):
                    cols += [f"Extra_{i+1}" for i in range(data.shape[1] - len(cols))]
                data.columns = cols[:data.shape[1]]
                data["SourceFile"] = os.path.basename(path)
                data["SourcePath"] = path

                frames.append(data)
                loaded_paths.append(path)
                header_info.append(f"{os.path.basename(path)}:{header_rows}")
                encodings.append(f"{os.path.basename(path)}:{enc}")
                delimiters.append(f"{os.path.basename(path)}:{delim}")
                header_strategy_info.append(f"{os.path.basename(path)}:{header_strategy}")
                header_validation_info.append(f"{os.path.basename(path)}:{header_validation}")
            except (OSError, UnicodeError, csv.Error, ValueError, pd.errors.ParserError) as e:
                file_errors.append(f"{os.path.basename(path)}: {type(e).__name__}: {e}")

        if not frames:
            meta["Error"] = "No valid files loaded"
            meta["FileErrors"] = " | ".join(file_errors)
            return None, meta

        combined = pd.concat(frames, ignore_index=True, sort=False)
        trace_cols = [c for c in ["SourceFile", "SourcePath"] if c in combined.columns]
        base_cols = [c for c in combined.columns if c not in trace_cols]
        combined = combined[base_cols + trace_cols]

        meta.update({
            "Loaded": True,
            "Path": " | ".join(loaded_paths),
            "Rows": int(len(combined)),
            "Columns": int(len(combined.columns)),
            "HeaderRows": " | ".join(header_info),
            "Encoding": " | ".join(encodings),
            "Delimiter": " | ".join(delimiters),
            "LoadedFiles": int(len(loaded_paths)),
            "LoadedPaths": " | ".join(loaded_paths),
            "FileErrors": " | ".join(file_errors),
            "HeaderStrategy": " | ".join(header_strategy_info),
            "HeaderValidation": " | ".join(header_validation_info) if header_validation_info else "PASS",
        })
        if file_errors and not meta["Error"]:
            meta["Error"] = "Some files skipped"
        return combined, meta
    except Exception as e:
        meta["Error"] = str(e)
        return None, meta

def load_day_files(
    folder: str,
    progress_callback=None,
    progress_label: str = "Processing",
) -> Dict[str, object]:
    file_map = {}
    file_meta_rows: List[Dict[str, object]] = []
    keywords = REQUIRED_FILE_KEYWORDS + OPTIONAL_FILE_KEYWORDS
    total_keywords = len(keywords)
    if progress_callback is not None:
        progress_callback(
            5,
            status=f"{progress_label}: scanning source files",
            summary=f"Folder: {folder}",
        )
    for idx, keyword in enumerate(keywords, start=1):
        if progress_callback is not None:
            progress_callback(
                min(45, max(10, int(idx * 40 / max(total_keywords, 1)))),
                status=f"{progress_label}: loading {keyword}",
                summary=f"Source file {idx}/{total_keywords}: {keyword}",
            )
        df, meta = load_csv_keyword(folder, keyword)
        if isinstance(df, pd.DataFrame):
            df = _prime_dataframe_col_index(df)
        alias = {
            "DDetailedReturn": "dd",
            "DAssetTypeReturn": "dat",
            "DAssetReturn": "dar",
            "TransactionListing": "txn",
            "BenchmarkStatic": "bmk",
        }[keyword]
        file_map[alias] = df
        file_meta_rows.append(meta)
    if progress_callback is not None:
        progress_callback(
            45,
            status=f"{progress_label}: source files loaded",
            summary=f"Loaded definitions for {len(file_meta_rows)} expected file types",
        )
    return {
        "dd": file_map.get("dd"),
        "dat": file_map.get("dat"),
        "dar": file_map.get("dar"),
        "txn": file_map.get("txn"),
        "bmk": file_map.get("bmk"),
        "file_meta_df": pd.DataFrame(file_meta_rows),
    }

__all__ = [
    'configure_ingestion',
    'load_csv_keyword',
    'load_day_files',
    '_find_header_row_by_tokens',
    '_row_profile',
    '_cell_clean',
]
