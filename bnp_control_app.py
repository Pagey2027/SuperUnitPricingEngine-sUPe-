# -*- coding: utf-8 -*-
"""
BNP Control App - production layout refresh

Version history (v279 through v363) has been moved to CHANGELOG.md, kept in the
same folder as this file, so this module docstring stays short. See CHANGELOG.md
for the full, dated history of every version referenced by the '_vXXX_' suffixes
used throughout this file's function/variable names.

v363: local_price_validation_template default now resolves to the app folder
(Static Data 'paths'), not a personal machine path; bnp_helpers_price_integrity.py
Material Movement population now reads mapping_filters/'Valuation T' from Static
Data (fallback retained); removed a dead duplicate month-alias builder from
bnp_helpers_static_data.py. See CHANGELOG.md for full detail.

Purpose
-------
This file keeps the single-day dashboard concept and adds a hardened multi-day
history / trend mode using the BNP network-root folder structure.

Design principles
-----------------
- Single source of truth: process_day(folder)
- Manual refresh only for history build
- Portfolio detail cache maintained through time
- Reconciliations persisted, not just displayed
- Business-friendly labels preferred over codes
- Diagnostics and processing exceptions persisted for supportability
"""

import os
import re
import csv
import hashlib
import json
import sys
import time
import html
import importlib.util
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import quote

import pandas as pd




# ========================================================
# v306.13.7.8 persistent folder fingerprint cache + rollup cleanup
# - Caches expensive folder_fingerprint(folder) results across Trend History runs
# - Uses a lightweight folder metadata signature to decide whether cache can be reused
# - Writes folder_fingerprint_cache_diagnostics_last_run.csv
# - Replaces v306.13.7.7 rollup generation with parent/mirror-aware additive rollups
# - Handles cached non-force runs where DAR profile A/B files are empty
# ========================================================
try:
    import os as _v306_13_7_8_os
    import json as _v306_13_7_8_json
    import hashlib as _v306_13_7_8_hashlib
    import time as _v306_13_7_8_time
    from pathlib import Path as _v306_13_7_8_Path
    import pandas as _v306_13_7_8_pd

    _V306_13_7_8_VERSION = "v306.13.7.8_fingerprint_cache_and_rollup_cleanup"
    _v306_13_7_8_fingerprint_diag_rows = []

    def _v306_13_7_8_cache_dir() -> _v306_13_7_8_Path:
        try:
            base = _v306_13_7_8_Path(__file__).resolve().parent
        except Exception:
            base = _v306_13_7_8_Path.cwd()
        out = base / ".bnp_manifest_cache"
        try:
            out.mkdir(parents=True, exist_ok=True)
        except Exception:
            out = _v306_13_7_8_Path.cwd()
        return out

    def _v306_13_7_8_trend_cache_dir() -> _v306_13_7_8_Path:
        try:
            cache_dir = globals().get("CACHE_DIR", "./trend_cache")
            out = _v306_13_7_8_Path(str(cache_dir))
            out.mkdir(parents=True, exist_ok=True)
            return out
        except Exception:
            out = _v306_13_7_8_Path("./trend_cache")
            try:
                out.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
            return out

    def _v306_13_7_8_cache_path() -> _v306_13_7_8_Path:
        return _v306_13_7_8_cache_dir() / "folder_fingerprint_fast_cache_v306_13_7_8.json"

    def _v306_13_7_8_load_cache() -> dict:
        path = _v306_13_7_8_cache_path()
        try:
            if path.exists():
                return _v306_13_7_8_json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def _v306_13_7_8_save_cache(cache: dict) -> None:
        try:
            _v306_13_7_8_cache_path().write_text(_v306_13_7_8_json.dumps(cache, sort_keys=True, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _v306_13_7_8_folder_metadata_signature(folder: str) -> str:
        """Lightweight metadata signature for a BNP day folder.

        This avoids hashing/parsing file contents on cached Trend reruns. It records
        immediate child file names, sizes, mtimes and directory mtimes. Directory mtime
        should change when child entries change within that directory on normal filesystems.
        """
        folder_text = str(folder or "").strip()
        rows = []
        try:
            with _v306_13_7_8_os.scandir(folder_text) as entries:
                for entry in entries:
                    try:
                        st = entry.stat(follow_symlinks=False)
                        kind = "D" if entry.is_dir(follow_symlinks=False) else "F"
                        size = int(getattr(st, "st_size", 0) or 0)
                        mtime_ns = int(getattr(st, "st_mtime_ns", int(getattr(st, "st_mtime", 0) * 1_000_000_000)) or 0)
                        rows.append(f"{kind}|{entry.name}|{size}|{mtime_ns}")
                    except Exception as exc:
                        rows.append(f"E|{getattr(entry, 'name', '')}|{type(exc).__name__}")
        except Exception as exc:
            rows.append(f"ROOT_ERROR|{type(exc).__name__}|{exc}")
        raw = "\n".join(sorted(rows))
        return _v306_13_7_8_hashlib.md5(raw.encode("utf-8", errors="ignore")).hexdigest()

    def _v306_13_7_8_write_fingerprint_diag() -> None:
        try:
            if not _v306_13_7_8_fingerprint_diag_rows:
                return
            df = _v306_13_7_8_pd.DataFrame(_v306_13_7_8_fingerprint_diag_rows)
            pass  # [removed] diagnostic CSV write
        except Exception:
            pass

    def _v306_13_7_8_wrap_folder_fingerprint() -> None:
        try:
            original = globals().get("folder_fingerprint")
            if original is None or getattr(original, "_v306_13_7_8_wrapped", False):
                return

            def _v306_13_7_8_folder_fingerprint_cached(folder: str):
                started = _v306_13_7_8_time.perf_counter()
                folder_text = str(folder or "")
                cache_key = _v306_13_7_8_hashlib.md5(folder_text.lower().encode("utf-8", errors="ignore")).hexdigest()
                metadata_started = _v306_13_7_8_time.perf_counter()
                metadata_sig = _v306_13_7_8_folder_metadata_signature(folder_text)
                metadata_elapsed = _v306_13_7_8_time.perf_counter() - metadata_started
                cache = _v306_13_7_8_load_cache()
                entry = cache.get(cache_key, {}) if isinstance(cache, dict) else {}
                status = "Miss"
                reason = "No existing cache entry"
                fingerprint_value = None
                if isinstance(entry, dict) and entry.get("metadata_signature") == metadata_sig and entry.get("fingerprint"):
                    status = "Hit"
                    reason = "Metadata signature unchanged"
                    fingerprint_value = entry.get("fingerprint")
                else:
                    if isinstance(entry, dict) and entry:
                        reason = "Metadata signature changed"
                    original_started = _v306_13_7_8_time.perf_counter()
                    fingerprint_value = original(folder_text)
                    original_elapsed = _v306_13_7_8_time.perf_counter() - original_started
                    cache[cache_key] = {
                        "folder": folder_text,
                        "metadata_signature": metadata_sig,
                        "fingerprint": fingerprint_value,
                        "updated_at": _v306_13_7_8_time.strftime("%Y-%m-%d %H:%M:%S"),
                        "version": _V306_13_7_8_VERSION,
                    }
                    _v306_13_7_8_save_cache(cache)
                    _v306_13_7_8_fingerprint_diag_rows.append({
                        "SourceFolder": folder_text,
                        "FingerprintCacheStatus": status,
                        "Reason": reason,
                        "MetadataElapsedSeconds": round(metadata_elapsed, 4),
                        "OriginalFingerprintElapsedSeconds": round(original_elapsed, 4),
                        "TotalElapsedSeconds": round(_v306_13_7_8_time.perf_counter() - started, 4),
                        "CacheKey": cache_key,
                        "MetadataSignature": metadata_sig,
                        "PatchVersion": _V306_13_7_8_VERSION,
                    })
                    _v306_13_7_8_write_fingerprint_diag()
                    return fingerprint_value

                _v306_13_7_8_fingerprint_diag_rows.append({
                    "SourceFolder": folder_text,
                    "FingerprintCacheStatus": status,
                    "Reason": reason,
                    "MetadataElapsedSeconds": round(metadata_elapsed, 4),
                    "OriginalFingerprintElapsedSeconds": 0.0,
                    "TotalElapsedSeconds": round(_v306_13_7_8_time.perf_counter() - started, 4),
                    "CacheKey": cache_key,
                    "MetadataSignature": metadata_sig,
                    "PatchVersion": _V306_13_7_8_VERSION,
                })
                _v306_13_7_8_write_fingerprint_diag()
                return fingerprint_value

            _v306_13_7_8_folder_fingerprint_cached._v306_13_7_8_wrapped = True
            globals()["folder_fingerprint"] = _v306_13_7_8_folder_fingerprint_cached
        except Exception:
            pass

    def _v306_13_7_8_phase_group(scope, phase, detail=""):
        text = (str(scope or "") + " " + str(phase or "") + " " + str(detail or "")).lower()
        if "source.folder_fingerprint" in text or "folder fingerprint" in text:
            return "01 folder fingerprint"
        if "cache.per_date_hit_check" in text:
            return "14 trend cache read/write/filter"
        if "dassetreturn selected" in text or "dassetreturn source" in text:
            return "02 DAssetReturn parse/load"
        if "dassetreturn total" in text:
            return "02 DAssetReturn parse/load"
        if "ddetailedreturn" in text:
            return "03 DDetailedReturn parse/load"
        if "dassettypereturn" in text:
            return "04 DAssetTypeReturn parse/load"
        if "benchmarkstatic" in text:
            return "05 BenchmarkStatic parse/load"
        if "persistent source dataframe cache" in text or "bnp load:" in text:
            return "06 persistent source cache"
        if "arc " in text or "arc_" in text or "prepare arc" in text:
            return "07 ARC load"
        if "fx find" in text or "fx workbook" in text or "fx diagnostics" in text or "fx load" in text or "fx validation" in text:
            return "08 FX load/validation"
        if "process_day" in text or "process day" in text:
            return "09 process_day core"
        if "portfolio calc" in text or "transaction map" in text:
            return "10 portfolio calc / transaction map"
        if "build executive summary" in text or "snapshot.executive" in text or "executive_summary" in text:
            return "11 executive summary / snapshot"
        if "minimum validation" in text:
            return "12 minimum validation"
        if "common candidate" in text or "common_validation" in text:
            return "13 common validation candidates"
        if "cache.read" in text or "cache.write" in text or "cache.dedupe" in text or "cache.filter" in text:
            return "14 trend cache read/write/filter"
        if "bundle.prepare_out_dashboard_bundle" in text:
            return "15 bundle.prepare_out_dashboard_bundle"
        if "trend_history.total" in text or "total_build" in text:
            return "99 trend history total"
        return "98 other / unclassified"

    def _v306_13_7_8_elapsed_role(scope, phase, detail=""):
        text = (str(scope or "") + " " + str(phase or "") + " " + str(detail or "")).lower()
        if "trend_history.total" in text or "total_build" in text:
            return "ParentTotal"
        if "bundle.prepare_out_dashboard_bundle" in text:
            return "ParentTotal"
        if "total source load/prime" in text:
            return "ParentTotal"
        if "memoized_store" in text:
            return "Mirror"
        if "selected-column parser memory" in text:
            return "DiagnosticZero"
        if "dassetreturn total" in text:
            return "ParentTotal"
        if "ddetailedreturn total" in text or "dassettypereturn total" in text or "benchmarkstatic total" in text:
            return "ParentTotal"
        if "process_day: total" in text or "portfolio calc: total" in text:
            return "ParentTotal"
        return "Child"

    def _v306_13_7_8_build_slim_projection(timing_csv_path):
        base_dir = _v306_13_7_8_Path(timing_csv_path).parent
        out_path = base_dir / "dar_trend_slim_projection_last_run.csv"
        ab_path = base_dir / "dar_profile_ab_comparison_last_run.csv"
        try:
            if not ab_path.exists() or ab_path.stat().st_size == 0:
                skip = _v306_13_7_8_pd.DataFrame([{
                    "Status": "Skipped",
                    "Detail": "DAR profile A/B comparison was not produced on this cached non-force run.",
                    "PatchVersion": _V306_13_7_8_VERSION,
                }])
                pass  # [removed] diagnostic CSV write
                return
            ab = _v306_13_7_8_pd.read_csv(ab_path)
            if ab.empty:
                skip = _v306_13_7_8_pd.DataFrame([{
                    "Status": "Skipped",
                    "Detail": "DAR profile A/B comparison file was empty on this cached non-force run.",
                    "PatchVersion": _V306_13_7_8_VERSION,
                }])
                pass  # [removed] diagnostic CSV write
                return
            rows = []
            for _, row in ab.iterrows():
                base_cols = _v306_13_7_8_pd.to_numeric(_v306_13_7_8_pd.Series([row.get("BaseColumns", 0)]), errors="coerce").fillna(0).iloc[0]
                profile_cols = _v306_13_7_8_pd.to_numeric(_v306_13_7_8_pd.Series([row.get("ProfileColumns", 0)]), errors="coerce").fillna(0).iloc[0]
                base_mb = _v306_13_7_8_pd.to_numeric(_v306_13_7_8_pd.Series([row.get("BaseMemoryMB", 0)]), errors="coerce").fillna(0).iloc[0]
                profile_mb = _v306_13_7_8_pd.to_numeric(_v306_13_7_8_pd.Series([row.get("ProfileMemoryMB", 0)]), errors="coerce").fillna(0).iloc[0]
                profile = str(row.get("Profile", ""))
                rows.append({
                    "SourceFolder": row.get("SourceFolder", ""),
                    "Profile": profile,
                    "Rows": row.get("ProfileRows", row.get("BaseRows", "")),
                    "BaseColumns": int(base_cols),
                    "ProfileColumns": int(profile_cols),
                    "ColumnReduction": int(base_cols - profile_cols),
                    "BaseMemoryMB": round(float(base_mb), 4),
                    "ProfileMemoryMB": round(float(profile_mb), 4),
                    "MemoryReductionMB": round(float(base_mb - profile_mb), 4),
                    "MemoryReductionPct": round(((float(base_mb) - float(profile_mb)) / float(base_mb) * 100.0), 2) if float(base_mb) else 0.0,
                    "MissingColumns": row.get("MissingColumns", ""),
                    "ProfileStatus": row.get("Status", ""),
                    "SuggestedUse": (
                        "Common validation / price validation path" if "18" in profile or "common_validation" in profile else
                        "Concentration / holdings candidate path" if "25" in profile or "concentration" in profile else
                        "Movement / tolerance extended path" if "29" in profile or "movement" in profile else
                        "Current full safe profile"
                    ),
                    "PatchVersion": _V306_13_7_8_VERSION,
                })
            pass  # [removed] diagnostic CSV write
        except Exception as exc:
            err = _v306_13_7_8_pd.DataFrame([{
                "Status": "Skipped",
                "Detail": f"DAR slim projection not rebuilt: {type(exc).__name__}: {exc}",
                "PatchVersion": _V306_13_7_8_VERSION,
            }])
            try:
                pass  # [removed] diagnostic CSV write
            except Exception:
                pass

    def _v306_13_7_8_build_trend_timing_rollups(timing_csv_path):
        try:
            path = _v306_13_7_8_Path(timing_csv_path)
            if not path.exists():
                return
            df = _v306_13_7_8_pd.read_csv(path)
            if df.empty or "ElapsedSeconds" not in df.columns:
                return
            df = df.copy()
            for required in ["RunDate", "Scope", "Phase", "Status", "Detail", "TimingSource", "SourceFolder", "PatchVersion"]:
                if required not in df.columns:
                    df[required] = ""
            df["ElapsedSecondsNum"] = _v306_13_7_8_pd.to_numeric(df["ElapsedSeconds"], errors="coerce").fillna(0.0)
            df["RowsNum"] = _v306_13_7_8_pd.to_numeric(df.get("Rows", 0), errors="coerce").fillna(0.0)
            df["RunDateRollup"] = df["RunDate"].fillna("").astype(str).replace({"nan": ""})
            df.loc[df["RunDateRollup"].str.strip() == "", "RunDateRollup"] = "ALL / build-level"
            df["PhaseGroup"] = df.apply(lambda r: _v306_13_7_8_phase_group(r.get("Scope"), r.get("Phase"), r.get("Detail")), axis=1)
            df["ElapsedRole"] = df.apply(lambda r: _v306_13_7_8_elapsed_role(r.get("Scope"), r.get("Phase"), r.get("Detail")), axis=1)
            df["IsAdditive"] = df["ElapsedRole"].eq("Child")
            df["AdditiveElapsedSeconds"] = df["ElapsedSecondsNum"].where(df["IsAdditive"], 0.0)

            per_run = (
                df.groupby(["RunDateRollup", "PhaseGroup"], dropna=False)
                .agg(
                    Events=("Phase", "size"),
                    AdditiveEvents=("IsAdditive", "sum"),
                    TotalElapsedSeconds=("ElapsedSecondsNum", "sum"),
                    AdditiveElapsedSeconds=("AdditiveElapsedSeconds", "sum"),
                    MaxElapsedSeconds=("ElapsedSecondsNum", "max"),
                    TotalRows=("RowsNum", "sum"),
                    Roles=("ElapsedRole", lambda s: " | ".join(sorted({str(x) for x in s}))),
                    ExamplePhase=("Phase", lambda s: " | ".join([str(x) for x in s.dropna().astype(str).head(5).tolist()])),
                    ExampleStatus=("Status", lambda s: " | ".join([str(x) for x in s.dropna().astype(str).head(5).tolist()])),
                )
                .reset_index()
            )
            for col in ["TotalElapsedSeconds", "AdditiveElapsedSeconds", "MaxElapsedSeconds"]:
                per_run[col] = per_run[col].round(4)
            per_run["PatchVersion"] = _V306_13_7_8_VERSION
            per_run = per_run.sort_values(["RunDateRollup", "PhaseGroup"])
            pass  # [removed] diagnostic CSV write

            summary = (
                df.groupby(["PhaseGroup"], dropna=False)
                .agg(
                    Events=("Phase", "size"),
                    AdditiveEvents=("IsAdditive", "sum"),
                    TotalElapsedSeconds=("ElapsedSecondsNum", "sum"),
                    AdditiveElapsedSeconds=("AdditiveElapsedSeconds", "sum"),
                    MaxElapsedSeconds=("ElapsedSecondsNum", "max"),
                    TotalRows=("RowsNum", "sum"),
                    Roles=("ElapsedRole", lambda s: " | ".join(sorted({str(x) for x in s}))),
                    RunDates=("RunDateRollup", lambda s: " | ".join(sorted({str(x) for x in s if str(x).strip()}))),
                    ExamplePhase=("Phase", lambda s: " | ".join([str(x) for x in s.dropna().astype(str).head(8).tolist()])),
                )
                .reset_index()
            )
            for col in ["TotalElapsedSeconds", "AdditiveElapsedSeconds", "MaxElapsedSeconds"]:
                summary[col] = summary[col].round(4)
            additive_total = float(summary["AdditiveElapsedSeconds"].sum())
            summary["PctOfAdditiveElapsed"] = summary["AdditiveElapsedSeconds"].apply(lambda x: round((float(x) / additive_total * 100.0), 2) if additive_total else 0.0)
            summary["PatchVersion"] = _V306_13_7_8_VERSION
            summary = summary.sort_values(["AdditiveElapsedSeconds", "TotalElapsedSeconds"], ascending=False)
            pass  # [removed] diagnostic CSV write

            detail = (
                df.groupby(["RunDateRollup", "PhaseGroup", "ElapsedRole", "Scope", "TimingSource"], dropna=False)
                .agg(
                    Events=("Phase", "size"),
                    AdditiveEvents=("IsAdditive", "sum"),
                    TotalElapsedSeconds=("ElapsedSecondsNum", "sum"),
                    AdditiveElapsedSeconds=("AdditiveElapsedSeconds", "sum"),
                    MaxElapsedSeconds=("ElapsedSecondsNum", "max"),
                    ExamplePhase=("Phase", lambda s: " | ".join([str(x) for x in s.dropna().astype(str).head(5).tolist()])),
                )
                .reset_index()
            )
            for col in ["TotalElapsedSeconds", "AdditiveElapsedSeconds", "MaxElapsedSeconds"]:
                detail[col] = detail[col].round(4)
            detail["PatchVersion"] = _V306_13_7_8_VERSION
            detail = detail.sort_values(["RunDateRollup", "PhaseGroup", "ElapsedRole", "AdditiveElapsedSeconds"], ascending=[True, True, True, False])
            pass  # [removed] diagnostic CSV write

            _v306_13_7_8_build_slim_projection(path)
        except Exception as exc:
            try:
                err = _v306_13_7_8_pd.DataFrame([{
                    "Status": "Error",
                    "Detail": f"{type(exc).__name__}: {exc}",
                    "PatchVersion": _V306_13_7_8_VERSION,
                }])
                pass  # [removed] diagnostic CSV write
            except Exception:
                pass

    _v306_13_7_8_BASE_TO_CSV = globals().get("_v306_13_7_7_ORIGINAL_TO_CSV", None)
    if _v306_13_7_8_BASE_TO_CSV is None:
        _v306_13_7_8_BASE_TO_CSV = getattr(_v306_13_7_8_pd.DataFrame, "to_csv")

    if not getattr(_v306_13_7_8_pd.DataFrame, "_v306_13_7_8_rollup_patched", False):
        def _v306_13_7_8_to_csv_wrapper(self, path_or_buf=None, *args, **kwargs):
            result = _v306_13_7_8_BASE_TO_CSV(self, path_or_buf, *args, **kwargs)
            try:
                path_text = str(path_or_buf or "")
                normalised = path_text.replace("/", _v306_13_7_8_os.sep).lower()
                if normalised.endswith("trend_timing_diagnostics_last_run.csv"):
                    _v306_13_7_8_build_trend_timing_rollups(path_or_buf)
            except Exception:
                pass
            return result

        _v306_13_7_8_pd.DataFrame.to_csv = _v306_13_7_8_to_csv_wrapper
        _v306_13_7_8_pd.DataFrame._v306_13_7_8_rollup_patched = True

except Exception:
    pass


# ========================================================
# v306.13.7.7 Trend History timing rollup diagnostics
# - Generates phase rollups whenever trend_timing_diagnostics_last_run.csv is written
# - Also repairs dar_trend_slim_projection_last_run.csv from DAR profile A/B diagnostics when available
# ========================================================
try:
    import os as _v306_13_7_7_os
    from pathlib import Path as _v306_13_7_7_Path
    import pandas as _v306_13_7_7_pd

    def _v306_13_7_7_phase_group(scope, phase, detail=""):
        text = (str(scope or "") + " " + str(phase or "") + " " + str(detail or "")).lower()
        if "source.folder_fingerprint" in text or "folder fingerprint" in text:
            return "01 folder fingerprint"
        if "dassetreturn selected" in text or "dassetreturn total" in text or "dassetreturn source" in text:
            return "02 DAssetReturn parse/load"
        if "ddetailedreturn" in text:
            return "03 DDetailedReturn parse/load"
        if "dassettypereturn" in text:
            return "04 DAssetTypeReturn parse/load"
        if "benchmarkstatic" in text:
            return "05 BenchmarkStatic parse/load"
        if "persistent source dataframe cache" in text or "bnp load:" in text:
            return "06 persistent source cache"
        if "arc " in text or "arc_" in text or "prepare arc" in text:
            return "07 ARC load"
        if "fx find" in text or "fx workbook" in text or "fx diagnostics" in text or "fx load" in text or "fx validation" in text:
            return "08 FX load/validation"
        if "process_day" in text or "process day" in text:
            return "09 process_day core"
        if "portfolio calc" in text or "transaction map" in text:
            return "10 portfolio calc / transaction map"
        if "build executive summary" in text or "snapshot.executive" in text or "executive_summary" in text:
            return "11 executive summary / snapshot"
        if "minimum validation" in text:
            return "12 minimum validation"
        if "common candidate" in text or "common_validation" in text:
            return "13 common validation candidates"
        if "cache.read" in text or "cache.write" in text or "cache.dedupe" in text or "cache.filter" in text:
            return "14 trend cache read/write/filter"
        if "bundle.prepare_out_dashboard_bundle" in text:
            return "15 bundle.prepare_out_dashboard_bundle"
        if "trend_history.total" in text or "total_build" in text:
            return "99 trend history total"
        return "98 other / unclassified"

    def _v306_13_7_7_safe_number(series):
        return _v306_13_7_7_pd.to_numeric(series, errors="coerce").fillna(0.0)

    def _v306_13_7_7_write_df(df, path):
        # Use original pandas writer to avoid triggering nested diagnostics.
        return None  # [removed] diagnostic CSV write

    def _v306_13_7_7_build_slim_projection(timing_csv_path):
        try:
            base_dir = _v306_13_7_7_Path(timing_csv_path).parent
            ab_path = base_dir / "dar_profile_ab_comparison_last_run.csv"
            if not ab_path.exists():
                return
            ab = _v306_13_7_7_pd.read_csv(ab_path)
            if ab.empty:
                return
            keep = []
            for _, row in ab.iterrows():
                profile = str(row.get("Profile", ""))
                base_cols = _v306_13_7_7_safe_number(_v306_13_7_7_pd.Series([row.get("BaseColumns", 0)])).iloc[0]
                profile_cols = _v306_13_7_7_safe_number(_v306_13_7_7_pd.Series([row.get("ProfileColumns", 0)])).iloc[0]
                base_mb = _v306_13_7_7_safe_number(_v306_13_7_7_pd.Series([row.get("BaseMemoryMB", 0)])).iloc[0]
                profile_mb = _v306_13_7_7_safe_number(_v306_13_7_7_pd.Series([row.get("ProfileMemoryMB", 0)])).iloc[0]
                keep.append({
                    "SourceFolder": row.get("SourceFolder", ""),
                    "Profile": profile,
                    "Rows": row.get("ProfileRows", row.get("BaseRows", "")),
                    "BaseColumns": int(base_cols),
                    "ProfileColumns": int(profile_cols),
                    "ColumnReduction": int(base_cols - profile_cols),
                    "BaseMemoryMB": round(float(base_mb), 4),
                    "ProfileMemoryMB": round(float(profile_mb), 4),
                    "MemoryReductionMB": round(float(base_mb - profile_mb), 4),
                    "MemoryReductionPct": round(((float(base_mb) - float(profile_mb)) / float(base_mb) * 100.0), 2) if float(base_mb) else 0.0,
                    "MissingColumns": row.get("MissingColumns", ""),
                    "ProfileStatus": row.get("Status", ""),
                    "SuggestedUse": (
                        "Common validation / price validation path" if "18" in profile or "common_validation" in profile else
                        "Concentration / holdings candidate path" if "25" in profile or "concentration" in profile else
                        "Movement / tolerance extended path" if "29" in profile or "movement" in profile else
                        "Current full safe profile"
                    ),
                    "PatchVersion": "v306.13.7.7_trend_timing_rollup_and_slim_projection",
                })
            out = _v306_13_7_7_pd.DataFrame(keep)
            _v306_13_7_7_write_df(out, base_dir / "dar_trend_slim_projection_last_run.csv")
        except Exception as exc:
            try:
                err = _v306_13_7_7_pd.DataFrame([{
                    "Status": "Error",
                    "Detail": f"{type(exc).__name__}: {exc}",
                    "PatchVersion": "v306.13.7.7_trend_timing_rollup_and_slim_projection",
                }])
                _v306_13_7_7_write_df(err, _v306_13_7_7_Path(timing_csv_path).parent / "dar_trend_slim_projection_last_run.csv")
            except Exception:
                pass

    def _v306_13_7_7_build_trend_timing_rollups(timing_csv_path):
        try:
            path = _v306_13_7_7_Path(timing_csv_path)
            if not path.exists():
                return
            df = _v306_13_7_7_pd.read_csv(path)
            if df.empty or "ElapsedSeconds" not in df.columns:
                return
            df = df.copy()
            for required in ["RunDate", "Scope", "Phase", "Status", "Detail", "TimingSource", "SourceFolder", "PatchVersion"]:
                if required not in df.columns:
                    df[required] = ""
            df["ElapsedSecondsNum"] = _v306_13_7_7_pd.to_numeric(df["ElapsedSeconds"], errors="coerce").fillna(0.0)
            df["RowsNum"] = _v306_13_7_7_pd.to_numeric(df.get("Rows", 0), errors="coerce").fillna(0.0)
            df["RunDateRollup"] = df["RunDate"].fillna("").astype(str).replace({"nan": ""})
            df.loc[df["RunDateRollup"].str.strip() == "", "RunDateRollup"] = "ALL / build-level"
            df["PhaseGroup"] = df.apply(lambda r: _v306_13_7_7_phase_group(r.get("Scope"), r.get("Phase"), r.get("Detail")), axis=1)

            per_run = (
                df.groupby(["RunDateRollup", "PhaseGroup"], dropna=False)
                .agg(
                    Events=("Phase", "size"),
                    TotalElapsedSeconds=("ElapsedSecondsNum", "sum"),
                    MaxElapsedSeconds=("ElapsedSecondsNum", "max"),
                    TotalRows=("RowsNum", "sum"),
                    ExamplePhase=("Phase", lambda s: " | ".join([str(x) for x in s.dropna().astype(str).head(5).tolist()])),
                    ExampleStatus=("Status", lambda s: " | ".join([str(x) for x in s.dropna().astype(str).head(5).tolist()])),
                )
                .reset_index()
            )
            per_run["TotalElapsedSeconds"] = per_run["TotalElapsedSeconds"].round(4)
            per_run["MaxElapsedSeconds"] = per_run["MaxElapsedSeconds"].round(4)
            per_run["PatchVersion"] = "v306.13.7.7_trend_timing_rollup"
            per_run = per_run.sort_values(["RunDateRollup", "PhaseGroup"])
            _v306_13_7_7_write_df(per_run, path.parent / "trend_timing_rollup_last_run.csv")

            summary = (
                df.groupby(["PhaseGroup"], dropna=False)
                .agg(
                    Events=("Phase", "size"),
                    TotalElapsedSeconds=("ElapsedSecondsNum", "sum"),
                    MaxElapsedSeconds=("ElapsedSecondsNum", "max"),
                    TotalRows=("RowsNum", "sum"),
                    RunDates=("RunDateRollup", lambda s: " | ".join(sorted({str(x) for x in s if str(x).strip()}))),
                    ExamplePhase=("Phase", lambda s: " | ".join([str(x) for x in s.dropna().astype(str).head(8).tolist()])),
                )
                .reset_index()
            )
            summary["TotalElapsedSeconds"] = summary["TotalElapsedSeconds"].round(4)
            summary["MaxElapsedSeconds"] = summary["MaxElapsedSeconds"].round(4)
            total = float(summary["TotalElapsedSeconds"].sum())
            summary["PctOfRolledUpElapsed"] = summary["TotalElapsedSeconds"].apply(lambda x: round((float(x) / total * 100.0), 2) if total else 0.0)
            summary["PatchVersion"] = "v306.13.7.7_trend_timing_rollup"
            summary = summary.sort_values(["TotalElapsedSeconds"], ascending=False)
            _v306_13_7_7_write_df(summary, path.parent / "trend_timing_rollup_summary_last_run.csv")

            detail = (
                df.groupby(["RunDateRollup", "PhaseGroup", "Scope", "TimingSource"], dropna=False)
                .agg(
                    Events=("Phase", "size"),
                    TotalElapsedSeconds=("ElapsedSecondsNum", "sum"),
                    MaxElapsedSeconds=("ElapsedSecondsNum", "max"),
                    ExamplePhase=("Phase", lambda s: " | ".join([str(x) for x in s.dropna().astype(str).head(5).tolist()])),
                )
                .reset_index()
            )
            detail["TotalElapsedSeconds"] = detail["TotalElapsedSeconds"].round(4)
            detail["MaxElapsedSeconds"] = detail["MaxElapsedSeconds"].round(4)
            detail["PatchVersion"] = "v306.13.7.7_trend_timing_rollup"
            detail = detail.sort_values(["RunDateRollup", "PhaseGroup", "TotalElapsedSeconds"], ascending=[True, True, False])
            _v306_13_7_7_write_df(detail, path.parent / "trend_timing_rollup_detail_last_run.csv")

            _v306_13_7_7_build_slim_projection(path)
        except Exception as exc:
            try:
                err = _v306_13_7_7_pd.DataFrame([{
                    "Status": "Error",
                    "Detail": f"{type(exc).__name__}: {exc}",
                    "PatchVersion": "v306.13.7.7_trend_timing_rollup",
                }])
                _v306_13_7_7_write_df(err, _v306_13_7_7_Path(timing_csv_path).parent / "trend_timing_rollup_summary_last_run.csv")
            except Exception:
                pass

    if not getattr(_v306_13_7_7_pd.DataFrame, "_v306_13_7_7_trend_rollup_patched", False):
        _v306_13_7_7_ORIGINAL_TO_CSV = _v306_13_7_7_pd.DataFrame.to_csv

        def _v306_13_7_7_to_csv_wrapper(self, path_or_buf=None, *args, **kwargs):
            result = _v306_13_7_7_ORIGINAL_TO_CSV(self, path_or_buf, *args, **kwargs)
            try:
                path_text = str(path_or_buf or "")
                normalised = path_text.replace("/", _v306_13_7_7_os.sep).lower()
                if normalised.endswith("trend_timing_diagnostics_last_run.csv"):
                    _v306_13_7_7_build_trend_timing_rollups(path_or_buf)
            except Exception:
                pass
            return result

        _v306_13_7_7_pd.DataFrame.to_csv = _v306_13_7_7_to_csv_wrapper
        _v306_13_7_7_pd.DataFrame._v306_13_7_7_trend_rollup_patched = True
except Exception:
    pass


from bnp_helpers_columns import (
    COLUMN_ALIASES,
    _normalise_col_token,
    _prime_dataframe_col_index,
    find_col,
    find_exact_normalized_col,
    normalise_join_key_series,
    resolve_benchmark_code_col,
    resolve_col,
    resolve_driver_label_col,
    resolve_fdv_current_value_col,
)
from bnp_helpers_columns import (
    _clean_mojibake_text,
    _date_string_yyyy_mm_dd,
    _decimal_string,
    _excel_currency_string,
    _percent_string_1dp,
    _percent_string_2dp,
)
from bnp_helpers_columns import (
    _coerce_mixed_object_series_to_string,
    _coerce_numeric_like,
    make_arrow_safe,
    num,
)
from bnp_helpers_processing import (
    configure_processing,
    process_day as _process_day_impl,
)
# v370: facade elimination. process_day is now a DIRECT ALIAS to the real
# implementation in bnp_helpers_processing.py, rather than a hand-copied thin
# wrapper function with its own separately-maintained parameter list. The old
# facade's only two jobs (call configure_processing(), then forward every
# argument to _process_day_impl) are preserved exactly - configure_processing()
# now runs inside _call_process_day_v304_3_1 (the sole caller of process_day),
# immediately before process_day is invoked, at the exact same point in program
# flow as before (zero timing/behaviour change). This permanently fixes the
# class of bug that caused the v369 hotfix (a parameter added to the real
# process_day - folder_fingerprint_override - silently missing from the app's
# hand-copied facade signature): inspect.signature(process_day) now always sees
# the REAL signature, automatically, with no manual mirroring required ever
# again. See CHANGELOG.md v370.
process_day = _process_day_impl
import bnp_helpers_ingestion as ingestion_v162
# v368: removed 'import bnp_helpers_arc as arc_v162' - bnp_helpers_arc.py is fully
# dead. ARC is no longer an input source (confirmed 2026-08): the live error-risk
# classifier sources exclusively from BP Impact Tool.xlsb via bnp_helpers_error_risk.py
# (_prepare_error_risk_source_v306_13_9), and the three former arc_v162 pass-through
# wrappers (_inspect_arc_workbook, _load_excel_sheet_normalised,
# _find_arc_workbook_for_date) had zero callers anywhere in this file or any helper
# module - confirmed via full-codebase search before removal. See CHANGELOG.md v368.
import bnp_helpers_exchange_rates as exchange_rates_v168

# v306.13.9: BP Impact Tool Error Risk Report replaces ARC error-risk sheet load.
try:
    from bnp_helpers_error_risk import prepare_error_risk_source as _prepare_error_risk_source_v306_13_9
except Exception:
    _prepare_error_risk_source_v306_13_9 = None
import bnp_helpers_fx_validation as fx_validation_v172
from bnp_helpers_transactionlisting import (
    apply_transaction_control_break_eligibility,
    build_transactionlisting_detail_rows,
)

# v306.13.8: Static Data workbook and Tableau/Unison BO source loading helpers.
try:
    from bnp_helpers_static_data import (
        load_static_data as _load_static_data_v306_13_8,
        get_config_value as _static_get_config_value_v306_13_8,
        get_threshold_value as _static_get_threshold_value_v306_13_8,
        get_active_table as _static_get_active_table_v306_13_8,
        build_ingestion_config as _static_build_ingestion_config_v306_13_8,
    )
    from bnp_helpers_tableau import prepare_tableau_sources as _prepare_tableau_sources_v306_13_8
except Exception:
    _static_get_active_table_v306_13_8 = None
    _load_static_data_v306_13_8 = None
    _static_get_config_value_v306_13_8 = None
    _static_get_threshold_value_v306_13_8 = None
    _static_build_ingestion_config_v306_13_8 = None
    _prepare_tableau_sources_v306_13_8 = None

# ========================================================
# v307 ARC REPLACEMENT - FOUNDATIONS & SLIM CONFIG
# ========================================================
# Additive, guarded imports for the v307 foundation modules. All fail safe so
# the app still runs if a module is absent.
# v368: removed 'from bnp_helpers_parity import render_parity_tab' - Parity Matrix
# audit-index tab removed at user request; bnp_helpers_parity.py has been deleted
# entirely. See CHANGELOG.md v368.
try:
    from bnp_helpers_error_risk import compute_hotcold_invariant as _compute_hotcold_invariant_v307
except Exception:
    _compute_hotcold_invariant_v307 = None
try:
    import bnp_helpers_static_data as _code_contracts_v307
except Exception:
    _code_contracts_v307 = None
try:
    from bnp_helpers_universe import render_universe_section as _render_universe_section_v308
    from bnp_helpers_universe import load_universe as _load_universe_v328, UniverseResult as _UniverseResult_v328
except Exception:
    _render_universe_section_v308 = None
    _load_universe_v328 = None
    _UniverseResult_v328 = None
try:
    from bnp_helpers_gav import render_gav_section as _render_gav_section_v309
except Exception:
    _render_gav_section_v309 = None
try:
    from bnp_helpers_uut import render_v311_1_corrected as _render_uut_v311_1
    from bnp_helpers_uut import render_advisor_uut_gav_style as _render_advisor_uut_gav_v359
except Exception:
    _render_uut_v311_1 = None
    _render_advisor_uut_gav_v359 = None
try:
    from bnp_helpers_uut import render_uut_section as _render_uut_section_v311
    from bnp_helpers_fdv_enrichment import load_fdv_enrichment_lookup as _fdv_load_lookup_v320, enrich_with_fdv as _fdv_enrich_v320, FDV_FIELDS as _FDV_FIELDS_v320
except Exception:
    _render_uut_section_v311 = None
    _fdv_load_lookup_v320 = None
    _fdv_enrich_v320 = None
# v344: Advisor-UUT internal step-timing hooks (used to break the ~24s render into
# FDV T load / FDV T-1 load / join+weight / aggregate / Unison map / advisor merge).
try:
    from bnp_helpers_uut import uut_reset_timings as _uut_reset_timings_v344, uut_get_timings as _uut_get_timings_v344
except Exception:
    _uut_reset_timings_v344 = None
    _uut_get_timings_v344 = None
    _FDV_FIELDS_v320 = {}
try:
    from bnp_helpers_price_integrity import (
        render_price_integrity_section as _render_price_integrity_v313,
        build_price_integrity as _build_price_integrity_v358_3,
        render_uut_material_mvt_gav_style as _render_uut_material_mvt_gav_v359,
        render_stale_price_gav_style as _render_stale_price_gav_v359,
    )
except Exception:
    _render_price_integrity_v313 = None
    _build_price_integrity_v358_3 = None
    _render_uut_material_mvt_gav_v359 = None
    _render_stale_price_gav_v359 = None
try:
    from bnp_helpers_outputs import render_outputs_section as _render_outputs_v314
except Exception:
    _render_outputs_v314 = None
try:
    # v315: ARC-named "Download everything" reconciliation workbook.
    from bnp_helpers_reconciliation_export import render_reconciliation_export as _render_recon_export_v315
except Exception:
    _render_recon_export_v315 = None
try:
    from bnp_helpers_ancillary import (
        render_ancillary_section as _render_ancillary_section_v312,
        render_investment_clearing_gav_style as _render_investment_clearing_gav_v359,
        render_cash_clearing_gav_style as _render_cash_clearing_gav_v359,
        render_negative_nav_gav_style as _render_negative_nav_gav_v359,
        render_liquidity_gav_style as _render_liquidity_gav_v361,
    )
except Exception:
    _render_ancillary_section_v312 = None
    _render_investment_clearing_gav_v359 = None
    _render_cash_clearing_gav_v359 = None
    _render_negative_nav_gav_v359 = None
    _render_liquidity_gav_v361 = None
try:
    from bnp_helpers_universe import render_portfolios_reconciliation_gav_style as _render_portfolios_recon_gav_v359
except Exception:
    _render_portfolios_recon_gav_v359 = None
try:
    from bnp_helpers_return_check import render_return_check_section as _render_return_check_section_v310
    from bnp_helpers_return_check import render_advisor_return_gav_style as _render_advisor_return_gav_v359
    from bnp_helpers_return_check import (
        attach_unison_volatility_column as _attach_unison_vot_v310_1,
        record_hotcold_reclassification as _record_hotcold_reclass_v310_1,
    )
except Exception:
    _render_return_check_section_v310 = None
    _render_advisor_return_gav_v359 = None
    _attach_unison_vot_v310_1 = None
    _record_hotcold_reclass_v310_1 = None

# ========================================================
# PHASE 1/2/3 SAFETY NOTES
# ========================================================
# - Streamlit bootstrap is deferred to main() so the module can be imported by
#   validation tooling without immediately rendering the dashboard.
# - Low-risk pure helpers are split into dedicated modules.
# - The processing core now lives in bnp_helpers_processing.py and is called via
#   a thin process_day() facade to preserve the public interface.



import streamlit as st

# ========================================================
# HELPER IMPORT CONTRACT CHECKS
# ========================================================
def _validate_helper_import_contract() -> None:
    required = {
        "COLUMN_ALIASES": COLUMN_ALIASES,
        "resolve_fdv_current_value_col": resolve_fdv_current_value_col,
        "resolve_driver_label_col": resolve_driver_label_col,
        "resolve_benchmark_code_col": resolve_benchmark_code_col,
        "num": num,
        "make_arrow_safe": make_arrow_safe,
    }
    missing = [name for name, value in required.items() if value is None]
    if missing:
        raise RuntimeError(
            "Main helper import contract failed: missing " + ", ".join(sorted(missing))
        )



# ========================================================
# CONFIG
# ========================================================
ROOT_FOLDER = r"\\hq.local\Corp\IOOF\Finance\IAS\Fund Accounting\Unit Pricing\BAU\MLCI & NULIS\Unison Pricing\Reports - BNPP"
CACHE_DIR = os.environ.get("TREND_CACHE_DIR", "").strip() or "./trend_cache"
os.makedirs(CACHE_DIR, exist_ok=True)
CACHE_VERSION = "v106_split_stale_and_material_subsections"

SUMMARY_FILE = os.path.join(CACHE_DIR, "trend_summary.parquet")
DRIVER_FILE = os.path.join(CACHE_DIR, "driver_breakdown.parquet")
COMMON_VALIDATION_CANDIDATES_FILE = os.path.join(CACHE_DIR, "common_validation_candidates_by_asset_type.parquet")
BMK_FILE = os.path.join(CACHE_DIR, "benchmark_breakdown.parquet")
PORTFOLIO_FILE = os.path.join(CACHE_DIR, "portfolio_detail.parquet")
DIAGNOSTIC_FILE = os.path.join(CACHE_DIR, "diagnostics.parquet")
EXCEPTION_FILE = os.path.join(CACHE_DIR, "processing_exceptions.parquet")
INDEX_FILE = os.path.join(CACHE_DIR, "history_index.parquet")
THRESHOLD_STATE_FILE = os.path.join(CACHE_DIR, "threshold_state.json")
SIDEBAR_SETTINGS_FILE = os.path.join(CACHE_DIR, "sidebar_settings.json")

SHOW_DEBUG = False
APP_PYTHON_VERSION = "v362 (Input Sources tab added, Control checks tab added, Single Portfolio Drill-through / Daily Movements renames, Input Sources restructured with download-all)"
# v357.1: RE-APPLIED the v354 basis-impact memoisation (lost in the v352.1->v355->
# v356->v357 rebuild lineage). The render-side
# _apply_basis_impact_error_risk_classification_v306_14_5 was running on EVERY
# Streamlit rerun (every click), even on a bundle cache hit - a full copy+groupby+
# row-match (~0.2s) with no idempotency guard, adding lag to every interaction. It now
# runs ONCE per date and skips on repeat clicks via the _basis_impact_classified_v354
# date-key flag (mirroring the working _bpimpact_classified_v344 overview-tab pattern),
# showing "basis-impact classification (cached)" 0.0s on subsequent clicks. No
# behaviour change - identical classification, just not recomputed redundantly. The
# separate v344 overview-tab classification guard and _v325_warm_checks guard were
# already present; a render-path sweep confirmed this was the only unguarded per-rerun
# recompute remaining.
# v357: control-break source-integrity check REBASED from excess to Actual Return.
# The surfaced "N control-break mismatches" warning (and the Portfolio Numbers ->
# Portfolios review table) previously compared DDetailedReturn Over/Under to summed
# DAssetReturn Excess Contribution. That excess basis was noisy (30 mismatches on
# 05-Aug, median gap 0.38pp). v357 replaces it with the "do the parts add up to the
# whole?" check: A = DDetailedReturn Actual Return vs B = summed DAssetReturn
# Asset-to-Portfolio Contributions, at the same 1bp tolerance. On 05-Aug this is a
# tighter, more meaningful 17-portfolio list (median gap 0.0000; led by M2AMP4 ~13pp).
# processing.py: adds _resolve_dassetreturn_contribution_by_portfolio + the A/B/gap
# columns and repoints "Source vs DAssetReturn Match Status" (+ mismatch count/warning)
# to the Actual-Return basis; the old excess columns are retained as
# "Source vs DAssetReturn Excess Match Status" for audit, and the Transaction-aware
# Control Break fallback (which uses the excess TOTAL) is unchanged. app: the v356
# Portfolios review panel now reads the Actual-Return A/B/gap columns.
# v356: three changes.
#  (1) CONTROL-BREAK MISMATCH DISPLAY (Portfolio Numbers -> Portfolios): the
#      "N DAssetReturn control-break mismatches" warning is now shown as a read-only,
#      ranked table (_render_control_break_source_mismatches_v356) reusing the existing
#      per-portfolio A-vs-B data in bundle['control_break_audit_df']. A = DDetailed
#      break, B = summed DAssetReturn line excess; flagged when |A-B| > 0.01pp (1bp).
#      Display-only - no logic/tolerance/classification change.
#  (2) STATIC DATA VALIDATOR FALSE-ALARM FIX (bnp_helpers_static_data.py): the required
#      -sheets list still demanded source_file_keywords / excluded_filename_tokens /
#      header_contracts, which v307 intentionally moved into code. Their (correct)
#      absence flagged the workbook as "Error" / DEGRADED. Removed from REQUIRED_SHEETS
#      / REQUIRED_COLUMNS (kept as CODE_OWNED_SHEETS for clarity). No data restored.
#  (3) FX WORKBOOK PATH CACHE (bnp_helpers_exchange_rates.py): the residual ~2.3s "FX
#      workbook" cost that didn't drop on revisit was the os.walk discovery of the
#      "04 Externals*" subtree. find_internal_securities_master_for_date now memoises
#      the resolved workbook path per (root, date); a cache hit skips the walk (path is
#      re-validated with os.path.exists). Force-refresh clears it. Parse handled by the
#      existing v346 sheet cache; this removes the last uncached FX discovery step.
# v355 PROTOTYPE (measure-only, default OFF): render the executive card with NATIVE
# Streamlit widgets as an A/B alternative to the custom-HTML component. The run-log
# showed "15 render executive summary HTML" ~3s at cold load - the cost is Streamlit
# MOUNTING the HTML component (st.html in v352 did not help, because it mounts too).
# This adds:
#   * a sidebar toggle "Exec card: native widgets (prototype)" (default OFF),
#   * _render_exec_card_native() - same numbers via st.container/columns/metric +
#     st.dataframe (no HTML-component mount),
#   * _driver_stage_matrix_rows_data() - the driver table as structured data (mirrors
#     the HTML builder's exact ordering/selection; number-parity verified).
# The existing HTML card is UNCHANGED and remains the default, so there is zero risk
# until you switch the toggle on. IMPORTANT: I cannot measure Streamlit render time in
# the sandbox - toggle it in your environment and compare the "15 render executive
# summary HTML" run-log row (native ON vs OFF) to decide if it is worth adopting. The
# native card's visual style differs from the blue-gradient HTML card (a UX trade-off).
# v352.1 CRASH FIX: KeyError "External portfolio reference norm". The v352 BP Impact
# Advisor-key fix populated arc_portfolio_df (previously always empty), which woke a
# DORMANT legacy ARC-schema consumer in _prepare_out_dashboard_bundle that expects the
# old ARC columns "External portfolio reference norm" / "ARC Hiport Code norm". The BP
# Impact replacement frame (Parent/Advisor/Error Risk Ratio) doesn't have them, so it
# KeyError'd. Each merge is now guarded by its required column, so the block stays
# dormant for the BP Impact schema (exactly as it behaved when the frame was empty)
# while the v352 Advisor coverage fix (warning cleared, 19,962 rows bound) stands.
# Hot/Cold classification is unaffected - it runs via the separate basis-impact path.
# v352: folder-scan three-tier + exec-render transport + BP Impact key fix.
#  (1) FOLDER SCAN (~14s -> ms on the morning open): _load_or_build_bnp_date_folder_cache
#      is now three-tier - reuse the persisted manifest if it already has the latest
#      expected BUSINESS day (Sat/Sun roll back to Fri, per the real workflow); else an
#      INCREMENTAL PROBE that lists only the relevant MONTH folder(s) to pick up a new
#      day (not the whole YYYY/MM/DD tree); else a FULL-SCAN fallback (forced refresh,
#      no cache, gap > 45 days, or any probe error). Fully guarded - degrades to the
#      v351 full scan, so date discovery is never worse. The "Refresh date folder scan"
#      button forces the full walk.
#  (2) EXEC RENDER ("15 render executive summary HTML" ~3s -> ~0.1s): _render_inline_html
#      now prefers st.html() over st.iframe(data:URI). The card HTML is a tiny trusted
#      ~2 KB string; the old iframe path URL-encoded the whole doc into a data: URI on
#      every render. st.html renders it natively; iframe kept only as a fallback.
#  (3) BP IMPACT WARNING FIX (correctness): the "Error Risk Report" sheet is keyed by
#      "Advisor"/"Parent", not the names the resolver looked for - so coverage never
#      bound and the app logged "portfolio coverage columns were not resolved". Added
#      "Advisor"/"Parent" to the key candidates (confirmed: Advisor maps to portfolio);
#      verified against the real workbook - binds all 19,962 rows, warning clears.
# v351.1 FIX: FDV/Excel pickle DIRECTORY + scan fold-in.
#  * PICKLE DIR BUG (the reason v351 reopens never hit): main() pointed the FDV and
#    Excel pickle caches at os.getcwd()/.bnp_manifest_cache. Under `streamlit run` the
#    working directory is usually NOT the app folder (and may be non-writable), so the
#    FDV pickle was written to the wrong place and reopens re-read ~22s every time. The
#    v351-era run-logs confirmed this (FDV 13-30s on every interaction, never cached).
#    v351.1 points both pickle caches at _manifest_cache_dir() - the SAME directory the
#    BNP source pickle uses (Path(__file__).parent/.bnp_manifest_cache), the one that
#    already works on reopen. This is the fix that should finally make a date REVISIT
#    (no refresh) drop FDV from ~22s to ~1s.
#  * SCAN FOLD-IN: the FDV T-1 resolver re-walked the year folder over G:/ with
#    os.scandir to find the previous day's folder, even though the "Scan BNP date
#    folders" stage already cached every date folder in session_state. v351.1 reuses
#    that cached list (falls back to the scandir walk only if unavailable). Small win
#    (~0.76s), removes a redundant network walk.
# v351 FDV PICKLE-PERSIST; remove parquet, copy-local, calamine + sidebar toggles.
# Benchmarks/logs settled the direction: the ~23s cold-load cost is the FIRST read of
# the ~59 MB of FDV CSVs over G:/ (pure network; local parse <1s). The other BNP
# reports pay the same cold cost but feel fast because they ride a persistent PICKLE
# cache (folder-fingerprint keyed) that makes REOPENS ~1s - and FDV was loaded OUTSIDE
# that cache. v350's Parquet + copy-local experiment is removed (copy-local made the
# first read WORSE - 64s - on this bandwidth-capped share; parquet didn't reliably
# engage on reopen). calamine gave no measurable gain (it can't touch the FDV CSV) and
# carried dtype risk. This build:
#   * FDV: persists the parsed shared frame as a local PICKLE keyed by (path,size,mtime)
#     in the SAME .bnp_manifest_cache folder the BNP source pickle uses. Reopen of a
#     date reads the pickle (~0.05s) instead of re-reading G:/. Parity verified on the
#     real files (pickle round-trip byte-identical; first read then pickle hit).
#   * Excel (FX/ER) cache: calamine engine path removed; on-disk cache switched from
#     Parquet to pickle (mem cache retained). "remove parquet entirely".
#   * Sidebar: "Fast Excel engine (calamine)" and "Copy-local FDV reads" toggles and
#     all their wiring removed. Force-refresh clears the FDV + Excel pickle caches.
# Modules changed: fdv_enrichment, columns, app. No new dependencies.
# v350 FDV PARQUET-PERSIST + COPY-LOCAL (attack the ~23s first FDV network read).
# The v349 run-log named the ~31s cold-load gap: it was the FIRST read of the ~59 MB
# of FDV CSVs over G:/ = 23.2s (network, not parse). The v345 shared frame already
# guarantees the files are read ONCE (later UUT loads were 0.39/0.47s cache hits) -
# so the only lever left is making that one read cheaper / avoidable:
#   * PARQUET-PERSIST: after the first parse, the shared named-column frame is written
#     to a local Parquet keyed by (path,size,mtime). Every REOPEN of that date - even
#     after an app restart - reads local Parquet (~1s) instead of G:/. Certain win on
#     reopens, regardless of why SMB is slow.
#   * COPY-LOCAL: first read streams one sequential shutil.copy of each network FDV to
#     a local temp, then parses locally. Big win if G:/ is latency-bound (the 2.5 MB/s
#     effective rate strongly suggests it); neutral (never slower - guarded fallback)
#     if bandwidth-capped. Toggle "Copy-local FDV reads" (default on) to A/B it.
# Parity: the parsed frame is byte-identical to the v349 direct read (canonical column
# order now applied so parse / Parquet-write / Parquet-read all match). Verified by an
# internal parity + persist test (copy-local parity, Parquet round-trip, single-read
# E2E across all consumers). Force-refresh drops the Parquet too. Modules changed:
# fdv_enrichment, app. Local cache dir: .bnp_fdv_cache (override BNP_FDV_CACHE_DIR).
# v349 INSTRUMENT-ONLY: name the ~31s cold-load HANDOFF GAP + the BNP cache miss.
# The v348 log proved the "Load FX & Error Risk files" stage is ~85% mislabelled -
# only ~5.7s is real FX/ER work, and a 30.9s window sits BETWEEN the last prepare
# step and the first executive-summary step (StartedAt 1304.15 -> 1335.06). That gap
# is the post-prepare wrapper + render-side handoff, which neither the v348 prepare
# nor exec-summary mirror touches. It also showed the BNP source cache REBUILT (19.4s)
# instead of hitting. This build adds deep timers (Phase "Post-prepare (gap)") around:
#   * _v311_resolve_fdv_paths TOTAL (the whole post-prepare resolver)
#   * FDV T-1 sibling-folder scandir walk (G:/ network directory walk)
#   * FDV enrichment lookup build (first full FDV read)
#   * basis-impact error-risk classification (render-side, pre-exec-summary)
# and records WHY the BNP source cache missed (MissReason + CacheExistedAtEntry +
# ForceRefresh), surfaced in the run-log detail. No behaviour change - one run now
# names the 31s culprit and says whether the fingerprint changed between runs.
# v348 INSTRUMENT-ONLY: decompose the ~39s uninstrumented cold-load gap. The v347 log
# proved the FX validation retests are trivial (0.67s + 0.69s) and the workbook parses
# are only ~5s - yet the "Load FX & Error Risk files" stage is ~38s. The remainder was
# invisible because those steps report via _record_prepare_timing / _exec_mark (which
# feed the loading-progress cards), NOT the deep-timing run-log. This build MIRRORS
# both of those timers into the deep-timing store (no behaviour change), so the next
# run-log shows every prepare phase (process_day, ARC enrichment, Hot/Cold, the shared
# Tier 1 assignment build, shared section artefacts) as Phase "Prepare bundle", and
# every executive-summary build step as Phase "Executive summary build" - pinning the
# real ~32s culprit before any optimisation.
# v347 INSTRUMENT-ONLY: measure the real split of the ~43s "Load FX & Error Risk
# files" stage. The v346 run-log proved the two workbook PARSES are only ~5s (Error
# Risk .xlsb 1.85s, FX .xlsx 3.37s) - so ~38s of that stage is NON-parse compute,
# almost certainly the FX contribution retests that run right after the FX source
# load. This build adds deep timers (NO behaviour change) around:
#   * "FX validation - initial contribution retest" (build_portfolio_fx_validation #1)
#   * "FX validation - final HOT-scoped contribution retest" (build #2, post-ARC)
#   * "FX validation - apply tier1 driver assignments to FX summary"
#   * "Cold load - Scan BNP date folders (network walk)"
# so one run's run-log shows exactly where the stage time goes before any fix. All
# timers are guarded and fall back cleanly; the store lives in st.session_state.
# v346 CACHED EXCEL READER for FX + ERROR RISK (G:/ network) + optional calamine
#  * SHARED CACHED EXCEL READER (in bnp_helpers_columns): each (file version, sheet,
#    header) is parsed from the network AT MOST ONCE - in-process cache + a local
#    Parquet cache so re-opening a date already loaded reads Parquet in ms.
#    error_risk._read_excel_flexible and the FX per-sheet reads route through it.
#  * PARITY-PRESERVING BY DEFAULT (pyxlsb/.xlsb, openpyxl/.xlsx). python-calamine
#    (Rust, ~10-18x faster) is used ONLY when the "Fast Excel engine (calamine)"
#    sidebar toggle is on, because its dtype inference differs and needs validating.
#  * Local cache dir set at startup; force-refresh clears the Excel cache (incl
#    Parquet); FX/Error-Risk loads are deep-timed and cache stats shown in diagnostics.
# v346.1 FIX: the calamine sidebar toggle previously lived inside the same try/except
# as the cache-dir setup, so if that setup threw (e.g. columns.py not yet deployed, or
# __file__ unavailable under `streamlit run`) the WHOLE block was skipped and the
# toggle silently vanished. The checkbox is now created FIRST and standalone, uses
# os.getcwd() instead of __file__, and each setup step is guarded independently - so
# the control always renders.
# NOTE: this build also requires the v346 helper files bnp_helpers_columns.py,
# bnp_helpers_error_risk.py and bnp_helpers_exchange_rates.py to be deployed for the
# caching to actually engage; the app-side imports are guarded so it degrades safely
# (no crash, no speed-up) if they are not yet present.
# v345 SHARED FDV FRAME (single source of truth) + CENTRAL MAPPING CACHE
# The warm-load timing log proved the real cost: the ~59 MB of FDV files (on a G:/
# network share) were read 4-5 SEPARATE times per cold load - UUT base build, UUT
# scope, price-integrity stale + material movement, and the enrichment lookup - each
# a row-by-row csv.reader pass costing ~11s/fileset over the network (~24s just for
# the UUT base build's two reads). And the Central Mapping workbook was re-opened via
# openpyxl on EVERY Advisor-UUT (corrected) click - the bulk of the ~23s warm render.
# This build:
#  * SHARED FDV FRAME - bnp_helpers_fdv_enrichment.load_fdv_frame reads each physical
#    FDV file from G:/ EXACTLY ONCE per process (vectorised, quote-aware pd.read_csv),
#    caches it by (path,size,mtime), and ALL consumers - UUT load_fdv_holdings /
#    load_uut_scope_from_fdv, price-integrity _load_fdv_prices, and the enrichment
#    lookup - now slice these cached frames. Parity verified on the live files:
#    holdings 27,923 rows byte-identical; scope securities/portfolios/pairs identical;
#    prices identical (with/without weight); enrichment 0 cell diffs.
#  * CENTRAL MAPPING CACHE - load_central_mapping_advisor_attrs caches the parsed
#    attrs by (path,size,mtime), so the G:/ workbook is opened once per version, not
#    every click. Expected warm Advisor-UUT ~23s -> ~1-2s.
#  * TIMING - the previously-BLIND corrected-panel path (resolve_uut_scope /
#    load_central_mapping_attrs / apply_v311_1) is now instrumented, and force-refresh
#    clears the FDV + Central Mapping caches for a clean audit trail.
# Expected: cold load ~114s -> ~30-40s (FDV read once, vectorised); warm Advisor-UUT
# ~24s -> low single digits. Modules changed: fdv_enrichment, uut, price_integrity, app.
# v344 TIMING DEEP-DIVE + PER-CLICK MEMOISATION
# Driven by the accumulated run-log, which pinned the render hotspot to ARC:
# Advisor-UUT (~24s EVERY click - genuinely rebuilt, not a cache hit) while every
# other section was <2.5s. This build does three things (no caching of the UUT
# frame itself, per request):
#  (1) COLD-LOAD INSTRUMENTATION - _v325_warm_checks now times EACH warm-up check
#      individually (Phase "Warm-up (cold load)"). Since warm-up runs the two UUT
#      builds once at load, this finally exposes the ~24s hiding inside the ~114s
#      cold "Render dashboard tabs".
#  (2) MEMOISE PER-CLICK OVERHEAD - the three non-ARC BP-Impact classification passes
#      and the iterrows-built group map were re-running on every Portfolio Numbers
#      click (~1.5s fixed overhead). Both are now computed ONCE per date and reused
#      (Phase "Overview tab overhead", with CacheHit flagged).
#  (3) ADVISOR-UUT INTERNAL BREAKDOWN (no cache) - bnp_helpers_uut now records
#      per-step timings (FDV T load / FDV T-1 load / join+weight / aggregate / Unison
#      map / advisor merge) which the app drains into the run-log as Phase
#      "Advisor-UUT internal". Prime suspect: the two row-by-row csv.reader FDV loads
#      in load_fdv_holdings (same anti-pattern vectorised in v343 enrichment).
# Timing coverage now spans all clickable units: main tabs, ARC + non-ARC
# sub-sections, warm-up checks, overview-tab overhead, and the UUT internal steps.
# v343 FDV LOADER ALIGNMENT (Part B) + ACCUMULATING TIMING LOG (Part C)
# Part B - FDV valuation now loads through the same vectorised, quote-aware path as
#          the other BNP reports (bnp_helpers_fdv_enrichment rewritten):
#            * NAMED-COLUMN resolution replaces hard-coded positional indices
#              (verified against all six live FDV files - headers identical, 92-wide).
#            * Quote-aware pandas.read_csv replaces the row-by-row csv.reader loop
#              (the files are quoted and carry embedded commas).
#            * A SINGLE df.merge replaces the 15x per-column .map(lambda) enrich.
#            * FIRST-WINS preserved via de-dupe-before-merge, so enriched row counts
#              are byte-identical to the legacy dict (parity test: 0 cell diffs over
#              15 cols x 5,003 rows; 24,302 keys match). ~1.4x faster lookup build,
#              ~1.8x faster enrich.
#            * Lookup is now built ONCE at load-time (alongside the other reports)
#              and cached, so render-side enrich is instant (no lazy first-click cost).
# Part C - The deep-timing run-log now ACCUMULATES across clicks. It was being wiped
#          at the start of every Streamlit rerun (so the exported CSV only ever had
#          the last sub-section). It now lives in st.session_state, stamps each row
#          with an Interaction counter, and is cleared only via a new "Clear timing
#          log" button in the diagnostics panel - so a full click-through builds ONE
#          exportable CSV.
# v342 DIAGNOSTICS CLEANUP + OPTION B DEEP TIMING
# Phase 1 - Collapsed the THREE identical "Diagnostic support - source load checks"
#           renderers (v306_13_11/_12/_14) into ONE. The old loop drew three
#           identical expanders and re-ran the same show_df work 3x on every
#           Portfolio Numbers render. Removed the two duplicate renderers and the
#           v11-only summary builder (dead code); kept the v14 renderer and the _12
#           summary it reuses.
# Phase 2 - Flattened the single panel: every detail table now renders as a headed
#           section (all shown at once), no nested collapsibles.
# Phase 3 - Removed the standalone "Diagnostics / support" expander and folded its
#           RETAINED tables (File load metadata, Run diagnostics, Processing
#           exceptions, Date-folder / BNP source / process_day cache status) into the
#           single panel. Dropped by request: Regular type debug, ARC mapping
#           preview, and ALL exchange-rate resolver/extraction/probe/preview blocks.
# Phase 4 - Source-load summary is computed ONCE per selected date and cached on the
#           bundle (_erdiag_cached_source_summary_v342), so re-opening the panel no
#           longer rebuilds it.
# Option B - Added a reusable deep-timing layer (_deep_timer context manager +
#           per-run store) that records the elapsed time of each dashboard tab and
#           each Portfolio Numbers sub-section (ARC + non-ARC). The consolidated
#           panel shows the per-step run-log with slowest-step callout and a
#           "Download detailed timing run-log CSV" button. This pinpoints exactly
#           which sub-section drives the ~114s "Render dashboard tabs" wallclock.
# v341 FIX (On UNISON sub-sections/radio disappearing): the executive card renders
# inside its own guarded placeholder so it always survives, but the section radio
# and every sub-section BELOW it were rendered UNGUARDED. Any exception raised on
# the On UNISON path (the only group with a non-empty scoped frame - Off UNISON and
# IISL scope to empty and safely no-op) aborted the whole region, leaving the card
# but no radio/sub-sections. This build FENCES the render regions rather than
# chasing individual throwers (the recurring root cause behind v333-v340):
#   (1) the Dashboard section radio + each _render_*_tab call are wrapped so a
#       section failure surfaces st.error() instead of killing the page;
#   (2) the non-ARC Portfolio Numbers sub-section dispatch is guarded the same way
#       the ARC panels already are (_render_pn_arc_panel);
#   (3) _build_hot_largest_tier1_driver_table tolerates a missing
#       "ARC Asset Type of portfolio" column instead of raising a raw KeyError.


# v306.13.0: canonical labels/colours for Trend Portfolio Numbers and Unexplained review sections.
TREND_PORTFOLIO_NUMBER_ORDER = ["Within tolerance", "Cold", "Hot"]
TREND_PORTFOLIO_NUMBER_COLOURS = {
    "Hot": "#D62728",              # red
    "Within tolerance": "#2CA02C", # green
    "Cold": "#FFC000",            # amber
}
TREND_HOT_WATERFALL_COLOURS = {
    "Auto explained by FX": "#2CA02C",
    "Nil actual return": "#FFC000",
    "Current Account dominated": "#9467BD",
    "Unexplained": "#D62728",
}
TREND_DEFAULT_COLOUR_RANGE = [
    "#1F77B4", "#FF7F0E", "#2CA02C", "#D62728", "#9467BD", "#8C564B",
    "#E377C2", "#7F7F7F", "#BCBD22", "#17BECF", "#636EFA", "#EF553B",
    "#00CC96", "#AB63FA", "#FFA15A",
]
UNEXPLAINED_REVIEW_SECTION_ORDER = [
    "Summary",
    "Common validation candidates",
    "Near zero actual yet benchmark movement",
    "Other",
]
STANDARD_PROMPT_SHEET_NAME = "standard prompt"
COMMON_VALIDATION_CANDIDATES_SHEET_NAME = "common validation candidates"
FULLY_PAID_ORDINARY_SHARE_LABEL = "Fully Paid Ordinary Share"
LOCAL_PRICE_VALIDATION_TEMPLATE_DEFAULT = r"C:\Users\cxp029\Downloads\Latest\local_price_validation_evidence_template.xlsx"
LOCAL_PRICE_VALIDATION_EVIDENCE_SHEET = "local_price_validation_evidence"
COPILOT_TEMPLATE_FILEPATH_SETTING_KEY = "copilot_prompt_package_template_filepath"
USER_SETTINGS_FILE = os.path.join(CACHE_DIR, "bnp_control_app_user_settings.json")
LOCAL_PRICE_VALIDATION_EVIDENCE_COLUMNS = ["Effective_date", "Portfolio", "Asset Type description", "Asset Code", "Asset Name", "CCY", "Asset Price Prev_Day", "Asset Price Curr_Day", "Actual Return", "Price Return", "Independent Source Name", "Independent Source URL", "Independent Source Accessed Date", "Independent Prev_Day Local Price", "Independent Curr_Day Local Price", "Independent Calculated Price Return", "Price Return Difference vs DAssetReturn", "Prev_Day Price Difference vs DAssetReturn", "Curr_Day Price Difference vs DAssetReturn", "Price Unit Checked", "Security Identity Validated", "Currency Validated", "Price Dates Validated", "Price Movement Direction Validated", "Return Recalculation Validated", "Validation Result", "Validation Notes", "Reviewer", "Review Date"]




MONTH_MAP = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}

REQUIRED_FILE_KEYWORDS = ["DDetailedReturn"]
OPTIONAL_FILE_KEYWORDS = ["DAssetTypeReturn", "DAssetReturn", "TransactionListing", "BenchmarkStatic"]
EXCLUDED_FILENAME_TOKENS = ["unverified"]
DEFAULT_EXCLUDE_AMOUNT = 100.0
DEFAULT_CURRENT_ACCOUNT_DOMINANCE_THRESHOLD_PCT = 80.0
CURRENT_ACCOUNT_ASSET_TYPE_CODE = "ZL01"
HOT_PORTFOLIO_TOOLTIP = "Hot portfolios: Outside-tolerance portfolios where, if the reported total movement is incorrect, the impact is likely to be material enough to result in a unit pricing error."
COLD_PORTFOLIO_TOOLTIP = "Cold portfolios: Outside-tolerance portfolios where, if the reported total movement is incorrect, diversification within the investment structure means the isolated impact is unlikely to result in a unit pricing error."

HEADER_CONTRACTS = {
    "DDetailedReturn": {
        "required_groups": [
            ["portfolio code", "portfoliocode", "portfolio"],
        ],
    },
    "DAssetTypeReturn": {
        "required_groups": [
            ["portfolio code", "portfoliocode", "portfolio"],
            ["asset type", "assettypename", "asset type name", "asset group", "asset group name", "driver"],
        ],
    },
    "BenchmarkStatic": {
        "required_groups": [
            ["portfolio code", "portfoliocode", "portfolio"],
            ["benchmark code", "benchmarkcode", "benchmark id", "benchmarkid", "index code", "indexcode", "bmk code", "bmkcode", "benchmark"],
        ],
    },
}


# ========================================================
# TEMPLATE-DRIVEN DISPLAY CONFIG
# ========================================================
BASE_PORTFOLIO_TEMPLATE_COLUMNS = [
    "Effective_Date", "Trust/Sector", "Portfolio code", "External portfolio reference",
    "Portfolio Name", "Portfolio Type", "FDV Cost(Previous Day)", "FDV Valuation(Previous Day)",
    "FDV Cashflow", "FDV Cost(Current Day)", "FDV Valuation(Current Day)", "Movement",
    "Change in Unrealised Profit", "Asset return %", "Income return %",
    "Expense Settlement Impact %", "Other%", "Actual Return", "Benchmark Return",
    "Actual vs Benchmark", "Tolerance", "Status", "Over/Under", "Comment",
    "SourcePath", "RunDate", "FolderFingerprint", "CacheVersion",
]
BASE_PORTFOLIO_TEMPLATE_FORMATS = {
    "Effective_Date": "yyyy-mm-dd",
    "FDV Cost(Previous Day)": "$#,##0.00;[Red]($#,##0.00)",
    "FDV Valuation(Previous Day)": "$#,##0.00;[Red]($#,##0.00)",
    "FDV Cashflow": "$#,##0.00;[Red]($#,##0.00)",
    "FDV Cost(Current Day)": "$#,##0.00;[Red]($#,##0.00)",
    "FDV Valuation(Current Day)": "$#,##0.00;[Red]($#,##0.00)",
    "Movement": "$#,##0.00;[Red]($#,##0.00)",
    "Change in Unrealised Profit": "$#,##0.00;[Red]($#,##0.00)",
}
VIEW_TEMPLATES = {
    "raw_out_detail": {
        "visible_columns": BASE_PORTFOLIO_TEMPLATE_COLUMNS,
        "formats": BASE_PORTFOLIO_TEMPLATE_FORMATS,
    },
    "portfolio_explorer": {
        "visible_columns": BASE_PORTFOLIO_TEMPLATE_COLUMNS + ["Portfolio"],
        "formats": {**BASE_PORTFOLIO_TEMPLATE_FORMATS, "Over/Under": "2 dp"},
    },
    "driver_reconciliation": {
        "visible_columns": [
            "Driver", "WeightedOutPortfolioCount", "RunDate", "FolderFingerprint",
            "ReconciliationTotal", "CacheVersion",
        ],
        "formats": {
            "WeightedOutPortfolioCount": "2 dp",
        },
    },
    "benchmark_reconciliation": {
        "visible_columns": [
            "BenchmarkCode", "OutPortfolioCount", "RunDate", "FolderFingerprint",
            "ReconciliationTotal", "CacheVersion",
        ],
        "formats": {},
    },
}

# ========================================================
# PATH / DATE HELPERS
# ========================================================
def parse_date_from_path(path: str) -> Optional[date]:
    r"""Tolerant parsing of ...\YYYY\MM Mmm\DD Mmm style folders."""
    try:
        parts = Path(path).parts
        if len(parts) < 3:
            return None
        year_part, month_part, day_part = parts[-3], parts[-2], parts[-1]

        year_match = re.search(r"(19\d{2}|20\d{2})", str(year_part))
        mon_match = re.search(r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b", str(month_part), re.I)
        day_match = re.search(r"\b(\d{1,2})\b", str(day_part))
        if not (year_match and mon_match and day_match):
            return None

        year = int(year_match.group(1))
        month = MONTH_MAP[mon_match.group(1).title()]
        day = int(day_match.group(1))
        return datetime(year, month, day).date()
    except Exception:
        return None


def _manifest_cache_dir() -> Path:
    # v375: MANIFEST_CACHE_DIR environment variable override. Checked FIRST so
    # .bnp_manifest_cache can be pointed at cache\ (or anywhere else) instead
    # of always sitting beside bnp_control_app.py. Falls back to the ORIGINAL
    # behaviour (Path(__file__).resolve().parent, then cwd) if the variable is
    # unset or invalid - so this is a no-op until Launch_Latest.bat actually
    # sets it.
    override = os.environ.get("MANIFEST_CACHE_DIR", "").strip()
    if override:
        try:
            cache_dir = Path(override).resolve()
            cache_dir.mkdir(parents=True, exist_ok=True)
            return cache_dir
        except Exception:
            pass  # fall through to original behaviour below
    try:
        base = Path(__file__).resolve().parent
    except Exception:
        base = Path.cwd()
    cache_dir = base / ".bnp_manifest_cache"
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        cache_dir = Path.cwd()
    return cache_dir


def _date_folder_cache_path(root: str) -> Path:
    root_norm = str(Path(str(root)).resolve()) if str(root or "").strip() else ""
    key = hashlib.md5(f"BNP_DATE_FOLDERS|{root_norm}|{CACHE_VERSION}".encode("utf-8", errors="ignore")).hexdigest()[:16]
    return _manifest_cache_dir() / f"bnp_date_folders_{key}.pkl"


def _scan_bnp_date_folders_direct(root: str) -> pd.DataFrame:
    """Scan only the expected YYYY / MM Mmm / DD Mmm date-folder levels.

    v300 safety fix: v299 recursively walked the full BNP root and could block
    startup on deep network folder trees. This direct scan preserves the original
    date-folder discovery scope while still enabling daily persistent caching.
    """
    built_at = datetime.now()
    root_path = Path(root)
    rows: List[Dict[str, object]] = []
    if not root_path.exists():
        return pd.DataFrame(columns=["RunDate", "Folder", "ManifestBuiltAt"])
    try:
        year_dirs = [p for p in root_path.iterdir() if p.is_dir()]
    except Exception:
        year_dirs = []
    for year_dir in year_dirs:
        try:
            month_dirs = [p for p in year_dir.iterdir() if p.is_dir()]
        except Exception:
            month_dirs = []
        for month_dir in month_dirs:
            try:
                day_dirs = [p for p in month_dir.iterdir() if p.is_dir()]
            except Exception:
                day_dirs = []
            for day_dir in day_dirs:
                dt = parse_date_from_path(str(day_dir))
                if dt is not None:
                    rows.append({"RunDate": dt, "Folder": str(day_dir), "ManifestBuiltAt": built_at})
    out = pd.DataFrame(rows)
    if not out.empty:
        out = out.drop_duplicates(subset=["RunDate", "Folder"]).sort_values(["RunDate", "Folder"]).reset_index(drop=True)
    return out


# v352: date -> month-folder path (inverse of parse_date_from_path), matching the
# on-disk naming "...\YYYY\MM Mmm\". Reused month-folder listing lets the incremental
# probe find a new day WITHOUT re-walking the whole tree.
_V352_MONTH_ABBR = {1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
                    7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"}


def _v352_month_folder_path(root: str, dt: date) -> str:
    try:
        return os.path.join(str(root or ""), f"{int(dt.year)}",
                            f"{int(dt.month):02d} {_V352_MONTH_ABBR.get(int(dt.month), '')}".strip())
    except Exception:
        return ""


def _v352_latest_expected_business_day(today: date) -> date:
    """The most recent business day on/before `today` (Sat/Sun roll back to Friday).
    Used to decide whether a probe is even needed - if the cache already has this
    date, there is nothing new to find. Public holidays are handled naturally: the
    isdir/listing simply won't find a folder, so we fall through to the next check."""
    wd = today.weekday()  # Mon=0 .. Sun=6
    if wd == 5:   # Saturday -> Friday
        return today - timedelta(days=1)
    if wd == 6:   # Sunday -> Friday
        return today - timedelta(days=2)
    return today


def _v352_list_month_day_folders(root: str, dt: date) -> List[Dict[str, object]]:
    """List the day folders inside ONE month folder (root\\YYYY\\MM Mmm) and return
    parsed {RunDate, Folder} rows. One directory listing, not a full-tree walk."""
    rows: List[Dict[str, object]] = []
    mfolder = _v352_month_folder_path(root, dt)
    try:
        if mfolder and os.path.isdir(mfolder):
            for entry in os.scandir(mfolder):
                if entry.is_dir():
                    d = parse_date_from_path(entry.path)
                    if d is not None:
                        rows.append({"RunDate": d, "Folder": str(entry.path)})
    except Exception:
        pass
    return rows


def _load_or_build_bnp_date_folder_cache(root: str, force_refresh: bool = False) -> Tuple[pd.DataFrame, Dict[str, object]]:
    """Return the BNP date-folder list.

    v352 THREE-TIER (replaces the v304.4 full-scan-every-load):
      * Tier 1 - reuse the persisted manifest if it already contains the latest
        expected BUSINESS day (Sat/Sun roll back to Fri), i.e. nothing new to find.
      * Tier 2 - INCREMENTAL PROBE: list only the relevant MONTH folder(s) between the
        last cached date and today (usually just the current month) to pick up a newly
        created day folder, then append + re-persist. Milliseconds vs the ~14s tree
        walk, and it still discovers each morning's new folder.
      * Tier 3 - FULL SCAN fallback: on force_refresh, no cache, an unusually large
        gap (spanning many months), or any probe uncertainty. This is the original
        _scan_bnp_date_folders_direct, so behaviour degrades safely to v351.
    Fully guarded - any failure falls back to the full scan, so date discovery can
    never be worse than before.
    """
    started = time.perf_counter()
    cache_path = _date_folder_cache_path(root)
    today = datetime.now().date()

    def _finish(folders_df, status_note, tier):
        built_at_val = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if isinstance(folders_df, pd.DataFrame) and not folders_df.empty:
            folders_df = folders_df.drop_duplicates(subset=["RunDate", "Folder"]).sort_values(["RunDate", "Folder"]).reset_index(drop=True)
            if "ManifestBuiltAt" not in folders_df.columns:
                folders_df["ManifestBuiltAt"] = built_at_val
        status = {
            "Manifest": "BNP date folders", "RootPath": str(root), "CachePath": str(cache_path),
            "Status": status_note, "Tier": tier,
            "Rows": int(len(folders_df)) if isinstance(folders_df, pd.DataFrame) else 0,
            "BuiltAt": built_at_val,
            "RefreshMode": "v352 three-tier (freshness skip / month-folder incremental probe / full-scan fallback)",
            "ElapsedSeconds": float(time.perf_counter() - started),
        }
        return folders_df, status

    # Tier 3 trigger: explicit refresh -> always full walk + persist
    if bool(force_refresh):
        folders_df = _scan_bnp_date_folders_direct(root)
        try:
            pd.to_pickle(folders_df, cache_path)
        except Exception:
            pass
        return _finish(folders_df, "Full scan (forced refresh)", "3 (full scan)")

    # Try to load the persisted manifest
    cached_df = None
    try:
        if cache_path.exists():
            payload = pd.read_pickle(cache_path)
            if isinstance(payload, pd.DataFrame) and not payload.empty and {"RunDate", "Folder"}.issubset(payload.columns):
                cached_df = payload.copy()
                cached_df["RunDate"] = pd.to_datetime(cached_df["RunDate"], errors="coerce").dt.date
                cached_df = cached_df.dropna(subset=["RunDate"])
    except Exception:
        cached_df = None

    if cached_df is None or cached_df.empty:
        # No usable cache -> full walk + persist (first ever run)
        folders_df = _scan_bnp_date_folders_direct(root)
        try:
            pd.to_pickle(folders_df, cache_path)
        except Exception:
            pass
        return _finish(folders_df, "Full scan (no usable cache)", "3 (full scan)")

    try:
        last_known = max(cached_df["RunDate"].tolist())
        target = _v352_latest_expected_business_day(today)

        # Tier 1: cache already has the latest expected business day -> reuse as-is
        if last_known >= target:
            return _finish(cached_df, "Reused persisted manifest (already current)", "1 (freshness skip)")

        # Tier 3 trigger: gap too large (spans many months) -> safer to full-walk
        if (today - last_known).days > 45:
            folders_df = _scan_bnp_date_folders_direct(root)
            try:
                pd.to_pickle(folders_df, cache_path)
            except Exception:
                pass
            return _finish(folders_df, "Full scan (cache gap > 45 days)", "3 (full scan)")

        # Tier 2: incremental probe - list only the month folder(s) from last_known..today
        new_rows: List[Dict[str, object]] = []
        probe_month = date(last_known.year, last_known.month, 1)
        end_month = date(today.year, today.month, 1)
        months_listed = 0
        while probe_month <= end_month and months_listed < 4:
            for r in _v352_list_month_day_folders(root, probe_month):
                if r["RunDate"] > last_known:
                    new_rows.append(r)
            months_listed += 1
            # advance to first of next month
            if probe_month.month == 12:
                probe_month = date(probe_month.year + 1, 1, 1)
            else:
                probe_month = date(probe_month.year, probe_month.month + 1, 1)

        if new_rows:
            merged = pd.concat([cached_df[["RunDate", "Folder"]], pd.DataFrame(new_rows)], ignore_index=True)
            try:
                pd.to_pickle(merged, cache_path)
            except Exception:
                pass
            return _finish(merged, f"Incremental probe found {len(new_rows)} new day folder(s)", "2 (incremental probe)")

        # Probe found nothing new (weekend/holiday, or feed not yet delivered) -> reuse cache
        return _finish(cached_df, "Incremental probe: no new day folder; reused manifest", "2 (incremental probe)")
    except Exception:
        # Any uncertainty -> safe full walk
        folders_df = _scan_bnp_date_folders_direct(root)
        try:
            pd.to_pickle(folders_df, cache_path)
        except Exception:
            pass
        return _finish(folders_df, "Full scan (probe error fallback)", "3 (full scan)")

def _manifest_status_df() -> pd.DataFrame:
    rows = []
    for key in ["_bnp_manifest_status"]:
        val = st.session_state.get(key, None) if hasattr(st, "session_state") else None
        if isinstance(val, dict):
            rows.append(val)
    return pd.DataFrame(rows)


def scan_folders(root: str, force_refresh: bool = False) -> List[Tuple[date, str]]:
    # v347 (instrument-only): deep-time the BNP date-folder scan (a network directory
    # walk, ~13s in the dashboard stage bar) so the run-log shows its true cost.
    try:
        with _deep_timer({}, "Cold load", "Scan BNP date folders (network walk)"):
            folders_df, status = _load_or_build_bnp_date_folder_cache(root, force_refresh=force_refresh)
    except Exception:
        folders_df, status = _load_or_build_bnp_date_folder_cache(root, force_refresh=force_refresh)
    try:
        st.session_state["_bnp_manifest_status"] = status
        st.session_state["_bnp_date_folder_cache_df"] = folders_df
    except Exception:
        pass
    if folders_df is None or not isinstance(folders_df, pd.DataFrame) or folders_df.empty:
        return []
    out: List[Tuple[date, str]] = []
    for _, row in folders_df.iterrows():
        try:
            out.append((pd.to_datetime(row.get("RunDate")).date(), str(row.get("Folder", ""))))
        except Exception:
            pass
    return sorted(out, key=lambda x: x[0])


def _persistent_date_cache_key(folder: str, folder_fp: str, cache_version: str, purpose: str, extra: str = "") -> str:
    folder_norm = str(Path(str(folder)).resolve()) if str(folder or "").strip() else ""
    raw = f"{purpose}|{folder_norm}|{folder_fp}|{cache_version}|{extra}"
    return hashlib.md5(raw.encode("utf-8", errors="ignore")).hexdigest()[:20]


def _persistent_date_cache_path(folder: str, folder_fp: str, cache_version: str, purpose: str, extra: str = "") -> Path:
    return _manifest_cache_dir() / f"{purpose.lower()}_{_persistent_date_cache_key(folder, folder_fp, cache_version, purpose, extra)}.pkl"




def _label_bnp_load_timing_scope(timing_df: pd.DataFrame, cache_status: Dict[str, object]) -> pd.DataFrame:
    """Clarify whether bnp_load_timing_df reflects current rebuild time or historical cached-payload build time."""
    if timing_df is None or not isinstance(timing_df, pd.DataFrame):
        return pd.DataFrame()
    out = timing_df.copy()
    status = str(cache_status.get("Status", "")) if isinstance(cache_status, dict) else ""
    if status == "Loaded from persistent cache":
        out["Timing Scope"] = "Historical payload-build timing, not current-run wall-clock"
    else:
        out["Timing Scope"] = "Current-run source rebuild timing"
    return out
def _cache_status_df(status: Dict[str, object]) -> pd.DataFrame:
    return pd.DataFrame([status]) if isinstance(status, dict) and status else pd.DataFrame()


def _load_bnp_source_persistent_cached(folder: str, folder_fp: str, cache_version: str, force_refresh: bool = False) -> Tuple[Dict[str, object], Dict[str, object]]:
    """Persistent per-date cache for cleaned/primed BNP source dataframes.

    v301: target current-date reloads and date switching by avoiding repeated parsing
    of DDetailedReturn, DAssetTypeReturn, DAssetReturn, TransactionListing and BenchmarkStatic
    when the selected folder fingerprint is unchanged.
    """
    started = time.perf_counter()
    cache_path = _persistent_date_cache_path(folder, folder_fp, cache_version, "BNP_SOURCE")
    # v349 (instrument-only): capture WHY the BNP source cache misses. The v348 log
    # showed this rebuilt (19.4s) instead of hitting. Record whether the cache file
    # existed at entry, the force-refresh flag, and a plain-English miss reason, so
    # the diagnostics/run-log show if the fingerprint changed between runs (orphaning
    # the pickle) vs a genuine cold first build. No behaviour change.
    _cache_existed_at_entry = False
    try:
        _cache_existed_at_entry = bool(cache_path.exists())
    except Exception:
        _cache_existed_at_entry = False
    status: Dict[str, object] = {
        "Cache": "BNP source dataframes",
        "Folder": str(folder),
        "CachePath": str(cache_path),
        "Status": "",
        "ElapsedSeconds": 0.0,
        "FolderFingerprint": str(folder_fp),
        "CacheVersion": str(cache_version),
        "CacheExistedAtEntry": _cache_existed_at_entry,
        "ForceRefresh": bool(force_refresh),
        "MissReason": "",
    }
    if not force_refresh and cache_path.exists():
        try:
            payload = pd.read_pickle(cache_path)
            if isinstance(payload, dict):
                status["Status"] = "Loaded from persistent cache"
                status["MissReason"] = "N/A (cache hit)"
                status["ElapsedSeconds"] = float(time.perf_counter() - started)
                status["TimingScope"] = "Current run cache read; bnp_load_timing_df is historical payload-build timing"
                return payload, status
        except Exception as exc:
            status["Status"] = f"Cache read failed; rebuilt: {type(exc).__name__}: {exc}"
            status["MissReason"] = f"Cache file existed but read failed: {type(exc).__name__}: {exc}"
    # classify the miss reason for the rebuild path
    if not status.get("MissReason"):
        if bool(force_refresh):
            status["MissReason"] = "Forced source refresh"
        elif not _cache_existed_at_entry:
            status["MissReason"] = ("No cache file for this (folder fingerprint, cache version) - "
                                    "either a genuine first build, or the folder fingerprint CHANGED "
                                    "since the last run (orphaning the previous pickle).")
        else:
            status["MissReason"] = "Cache file existed but was not a usable dict payload; rebuilt."
    rebuild_started = time.perf_counter()
    try:
        # v302: use the faster read_csv-backed source loader for first-build/current-date rebuilds.
        loaded = load_day_files_v184_readcsv_cached(folder, folder_fp, cache_version)
        status["BuildLoader"] = "v184 read_csv source load/prime"
    except Exception as exc:
        loaded = load_day_files_v183_aggregated_cached(folder, folder_fp, cache_version)
        status["BuildLoader"] = f"v183 fallback after {type(exc).__name__}"
    status["SourceBuildElapsedSeconds"] = float(time.perf_counter() - rebuild_started)
    try:
        pd.to_pickle(loaded, cache_path)
        if not status.get("Status"):
            status["Status"] = "Rebuilt and saved" if not force_refresh else "Force refreshed and saved"
    except Exception as exc:
        status["Status"] = f"Rebuilt; cache write failed: {type(exc).__name__}: {exc}"
    status["ElapsedSeconds"] = float(time.perf_counter() - started)
    status["TimingScope"] = "Current run rebuild" if "Rebuilt" in str(status.get("Status", "")) or "refreshed" in str(status.get("Status", "")).lower() else "Current run cache read"
    return loaded, status


def _call_process_day_v304_3_1(
    folder: str,
    *,
    progress_label: str,
    exclude_below_current_value: float,
    loaded_files: Dict[str, object],
    folder_fp: str,
) -> Dict[str, object]:
    """Call process_day with folder fingerprint override when supported.

    v304.3 required the matching bnp_helpers_processing.py. This guard keeps the
    app runnable if an older helper remains in the deployment folder, while the
    packaged v304.3.1 helper still provides the intended override behaviour.
    """
    kwargs = dict(
        progress_bar=None,
        status_text=None,
        summary_text=None,
        progress_label=progress_label,
        exclude_below_current_value=exclude_below_current_value,
        loaded_files=loaded_files,
    )
    try:
        import inspect
        if "folder_fingerprint_override" in inspect.signature(process_day).parameters:
            kwargs["folder_fingerprint_override"] = folder_fp
    except Exception:
        # If introspection fails, fall back to the historical signature rather than crash.
        pass
    # v370: configure_processing() moved here from the now-removed process_day()
    # facade - this is the ONLY caller of process_day in the whole app, so this
    # call fires at the exact same point in program flow, with the exact same
    # per-call timing, as it always did (zero behaviour change). process_day is
    # now a direct alias to the real bnp_helpers_processing.process_day, so the
    # inspect.signature() check above automatically sees any future parameter
    # added to the real implementation, with no facade signature to keep in
    # sync by hand. See CHANGELOG.md v370.
    configure_processing(
        cache_version=CACHE_VERSION,
        required_file_keywords=REQUIRED_FILE_KEYWORDS,
        parse_date_from_path_fn=parse_date_from_path,
        folder_fingerprint_fn=folder_fingerprint,
        load_day_files_fn=ingestion_v162.load_day_files,
        string_series_fn=_string_series,
        safe_series_fn=_safe_series,
        apply_fdv_exclusion_fn=apply_fdv_exclusion,
    )
    return process_day(folder, **kwargs)


def _load_process_day_persistent_cached(folder: str, folder_fp: str, exclude_below_current_value: float, cache_version: str, loaded_files: Dict[str, object], force_refresh: bool = False, use_persistent_cache: bool = False) -> Tuple[Dict[str, object], Dict[str, object]]:
    """Process day core output loader.

    v304.2: persistent process_day cache is bypassed by default because the
    internal process_day calculation is fast and the pickle write/read overhead
    was dominating normal one-day first loads. Set use_persistent_cache=True to
    retain the historical cache behaviour.
    """
    started = time.perf_counter()
    extra = f"exclude={float(exclude_below_current_value):.8f}"
    cache_path = _persistent_date_cache_path(folder, folder_fp, cache_version, "PROCESS_DAY", extra=extra)
    status: Dict[str, object] = {
        "Cache": "process_day core output",
        "Folder": str(folder),
        "CachePath": str(cache_path),
        "Status": "",
        "ElapsedSeconds": 0.0,
        "FolderFingerprint": str(folder_fp),
        "CacheVersion": str(cache_version),
        "Extra": extra,
    }
    if not use_persistent_cache:
        out = _call_process_day_v304_3_1(
            folder,
            progress_label="Direct day processing",
            exclude_below_current_value=exclude_below_current_value,
            loaded_files=loaded_files,
            folder_fp=folder_fp,
        )
        status["Status"] = "Bypassed persistent cache"
        status["TimingScope"] = "Current run direct process_day; no persistent cache read/write"
        status["OutputTables"] = ", ".join([f"{k}:{len(v):,}" for k, v in out.items() if isinstance(v, pd.DataFrame)]) if isinstance(out, dict) else ""
        status["CacheWriteElapsedSeconds"] = 0.0
        status["ElapsedSeconds"] = float(time.perf_counter() - started)
        return out, status

    if not force_refresh and cache_path.exists():
        try:
            payload = pd.read_pickle(cache_path)
            if isinstance(payload, dict):
                status["Status"] = "Loaded from persistent cache"
                status["ElapsedSeconds"] = float(time.perf_counter() - started)
                status["TimingScope"] = "Current run process_day cache read"
                return payload, status
        except Exception as exc:
            status["Status"] = f"Cache read failed; rebuilt: {type(exc).__name__}: {exc}"
    out = _call_process_day_v304_3_1(
        folder,
        progress_label="Persistent cached day processing",
        exclude_below_current_value=exclude_below_current_value,
        loaded_files=loaded_files,
        folder_fp=folder_fp,
    )
    status["OutputTables"] = ", ".join([f"{k}:{len(v):,}" for k, v in out.items() if isinstance(v, pd.DataFrame)]) if isinstance(out, dict) else ""
    cache_write_started = time.perf_counter()
    try:
        pd.to_pickle(out, cache_path)
        status["CacheWriteElapsedSeconds"] = float(time.perf_counter() - cache_write_started)
        if not status.get("Status"):
            status["Status"] = "Rebuilt and saved" if not force_refresh else "Force refreshed and saved"
    except Exception as exc:
        status["CacheWriteElapsedSeconds"] = float(time.perf_counter() - cache_write_started)
        status["Status"] = f"Rebuilt; cache write failed: {type(exc).__name__}: {exc}"
    status["ElapsedSeconds"] = float(time.perf_counter() - started)
    status["TimingScope"] = "Current run rebuild" if "Rebuilt" in str(status.get("Status", "")) or "refreshed" in str(status.get("Status", "")).lower() else "Current run cache read"
    return out, status


def folder_fingerprint(folder: str) -> str:
    """Simple fingerprint to detect folder content changes across refreshes.

    Uses nanosecond mtimes so same-second file rewrites are less likely to be missed.
    """
    try:
        parts = []
        for f in sorted(os.listdir(folder)):
            fp = os.path.join(folder, f)
            try:
                stat = os.stat(fp)
                parts.append(f"{f}|{stat.st_mtime_ns}|{stat.st_size}")
            except Exception:
                parts.append(f"{f}|ERR")
        payload = "||".join(parts).encode("utf-8", errors="replace")
        return hashlib.md5(payload).hexdigest()
    except Exception:
        return ""

# ========================================================
# v368: removed the dead CSV/HEADER UTILITIES cluster (_try_read_text,
# _sniff_delimiter, _robust_csv_to_df, _cell_clean, _row_profile,
# _detect_header_rows, _find_header_row_by_tokens, normalize_header,
# _describe_header_contract, _header_contract_met,
# _select_header_rows_for_keyword, _should_exclude_report_file, and this
# file's own load_csv_keyword wrapper) - confirmed dead: every function in
# this cluster only called others within the same cluster, and the
# cluster's only two entry points (load_day_files_cached,
# load_day_files_detailed_cached, both further down this file) had zero
# callers anywhere in the app. The live ingestion pipeline is
# bnp_helpers_ingestion.py (imported as ingestion_v162), used via
# ingestion_v162.load_csv_keyword / ingestion_v162.load_day_files
# elsewhere in this file. See CHANGELOG.md v368.
# ========================================================
# GENERIC HELPERS
# ========================================================














def _safe_series(df: pd.DataFrame, col: Optional[str]) -> pd.Series:
    if col is None or col not in df.columns:
        return pd.Series([pd.NA] * len(df), index=df.index)
    return df[col]


def _string_series(df: pd.DataFrame, col: Optional[str]) -> pd.Series:
    if col is None or col not in df.columns:
        return pd.Series([""] * len(df), index=df.index, dtype="object")
    return df[col].astype(str)



def _prepare_portfolio_code_frame(
    df: Optional[pd.DataFrame],
    source_col: Optional[str],
    *,
    output_name: str = "Portfolio code",
    extra_cols: Optional[List[str]] = None,
) -> pd.DataFrame:
    """Standardise portfolio-code dataframe prep for joins and indexing."""
    extra_cols = [c for c in (extra_cols or []) if c]
    selected_cols: List[str] = []
    for col in ([source_col] if source_col else []) + extra_cols:
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


def _build_portfolio_detail_index(df: Optional[pd.DataFrame]) -> Dict[str, pd.DataFrame]:
    if df is None or df.empty:
        return {}
    port_col = find_col(df, ["Portfolio code", "Portfolio", "portfolio"])
    if port_col is None or port_col not in df.columns:
        return {}
    tmp = df.copy()
    tmp[port_col] = _string_series(tmp, port_col).str.strip()
    tmp["portkey"] = normalise_join_key_series(tmp[port_col])
    tmp = tmp[tmp["portkey"].replace("", pd.NA).notna()].copy()
    return {str(key): group.drop(columns=["portkey"]).copy() for key, group in tmp.groupby("portkey", sort=False)}


















def apply_fdv_exclusion(df: Optional[pd.DataFrame], threshold: float, valuation_col: Optional[str]) -> Tuple[pd.DataFrame, int, int]:
    if df is None or df.empty:
        return pd.DataFrame(), 0, 0
    try:
        threshold = float(threshold or 0.0)
    except Exception:
        threshold = 0.0
    if threshold <= 0 or valuation_col is None or valuation_col not in df.columns:
        return df.copy(), 0, 0

    vals = pd.to_numeric(_safe_series(df, valuation_col), errors='coerce')
    non_numeric_mask = vals.isna()
    below_threshold_mask = vals.notna() & (vals.abs() < threshold)
    excluded_count = int(below_threshold_mask.sum())
    non_numeric_count = int(non_numeric_mask.sum())
    keep_mask = ~below_threshold_mask
    return df.loc[keep_mask].copy(), excluded_count, non_numeric_count


def _read_parquet_if_exists(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        return pd.DataFrame()
    try:
        return pd.read_parquet(path)
    except FileNotFoundError:
        return pd.DataFrame()
    except (OSError, ValueError, ImportError) as e:
        raise RuntimeError(f"Failed to read parquet cache '{path}': {type(e).__name__}: {e}") from e






def _is_count_like_column(col_name: object) -> bool:
    token = _normalise_col_token(col_name)
    return "count" in token or token.endswith("rows") or "rowcount" in token


def _format_numeric_df_for_display(df: Optional[pd.DataFrame]) -> pd.DataFrame:
    if df is None:
        return pd.DataFrame()
    if df.empty:
        out_empty = df.copy()
        if isinstance(out_empty, pd.DataFrame) and out_empty.columns.duplicated().any():
            out_empty = out_empty.loc[:, ~pd.Index(out_empty.columns).duplicated()].copy()
        return make_arrow_safe(out_empty)

    out = df.copy()
    # v263: Streamlit/PyArrow cannot render duplicate column labels. Keep first occurrence.
    if isinstance(out, pd.DataFrame) and out.columns.duplicated().any():
        out = out.loc[:, ~pd.Index(out.columns).duplicated()].copy()
    for col in out.columns:
        series = out[col]
        try:
            if pd.api.types.is_datetime64_any_dtype(series):
                out[col] = series.map(_date_string_yyyy_mm_dd)
            elif pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_bool_dtype(series):
                if _is_count_like_column(col):
                    out[col] = series.map(lambda v: "" if pd.isna(v) else f"{int(round(float(v))):,}")
                else:
                    out[col] = series.map(lambda v: "" if pd.isna(v) else _decimal_string(v, 2))
        except Exception:
            continue
    return make_arrow_safe(out)





def _normalise_dataframe_kwargs(kwargs: Dict[str, object], hide_index_default: Optional[bool] = None) -> Dict[str, object]:
    out = dict(kwargs)
    out.pop("use_container_width", None)
    if "width" not in out:
        out["width"] = "stretch"
    if hide_index_default is not None:
        out.setdefault("hide_index", hide_index_default)
    return out

def show_df(df: Optional[pd.DataFrame], **kwargs):
    kwargs = _normalise_dataframe_kwargs(kwargs)
    st.dataframe(_format_numeric_df_for_display(df), **kwargs)


def _bundle_display_cache(bundle: Dict[str, object]) -> Dict[str, pd.DataFrame]:
    """Return the per-date display cache stored on the dashboard bundle.

    v306.0: section renderers reuse Arrow-safe/display-safe tables instead of
    re-copying and re-coercing the same dataframe every time a section is opened.
    """
    if not isinstance(bundle, dict):
        return {}
    cache = bundle.get("_display_cache")
    if not isinstance(cache, dict):
        cache = {}
        bundle["_display_cache"] = cache
    return cache


def _get_or_build_display_df(bundle: Dict[str, object], key: str, builder) -> pd.DataFrame:
    cache = _bundle_display_cache(bundle)
    key = str(key or "")
    if key in cache and isinstance(cache.get(key), pd.DataFrame):
        return cache[key]
    try:
        df = builder()
    except Exception:
        df = pd.DataFrame()
    cache[key] = _format_numeric_df_for_display(df)
    return cache[key]


def show_cached_df(bundle: Dict[str, object], key: str, builder, **kwargs):
    """Render a cached display dataframe for static selected-date tables."""
    kwargs = _normalise_dataframe_kwargs(kwargs)
    st.dataframe(_get_or_build_display_df(bundle, key, builder), **kwargs)













#
#     template = VIEW_TEMPLATES.get(template_name, {})
#     visible_columns = template.get("visible_columns", [])
#     formats = template.get("formats", {})
#
#     out = df.copy()
#     if template_name == "driver_reconciliation" and "Driver" not in out.columns and "Asset Type" in out.columns:
#         out = out.rename(columns={"Asset Type": "Driver"})
#
#     columns_to_show = [c for c in visible_columns if c in out.columns]
#     if not columns_to_show:
#         columns_to_show = list(out.columns)
#     out = out[columns_to_show].copy()
#
#     for col, fmt in formats.items():
#         if col not in out.columns:
#             continue
#         fmt_norm = str(fmt).strip().lower()
#         if fmt_norm == "yyyy-mm-dd":
#             out[col] = out[col].map(_date_string_yyyy_mm_dd)
#         elif "$#,##0.00" in str(fmt):
#             out[col] = out[col].map(_excel_currency_string)
#         elif fmt_norm == "2 dp":
#             out[col] = out[col].map(lambda v: _decimal_string(v, 2))
#
#     return make_arrow_safe(out)










def _section_timing_store(bundle: Dict[str, object]) -> List[Dict[str, object]]:
    if not isinstance(bundle, dict):
        return []
    rows = bundle.get("section_timing_rows")
    if not isinstance(rows, list):
        rows = []
        bundle["section_timing_rows"] = rows
    return rows


def _reset_section_timing(bundle: Dict[str, object], section_name: str = "") -> None:
    if isinstance(bundle, dict):
        bundle["section_timing_rows"] = []
        bundle["section_timing_section"] = str(section_name or "")


def _record_section_timing(bundle: Dict[str, object], section_name: str, phase: str, started_at: float, *, rows: object = "", detail: str = "", status: str = "Done") -> None:
    if not isinstance(bundle, dict):
        return
    try:
        elapsed = round(float(time.perf_counter() - started_at), 4)
    except Exception:
        elapsed = 0.0
    _section_timing_store(bundle).append({"Section": str(section_name or ""), "Phase": str(phase or ""), "Status": str(status or "Done"), "ElapsedSeconds": elapsed, "Rows": rows, "Detail": str(detail or "")})


def _section_timing_df(bundle: Dict[str, object]) -> pd.DataFrame:
    cols = ["Section", "Phase", "Status", "ElapsedSeconds", "Rows", "Detail"]
    rows = _section_timing_store(bundle)
    return pd.DataFrame(rows, columns=cols) if rows else pd.DataFrame(columns=cols)


# ========================================================
# v342 OPTION B: deep per-step timing run-log
# ========================================================
# A lightweight, reusable instrumentation layer that records the elapsed time of
# individual heavy operations (source loads, hot-resolution sets, Tier 1 assignment
# build, each dashboard tab, and each Portfolio Numbers sub-section). Every step is
# captured as one row so the exact contributor to a slow "Render dashboard tabs"
# wallclock can be pinpointed and exported to CSV. Overhead is a single
# time.perf_counter() pair per wrapped block; the context manager never raises into
# the wrapped body (timing must never break a render).
_DEEP_TIMING_COLUMNS = ["Interaction", "Sequence", "Phase", "Function", "Status", "ElapsedSeconds", "Rows", "CacheHit", "Detail", "StartedAt"]


_DEEP_TIMING_SESSION_KEY = "_deep_timing_log_v343"
_DEEP_TIMING_INTERACTION_KEY = "_deep_timing_interaction_v343"


def _deep_timing_store(bundle: Dict[str, object] = None) -> List[Dict[str, object]]:
    """v343 (Part C): the deep-timing run-log now lives in st.session_state so it
    ACCUMULATES across Streamlit reruns (each radio click is a rerun). Previously it
    was stored on the per-render bundle and wiped every rerun, so only the LAST
    sub-section survived - which is why the exported CSV only ever had one row. The
    `bundle` argument is retained for signature compatibility but no longer used for
    storage. Falls back to a module-level list if session_state is unavailable
    (e.g. unit tests / self-test outside Streamlit)."""
    try:
        ss = st.session_state
        rows = ss.get(_DEEP_TIMING_SESSION_KEY)
        if not isinstance(rows, list):
            rows = []
            ss[_DEEP_TIMING_SESSION_KEY] = rows
        return rows
    except Exception:
        # non-Streamlit context: fall back to a bundle list if given, else a global.
        if isinstance(bundle, dict):
            rows = bundle.get("deep_timing_rows")
            if not isinstance(rows, list):
                rows = []
                bundle["deep_timing_rows"] = rows
            return rows
        global _DEEP_TIMING_FALLBACK
        try:
            _DEEP_TIMING_FALLBACK
        except NameError:
            _DEEP_TIMING_FALLBACK = []
        return _DEEP_TIMING_FALLBACK


def _deep_timing_current_interaction() -> int:
    """A monotonically increasing counter incremented once per dashboard render pass,
    stamped on every timed row so the click/rerun sequence is visible in the log."""
    try:
        ss = st.session_state
        return int(ss.get(_DEEP_TIMING_INTERACTION_KEY, 0) or 0)
    except Exception:
        return 0


def _deep_timing_begin_interaction(bundle: Dict[str, object] = None) -> None:
    """v343 (Part C): called once at the start of each dashboard render. It NO LONGER
    clears the log (that was the bug) - it only bumps the interaction counter so rows
    added during this rerun are grouped/ordered. Clearing is now user-driven via the
    'Clear timing log' button in the diagnostics panel."""
    try:
        ss = st.session_state
        ss[_DEEP_TIMING_INTERACTION_KEY] = int(ss.get(_DEEP_TIMING_INTERACTION_KEY, 0) or 0) + 1
    except Exception:
        pass


def _reset_deep_timing(bundle: Dict[str, object] = None) -> None:
    """v343 (Part C): explicit clear (now user-driven via the 'Clear timing log'
    button). Empties the accumulated session-state run-log and resets the interaction
    counter so the next click-through starts a fresh, self-contained profiling pass."""
    try:
        st.session_state[_DEEP_TIMING_SESSION_KEY] = []
        st.session_state[_DEEP_TIMING_INTERACTION_KEY] = 0
    except Exception:
        pass
    if isinstance(bundle, dict):
        bundle["deep_timing_rows"] = []


class _deep_timer:
    """Context manager that records one deep-timing row for the wrapped block.

    Usage:
        with _deep_timer(bundle, "Render sub-section", "Within tolerance") as _t:
            ...work...
            _t.rows = len(df)          # optional
            _t.cache_hit = True        # optional
            _t.detail = "extra note"   # optional
    Exceptions inside the block are recorded (Status="Error") and re-raised so the
    caller's own guard can still surface them; timing itself never swallows errors.
    """

    def __init__(self, bundle: Dict[str, object], phase: str, function: str, detail: str = "", rows: object = "", cache_hit: object = ""):
        self.bundle = bundle
        self.phase = str(phase or "")
        self.function = str(function or "")
        self.detail = str(detail or "")
        self.rows = rows
        self.cache_hit = cache_hit
        self._started = 0.0

    def __enter__(self):
        self._started = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            elapsed = round(float(time.perf_counter() - self._started), 4)
        except Exception:
            elapsed = 0.0
        try:
            store = _deep_timing_store(self.bundle)
            store.append({
                "Interaction": _deep_timing_current_interaction(),
                "Sequence": len(store) + 1,
                "Phase": self.phase,
                "Function": self.function,
                "Status": "Error" if exc_type is not None else "Done",
                "ElapsedSeconds": elapsed,
                "Rows": self.rows,
                "CacheHit": self.cache_hit,
                "Detail": (f"{exc_type.__name__}: {exc_val}" if exc_type is not None else self.detail),
                "StartedAt": round(float(self._started), 4),
            })
        except Exception:
            pass
        # never suppress the wrapped exception - let the caller's guard handle it.
        return False


def _deep_timing_df(bundle: Dict[str, object]) -> pd.DataFrame:
    rows = _deep_timing_store(bundle)
    if not rows:
        return pd.DataFrame(columns=_DEEP_TIMING_COLUMNS)
    df = pd.DataFrame(rows)
    for c in _DEEP_TIMING_COLUMNS:
        if c not in df.columns:
            df[c] = ""
    return df[_DEEP_TIMING_COLUMNS]


def _deep_timing_run_log_df(bundle: Dict[str, object]) -> pd.DataFrame:
    """The full detailed run-log for CSV export: the per-step deep-timing rows plus a
    RunTimestamp/RunDate stamp so exported logs are self-describing and comparable
    across runs."""
    df = _deep_timing_df(bundle)
    if df is None or not isinstance(df, pd.DataFrame):
        return pd.DataFrame(columns=["RunTimestamp", "RunDate"] + _DEEP_TIMING_COLUMNS)
    df = df.copy()
    try:
        run_ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        run_ts = ""
    run_date = str(bundle.get("selected_date_label", "")) if isinstance(bundle, dict) else ""
    df.insert(0, "RunDate", run_date)
    df.insert(0, "RunTimestamp", run_ts)
    return df


def _drain_uut_internal_timings_v344() -> None:
    """v344: pull the Advisor-UUT internal step timings recorded by bnp_helpers_uut
    (FDV T / T-1 loads, join+weight, aggregate, Unison map, advisor merge) and append
    them to the accumulating deep-timing run-log as sub-rows. Called right after an
    Advisor-UUT render. Fully guarded - timing must never break a render."""
    try:
        if not callable(globals().get("_uut_get_timings_v344")):
            return
        rows = _uut_get_timings_v344() or []
        store = _deep_timing_store(None)
        for r in rows:
            store.append({
                "Interaction": _deep_timing_current_interaction(),
                "Sequence": len(store) + 1,
                "Phase": "Advisor-UUT internal",
                "Function": str(r.get("label", "")),
                "Status": str(r.get("status", "Done")),
                "ElapsedSeconds": r.get("elapsed", ""),
                "Rows": r.get("rows", ""),
                "CacheHit": "",
                "Detail": str(r.get("detail", "")),
                "StartedAt": "",
            })
    except Exception:
        pass


def _render_section_timing_diagnostics(bundle: Dict[str, object]) -> None:
    """[removed] timing diagnostic - body intentionally emptied."""
    return None
def _combined_user_wait_timing_df(bundle: Dict[str, object]) -> pd.DataFrame:
    """Combine timings that explain the full Streamlit rerun / user wait.

    v306.4.1 excludes historical cached-bundle build rows from current-run summary.
    """
    rows: List[Dict[str, object]] = []
    bundle_status = ""
    try:
        status_df = bundle.get("dashboard_bundle_cache_status_df", pd.DataFrame()) if isinstance(bundle, dict) else pd.DataFrame()
        if isinstance(status_df, pd.DataFrame) and not status_df.empty and "Status" in status_df.columns:
            bundle_status = str(status_df["Status"].iloc[0])
    except Exception:
        bundle_status = ""
    bundle_cache_hit = bundle_status.strip().lower() == "session cache hit"
    stale_scopes = {"Prepare bundle sub-step", "BNP source load timing", "process_day internal timing"}

    def _append(scope: str, phase: object, elapsed: object, rows_value: object = "", detail: object = "", status: object = "") -> None:
        try:
            elapsed_value = float(pd.to_numeric(pd.Series([elapsed]), errors="coerce").fillna(0.0).iloc[0])
        except Exception:
            elapsed_value = 0.0
        scope_text = str(scope or "")
        phase_text = str(phase or "")
        detail_text = str(detail or "")
        is_total = phase_text.upper().startswith("99 TOTAL") or phase_text.upper().startswith("TOTAL ")
        is_historical_payload = "Historical payload-build timing" in detail_text
        is_cached_bundle_history = bool(bundle_cache_hit and scope_text in stale_scopes)
        if is_historical_payload:
            row_type = "Historical"
        elif is_cached_bundle_history:
            row_type = "Cached bundle build history"
            detail_text = (detail_text + "; " if detail_text else "") + "cached bundle build history, not current rerun wall-clock"
        elif is_total:
            row_type = "Total"
        else:
            row_type = "Component"
        rows.append({
            "Scope": scope_text,
            "Phase": phase_text,
            "Status": str(status or ""),
            "ElapsedSeconds": round(elapsed_value, 4),
            "Rows": rows_value,
            "Detail": detail_text,
            "RowType": row_type,
            "IncludeInCurrentRunSummary": bool(row_type == "Component"),
        })

    if not isinstance(bundle, dict):
        return pd.DataFrame(columns=["Scope", "Phase", "Status", "ElapsedSeconds", "Rows", "Detail", "RowType", "IncludeInCurrentRunSummary"])
    sources = [
        ("Full rerun wall-clock", bundle.get("dashboard_wallclock_timing_df", pd.DataFrame()), "Phase"),
        ("Loading stage", bundle.get("loading_stage_timing_df", pd.DataFrame()), "Stage"),
        ("Prepare bundle sub-step", bundle.get("prepare_bundle_timing_df", pd.DataFrame()), "Sub-step"),
        ("BNP source load timing", bundle.get("bnp_load_timing_df", pd.DataFrame()), "Sub-step"),
        ("process_day internal timing", bundle.get("process_day_timing_df", pd.DataFrame()), "Step"),
        ("Executive summary timing", bundle.get("executive_summary_timing_df", pd.DataFrame()), "Step"),
        ("Selected section render timing", bundle.get("render_tab_timing_df", pd.DataFrame()), "Tab"),
        ("Selected section phase timing", _section_timing_df(bundle), "Phase"),
    ]
    for scope, df, preferred_phase_col in sources:
        if not isinstance(df, pd.DataFrame) or df.empty:
            continue
        phase_col = preferred_phase_col if preferred_phase_col in df.columns else ("Sub-step" if "Sub-step" in df.columns else (df.columns[0] if len(df.columns) else ""))
        for _, r in df.iterrows():
            _append(scope, r.get(phase_col, ""), r.get("ElapsedSeconds", 0.0), r.get("Rows", ""), r.get("Detail", r.get("Timing Scope", "")), r.get("Status", ""))
    out = pd.DataFrame(rows, columns=["Scope", "Phase", "Status", "ElapsedSeconds", "Rows", "Detail", "RowType", "IncludeInCurrentRunSummary"])
    if not out.empty:
        out["ElapsedSeconds"] = pd.to_numeric(out["ElapsedSeconds"], errors="coerce").fillna(0.0)
    return out


def _render_user_wait_timing_diagnostics(bundle: Dict[str, object]) -> None:
    """[removed] timing diagnostic - body intentionally emptied."""
    return None
def _render_loading_progress_cards(container, stage_state: Dict[str, Dict[str, object]], total_elapsed: float, fx_subtimings=None) -> None:
    """Render loading progress as a compact two-row strip.

    v306.4.9: deliberately no browser-side live timer. Streamlit cannot reliably
    stop client-side JavaScript during a blocking server run. The progress strip
    now uses one server-side state machine: _mark_stage() completes the previous
    phase and starts the next; _complete_active_stage() closes the final phase.
    """
    def _elapsed_seconds_text(info: Dict[str, object]) -> str:
        elapsed = info.get("elapsed", None)
        return "--" if elapsed is None else f"{float(elapsed):,.1f}s"

    def _cell_html(label: str, elapsed_text: str, *, first: bool = False) -> str:
        bg = "#93C5FD" if first else "#DBEAFE"
        border = "" if first else "border-left:1px solid #93C5FD;"
        min_width = "165px" if first else "172px"
        return (
            f"<td style='padding:8px 12px;{border}vertical-align:middle;min-width:{min_width};background:{bg};'>"
            f"<div style='display:flex;align-items:center;justify-content:flex-start;gap:9px;line-height:1.12;white-space:normal;'>"
            f"<span style='color:#0F172A;font-weight:950;overflow-wrap:anywhere;'>{html.escape(str(label))}</span>"
            f"<span style='color:#1E293B;font-weight:850;font-variant-numeric:tabular-nums;white-space:nowrap;'>{html.escape(str(elapsed_text))}</span>"
            f"</div></td>"
        )

    stage_cells = []
    for stage, info in stage_state.items():
        stage_cells.append(_cell_html(stage, _elapsed_seconds_text(info)))

    first_row_stage_count = 4
    first_row = _cell_html('Loading progress', f'{float(total_elapsed or 0):,.1f}s', first=True) + ''.join(stage_cells[:first_row_stage_count])
    second_row = ''.join(stage_cells[first_row_stage_count:])

    container.markdown(
        f"""
        <table style="width:100%;border-collapse:separate;border-spacing:0;border:1px solid #60A5FA;border-radius:16px;overflow:hidden;background:#BFDBFE;box-shadow:0 9px 20px rgba(37,99,235,0.16);font-size:0.90rem;margin:0.35rem 0 0.8rem 0;table-layout:fixed;">
          <tbody>
            <tr>{first_row}</tr>
            <tr>{second_row}</tr>
          </tbody>
        </table>
        """,
        unsafe_allow_html=True,
    )

def create_progress_widgets(title: str, host=None):
    host = host or st
    host.markdown(f"#### {title}")
    progress_bar = host.progress(0)
    status_text = host.empty()
    summary_text = host.empty()
    return progress_bar, status_text, summary_text




def _sidebar_settings_default() -> Dict[str, float]:
    return {"mv_tiny_upper_bound": float(DEFAULT_EXCLUDE_AMOUNT), "fx_line_match_tolerance_dollar": 100.0, "current_account_dominance_threshold_pct": float(DEFAULT_CURRENT_ACCOUNT_DOMINANCE_THRESHOLD_PCT)}

def load_sidebar_settings() -> Dict[str, float]:
    settings = _sidebar_settings_default()
    for path in [globals().get("SIDEBAR_SETTINGS_FILE", ""), globals().get("THRESHOLD_STATE_FILE", "")]:
        try:
            if path and os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    payload = json.load(f)
                if isinstance(payload, dict):
                    if "mv_tiny_upper_bound" in payload:
                        settings["mv_tiny_upper_bound"] = float(payload.get("mv_tiny_upper_bound"))
                    if "fx_line_match_tolerance_dollar" in payload:
                        settings["fx_line_match_tolerance_dollar"] = float(payload.get("fx_line_match_tolerance_dollar"))
                    if "current_account_dominance_threshold_pct" in payload:
                        settings["current_account_dominance_threshold_pct"] = float(payload.get("current_account_dominance_threshold_pct"))
                    if "threshold" in payload and "mv_tiny_upper_bound" not in payload:
                        settings["mv_tiny_upper_bound"] = float(payload.get("threshold"))
        except Exception:
            pass
    return settings

def save_sidebar_settings(settings: Dict[str, float]) -> None:
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        current = load_sidebar_settings()
        for k, v in dict(settings or {}).items():
            if k in _sidebar_settings_default():
                current[k] = float(v)
        with open(SIDEBAR_SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(current, f, indent=2, sort_keys=True)
        with open(THRESHOLD_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"threshold": float(current.get("mv_tiny_upper_bound", DEFAULT_EXCLUDE_AMOUNT)), **current}, f, indent=2, sort_keys=True)
    except Exception:
        pass

def _remember_sidebar_setting(key: str, value: object) -> float:
    try:
        value_f = float(value)
    except Exception:
        value_f = float(_sidebar_settings_default().get(key, 0.0))
    save_sidebar_settings({key: value_f})
    return value_f

def _persistent_sidebar_number_input(label: str, setting_key: str, default: float, *, min_value: float = 0.0, step: float = 50.0, help: str = "") -> float:
    """Render a sidebar number input whose value is persisted across app sessions.

    Streamlit warning fix: after priming st.session_state for a widget key, do not
    also pass a value= argument to st.sidebar.number_input for the same key.
    """
    settings = load_sidebar_settings()
    widget_key = f"persisted_sidebar_{setting_key}"
    if widget_key not in st.session_state:
        try:
            st.session_state[widget_key] = float(settings.get(setting_key, default))
        except Exception:
            st.session_state[widget_key] = float(default)
    value = st.sidebar.number_input(
        label,
        min_value=float(min_value),
        step=float(step),
        format="%.2f",
        key=widget_key,
        help=help or None,
    )
    return _remember_sidebar_setting(setting_key, value)

def load_threshold_state() -> Dict[str, float]:
    settings = load_sidebar_settings()
    return {"threshold": float(settings.get("mv_tiny_upper_bound", DEFAULT_EXCLUDE_AMOUNT))}



# v368: removed load_day_files_cached and load_day_files_detailed_cached -
# both confirmed to have ZERO callers anywhere in the app (dead entry
# points into the ingestion cluster removed above). The live BNP source
# loader is load_day_files_v184_readcsv_cached (with
# load_day_files_v183_aggregated_cached as its fallback), defined further
# down this file. See CHANGELOG.md v368.
def _bnp_source_file_diagnostics(keyword: str, folder: str) -> Tuple[Optional[pd.DataFrame], Dict[str, object], List[Dict[str, object]]]:
    meta = {'Keyword': keyword, 'Loaded': False, 'Path': '', 'Rows': 0, 'Columns': 0, 'HeaderRows': '', 'Encoding': '', 'Delimiter': '', 'Error': '', 'MatchedFiles': 0, 'LoadedFiles': 0, 'ExcludedCount': 0, 'ExcludedFiles': '', 'LoadedPaths': '', 'FileErrors': '', 'HeaderStrategy': '', 'HeaderValidation': ''}
    timing_rows: List[Dict[str, object]] = []
    def _add(label: str, started_at: float, status: str = 'Done', extra: str = '') -> None:
        suffix = f' - {extra}' if extra else ''
        timing_rows.append({'Sub-step': f'BNP parse: {keyword} {label}{suffix}', 'Status': status, 'ElapsedSeconds': float(time.perf_counter() - started_at)})

    list_started = time.perf_counter()
    try:
        folder_names = sorted(os.listdir(folder))
        _add('list folder', list_started, 'Done', f'{len(folder_names):,} entries')
    except Exception as e:
        meta['Error'] = f'{type(e).__name__}: {e}'
        _add('list folder', list_started, 'Error', meta['Error'])
        return None, meta, timing_rows

    match_started = time.perf_counter()
    matches: List[str] = []
    excluded: List[str] = []
    for file_name in folder_names:
        lower_name = str(file_name).lower()
        if keyword.lower() in lower_name and lower_name.endswith(('.csv', '.txt')):
            full_path = os.path.join(folder, file_name)
            if any(token.lower() in lower_name for token in EXCLUDED_FILENAME_TOKENS):
                excluded.append(full_path)
            else:
                matches.append(full_path)
    matches = sorted(matches)
    meta['MatchedFiles'] = int(len(matches) + len(excluded))
    meta['ExcludedCount'] = int(len(excluded))
    meta['ExcludedFiles'] = ' | '.join(excluded[:10])
    _add('match files', match_started, 'Done' if matches else 'Missing', f'matched {len(matches):,}; excluded {len(excluded):,}')
    if not matches:
        meta['Error'] = 'File not found'
        return None, meta, timing_rows

    frames: List[pd.DataFrame] = []
    loaded_paths: List[str] = []
    file_errors: List[str] = []
    encodings: List[str] = []
    delimiters: List[str] = []
    header_rows_seen: List[str] = []
    header_strategy_seen: List[str] = []
    header_validation_seen: List[str] = []

    for idx, path in enumerate(matches, start=1):
        file_label = f'file {idx}/{len(matches)} {os.path.basename(path)}'
        try:
            stat_started = time.perf_counter()
            try:
                size_bytes = os.path.getsize(path)
                stat_extra = f'{size_bytes:,} bytes'
            except Exception as e:
                size_bytes = 0
                stat_extra = f'stat error {type(e).__name__}: {e}'
            _add(f'{file_label} stat', stat_started, 'Done', stat_extra)

            sample_started = time.perf_counter()
            sample_text, encoding = ingestion_v162._try_read_text(path)
            encodings.append(str(encoding))
            _add(f'{file_label} read text sample / encoding', sample_started, 'Done', str(encoding))

            sniff_started = time.perf_counter()
            delimiter = ingestion_v162._sniff_delimiter(sample_text)
            delimiters.append(str(delimiter))
            _add(f'{file_label} delimiter sniff', sniff_started, 'Done', repr(delimiter))

            parse_started = time.perf_counter()
            raw = ingestion_v162._robust_csv_to_df(path, delimiter, encoding)
            _add(f'{file_label} robust csv parse', parse_started, 'Done', f'{len(raw):,}r x {len(raw.columns):,}c')

            header_started = time.perf_counter()
            try:
                header_rows, header_strategy, header_validation = ingestion_v162._select_header_rows_for_keyword(raw, keyword)
            except AttributeError:
                header_rows = ingestion_v162._detect_header_rows(raw)
                header_strategy = 'fallback _detect_header_rows'
                header_validation = ''
            headers = ingestion_v162.normalize_header(raw, header_rows)
            header_rows_seen.append(','.join(str(x) for x in header_rows))
            header_strategy_seen.append(str(header_strategy))
            header_validation_seen.append(str(header_validation))
            start_row = max(header_rows) + 1 if header_rows else 1
            data = raw.iloc[start_row:].copy().reset_index(drop=True)
            if len(headers) < len(data.columns):
                headers = list(headers) + [f'Column_{i+1}' for i in range(len(headers), len(data.columns))]
            data.columns = headers[:len(data.columns)]
            _add(f'{file_label} header normalisation', header_started, 'Done', f'header rows {header_rows}; data {len(data):,}r x {len(data.columns):,}c')

            clean_started = time.perf_counter()
            data = data[~data.apply(lambda r: all(str(v).strip() == '' for v in r.tolist()), axis=1)].copy()
            _add(f'{file_label} blank-row cleanup', clean_started, 'Done', f'{len(data):,}r')

            frames.append(data)
            loaded_paths.append(path)
        except Exception as e:
            err = f'{os.path.basename(path)}: {type(e).__name__}: {e}'
            file_errors.append(err)
            timing_rows.append({'Sub-step': f'BNP parse: {keyword} {file_label} error', 'Status': 'Error', 'ElapsedSeconds': 0.0})

    concat_started = time.perf_counter()
    if frames:
        df = pd.concat(frames, ignore_index=True, sort=False)
        meta['Loaded'] = True
        meta['Rows'] = int(len(df))
        meta['Columns'] = int(len(df.columns))
        meta['Path'] = loaded_paths[0] if len(loaded_paths) == 1 else ''
        meta['LoadedFiles'] = int(len(loaded_paths))
        meta['LoadedPaths'] = ' | '.join(loaded_paths)
        meta['Encoding'] = ' | '.join(sorted(set(encodings)))
        meta['Delimiter'] = ' | '.join(sorted(set(delimiters)))
        meta['HeaderRows'] = ' | '.join(header_rows_seen)
        meta['HeaderStrategy'] = ' | '.join(sorted(set(header_strategy_seen)))
        meta['HeaderValidation'] = ' | '.join(sorted(set(header_validation_seen)))
        meta['FileErrors'] = ' | '.join(file_errors)
        _add('concat loaded files', concat_started, 'Done', f'{len(df):,}r x {len(df.columns):,}c')
        return df, meta, timing_rows
    meta['Error'] = 'No files loaded' if not file_errors else ' | '.join(file_errors)
    meta['FileErrors'] = ' | '.join(file_errors)
    _add('concat loaded files', concat_started, 'Missing', meta['Error'])
    return None, meta, timing_rows


# v365: removed dead loaders load_day_files_v181_detailed_cached and
# load_day_files_v182_fast_detailed_cached (~300 lines total). Neither was
# ever called anywhere in the codebase - process_day only calls v184
# (primary) with v183 as its fallback (see call site ~line 1653). v181/v182
# predate both and were fully superseded. Confirmed via full-file grep
# before removal. See CHANGELOG.md v365.

# v369 HOTFIX: _bnp_source_file_aggregated_v183 (below) was ACCIDENTALLY DELETED
# during the v365 dead-loader cleanup - it is NOT dead code; it is the real
# per-keyword file-aggregation helper called by load_day_files_v183_aggregated_cached
# immediately below (the live fallback path when v184 raises). This was a genuine
# mistake in the earlier cleanup (a NameError at runtime, confirmed 2026-08-12) -
# restored verbatim from the pre-cleanup source. See CHANGELOG.md v369.
def _bnp_source_file_aggregated_v183(keyword: str, folder: str) -> Tuple[Optional[pd.DataFrame], Dict[str, object], List[Dict[str, object]]]:
    meta = {'Keyword': keyword, 'Loaded': False, 'Path': '', 'Rows': 0, 'Columns': 0, 'HeaderRows': '', 'Encoding': '', 'Delimiter': '', 'Error': '', 'MatchedFiles': 0, 'LoadedFiles': 0, 'ExcludedCount': 0, 'ExcludedFiles': '', 'LoadedPaths': '', 'FileErrors': '', 'HeaderStrategy': '', 'HeaderValidation': ''}
    timing_rows: List[Dict[str, object]] = []
    def _add(label: str, started_at: float, status: str = 'Done', extra: str = '') -> None:
        suffix = f' - {extra}' if extra else ''
        timing_rows.append({'Sub-step': f'BNP v183: {keyword} {label}{suffix}', 'Status': status, 'ElapsedSeconds': float(time.perf_counter() - started_at)})

    discovery_started = time.perf_counter()
    try:
        folder_names = sorted(os.listdir(folder))
    except Exception as e:
        meta['Error'] = f'{type(e).__name__}: {e}'
        _add('discovery', discovery_started, 'Error', meta['Error'])
        return None, meta, timing_rows
    matches: List[str] = []
    excluded: List[str] = []
    for file_name in folder_names:
        lower_name = str(file_name).lower()
        if keyword.lower() in lower_name and lower_name.endswith(('.csv', '.txt')):
            full_path = os.path.join(folder, file_name)
            if any(token.lower() in lower_name for token in EXCLUDED_FILENAME_TOKENS):
                excluded.append(full_path)
            else:
                matches.append(full_path)
    matches = sorted(matches)
    meta['MatchedFiles'] = int(len(matches) + len(excluded))
    meta['ExcludedCount'] = int(len(excluded))
    meta['ExcludedFiles'] = ' | '.join(excluded[:10])
    _add('discovery', discovery_started, 'Done' if matches else 'Missing', f'{len(folder_names):,} folder entries; matched {len(matches):,}; excluded {len(excluded):,}')
    if not matches:
        meta['Error'] = 'File not found'
        return None, meta, timing_rows

    frames: List[pd.DataFrame] = []
    loaded_paths: List[str] = []
    file_errors: List[str] = []
    header_rows_seen: List[str] = []
    header_strategy_seen: List[str] = []
    header_validation_seen: List[str] = []
    encoding = 'utf-8-sig'
    delimiter = ','
    total_raw_rows = 0
    total_raw_cols = 0
    total_data_rows_before_cleanup = 0
    total_bytes = 0

    parse_started = time.perf_counter()
    parsed_payloads: List[Tuple[str, pd.DataFrame, int]] = []
    for path in matches:
        try:
            try:
                total_bytes += int(os.path.getsize(path))
            except Exception:
                pass
            try:
                raw = ingestion_v162._robust_csv_to_df(path, delimiter, encoding)
            except Exception:
                sample_text, encoding_fallback = ingestion_v162._try_read_text(path)
                delimiter_fallback = ingestion_v162._sniff_delimiter(sample_text)
                raw = ingestion_v162._robust_csv_to_df(path, delimiter_fallback, encoding_fallback)
            total_raw_rows += int(len(raw))
            total_raw_cols = max(total_raw_cols, int(len(raw.columns)))
            parsed_payloads.append((path, raw, int(len(raw.columns))))
        except Exception as e:
            file_errors.append(f'{os.path.basename(path)}: {type(e).__name__}: {e}')
    _add('source parse aggregate', parse_started, 'Done' if parsed_payloads else 'Missing', f'{len(parsed_payloads):,}/{len(matches):,} files; {total_raw_rows:,} raw rows; max {total_raw_cols:,} cols; {total_bytes:,} bytes')

    header_cleanup_started = time.perf_counter()
    for path, raw, _raw_cols in parsed_payloads:
        try:
            try:
                header_rows, header_strategy, header_validation = ingestion_v162._select_header_rows_for_keyword(raw, keyword)
            except AttributeError:
                header_rows = ingestion_v162._detect_header_rows(raw)
                header_strategy = 'fallback _detect_header_rows'
                header_validation = ''
            headers = ingestion_v162.normalize_header(raw, header_rows)
            header_rows_seen.append(','.join(str(x) for x in header_rows))
            header_strategy_seen.append(str(header_strategy))
            header_validation_seen.append(str(header_validation))
            start_row = max(header_rows) + 1 if header_rows else 1
            data = raw.iloc[start_row:].copy().reset_index(drop=True)
            total_data_rows_before_cleanup += int(len(data))
            if len(headers) < len(data.columns):
                headers = list(headers) + [f'Column_{i+1}' for i in range(len(headers), len(data.columns))]
            data.columns = headers[:len(data.columns)]
            try:
                mask = data.fillna('').ne('').any(axis=1)
                data = data.loc[mask].copy()
            except Exception:
                data = data[~data.apply(lambda r: all(str(v).strip() == '' for v in r.tolist()), axis=1)].copy()
            frames.append(data)
            loaded_paths.append(path)
        except Exception as e:
            file_errors.append(f'{os.path.basename(path)} header/cleanup: {type(e).__name__}: {e}')
    _add('header/cleanup aggregate', header_cleanup_started, 'Done' if frames else 'Missing', f'{total_data_rows_before_cleanup:,} data rows before cleanup; {sum(len(x) for x in frames):,} rows after cleanup')

    concat_started = time.perf_counter()
    if frames:
        df = pd.concat(frames, ignore_index=True, sort=False)
        meta['Loaded'] = True
        meta['Rows'] = int(len(df))
        meta['Columns'] = int(len(df.columns))
        meta['Path'] = loaded_paths[0] if len(loaded_paths) == 1 else ''
        meta['LoadedFiles'] = int(len(loaded_paths))
        meta['LoadedPaths'] = ' | '.join(loaded_paths)
        meta['Encoding'] = encoding
        meta['Delimiter'] = delimiter
        meta['HeaderRows'] = ' | '.join(header_rows_seen)
        meta['HeaderStrategy'] = ' | '.join(sorted(set(header_strategy_seen)))
        meta['HeaderValidation'] = ' | '.join(sorted(set(header_validation_seen)))
        meta['FileErrors'] = ' | '.join(file_errors)
        _add('concat aggregate', concat_started, 'Done', f'{len(df):,}r x {len(df.columns):,}c')
        return df, meta, timing_rows
    meta['Error'] = 'No files loaded' if not file_errors else ' | '.join(file_errors)
    meta['FileErrors'] = ' | '.join(file_errors)
    _add('concat aggregate', concat_started, 'Missing', meta['Error'])
    return None, meta, timing_rows


@st.cache_data(show_spinner=False)
def load_day_files_v183_aggregated_cached(folder: str, folder_fp: str, cache_version: str) -> Dict[str, object]:
    _ = folder_fp, cache_version
    ingestion_v162.configure_ingestion(header_contracts=HEADER_CONTRACTS, excluded_filename_tokens=EXCLUDED_FILENAME_TOKENS, required_file_keywords=REQUIRED_FILE_KEYWORDS, optional_file_keywords=OPTIONAL_FILE_KEYWORDS)
    file_map: Dict[str, object] = {}
    file_meta_rows: List[Dict[str, object]] = []
    timing_rows: List[Dict[str, object]] = []
    alias_map = {'DDetailedReturn': 'dd', 'DAssetTypeReturn': 'dat', 'DAssetReturn': 'dar', 'TransactionListing': 'txn', 'BenchmarkStatic': 'bmk'}
    total_started = time.perf_counter()
    for keyword in REQUIRED_FILE_KEYWORDS + OPTIONAL_FILE_KEYWORDS:
        keyword_started = time.perf_counter()
        df, meta, keyword_timing_rows = _bnp_source_file_aggregated_v183(keyword, folder)
        timing_rows.extend(keyword_timing_rows)
        if isinstance(df, pd.DataFrame):
            prime_started = time.perf_counter()
            df = _prime_dataframe_col_index(df)
            timing_rows.append({'Sub-step': f'BNP v183: {keyword} prime dataframe columns', 'Status': 'Done', 'ElapsedSeconds': float(time.perf_counter() - prime_started)})
            alias = alias_map.get(keyword)
            if alias:
                file_map[alias] = df
        timing_rows.append({'Sub-step': f'BNP v183: {keyword} total', 'Status': 'Done' if isinstance(df, pd.DataFrame) else 'Missing', 'ElapsedSeconds': float(time.perf_counter() - keyword_started)})
        file_meta_rows.append(meta)
    timing_rows.append({'Sub-step': 'BNP v183: total aggregated source load/prime', 'Status': 'Done', 'ElapsedSeconds': float(time.perf_counter() - total_started)})
    return {'dd': file_map.get('dd'), 'dat': file_map.get('dat'), 'dar': file_map.get('dar'), 'txn': file_map.get('txn'), 'bmk': file_map.get('bmk'), 'file_meta_df': pd.DataFrame(file_meta_rows), 'bnp_load_timing_df': pd.DataFrame(timing_rows)}

def _read_bnp_first_n_fields_custom_v304_2(path: str, field_count: int) -> Tuple[pd.DataFrame, str]:
    """Read only the first N delimited fields using csv.reader.

    This avoids pandas ParserError/ValueError on irregular trailing fields while
    preserving quoted delimiter handling. Rows shorter than N are padded; rows
    wider than N are truncated before DataFrame construction.
    """
    sample_text, encoding = ingestion_v162._try_read_text(path)
    delimiter = ingestion_v162._sniff_delimiter(sample_text)
    rows: List[List[str]] = []
    with open(path, "r", encoding=encoding, errors="replace", newline="") as f:
        reader = csv.reader(f, delimiter=delimiter)
        for row in reader:
            values = ["" if v is None else str(v) for v in row[:field_count]]
            if len(values) < field_count:
                values.extend([""] * (field_count - len(values)))
            rows.append(values)
    if not rows:
        return pd.DataFrame(columns=list(range(field_count))), f"{encoding}/{repr(delimiter)}/custom_first_{field_count}_fields"
    return pd.DataFrame(rows, columns=list(range(field_count))), f"{encoding}/{repr(delimiter)}/custom_first_{field_count}_fields"


def _read_bnp_csv_fast_v184(path: str, keyword: str) -> Tuple[pd.DataFrame, str, str]:
    # Fast happy path for BNP CSVs. Falls back to the existing robust parser if pandas cannot parse the file shape/encoding.
    # v303: TransactionListing initial dashboard source load only reads the first 54 columns.
    # v304: DAssetReturn uses a bounded first-41-column read to avoid ParserError from trailing irregular fields.
    try:
        keyword_norm = str(keyword or "").strip().lower()
        if keyword_norm == "transactionlisting":
            raw = pd.read_csv(
                path,
                header=None,
                dtype=str,
                keep_default_na=False,
                encoding='utf-8-sig',
                engine='c',
                low_memory=False,
                usecols=range(54),
            )
            return raw, 'pd.read_csv fast path first 54 columns', 'utf-8-sig/comma/usecols=0:53'
        if keyword_norm == "dassetreturn":
            raw, encoding_detail = _read_bnp_first_n_fields_custom_v304_2(path, 41)
            return raw, 'custom csv.reader first 41 fields', encoding_detail
        raw = pd.read_csv(path, header=None, dtype=str, keep_default_na=False, encoding='utf-8-sig', engine='c', low_memory=False)
        return raw, 'pd.read_csv fast path', 'utf-8-sig/comma'
    except Exception as first_error:
        sample_text, encoding_fallback = ingestion_v162._try_read_text(path)
        delimiter_fallback = ingestion_v162._sniff_delimiter(sample_text)
        raw = ingestion_v162._robust_csv_to_df(path, delimiter_fallback, encoding_fallback)
        return raw, f'robust fallback after {type(first_error).__name__}', f'{encoding_fallback}/{repr(delimiter_fallback)}'


def _bnp_source_file_aggregated_v184(keyword: str, folder: str) -> Tuple[Optional[pd.DataFrame], Dict[str, object], List[Dict[str, object]]]:
    meta = {'Keyword': keyword, 'Loaded': False, 'Path': '', 'Rows': 0, 'Columns': 0, 'HeaderRows': '', 'Encoding': '', 'Delimiter': '', 'Error': '', 'MatchedFiles': 0, 'LoadedFiles': 0, 'ExcludedCount': 0, 'ExcludedFiles': '', 'LoadedPaths': '', 'FileErrors': '', 'HeaderStrategy': '', 'HeaderValidation': ''}
    timing_rows: List[Dict[str, object]] = []
    fast_count = 0
    fallback_count = 0
    parse_modes: List[str] = []
    parse_encodings: List[str] = []
    def _add(label: str, started_at: float, status: str = 'Done', extra: str = '') -> None:
        suffix = f' - {extra}' if extra else ''
        timing_rows.append({'Sub-step': f'BNP v184: {keyword} {label}{suffix}', 'Status': status, 'ElapsedSeconds': float(time.perf_counter() - started_at)})

    discovery_started = time.perf_counter()
    try:
        folder_names = sorted(os.listdir(folder))
    except Exception as e:
        meta['Error'] = f'{type(e).__name__}: {e}'
        _add('discovery', discovery_started, 'Error', meta['Error'])
        return None, meta, timing_rows
    matches: List[str] = []
    excluded: List[str] = []
    for file_name in folder_names:
        lower_name = str(file_name).lower()
        if keyword.lower() in lower_name and lower_name.endswith(('.csv', '.txt')):
            full_path = os.path.join(folder, file_name)
            if any(token.lower() in lower_name for token in EXCLUDED_FILENAME_TOKENS):
                excluded.append(full_path)
            else:
                matches.append(full_path)
    matches = sorted(matches)
    meta['MatchedFiles'] = int(len(matches) + len(excluded))
    meta['ExcludedCount'] = int(len(excluded))
    meta['ExcludedFiles'] = ' | '.join(excluded[:10])
    _add('discovery', discovery_started, 'Done' if matches else 'Missing', f'{len(folder_names):,} folder entries; matched {len(matches):,}; excluded {len(excluded):,}')
    if not matches:
        meta['Error'] = 'File not found'
        return None, meta, timing_rows

    frames: List[pd.DataFrame] = []
    loaded_paths: List[str] = []
    file_errors: List[str] = []
    header_rows_seen: List[str] = []
    header_strategy_seen: List[str] = []
    header_validation_seen: List[str] = []
    total_raw_rows = 0
    total_raw_cols = 0
    total_data_rows_before_cleanup = 0
    total_bytes = 0

    parse_started = time.perf_counter()
    parsed_payloads: List[Tuple[str, pd.DataFrame, int]] = []
    for path in matches:
        try:
            try:
                total_bytes += int(os.path.getsize(path))
            except Exception:
                pass
            raw, parse_mode, parse_encoding = _read_bnp_csv_fast_v184(path, keyword)
            parse_modes.append(parse_mode)
            parse_encodings.append(parse_encoding)
            if str(parse_mode).startswith('pd.read_csv fast path'):
                fast_count += 1
            else:
                fallback_count += 1
            total_raw_rows += int(len(raw))
            total_raw_cols = max(total_raw_cols, int(len(raw.columns)))
            parsed_payloads.append((path, raw, int(len(raw.columns))))
        except Exception as e:
            fallback_count += 1
            file_errors.append(f'{os.path.basename(path)}: {type(e).__name__}: {e}')
    mode_summary = f'fast {fast_count:,}; fallback {fallback_count:,}; modes: ' + ' | '.join(sorted(set(parse_modes))[:4])
    _add('source parse aggregate', parse_started, 'Done' if parsed_payloads else 'Missing', f'{len(parsed_payloads):,}/{len(matches):,} files; {total_raw_rows:,} raw rows; max {total_raw_cols:,} cols; {total_bytes:,} bytes; {mode_summary}')

    header_cleanup_started = time.perf_counter()
    for path, raw, _raw_cols in parsed_payloads:
        try:
            try:
                header_rows, header_strategy, header_validation = ingestion_v162._select_header_rows_for_keyword(raw, keyword)
            except AttributeError:
                header_rows = ingestion_v162._detect_header_rows(raw)
                header_strategy = 'fallback _detect_header_rows'
                header_validation = ''
            headers = ingestion_v162.normalize_header(raw, header_rows)
            header_rows_seen.append(','.join(str(x) for x in header_rows))
            header_strategy_seen.append(str(header_strategy))
            header_validation_seen.append(str(header_validation))
            start_row = max(header_rows) + 1 if header_rows else 1
            data = raw.iloc[start_row:].copy().reset_index(drop=True)
            total_data_rows_before_cleanup += int(len(data))
            if len(headers) < len(data.columns):
                headers = list(headers) + [f'Column_{i+1}' for i in range(len(headers), len(data.columns))]
            data.columns = headers[:len(data.columns)]
            try:
                mask = data.fillna('').ne('').any(axis=1)
                data = data.loc[mask].copy()
            except Exception:
                data = data[~data.apply(lambda r: all(str(v).strip() == '' for v in r.tolist()), axis=1)].copy()
            frames.append(data)
            loaded_paths.append(path)
        except Exception as e:
            file_errors.append(f'{os.path.basename(path)} header/cleanup: {type(e).__name__}: {e}')
    _add('header/cleanup aggregate', header_cleanup_started, 'Done' if frames else 'Missing', f'{total_data_rows_before_cleanup:,} data rows before cleanup; {sum(len(x) for x in frames):,} rows after cleanup')

    concat_started = time.perf_counter()
    if frames:
        df = pd.concat(frames, ignore_index=True, sort=False)
        meta['Loaded'] = True
        meta['Rows'] = int(len(df))
        meta['Columns'] = int(len(df.columns))
        meta['Path'] = loaded_paths[0] if len(loaded_paths) == 1 else ''
        meta['LoadedFiles'] = int(len(loaded_paths))
        meta['LoadedPaths'] = ' | '.join(loaded_paths)
        meta['Encoding'] = ' | '.join(sorted(set(parse_encodings)))
        meta['Delimiter'] = 'comma fast path unless fallback noted'
        meta['HeaderRows'] = ' | '.join(header_rows_seen)
        meta['HeaderStrategy'] = ' | '.join(sorted(set(header_strategy_seen)))
        meta['HeaderValidation'] = ' | '.join(sorted(set(header_validation_seen)))
        meta['FileErrors'] = ' | '.join(file_errors)
        _add('concat aggregate', concat_started, 'Done', f'{len(df):,}r x {len(df.columns):,}c')
        return df, meta, timing_rows
    meta['Error'] = 'No files loaded' if not file_errors else ' | '.join(file_errors)
    meta['FileErrors'] = ' | '.join(file_errors)
    _add('concat aggregate', concat_started, 'Missing', meta['Error'])
    return None, meta, timing_rows


@st.cache_data(show_spinner=False)
def load_day_files_v184_readcsv_cached(folder: str, folder_fp: str, cache_version: str) -> Dict[str, object]:
    _ = folder_fp, cache_version
    ingestion_v162.configure_ingestion(header_contracts=HEADER_CONTRACTS, excluded_filename_tokens=EXCLUDED_FILENAME_TOKENS, required_file_keywords=REQUIRED_FILE_KEYWORDS, optional_file_keywords=OPTIONAL_FILE_KEYWORDS)
    file_map: Dict[str, object] = {}
    file_meta_rows: List[Dict[str, object]] = []
    timing_rows: List[Dict[str, object]] = []
    alias_map = {'DDetailedReturn': 'dd', 'DAssetTypeReturn': 'dat', 'DAssetReturn': 'dar', 'TransactionListing': 'txn', 'BenchmarkStatic': 'bmk'}
    total_started = time.perf_counter()
    for keyword in REQUIRED_FILE_KEYWORDS + OPTIONAL_FILE_KEYWORDS:
        keyword_started = time.perf_counter()
        df, meta, keyword_timing_rows = _bnp_source_file_aggregated_v184(keyword, folder)
        timing_rows.extend(keyword_timing_rows)
        if isinstance(df, pd.DataFrame):
            prime_started = time.perf_counter()
            df = _prime_dataframe_col_index(df)
            timing_rows.append({'Sub-step': f'BNP v184: {keyword} prime dataframe columns', 'Status': 'Done', 'ElapsedSeconds': float(time.perf_counter() - prime_started)})
            alias = alias_map.get(keyword)
            if alias:
                file_map[alias] = df
        timing_rows.append({'Sub-step': f'BNP v184: {keyword} total', 'Status': 'Done' if isinstance(df, pd.DataFrame) else 'Missing', 'ElapsedSeconds': float(time.perf_counter() - keyword_started)})
        file_meta_rows.append(meta)
    timing_rows.append({'Sub-step': 'BNP v184: total read_csv source load/prime', 'Status': 'Done', 'ElapsedSeconds': float(time.perf_counter() - total_started)})
    return {'dd': file_map.get('dd'), 'dat': file_map.get('dat'), 'dar': file_map.get('dar'), 'txn': file_map.get('txn'), 'bmk': file_map.get('bmk'), 'file_meta_df': pd.DataFrame(file_meta_rows), 'bnp_load_timing_df': pd.DataFrame(timing_rows)}

@st.cache_data(show_spinner=False)
def process_day_cached(folder: str, folder_fp: str, exclude_below_current_value: float, cache_version: str) -> Dict[str, pd.DataFrame]:
    """Cache processed day outputs for no-progress call sites only."""
    loaded = load_day_files_v183_aggregated_cached(folder, folder_fp, cache_version)
    return process_day(
        folder,
        progress_bar=None,
        status_text=None,
        summary_text=None,
        progress_label="Cached day processing",
        exclude_below_current_value=exclude_below_current_value,
        loaded_files=loaded,
    )














# v368: removed this file's own bare load_day_files() (a thin
# configure-then-delegate wrapper around ingestion_v162.load_day_files).
# Confirmed dead: its only caller, load_day_files_cached, was itself dead
# and removed above. See CHANGELOG.md v368.




















# v370: removed the process_day() facade function that used to live here (it
# only called configure_processing() then forwarded every argument to
# _process_day_impl - no business logic of its own). process_day is now a
# direct alias to _process_day_impl (see the import block near the top of this
# file), and the configure_processing() call now lives in
# _call_process_day_v304_3_1 (the sole caller of process_day), executed at the
# exact same point in program flow as before. See CHANGELOG.md v370.

# ========================================================
# CACHE MANAGEMENT
# ========================================================

def _dedupe_history(df: pd.DataFrame, subset: List[str], sort_cols: List[str]) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    tie_breakers = [c for c in ["ProcessedAt", "FolderFingerprint", "CacheVersion"] if c in out.columns and c not in sort_cols]
    pre_sort_cols = list(sort_cols) + tie_breakers
    if pre_sort_cols:
        out = out.sort_values(pre_sort_cols, kind="mergesort")
    out = out.drop_duplicates(subset=subset, keep="last")
    final_sort_cols = [c for c in sort_cols if c in out.columns]
    if final_sort_cols:
        out = out.sort_values(final_sort_cols, kind="mergesort")
    return out.reset_index(drop=True)



# ========================================================
# UI - DAILY MODE
# ========================================================


# ========================================================
# UI - TREND MODE (head-of audience)
# ========================================================


# ========================================================
# APP SHELL
# ========================================================


# ========================================================
# OUT DASHBOARD REPLACEMENT UI (with ARC integration)
# ========================================================

ARC_ROOT_FOLDER = r"\\hq.local\Corp\IOOF\Finance\IAS\Fund Accounting\Unit Pricing\BAU\MLCI & NULIS\Unison Pricing\ARC"
ARC_ARCHIVE_ROOT = os.path.join(ARC_ROOT_FOLDER, "Archive")
EXCHANGE_RATES_ROOT_FOLDER = r"G:\IOOF\Finance\IAS\Fund Accounting\Unit Pricing\BAU\MLCI & NULIS\Unison Pricing"


COMPOSITION_ORDER = ["Single-asset dominated", "Mostly single-asset", "Mixed-asset", "Unclassified"]
CONCENTRATION_ORDER = ["High", "Moderate", "Broad", "Unclassified"]
TRANSACTION_ORDER = ["None", "Settlement-only", "Mixed implementation", "Direct security trading", "Unclassified"]
NIL_ACTUAL_RETURN_ZERO_TOLERANCE_PP = 1e-9
NIL_ACTUAL_RETURN_REASON = "Actual Return is zero/nil and Benchmark Return is non-zero after FX explanation removed"
REGULAR_TYPE_ORDER = [
    "Type A - regular benchmark",
    "Type B - pseudo benchmark (UBSCASH)",
    "Type C - zero benchmark movement",
    "Benchmark return unavailable",
]
HOT_COLD_ORDER = ["No ARC match", "Cold", "Hot"]


def _series_or_default(df: Optional[pd.DataFrame], col: Optional[str], default="") -> pd.Series:
    if df is None or df.empty:
        return pd.Series(dtype="object")
    if col is None or col not in df.columns:
        return pd.Series([default] * len(df), index=df.index, dtype="object")
    return df[col]


# def pd.to_numeric(df: Optional[pd.DataFrame][col: Optional[str]], errors='coerce').fillna(0) -> pd.Series:
    if df is None or df.empty:
        return pd.Series(dtype="float64")
    if col is None or col not in df.columns:
        return pd.Series([float("nan")] * len(df), index=df.index, dtype="float64")
    return pd.to_numeric(df[col], errors='coerce').fillna(0)


def _series_unique_preview(s: pd.Series, limit: int = 6) -> str:
    vals = sorted({str(v).strip() for v in s.astype(str).tolist() if str(v).strip()})[:limit]
    return " | ".join(vals)


def _first_non_blank(series: pd.Series) -> str:
    for v in series.astype(str).tolist():
        v = str(v).strip()
        if v:
            return v
    return ""


def _standardise_out_portfolio_df(portfolio_df: pd.DataFrame) -> pd.DataFrame:
    if portfolio_df is None or portfolio_df.empty:
        return pd.DataFrame()
    out = portfolio_df.copy()

    code_col = resolve_col(out, ["Portfolio code"], COLUMN_ALIASES["portfolio_code"])
    if code_col is None:
        code_col = "Portfolio" if "Portfolio" in out.columns else None

    out["Portfolio code"] = _series_or_default(out, code_col, "").astype(str).str.strip()
    out["Portfolio Name"] = _series_or_default(out, find_col(out, COLUMN_ALIASES["portfolio_name"]), "").astype(str).str.strip()
    out["Trust/Sector"] = _series_or_default(out, find_col(out, COLUMN_ALIASES["trust_sector"]), "").astype(str).str.strip()
    out["Portfolio Type"] = _series_or_default(out, find_col(out, COLUMN_ALIASES["portfolio_type"]), "").astype(str).str.strip()
    out["External portfolio reference"] = _series_or_default(out, find_col(out, COLUMN_ALIASES["external_portfolio_reference"]), "").astype(str).str.strip()
    out["Status"] = _series_or_default(out, find_col(out, COLUMN_ALIASES["status"]), "OUT").astype(str).str.strip()
    out["Status Normalised"] = out["Status"].astype(str).str.upper().str.strip()
    out["Within Tolerance"] = out["Status Normalised"].ne("OUT")
    out["Tolerance Bucket"] = out["Within Tolerance"].map({True: "Within Tolerance", False: "OUT"})
    out["Comment"] = _series_or_default(out, find_col(out, COLUMN_ALIASES["comment"]), "").astype(str).str.strip()
    out["Benchmark Code"] = _series_or_default(out, resolve_benchmark_code_col(out), "").astype(str).str.strip()

    fdv_col = resolve_fdv_current_value_col(out) or find_col(out, COLUMN_ALIASES["fdv_curr"])
    out["FDV Valuation(Current Day) Num"] = num(out, fdv_col)
    out["abs_fdv"] = out["FDV Valuation(Current Day) Num"].abs()
    out["Actual vs Benchmark Num"] = num(out, find_col(out, COLUMN_ALIASES["actual_vs_benchmark"]))
    out["Actual Return Num"] = num(out, find_col(out, COLUMN_ALIASES["actual_return"]))
    out["Benchmark Return Num"] = num(out, find_col(out, COLUMN_ALIASES["benchmark_return"]))
    reported_over_col = find_col(out, COLUMN_ALIASES["over_under"])
    out["Reported DDetailedReturn over/under"] = num(out, reported_over_col)
    out["Calculated over/under"] = out["Actual Return Num"] - out["Benchmark Return Num"]
    out["Reported vs Calculated over/under Difference"] = out["Reported DDetailedReturn over/under"] - out["Calculated over/under"]
    out["Abs Reported vs Calculated over/under Difference"] = out["Reported vs Calculated over/under Difference"].abs()
    out["Over/Under Num"] = out["Calculated over/under"]
    out["Tolerance Num"] = num(out, find_col(out, COLUMN_ALIASES["tolerance"]))

    out["Portfolio"] = out["Portfolio code"]
    out["Actual Return Decimal"] = out["Actual Return Num"] / 100.0
    out["Benchmark Return Decimal"] = out["Benchmark Return Num"] / 100.0
    out["Calculated over/under Decimal"] = out["Calculated over/under"] / 100.0
    out["Tolerance Decimal"] = out["Tolerance Num"] / 100.0
    out["Calculated Actual v Benchmark Diff Num"] = out["Calculated over/under Decimal"].abs()
    out["Volatility over Tolerance Num"] = (out["Calculated Actual v Benchmark Diff Num"] - out["Tolerance Decimal"].abs()).clip(lower=0.0)
    calc_available = out["Calculated over/under"].notna() & out["Tolerance Num"].notna()
    out.loc[calc_available, "Within Tolerance"] = out.loc[calc_available, "Calculated over/under"].abs() <= out.loc[calc_available, "Tolerance Num"].abs()
    out["Tolerance Bucket"] = out["Within Tolerance"].map({True: "Within Tolerance", False: "OUT"})
    if "sev_ratio" not in out.columns:
        out["sev_ratio"] = out["Volatility over Tolerance Num"]
    else:
        out["sev_ratio"] = num(out, "sev_ratio").fillna(out["Volatility over Tolerance Num"])
    out["External portfolio reference norm"] = normalise_join_key_series(out["External portfolio reference"])
    out["Portfolio code norm"] = normalise_join_key_series(out["Portfolio code"])
    return out


def _dedupe_dashboard_portfolio_df(portfolio_df: pd.DataFrame) -> pd.DataFrame:
    if portfolio_df is None or portfolio_df.empty:
        return pd.DataFrame()
    out = portfolio_df.copy()
    out = out[out["Portfolio code"].astype(str).str.strip() != ""].copy()
    if out.empty:
        return out

    out["_status_rank"] = out["Status Normalised"].eq("OUT").map({True: 0, False: 1})
    out["_benchmark_source_rank"] = out.get(
        "Benchmark Code Source",
        pd.Series(["DDetailedReturn"] * len(out), index=out.index)
    ).astype(str).eq("BenchmarkStatic").map({True: 0, False: 1})
    out["_benchmark_code_nonblank_rank"] = out.get(
        "Benchmark Code",
        pd.Series([""] * len(out), index=out.index)
    ).astype(str).str.strip().ne("").map({True: 0, False: 1})
    out["_abs_variance_rank"] = pd.to_numeric(out.get("Calculated over/under", pd.Series(dtype="float64")), errors='coerce').abs().fillna(-1.0)
    out["_abs_fdv_rank"] = num(out, "FDV Valuation(Current Day) Num").abs().fillna(-1.0)

    out = out.sort_values(
        [
            "Portfolio code",
            "_status_rank",
            "_benchmark_source_rank",
            "_benchmark_code_nonblank_rank",
            "_abs_variance_rank",
            "_abs_fdv_rank",
        ],
        ascending=[True, True, True, True, False, False],
        kind="mergesort",
    )
    out = out.drop_duplicates(subset=["Portfolio code"], keep="first").copy()
    return out.drop(columns=[
        c for c in [
            "_status_rank",
            "_benchmark_source_rank",
            "_benchmark_code_nonblank_rank",
            "_abs_variance_rank",
            "_abs_fdv_rank",
        ] if c in out.columns
    ]).reset_index(drop=True)

def _classify_composition_from_dat(dat: Optional[pd.DataFrame]) -> pd.DataFrame:
    empty = pd.DataFrame(columns=["Portfolio code", "Composition", "AssetTypeCount", "Top asset types"])
    if dat is None or dat.empty:
        return empty
    port_col = find_col(dat, ["Portfolio code", "Portfolio", "portfolio"])
    driver_col = resolve_driver_label_col(dat)
    if port_col is None or driver_col is None:
        return empty
    tmp = dat[[port_col, driver_col]].copy()
    tmp[port_col] = tmp[port_col].astype(str).str.strip()
    tmp[driver_col] = tmp[driver_col].astype(str).str.strip()
    tmp = tmp[(tmp[port_col] != "") & (tmp[driver_col] != "")].drop_duplicates()
    if tmp.empty:
        return empty

    counts = tmp.groupby(port_col)[driver_col].nunique().rename("AssetTypeCount").reset_index()
    previews = tmp.groupby(port_col)[driver_col].agg(_series_unique_preview).rename("Top asset types").reset_index()
    out = counts.merge(previews, on=port_col, how="left").rename(columns={port_col: "Portfolio code"})

    def bucket(n: object) -> str:
        n_num = pd.to_numeric(n, errors='coerce')
        if pd.isna(n_num):
            return "Unclassified"
        n_int = int(n_num)
        if n_int <= 1:
            return "Single-asset dominated"
        if n_int == 2:
            return "Mostly single-asset"
        return "Mixed-asset"

    out["Composition"] = out["AssetTypeCount"].map(bucket)
    return out[["Portfolio code", "Composition", "AssetTypeCount", "Top asset types"]]


def _classify_concentration_from_dar(dar: Optional[pd.DataFrame]) -> pd.DataFrame:
    empty = pd.DataFrame(columns=["Portfolio code", "Concentration", "HoldingCount", "Holding label preview"])
    if dar is None or dar.empty:
        return empty
    port_col = find_col(dar, ["Portfolio code", "Portfolio", "portfolio"])
    holding_col = (
        find_col(dar, ["Asset Name", "asset name", "Security Name", "Security Description", "Asset description", "Holding", "Investment Name", "Description", "Asset"])
        or resolve_driver_label_col(dar)
    )
    if port_col is None:
        return empty

    if holding_col is not None and holding_col in dar.columns:
        tmp = dar[[port_col, holding_col]].copy()
        tmp[port_col] = tmp[port_col].astype(str).str.strip()
        tmp[holding_col] = tmp[holding_col].astype(str).str.strip()
        tmp = tmp[(tmp[port_col] != "") & (tmp[holding_col] != "")]
        if tmp.empty:
            return empty
        counts = tmp.groupby(port_col)[holding_col].nunique().rename("HoldingCount").reset_index()
        previews = tmp.groupby(port_col)[holding_col].agg(_series_unique_preview).rename("Holding label preview").reset_index()
        out = counts.merge(previews, on=port_col, how="left").rename(columns={port_col: "Portfolio code"})
    else:
        tmp = dar[[port_col]].copy()
        tmp[port_col] = tmp[port_col].astype(str).str.strip()
        tmp = tmp[tmp[port_col] != ""]
        if tmp.empty:
            return empty
        out = tmp.groupby(port_col).size().rename("HoldingCount").reset_index().rename(columns={port_col: "Portfolio code"})
        out["Holding label preview"] = ""

    def bucket(n: object) -> str:
        n_num = pd.to_numeric(n, errors='coerce')
        if pd.isna(n_num):
            return "Unclassified"
        n_int = int(n_num)
        if n_int <= 3:
            return "High"
        if n_int <= 7:
            return "Moderate"
        return "Broad"

    out["Concentration"] = out["HoldingCount"].map(bucket)
    return out[["Portfolio code", "Concentration", "HoldingCount", "Holding label preview"]]



def _classify_transaction_nature_from_txn_core(txn: Optional[pd.DataFrame]) -> pd.DataFrame:
    """Fast transaction mapper.

    v299: avoid row-wise wide text concatenation and preview construction during
    initial load. Classification uses vectorised per-column masks and preview text
    is deferred to selected-portfolio detail views.
    """
    empty = pd.DataFrame(columns=["Portfolio code", "Transaction nature", "Transaction row count", "Transaction preview"])
    if txn is None or not isinstance(txn, pd.DataFrame) or txn.empty:
        return empty

    port_col = find_col(txn, ["Portfolio code", "Portfolio", "portfolio", "PortfolioCode"])
    if port_col is None or port_col not in txn.columns:
        return empty

    candidate_cols = []
    for key in [
        "Transaction Type", "Transaction Description", "Description", "Narration", "Comment",
        "Asset Name", "Security Name", "Security Description", "Asset Type", "Investment Name",
    ]:
        col = find_col(txn, [key])
        if col is not None and col in txn.columns and col not in candidate_cols:
            candidate_cols.append(col)

    tmp = txn[[port_col] + candidate_cols].copy() if candidate_cols else txn[[port_col]].copy()
    tmp[port_col] = tmp[port_col].astype(str).str.strip()
    tmp = tmp[tmp[port_col] != ""]
    if tmp.empty:
        return empty

    grouped = tmp.groupby(port_col, dropna=False).size().reset_index(name="Transaction row count")
    grouped = grouped.rename(columns={port_col: "Portfolio code"})
    grouped["Portfolio code"] = grouped["Portfolio code"].astype(str).str.strip()
    grouped["Transaction nature"] = "Mixed implementation"
    grouped["Transaction preview"] = ""

    if candidate_cols:
        settlement_pattern = r"settle|settlement|cash|income|expense|fee|tax|gst|distribution|accrual"
        trade_pattern = r"buy|sell|purchase|redeem|redemption|subscribe|subscription|trade|switch|security"
        has_settlement_row = pd.Series(False, index=tmp.index)
        has_trade_row = pd.Series(False, index=tmp.index)
        for col in candidate_cols:
            s = tmp[col].fillna("").astype(str).str.lower()
            has_settlement_row = has_settlement_row | s.str.contains(settlement_pattern, regex=True, na=False)
            has_trade_row = has_trade_row | s.str.contains(trade_pattern, regex=True, na=False)
        flags = pd.DataFrame({
            "Portfolio code": tmp[port_col].astype(str).str.strip(),
            "_has_settlement": has_settlement_row.astype(bool),
            "_has_trade": has_trade_row.astype(bool),
        })
        flag_by_port = flags.groupby("Portfolio code", dropna=False).agg(
            _has_settlement=("_has_settlement", "max"),
            _has_trade=("_has_trade", "max"),
        ).reset_index()
        grouped = grouped.merge(flag_by_port, on="Portfolio code", how="left")
        has_security_hint = any(any(word in str(c).lower() for word in ["security", "asset", "investment"]) for c in candidate_cols)
        grouped["_has_settlement"] = grouped["_has_settlement"].fillna(False).astype(bool)
        grouped["_has_trade"] = grouped["_has_trade"].fillna(False).astype(bool)
        grouped.loc[(~grouped["_has_trade"]) & grouped["_has_settlement"], "Transaction nature"] = "Settlement-only"
        grouped.loc[grouped["_has_trade"] & bool(has_security_hint) & (~grouped["_has_settlement"]), "Transaction nature"] = "Direct security trading"
        grouped = grouped.drop(columns=["_has_settlement", "_has_trade"], errors="ignore")

    grouped.loc[pd.to_numeric(grouped["Transaction row count"], errors="coerce").fillna(0).astype(int).eq(0), "Transaction nature"] = "None"
    return grouped[["Portfolio code", "Transaction nature", "Transaction row count", "Transaction preview"]].copy()

SHOW_TRANSACTION_DIAGNOSTICS = False  # v193: production default; set True only for transaction timing investigations

def _classify_transaction_nature_from_txn(txn: pd.DataFrame, timing_callback=None) -> pd.DataFrame:
    """Instrumented wrapper around the original transaction mapper.

    The output remains delegated to _classify_transaction_nature_from_txn_core(...).
    The extra timings are diagnostic-only so they do not change classification logic.
    """
    total_started = time.perf_counter()

    def _emit(label: str, started_at: float, status: str = "Done") -> None:
        if timing_callback is not None:
            try:
                timing_callback(label, started_at, status)
            except Exception:
                pass

    step_started = time.perf_counter()
    port_col = None
    text_cols = []
    txn_frame = txn if isinstance(txn, pd.DataFrame) else pd.DataFrame()
    if not txn_frame.empty:
        try:
            port_col = find_col(txn_frame, ["portfoliocode", "portfolio code", "portfolio", "hiport code", "fund code"])
        except Exception:
            port_col = None
        try:
            for c in txn_frame.columns:
                lc = str(c).strip().lower()
                if any(token in lc for token in ["description", "transaction", "movement", "narrative", "type", "subtype", "security", "asset", "amount"]):
                    text_cols.append(c)
            text_cols = text_cols[:12]
        except Exception:
            text_cols = []
    _emit(f"Transaction map: resolve columns - portfolio={port_col or 'not found'}; text cols={len(text_cols):,}", step_started)

    step_started = time.perf_counter()
    key_series = pd.Series(dtype="object")
    unique_keys = 0
    if not txn_frame.empty and port_col is not None and port_col in txn_frame.columns:
        try:
            key_series = txn_frame[port_col].astype(str).str.strip()
            unique_keys = int(key_series[key_series != ""].nunique(dropna=True))
        except Exception:
            key_series = pd.Series(dtype="object")
            unique_keys = 0
    _emit(f"Transaction map: normalise portfolio keys - unique portfolios={unique_keys:,}", step_started)

    if SHOW_TRANSACTION_DIAGNOSTICS:
        step_started = time.perf_counter()
        signal_rows = 0
        if not txn_frame.empty and text_cols:
            try:
                text_blob = txn_frame[text_cols].fillna("").astype(str).agg(" ".join, axis=1).str.lower()
                signal_mask = text_blob.str.contains("margin|cash|fx|foreign exchange|buy|sell|subscription|redemption|income|fee|tax", regex=True, na=False)
                signal_rows = int(signal_mask.sum())
            except Exception:
                signal_rows = 0
        _emit(f"Transaction map: scan/classify transaction text diagnostic - signal rows={signal_rows:,}", step_started)
    else:
        _emit("Transaction map: scan/classify transaction text diagnostic skipped", time.perf_counter(), "Skipped")

    step_started = time.perf_counter()
    group_count = 0
    if not key_series.empty:
        try:
            nonblank_keys = key_series[key_series != ""]
            group_count = int(nonblank_keys.groupby(nonblank_keys).size().shape[0])
        except Exception:
            group_count = 0
    _emit(f"Transaction map: group by portfolio - groups={group_count:,}", step_started)

    if SHOW_TRANSACTION_DIAGNOSTICS:
        step_started = time.perf_counter()
        preview_count = 0
        if not txn_frame.empty and port_col is not None and text_cols:
            try:
                preview_frame = txn_frame[[port_col] + text_cols[:4]].copy()
                preview_frame["__preview__"] = preview_frame[text_cols[:4]].fillna("").astype(str).agg(" | ".join, axis=1).str.slice(0, 240)
                preview_count = int(preview_frame.groupby(port_col)["__preview__"].head(3).shape[0])
            except Exception:
                preview_count = 0
        _emit(f"Transaction map: build preview strings diagnostic - preview rows={preview_count:,}", step_started)
    else:
        _emit("Transaction map: build preview strings diagnostic skipped", time.perf_counter(), "Skipped")

    step_started = time.perf_counter()
    core_started = step_started
    result = _classify_transaction_nature_from_txn_core(txn)
    result_rows = len(result) if isinstance(result, pd.DataFrame) else 0
    core_elapsed = float(time.perf_counter() - core_started)
    _emit(f"Transaction map: core build split - delegated vectorised mapper complete; rows={result_rows:,}", core_started)
    _emit(f"Transaction map: original mapper output build - rows={result_rows:,}; core_elapsed={core_elapsed:,.4f}s", step_started)
    _emit("Transaction map: total detailed wrapper", total_started)
    return result

def _derive_mv_bucket(abs_fdv: object, tiny_upper: float) -> str:
    val = pd.to_numeric(abs_fdv, errors='coerce')
    if pd.isna(val):
        return "Regular"
    val = abs(float(val))
    if 0 < val <= float(tiny_upper):
        return "MV Tiny"
    return "Regular"


def _derive_regular_type(benchmark_code: object, benchmark_return: object) -> str:
    """Classify regular portfolios by benchmark type.

    Blank/missing benchmark returns are not the same as true zero benchmark movement.
    Only numeric benchmark returns that are effectively zero are classified as Type C.
    """
    code = str(benchmark_code or "").strip().upper()
    bmk_ret = pd.to_numeric(benchmark_return, errors='coerce')
    if code == "UBSCASH":
        return "Type B - pseudo benchmark (UBSCASH)"
    if pd.isna(bmk_ret):
        return "Benchmark return unavailable"
    if abs(float(bmk_ret)) < 1e-12:
        return "Type C - zero benchmark movement"
    return "Type A - regular benchmark"


def _metric_series(df: pd.DataFrame, metric_view: str) -> pd.Series:
    metric = str(metric_view or "Count")
    if metric == "Market Value":
        if "abs_fdv" in df.columns:
            return pd.to_numeric(df["abs_fdv"], errors='coerce').fillna(0.0)
        return num(df, "FDV Valuation(Current Day) Num").abs().fillna(0.0)
    if metric == "Severity-weighted":
        if "sev_ratio" in df.columns:
            return pd.to_numeric(df["sev_ratio"], errors='coerce').fillna(0.0)
        return num(df, "Volatility over Tolerance Num").fillna(0.0)
    return pd.Series([1.0] * len(df), index=df.index, dtype="float64")


# v368: removed _inspect_arc_workbook, _load_excel_sheet_normalised and
# _find_arc_workbook_for_date - all three were thin pass-through wrappers around
# bnp_helpers_arc.py (arc_v162), confirmed to have ZERO callers anywhere in this
# file or any helper module (full-codebase search). ARC is no longer an input
# source; bnp_helpers_arc.py has been deleted entirely. See CHANGELOG.md v368.



# v367: removed the ORIGINAL _prepare_arc_error_risk (ARC-workbook-based,
# via arc_v162._prepare_arc_error_risk). Confirmed dead: this name is
# reassigned twice more further down the file by unconditional top-level
# 'def' statements (v306.13.15 'No-ARC-workbook replacement', then
# v306.13.16 'Non-ARC replacement', which is the one actually bound and
# called at runtime) - this body never executed. arc_v162 itself, and the
# other thin wrappers around it (_inspect_arc_workbook,
# _load_excel_sheet_normalised, _find_arc_workbook_for_date, immediately
# above) are UNRELATED to this function and are kept unchanged. See
# CHANGELOG.md v367.




def _prepare_exchange_rate_source(run_date: object, timing_callback=None) -> Dict[str, object]:
    exchange_rates_v168.configure_exchange_rates(exchange_rates_root_folder=EXCHANGE_RATES_ROOT_FOLDER)
    return exchange_rates_v168.prepare_exchange_rate_source(run_date, timing_callback=timing_callback)



def _filter_exchange_rate_bundle_to_hot_portfolios(exchange_rate_bundle: Dict[str, object], portfolio_df: pd.DataFrame) -> Dict[str, object]:
    """Limit Auto explained by FX outputs to HOT portfolios only.

    This keeps the FX validation calculation unchanged, then filters the displayed/control bundle
    used by the Auto explained by FX tab and KPI count.
    """
    if not isinstance(exchange_rate_bundle, dict):
        return exchange_rate_bundle
    if portfolio_df is None or not isinstance(portfolio_df, pd.DataFrame) or portfolio_df.empty:
        exchange_rate_bundle = dict(exchange_rate_bundle)
        exchange_rate_bundle["portfolio_fx_summary_df"] = pd.DataFrame()
        exchange_rate_bundle["portfolio_fx_detail_df"] = pd.DataFrame()
        return exchange_rate_bundle
    if "Hot / Cold" not in portfolio_df.columns or "Portfolio code" not in portfolio_df.columns:
        return exchange_rate_bundle

    hot_codes = portfolio_df.loc[
        portfolio_df["Hot / Cold"].astype(str).str.strip().eq("Hot"),
        "Portfolio code",
    ].astype(str).str.strip()
    hot_keys = set(normalise_join_key_series(hot_codes).astype(str).tolist())

    def _filter_portfolio_df(df: object) -> pd.DataFrame:
        if df is None or not isinstance(df, pd.DataFrame) or df.empty:
            return pd.DataFrame() if df is None else df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()
        port_col = find_col(df, ["Portfolio", "Portfolio code", "PortfolioCode", "portfolio", "portfolio code"])
        if port_col is None or port_col not in df.columns:
            return df.copy()
        keys = normalise_join_key_series(df[port_col].astype(str).str.strip()).astype(str)
        return df.loc[keys.isin(hot_keys)].copy()

    out = dict(exchange_rate_bundle)
    before_summary = len(out.get("portfolio_fx_summary_df", pd.DataFrame())) if isinstance(out.get("portfolio_fx_summary_df", pd.DataFrame()), pd.DataFrame) else 0
    before_detail = len(out.get("portfolio_fx_detail_df", pd.DataFrame())) if isinstance(out.get("portfolio_fx_detail_df", pd.DataFrame()), pd.DataFrame) else 0
    out["portfolio_fx_summary_df"] = _filter_portfolio_df(out.get("portfolio_fx_summary_df", pd.DataFrame()))
    out["portfolio_fx_detail_df"] = _filter_portfolio_df(out.get("portfolio_fx_detail_df", pd.DataFrame()))
    after_summary = len(out.get("portfolio_fx_summary_df", pd.DataFrame())) if isinstance(out.get("portfolio_fx_summary_df", pd.DataFrame()), pd.DataFrame) else 0
    after_detail = len(out.get("portfolio_fx_detail_df", pd.DataFrame())) if isinstance(out.get("portfolio_fx_detail_df", pd.DataFrame()), pd.DataFrame) else 0

    control_df = out.get("portfolio_fx_control_df", pd.DataFrame())
    filter_rows = pd.DataFrame([
        {"Measure": "Auto explained by FX portfolio scope", "Value": "HOT portfolios only"},
        {"Measure": "HOT portfolio count used for FX scope", "Value": int(len(hot_keys))},
        {"Measure": "FX summary rows before HOT filter", "Value": int(before_summary)},
        {"Measure": "FX summary rows after HOT filter", "Value": int(after_summary)},
        {"Measure": "FX detail rows before HOT filter", "Value": int(before_detail)},
        {"Measure": "FX detail rows after HOT filter", "Value": int(after_detail)},
    ])
    if isinstance(control_df, pd.DataFrame) and not control_df.empty:
        out["portfolio_fx_control_df"] = pd.concat([control_df, filter_rows], ignore_index=True, sort=False)
    else:
        out["portfolio_fx_control_df"] = filter_rows
    return out

def _prepare_out_dashboard_bundle(folder: str, tiny_upper: float, progress_callback=None, fx_timing_callback=None, force_source_refresh: bool = False, force_process_refresh: bool = False, fx_line_match_tolerance_dollar: float = 100.0, current_account_dominance_threshold_pct: float = DEFAULT_CURRENT_ACCOUNT_DOMINANCE_THRESHOLD_PCT) -> Dict[str, object]:
    prepare_timing_rows: List[Dict[str, object]] = []
    # v345: on a forced source refresh, drop the shared FDV per-file cache and the
    # Central Mapping attrs cache so the next read re-pulls from G:/ (keeps the audit
    # trail honest - a refresh really re-reads the network).
    if bool(force_source_refresh):
        try:
            from bnp_helpers_fdv_enrichment import clear_fdv_cache as _clear_fdv_cache_v345
            # v350: also drop the on-disk FDV Parquet so a forced refresh truly re-reads G:/.
            _clear_fdv_cache_v345(drop_persisted=True)
        except Exception:
            pass
        try:
            from bnp_helpers_uut import clear_central_mapping_cache as _clear_cm_cache_v345
            _clear_cm_cache_v345()
        except Exception:
            pass
        # v346: also drop the cached FX / Error Risk Excel parses (incl. on-disk
        # Parquet) so a forced refresh genuinely re-reads the G:/ workbooks.
        try:
            from bnp_helpers_columns import clear_excel_cache as _clear_excel_cache_v346
            _clear_excel_cache_v346(drop_persisted=True)
        except Exception:
            pass
        # v356: also drop the per-date FX workbook PATH cache so a forced refresh
        # re-runs the Externals discovery walk (in case the workbook moved/renamed).
        try:
            from bnp_helpers_exchange_rates import clear_fx_workbook_path_cache as _clear_fx_path_v356
            _clear_fx_path_v356()
        except Exception:
            pass
    try:
        fx_line_match_tolerance_dollar = float(fx_line_match_tolerance_dollar)
    except Exception:
        fx_line_match_tolerance_dollar = 100.0
    if fx_line_match_tolerance_dollar < 0:
        fx_line_match_tolerance_dollar = 0.0
    try:
        current_account_dominance_threshold_pct = float(current_account_dominance_threshold_pct)
    except Exception:
        current_account_dominance_threshold_pct = float(DEFAULT_CURRENT_ACCOUNT_DOMINANCE_THRESHOLD_PCT)
    current_account_dominance_threshold_pct = max(0.0, min(100.0, float(current_account_dominance_threshold_pct)))

    def _progress(stage: str) -> None:
        if progress_callback is not None:
            try:
                progress_callback(stage)
            except Exception:
                pass

    def _record_prepare_timing(label: str, started_at: float, status: str = "Done", detail: str = "") -> None:
        elapsed = float(time.perf_counter() - started_at)
        # [removed] diagnostic timing-frame generation (prepare_timing_rows append).
        # fx_timing_callback is INTENTIONALLY retained: it drives the initial-load
        # FX subtimings shown in the loading progress cards.
        if fx_timing_callback is not None:
            try:
                fx_timing_callback(label, elapsed, status)
            except Exception:
                pass
        # v348 (instrument-only): mirror EVERY prepare phase into the deep-timing
        # run-log. The v347 log showed a ~39s window in the cold load that is timed
        # here (process_day, ARC enrichment, Hot/Cold classification, the shared
        # Tier 1 assignment build, shared section artefacts) but was invisible in the
        # run-log because these go to fx_timing_callback, not the deep-timing store.
        # Surfacing them here decomposes the "Load FX & Error Risk files" stage bar
        # end-to-end so the true ~32s culprit is named. No behaviour change.
        try:
            store = _deep_timing_store(None)
            store.append({
                "Interaction": _deep_timing_current_interaction(),
                "Sequence": len(store) + 1,
                "Phase": "Prepare bundle",
                "Function": str(label),
                "Status": str(status or "Done"),
                "ElapsedSeconds": round(float(elapsed), 4),
                "Rows": "",
                "CacheHit": "",
                "Detail": str(detail or ""),
                "StartedAt": round(float(started_at), 4),
            })
        except Exception:
            pass

    _progress("Load BNP day files")
    folder_fp = folder_fingerprint(folder)
    bnp_load_started = time.perf_counter()
    loaded, bnp_source_cache_status = _load_bnp_source_persistent_cached(folder, folder_fp, CACHE_VERSION, force_refresh=bool(force_source_refresh))
    _record_prepare_timing(
        "BNP load: persistent source dataframe cache",
        bnp_load_started,
        str(bnp_source_cache_status.get("Status", "Done")),
        # v349: surface the miss reason + whether the cache file existed at entry, so
        # the run-log shows WHY this rebuilt (e.g. fingerprint changed vs first build).
        f"missreason={bnp_source_cache_status.get('MissReason', '')}; "
        f"cache_existed_at_entry={bnp_source_cache_status.get('CacheExistedAtEntry', '')}; "
        f"fingerprint={folder_fp}; cache_path={bnp_source_cache_status.get('CachePath', '')}",
    )

    def _portfolio_timing(label: str, started_at: float, status: str = "Done") -> None:
        _record_prepare_timing(label, started_at, status)

    def _record_elapsed_subtiming(label: str, elapsed_seconds: float, status: str = "Done") -> None:
        # [removed] diagnostic timing-frame generation; fx_timing_callback retained
        # (drives the initial-load FX subtimings display).
        if fx_timing_callback is not None:
            try:
                fx_timing_callback(label, float(elapsed_seconds), status)
            except Exception:
                pass

    _progress("Portfolio calcs")
    portfolio_calc_total_started = time.perf_counter()
    portfolio_calc_step_started = time.perf_counter()
    out, process_day_cache_status = _load_process_day_persistent_cached(
        folder,
        folder_fp,
        0.0,
        CACHE_VERSION,
        loaded,
        force_refresh=bool(force_process_refresh),
        use_persistent_cache=bool(force_process_refresh),
    )
    dd = loaded.get("dd")
    dat = loaded.get("dat")
    dar = loaded.get("dar")
    txn = loaded.get("txn")
    bmk = loaded.get("bmk")
    _portfolio_timing("Portfolio calc: process_day core", portfolio_calc_step_started, str(process_day_cache_status.get("Status", "Done")))

    portfolio_calc_step_started = time.perf_counter()
    # v299: defer detail indexes until a detail-heavy section needs them.
    dat_index: Dict[str, pd.DataFrame] = {}
    dar_index: Dict[str, pd.DataFrame] = {}
    txn_index: Dict[str, pd.DataFrame] = {}
    _portfolio_timing("Portfolio calc: build detail indexes deferred", portfolio_calc_step_started, "Deferred")

    portfolio_calc_step_started = time.perf_counter()
    base_df = pd.DataFrame()
    if isinstance(dd, pd.DataFrame) and not dd.empty:
        base_df = _standardise_out_portfolio_df(dd)
    elif isinstance(out.get("portfolio_df"), pd.DataFrame) and not out.get("portfolio_df").empty:
        base_df = _standardise_out_portfolio_df(out.get("portfolio_df", pd.DataFrame()))

    if isinstance(base_df, pd.DataFrame) and not base_df.empty:
        base_df["Benchmark Code Original"] = base_df["Benchmark Code"].astype(str).str.strip()
        base_df["Benchmark Code Source"] = "DDetailedReturn"
        base_df["Benchmark Code Mapped"] = ""

    if isinstance(base_df, pd.DataFrame) and not base_df.empty and isinstance(bmk, pd.DataFrame) and not bmk.empty:
        bmk_port_col = find_col(bmk, ["portfoliocode", "portfolio code", "portfolio"])
        bmk_code_col = resolve_benchmark_code_col(bmk)
        if bmk_port_col is not None and bmk_code_col is not None:
            bmk_map = _prepare_portfolio_code_frame(bmk, bmk_port_col, output_name="Portfolio code", extra_cols=[bmk_code_col])
            if not bmk_map.empty and bmk_code_col in bmk_map.columns:
                bmk_map["Benchmark Code Mapped"] = bmk_map[bmk_code_col]
                bmk_map = bmk_map[bmk_map["Benchmark Code Mapped"] != ""]
                bmk_map = bmk_map[["Portfolio code", "Benchmark Code Mapped"]].drop_duplicates(subset=["Portfolio code"], keep="first")
            if not bmk_map.empty:
                base_df = base_df.drop(columns=[c for c in ["Benchmark Code Mapped"] if c in base_df.columns])
                base_df = base_df.merge(bmk_map, on="Portfolio code", how="left")
                has_mapped = base_df["Benchmark Code Mapped"].astype(str).str.strip() != ""
                base_df.loc[has_mapped, "Benchmark Code"] = base_df.loc[has_mapped, "Benchmark Code Mapped"]
                base_df.loc[has_mapped, "Benchmark Code Source"] = "BenchmarkStatic"

    portfolio_df = _dedupe_dashboard_portfolio_df(base_df)
    _portfolio_timing("Portfolio calc: standardise base and benchmark mapping", portfolio_calc_step_started)

    portfolio_calc_step_started = time.perf_counter()
    composition_map = _classify_composition_from_dat(dat)
    _portfolio_timing("Portfolio calc: composition map from DAssetTypeReturn", portfolio_calc_step_started)

    portfolio_calc_step_started = time.perf_counter()
    concentration_map = _classify_concentration_from_dar(dar)
    _portfolio_timing("Portfolio calc: concentration map from DAssetReturn", portfolio_calc_step_started)

    portfolio_calc_step_started = time.perf_counter()
    transaction_map = _classify_transaction_nature_from_txn(txn, timing_callback=_portfolio_timing)
    _portfolio_timing("Portfolio calc: transaction map from TransactionListing", portfolio_calc_step_started)

    portfolio_calc_step_started = time.perf_counter()
    txn_eligible_df = pd.DataFrame()
    try:
        if isinstance(txn, pd.DataFrame) and not txn.empty:
            txn_eligible_df = apply_transaction_control_break_eligibility(txn)
            _portfolio_timing("Portfolio calc: transaction eligibility precompute", portfolio_calc_step_started, "Done")
        else:
            _portfolio_timing("Portfolio calc: transaction eligibility precompute", portfolio_calc_step_started, "No TransactionListing")
    except Exception as e:
        txn_eligible_df = pd.DataFrame()
        _portfolio_timing("Portfolio calc: transaction eligibility precompute", portfolio_calc_step_started, f"Error: {type(e).__name__}: {e}")

    portfolio_calc_step_started = time.perf_counter()
    run_date = parse_date_from_path(folder)
    _portfolio_timing("Portfolio calc: parse run date", portfolio_calc_step_started)
    _portfolio_timing("Portfolio calc: total", portfolio_calc_total_started)
    _progress("Load ARC.xlb")
    arc_started = time.perf_counter()
    # v346: deep-time the Error Risk (BP Impact Tool.xlsb, G:/) load so the cold-load
    # cost - and the cache hit/miss on repeat opens - is visible in the run-log.
    # NOTE: pass {} (not `bundle`, which is not yet defined here) - the deep-timing
    # store lives in st.session_state, so the arg is ignored anyway.
    with _deep_timer({}, "Cold load", "Error Risk workbook (.xlsb, G:/)"):
        arc_bundle = _prepare_arc_error_risk(run_date, timing_callback=_record_elapsed_subtiming)
    _record_prepare_timing("ARC load: prepare ARC error risk", arc_started, "Done", str(arc_bundle.get("status", "")) if isinstance(arc_bundle, dict) else "")
    _progress("Load FX.xlsx")
    fx_source_started = time.perf_counter()
    # v346: deep-time the FX workbook (.xlsx, G:/) resolve+extract.
    with _deep_timer({}, "Cold load", "FX workbook (.xlsx, G:/)"):
        exchange_rate_bundle = _prepare_exchange_rate_source(run_date, timing_callback=_record_elapsed_subtiming)
    _record_prepare_timing("FX load: prepare exchange-rate source", fx_source_started, "Done", str(exchange_rate_bundle.get("status", "")) if isinstance(exchange_rate_bundle, dict) else "")
    # FX validation is included in the combined Independent FX workbook + validation progress step.
    try:
        fx_validation_started = time.perf_counter()
        # v347 (instrument-only): deep-time the INITIAL FX contribution retest. The
        # timing log showed the "Load FX & Error Risk files" stage is ~43s while the
        # two workbook parses are only ~5s - the remainder is this FX validation
        # compute (initial + final). This measures the initial pass so the run-log
        # shows its true cost. No behaviour change.
        with _deep_timer({}, "FX validation", "initial contribution retest"):
            portfolio_fx_summary_df, portfolio_fx_detail_df, portfolio_fx_control_df = fx_validation_v172.build_portfolio_fx_validation(
                dar if isinstance(dar, pd.DataFrame) else pd.DataFrame(),
                exchange_rate_bundle.get("exchange_rate_df", pd.DataFrame()) if isinstance(exchange_rate_bundle, dict) else pd.DataFrame(),
                portfolio_df=portfolio_df if "portfolio_df" in locals() else None,
                line_match_tolerance_dollar=fx_line_match_tolerance_dollar,
            )
        _record_prepare_timing("FX validation: initial contribution retest", fx_validation_started, "Done", f"summary_rows={len(portfolio_fx_summary_df) if isinstance(portfolio_fx_summary_df, pd.DataFrame) else 0}")
        if isinstance(exchange_rate_bundle, dict):
            exchange_rate_bundle["portfolio_fx_summary_df"] = portfolio_fx_summary_df
            exchange_rate_bundle["portfolio_fx_detail_df"] = portfolio_fx_detail_df
            exchange_rate_bundle["portfolio_fx_control_df"] = portfolio_fx_control_df
    except Exception as e:
        if isinstance(exchange_rate_bundle, dict):
            exchange_rate_bundle["portfolio_fx_summary_df"] = pd.DataFrame()
            exchange_rate_bundle["portfolio_fx_detail_df"] = pd.DataFrame()
            exchange_rate_bundle["portfolio_fx_control_df"] = pd.DataFrame([
                {"Measure": "Auto explained by FX error", "Value": f"{type(e).__name__}: {e}"}
            ])

    if not portfolio_df.empty:
        portfolio_df["mv_bucket"] = portfolio_df["abs_fdv"].map(lambda x: _derive_mv_bucket(x, tiny_upper))
        portfolio_df["regular_type"] = portfolio_df.apply(lambda r: _derive_regular_type(r.get("Benchmark Code", ""), r.get("Benchmark Return Num", pd.NA)), axis=1)
        portfolio_df.loc[portfolio_df["mv_bucket"] != "Regular", "regular_type"] = ""
        portfolio_df = portfolio_df.merge(composition_map, on="Portfolio code", how="left")
        portfolio_df = portfolio_df.merge(concentration_map, on="Portfolio code", how="left")
        portfolio_df = portfolio_df.merge(transaction_map, on="Portfolio code", how="left")
        for col, default in [("Composition", "Unclassified"), ("Concentration", "Unclassified"), ("Transaction nature", "None"), ("Top asset types", ""), ("Holding label preview", ""), ("Transaction preview", "")]:
            if col not in portfolio_df.columns:
                portfolio_df[col] = default
            else:
                portfolio_df[col] = portfolio_df[col].fillna(default)

        arc_portfolio_df = arc_bundle.get("arc_portfolio_df", pd.DataFrame())
        if isinstance(arc_portfolio_df, pd.DataFrame) and not arc_portfolio_df.empty:
            # v352.1 CRASH FIX: this is the LEGACY ARC-schema consumer. It expects the
            # columns "External portfolio reference norm" / "ARC Hiport Code norm" that
            # the old ARC workbook produced. The v306.13.16 BP Impact replacement frame
            # (Parent/Advisor/Error Risk Ratio) does NOT have them. Pre-v352 this block
            # was simply SKIPPED because the coverage frame was empty (the Advisor key
            # never bound), and Hot/Cold worked fine via the separate basis-impact path.
            # The v352 Advisor fix POPULATED the frame, which woke this dormant block and
            # it KeyError'd on the missing "External portfolio reference norm" column.
            # Guarding each merge on its required column keeps the block dormant for the
            # BP Impact schema (exactly as before) while the Advisor coverage fix stands.
            if "External portfolio reference norm" in arc_portfolio_df.columns:
                arc_by_ext = arc_portfolio_df.drop(columns=[c for c in ["advisor_norm", "ARC Hiport Code norm"] if c in arc_portfolio_df.columns]).copy()
                ext_nonblank = arc_by_ext[arc_by_ext["External portfolio reference norm"].astype(str).str.strip() != ""].copy()
                if not ext_nonblank.empty:
                    portfolio_df = portfolio_df.merge(ext_nonblank, on="External portfolio reference norm", how="left")
            if "ARC Hiport Code norm" in arc_portfolio_df.columns:
                hiport_nonblank = arc_portfolio_df[arc_portfolio_df["ARC Hiport Code norm"].astype(str).str.strip() != ""].copy()
                if not hiport_nonblank.empty:
                    hiport_cols = [c for c in ["ARC Advisor", "ARC Hiport Code", "ARC Asset Type of portfolio", "ARC Error Risk Ratio Pct", "ARC Error Risk Ratio Decimal"] if c in hiport_nonblank.columns]
                    hiport_merge = hiport_nonblank[["ARC Hiport Code norm"] + hiport_cols].drop_duplicates()
                    hiport_merge = hiport_merge.rename(columns={
                        "ARC Advisor": "ARC Advisor_fallback",
                        "ARC Hiport Code": "ARC Hiport Code_fallback",
                        "ARC Asset Type of portfolio": "ARC Asset Type of portfolio_fallback",
                        "ARC Error Risk Ratio Pct": "ARC Error Risk Ratio Pct_fallback",
                        "ARC Error Risk Ratio Decimal": "ARC Error Risk Ratio Decimal_fallback",
                    })
                    portfolio_df = portfolio_df.merge(hiport_merge, left_on="Portfolio code norm", right_on="ARC Hiport Code norm", how="left")
                    for base_col in ["ARC Advisor", "ARC Hiport Code", "ARC Asset Type of portfolio", "ARC Error Risk Ratio Pct", "ARC Error Risk Ratio Decimal"]:
                        fb_col = f"{base_col}_fallback"
                        if fb_col in portfolio_df.columns:
                            if base_col not in portfolio_df.columns:
                                portfolio_df[base_col] = portfolio_df[fb_col]
                            else:
                                portfolio_df[base_col] = portfolio_df[base_col].where(portfolio_df[base_col].notna() & (portfolio_df[base_col].astype(str).str.strip() != ""), portfolio_df[fb_col])
                            portfolio_df = portfolio_df.drop(columns=[fb_col])
                    if "ARC Hiport Code norm" in portfolio_df.columns:
                        portfolio_df = portfolio_df.drop(columns=["ARC Hiport Code norm"])
        for col, default in [
            ("ARC Advisor", ""),
            ("ARC Hiport Code", ""),
            ("ARC Asset Type of portfolio", ""),
            ("ARC Error Risk Ratio Pct", float("nan")),
            ("ARC Error Risk Ratio Decimal", float("nan")),
        ]:
            if col not in portfolio_df.columns:
                portfolio_df[col] = default

        calc_available = portfolio_df["Calculated over/under"].notna() & portfolio_df["Tolerance Num"].notna()
        portfolio_df["Within Tolerance"] = portfolio_df["Status Normalised"].ne("OUT")
        portfolio_df.loc[calc_available, "Within Tolerance"] = portfolio_df.loc[calc_available, "Calculated over/under"].abs() <= portfolio_df.loc[calc_available, "Tolerance Num"].abs()
        portfolio_df["Tolerance Bucket"] = portfolio_df["Within Tolerance"].map({True: "Within Tolerance", False: "OUT"})
        portfolio_df["Hot / Cold"] = pd.Series([""] * len(portfolio_df), index=portfolio_df.index, dtype="object")
        portfolio_df.loc[portfolio_df["Within Tolerance"], "Hot / Cold"] = "N/A"
        portfolio_df.loc[~portfolio_df["Within Tolerance"], "Hot / Cold"] = "No ARC match"
        comparable = (~portfolio_df["Within Tolerance"]) & portfolio_df["ARC Error Risk Ratio Decimal"].notna() & portfolio_df["Volatility over Tolerance Num"].notna()
        portfolio_df.loc[comparable & (portfolio_df["Volatility over Tolerance Num"] >= portfolio_df["ARC Error Risk Ratio Decimal"]), "Hot / Cold"] = "Hot"
        portfolio_df.loc[comparable & (portfolio_df["Volatility over Tolerance Num"] < portfolio_df["ARC Error Risk Ratio Decimal"]), "Hot / Cold"] = "Cold"
        portfolio_df = _attach_current_account_dominance_metrics(portfolio_df, dar if isinstance(dar, pd.DataFrame) else pd.DataFrame(), current_account_dominance_threshold_pct)
        portfolio_df["Auto explained label"] = ""
        def _v318_portfolio_label(r):
            # Unison code (External portfolio reference) first, then Hiport
            # (Portfolio code), then description (Portfolio Name is usually prefixed
            # with the unison code, so strip that leading token to avoid duplication).
            unison = str(r.get("External portfolio reference", "") or "").strip()
            hiport = str(r.get("Portfolio code", "") or "").strip()
            name = str(r.get("Portfolio Name", "") or "").strip()
            desc = name
            if unison and desc.upper().startswith(unison.upper()):
                desc = desc[len(unison):].strip()
            head = " - ".join([p for p in [unison, hiport] if p])
            core = head + (" - " + desc if desc else "")
            return f"{core} [{r.get('Tolerance Bucket', '')} / {r.get('Hot / Cold', '') or 'N/A'}]".strip(" -")
        portfolio_df["Portfolio label"] = portfolio_df.apply(_v318_portfolio_label, axis=1)

    txn_expl_summary_df = pd.DataFrame()

    debug_cols = [
        c for c in [
            "Portfolio code",
            "Portfolio Name",
            "Status",
            "Within Tolerance",
            "mv_bucket",
            "Benchmark Code Original",
            "Benchmark Code Mapped",
            "Benchmark Code",
            "Benchmark Code Source",
            "Benchmark Return Num",
            "regular_type",
        ] if c in portfolio_df.columns
    ]
    regular_type_debug_df = portfolio_df[debug_cols].copy() if debug_cols else pd.DataFrame()
    if not regular_type_debug_df.empty:
        if "Within Tolerance" in regular_type_debug_df.columns:
            regular_type_debug_df["Within Tolerance"] = regular_type_debug_df["Within Tolerance"].map(lambda x: "Yes" if bool(x) else "No")
        if "Benchmark Return Num" in regular_type_debug_df.columns:
            regular_type_debug_df["Benchmark Return Num"] = regular_type_debug_df["Benchmark Return Num"].map(lambda x: "" if pd.isna(x) else f"{float(x):,.6f}")

    # v306.0: precompute shared Tier 1 driver assignments once for all section renderers.
    tier1_assignments_df = pd.DataFrame()
    tier1_assignment_diag_df = pd.DataFrame()
    if isinstance(portfolio_df, pd.DataFrame) and not portfolio_df.empty:
        try:
            tier1_started = time.perf_counter()
            hot_for_tier1_df = portfolio_df[portfolio_df.get("Hot / Cold", pd.Series(dtype="object")).astype(str).str.strip().eq("Hot")].copy() if "Hot / Cold" in portfolio_df.columns else portfolio_df.copy()
            tier1_assignments_df, tier1_assignment_diag_df = _build_tier1_driver_assignments_vectorized(
                hot_for_tier1_df,
                dat_index or (dat if isinstance(dat, pd.DataFrame) else pd.DataFrame()),
                dar_index or (dar if isinstance(dar, pd.DataFrame) else pd.DataFrame()),
            )
            _record_prepare_timing("Build executive summary: shared Tier 1 assignments", tier1_started, "Done", f"assignment_rows={len(tier1_assignments_df) if isinstance(tier1_assignments_df, pd.DataFrame) else 0}")
        except Exception as e:
            tier1_assignments_df = pd.DataFrame()
            tier1_assignment_diag_df = pd.DataFrame([{"Stage": "Shared Tier 1 assignments", "Error": f"{type(e).__name__}: {e}"}])
            _record_prepare_timing("Build executive summary: shared Tier 1 assignments", tier1_started if 'tier1_started' in locals() else time.perf_counter(), "Error", f"{type(e).__name__}: {e}")

    # Re-run FX validation after ARC enrichment and Hot/Cold classification.
    if isinstance(exchange_rate_bundle, dict):
        try:
            fx_validation_final_started = time.perf_counter()
            # v347 (instrument-only): deep-time the FINAL HOT-scoped FX contribution
            # retest - this runs a SECOND full build_portfolio_fx_validation after ARC
            # enrichment. If both passes are individually large in the run-log, that
            # confirms the ~38s non-parse cost of the FX/Error-Risk stage and shows
            # whether the initial pass is redundant. No behaviour change.
            with _deep_timer({}, "FX validation", "final HOT-scoped contribution retest"):
                portfolio_fx_summary_df, portfolio_fx_detail_df, portfolio_fx_control_df = fx_validation_v172.build_portfolio_fx_validation(
                    dar if isinstance(dar, pd.DataFrame) else pd.DataFrame(),
                    exchange_rate_bundle.get("exchange_rate_df", pd.DataFrame()) if isinstance(exchange_rate_bundle, dict) else pd.DataFrame(),
                    portfolio_df=portfolio_df,
                    line_match_tolerance_dollar=fx_line_match_tolerance_dollar,
                )
            tier1_context_bundle = {
                "portfolio_df": portfolio_df,
                "dat": dat if isinstance(dat, pd.DataFrame) else pd.DataFrame(),
                "dar": dar if isinstance(dar, pd.DataFrame) else pd.DataFrame(),
                "dat_index": dat_index,
                "dar_index": dar_index,
                "tier1_assignments_df": tier1_assignments_df,
                "tier1_assignment_diag_df": tier1_assignment_diag_df,
            }
            # v347 (instrument-only): also time the tier1 driver assignment applied to
            # the FX summary - it runs inside the same FX stage, so timing it fully
            # decomposes the ~43s "Load FX & Error Risk files" bar.
            with _deep_timer({}, "FX validation", "apply tier1 driver assignments to FX summary"):
                portfolio_fx_summary_df = _apply_tier1_driver_assignments_to_fx_summary(tier1_context_bundle, portfolio_fx_summary_df)
            _record_prepare_timing("FX validation: final HOT-scoped contribution retest", fx_validation_final_started, "Done", f"summary_rows={len(portfolio_fx_summary_df) if isinstance(portfolio_fx_summary_df, pd.DataFrame) else 0}")
            exchange_rate_bundle["portfolio_fx_summary_df"] = portfolio_fx_summary_df
            exchange_rate_bundle["portfolio_fx_detail_df"] = portfolio_fx_detail_df
            exchange_rate_bundle["portfolio_fx_control_df"] = portfolio_fx_control_df
        except Exception as e:
            exchange_rate_bundle["portfolio_fx_summary_df"] = pd.DataFrame()
            exchange_rate_bundle["portfolio_fx_detail_df"] = pd.DataFrame()
            exchange_rate_bundle["portfolio_fx_control_df"] = pd.DataFrame([
                {"Measure": "Auto explained by FX contribution retest error", "Value": f"{type(e).__name__}: {e}"}
            ])

    if isinstance(exchange_rate_bundle, dict):
        exchange_rate_bundle = _filter_exchange_rate_bundle_to_hot_portfolios(exchange_rate_bundle, portfolio_df)

    # v306.0: prepare shared section artefacts once so section switching is mostly render-only.
    shared_context_bundle = {
        "portfolio_df": portfolio_df,
        "dat": dat if isinstance(dat, pd.DataFrame) else pd.DataFrame(),
        "dar": dar if isinstance(dar, pd.DataFrame) else pd.DataFrame(),
        "dat_index": dat_index,
        "dar_index": dar_index,
        "tier1_assignments_df": tier1_assignments_df,
        "tier1_assignment_diag_df": tier1_assignment_diag_df,
    }
    auto_fx_summary_display_df = pd.DataFrame()
    auto_fx_section_frames: Dict[str, pd.DataFrame] = {}
    hot_resolution_sets: Dict[str, pd.DataFrame] = {"hot": pd.DataFrame(), "auto_fx": pd.DataFrame(), "nil_actual_return": pd.DataFrame(), "current_account": pd.DataFrame(), "unexplained": pd.DataFrame()}
    tier1_driver_count_frames: Dict[str, pd.DataFrame] = {}
    try:
        shared_started = time.perf_counter()
        auto_fx_summary_raw_df = exchange_rate_bundle.get("portfolio_fx_summary_df", pd.DataFrame()) if isinstance(exchange_rate_bundle, dict) else pd.DataFrame()
        auto_fx_summary_display_df = _prepare_auto_fx_summary_display(shared_context_bundle, auto_fx_summary_raw_df)
        auto_fx_section_frames = {
            key: _format_numeric_df_for_display(_auto_fx_section_display_df(auto_fx_summary_display_df, key))
            for key in ["A", "B", "C", "D", "E"]
        }
        hot_df, auto_fx_df, nil_actual_return_df, current_account_df, unexplained_df = _hot_resolution_sets({"portfolio_df": portfolio_df}, auto_fx_summary_raw_df)
        hot_resolution_sets = {"hot": hot_df, "auto_fx": auto_fx_df, "nil_actual_return": nil_actual_return_df, "current_account": current_account_df, "unexplained": unexplained_df}
        tier1_driver_count_frames = {
            "hot": _tier1_count_frame_from_assignments(hot_df, tier1_assignments_df),
            "auto_fx": _tier1_count_frame_from_assignments(auto_fx_df, tier1_assignments_df),
            "nil_actual_return": _tier1_count_frame_from_assignments(nil_actual_return_df, tier1_assignments_df),
            "current_account": _tier1_count_frame_from_assignments(current_account_df, tier1_assignments_df),
            "unexplained": _tier1_count_frame_from_assignments(unexplained_df, tier1_assignments_df),
        }
        _record_prepare_timing("Build executive summary: shared section artefacts", shared_started, "Done", f"hot={len(hot_df)}; fx={len(auto_fx_df)}; nil_actual_return={len(nil_actual_return_df)}; current_account={len(current_account_df)}; unexplained={len(unexplained_df)}")
    except Exception as e:
        _record_prepare_timing("Build executive summary: shared section artefacts", shared_started if 'shared_started' in locals() else time.perf_counter(), "Error", f"{type(e).__name__}: {e}")

    return {
        "out": out,
        "summary_df": out.get("summary_df", pd.DataFrame()) if isinstance(out, dict) else pd.DataFrame(),
        "control_break_audit_df": out.get("control_break_audit_df", pd.DataFrame()) if isinstance(out, dict) else pd.DataFrame(),
        "diagnostic_df": out.get("diagnostic_df", pd.DataFrame()) if isinstance(out, dict) else pd.DataFrame(),
        "exception_df": out.get("exception_df", pd.DataFrame()) if isinstance(out, dict) else pd.DataFrame(),
        "portfolio_df": portfolio_df,
        "dat": dat if isinstance(dat, pd.DataFrame) else pd.DataFrame(),
        "dar": dar if isinstance(dar, pd.DataFrame) else pd.DataFrame(),
        "txn": txn if isinstance(txn, pd.DataFrame) else pd.DataFrame(),
        "txn_eligible_df": txn_eligible_df if isinstance(txn_eligible_df, pd.DataFrame) else pd.DataFrame(),
        "bmk": bmk if isinstance(bmk, pd.DataFrame) else pd.DataFrame(),
        "file_meta_df": loaded.get("file_meta_df", pd.DataFrame()) if isinstance(loaded, dict) else pd.DataFrame(),
        "bnp_load_timing_df": _label_bnp_load_timing_scope(loaded.get("bnp_load_timing_df", pd.DataFrame()) if isinstance(loaded, dict) else pd.DataFrame(), bnp_source_cache_status),
        "bnp_source_cache_status_df": _cache_status_df(bnp_source_cache_status),
        "process_day_cache_status_df": _cache_status_df(process_day_cache_status),
        "process_day_timing_df": out.get("process_day_timing_df", pd.DataFrame()) if isinstance(out, dict) else pd.DataFrame(),
        "prepare_bundle_timing_df": pd.DataFrame(prepare_timing_rows),
        "dat_index": dat_index,
        "dar_index": dar_index,
        "txn_index": txn_index,
        "tiny_upper": float(tiny_upper),
        "fx_line_match_tolerance_dollar": float(fx_line_match_tolerance_dollar),
        "current_account_dominance_threshold_pct": float(current_account_dominance_threshold_pct),
        "folder": folder,
        "arc": arc_bundle,
        "exchange_rates": exchange_rate_bundle,
        "regular_type_debug_df": regular_type_debug_df,
        "txn_expl_summary_df": txn_expl_summary_df if isinstance(txn_expl_summary_df, pd.DataFrame) else pd.DataFrame(),
        "tier1_assignments_df": tier1_assignments_df if isinstance(tier1_assignments_df, pd.DataFrame) else pd.DataFrame(),
        "tier1_assignment_diag_df": tier1_assignment_diag_df if isinstance(tier1_assignment_diag_df, pd.DataFrame) else pd.DataFrame(),
        "hot_resolution_sets": hot_resolution_sets,
        "tier1_driver_count_frames": tier1_driver_count_frames,
        "auto_fx_summary_display_df": auto_fx_summary_display_df if isinstance(auto_fx_summary_display_df, pd.DataFrame) else pd.DataFrame(),
        "auto_fx_section_frames": auto_fx_section_frames if isinstance(auto_fx_section_frames, dict) else {},
        "_display_cache": {},
    }


def _frame_for_portfolio_subset(source: object, portfolio_df: pd.DataFrame) -> pd.DataFrame:
    """Return rows for a portfolio subset from either an indexed dict or a DataFrame."""
    if portfolio_df is None or not isinstance(portfolio_df, pd.DataFrame) or portfolio_df.empty:
        return pd.DataFrame()
    port_col = find_col(portfolio_df, ["Portfolio code", "Portfolio", "PortfolioCode", "portfolio", "portfolio code"])
    if not port_col:
        return pd.DataFrame()
    keys_df = portfolio_df[[port_col]].copy()
    keys_df["_pkey"] = normalise_join_key_series(keys_df[port_col].astype(str).str.strip())
    wanted = set(keys_df["_pkey"].astype(str).str.strip().replace("", pd.NA).dropna().tolist())
    if not wanted:
        return pd.DataFrame()
    frames = []
    if isinstance(source, dict):
        for k in wanted:
            rows = source.get(str(k), pd.DataFrame())
            if isinstance(rows, pd.DataFrame) and not rows.empty:
                tmp = rows.copy()
                if not find_col(tmp, ["Portfolio code", "Portfolio", "PortfolioCode", "portfolio", "portfolio code"]):
                    tmp["Portfolio code"] = str(k)
                frames.append(tmp)
        return pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()
    if source is None or not isinstance(source, pd.DataFrame) or source.empty:
        return pd.DataFrame()
    src_port_col = find_col(source, ["Portfolio code", "Portfolio", "PortfolioCode", "portfolio", "portfolio code"])
    if not src_port_col or src_port_col not in source.columns:
        return pd.DataFrame()
    tmp = source.copy()
    tmp["_pkey"] = normalise_join_key_series(tmp[src_port_col].astype(str).str.strip())
    tmp = tmp[tmp["_pkey"].astype(str).isin(wanted)].drop(columns=["_pkey"], errors="ignore")
    return tmp.reset_index(drop=True)


def _build_tier1_driver_assignments_vectorized(hot_df: pd.DataFrame, dat: object, dar: object) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """Fast portfolio-level Tier 1 assignment for the executive OUT population.

    Source of truth rules:
    - Use DAssetTypeReturn where usable contribution rows exist.
    - Overlay DAssetReturn using Asset to Portfolio Contribution only.
    - Do not use DAssetReturn Excess Contribution in this assignment path.
    - Return one assignment per portfolio so Driver Movement, Hot Tier 1 summary,
      Auto FX grouping, and Unexplained grouping can all use the same source table.
    """
    started_total = time.perf_counter()

    base_cols = [
        "Largest Tier 1 driver", "Portfolio code", "Portfolio Name", "FDV Valuation(Current Day)",
        "Benchmark Code", "ARC Asset Type of portfolio", "Hot / Cold", "Actual Return", "Benchmark Return",
        "Calculated Actual v Benchmark Diff", "Tolerance", "Volatility over Tolerance", "ARC Error Risk Ratio",
    ]

    def _empty_result(status: str = "No assignment input", error: str = "") -> Tuple[pd.DataFrame, pd.DataFrame]:
        timing_df = pd.DataFrame([{
            "Portfolio code": "<vectorized>",
            "Portfolio Name": "All OUT portfolios",
            "Hot / Cold": "Mixed",
            "Largest Tier 1 driver": "No DAssetTypeReturn",
            "ElapsedSeconds": round(float(time.perf_counter() - started_total), 4),
            "DAT rows": 0,
            "DAR rows": 0,
            "Status": status,
            "Error": error,
        }])
        return pd.DataFrame(columns=base_cols), timing_df

    if hot_df is None or not isinstance(hot_df, pd.DataFrame) or hot_df.empty:
        return _empty_result("No hot / OUT rows")

    try:
        port_col = find_col(hot_df, ["Portfolio code", "Portfolio", "PortfolioCode", "portfolio", "portfolio code"])
        if not port_col:
            return _empty_result("Portfolio column unresolved")

        work_port = hot_df.copy()
        work_port["_pkey"] = normalise_join_key_series(work_port[port_col].astype(str).str.strip())
        prev_map = {str(r["_pkey"]): _asset_type_detail_portfolio_prev_fdv_num(r) for _, r in work_port.iterrows()}

        dat_frame = _frame_for_portfolio_subset(dat, hot_df)
        dar_frame = _frame_for_portfolio_subset(dar, hot_df)

        dat_groups = pd.DataFrame(columns=["_pkey", "Tier 1 Group", "Contribution"])
        if isinstance(dat_frame, pd.DataFrame) and not dat_frame.empty:
            dat_port_col = find_col(dat_frame, ["Portfolio code", "Portfolio", "PortfolioCode", "portfolio", "portfolio code"])
            if dat_port_col:
                dat_prep, *_ = _prepare_asset_type_detail_rows(dat_frame)
                dat_prep["_pkey"] = normalise_join_key_series(dat_prep[dat_port_col].astype(str).str.strip())
                dat_prep["_portfolio_prev_fdv_num"] = dat_prep["_pkey"].map(prev_map)
                # v306.5.7: executive driver assignment may receive display-shaped portfolio rows
                # that contain current FDV only. In that case the existing portfolio-level
                # previous-day FDV denominator is blank, even though DAssetTypeReturn has the
                # required FDV Valuation Prev_Day rows. Fall back to summed DAssetTypeReturn
                # previous FDV by portfolio so valid rows are not excluded as unavailable.
                dat_prev_by_key = (
                    dat_prep.groupby("_pkey", dropna=False)["_fdv_prev_num"]
                    .apply(lambda s: pd.to_numeric(s, errors="coerce").sum(min_count=1))
                    if "_fdv_prev_num" in dat_prep.columns else pd.Series(dtype="float64")
                )
                portfolio_prev_num = pd.to_numeric(dat_prep["_portfolio_prev_fdv_num"], errors="coerce")
                dat_prev_fallback = dat_prep["_pkey"].map(dat_prev_by_key) if not dat_prev_by_key.empty else pd.Series(float("nan"), index=dat_prep.index)
                dat_prep["_portfolio_prev_fdv_num"] = portfolio_prev_num.where(portfolio_prev_num.notna() & portfolio_prev_num.abs().gt(0), dat_prev_fallback)
                dat_prep["_contribution_num"] = dat_prep["_movement_ex_cf_num"] / pd.to_numeric(dat_prep["_portfolio_prev_fdv_num"], errors="coerce").replace({0.0: float('nan')})
                dat_prep, inc, _exc = _classify_asset_type_detail_source_rows(dat_prep)
                if not inc.empty:
                    dat_groups = inc.groupby(["_pkey", "_tier1_group"], dropna=False).agg(
                        BreakContribution=("_break_contribution_num", lambda s: pd.to_numeric(s, errors="coerce").sum(min_count=1)),
                        ReturnContribution=("_contribution_num", lambda s: pd.to_numeric(s, errors="coerce").sum(min_count=1)),
                    ).reset_index().rename(columns={"_tier1_group": "Tier 1 Group"})
                    dat_groups["Contribution"] = pd.to_numeric(dat_groups["BreakContribution"], errors="coerce").where(
                        pd.to_numeric(dat_groups["BreakContribution"], errors="coerce").notna(),
                        pd.to_numeric(dat_groups["ReturnContribution"], errors="coerce")
                    )
                    dat_groups = dat_groups[["_pkey", "Tier 1 Group", "Contribution"]]

        overlay_groups = pd.DataFrame(columns=["_pkey", "Tier 1 Group", "DAssetReturn Asset to Portfolio Contribution"])
        if isinstance(dar_frame, pd.DataFrame) and not dar_frame.empty:
            dar_port_col = find_col(dar_frame, ["Portfolio code", "Portfolio", "PortfolioCode", "portfolio", "portfolio code"])
            asset_type_col = _resolve_asset_type_driver_code_col(dar_frame)
            asset_to_portfolio_col = find_col(dar_frame, [
                "Asset to Portfolio Contribution",
                "AssetToPortfolioContribution",
                "Asset to portfolio contribution",
                "Asset Portfolio Contribution",
                "Asset-to-Portfolio Contribution",
            ])
            if dar_port_col and asset_type_col and asset_to_portfolio_col:
                ov = dar_frame[[dar_port_col, asset_type_col, asset_to_portfolio_col]].copy()
                ov["_pkey"] = normalise_join_key_series(ov[dar_port_col].astype(str).str.strip())
                ov["_driver_code"] = ov[asset_type_col].astype(str).str.strip().str.upper().str[:2]
                ov = ov[ov["_driver_code"].isin(set(ASSET_TYPE_DETAIL_TIER1_MAP.keys()))].copy()
                if not ov.empty:
                    ov["Tier 1 Group"] = ov["_driver_code"].map(ASSET_TYPE_DETAIL_TIER1_MAP)
                    ov["_asset_to_portfolio_contribution_num"] = num(ov, asset_to_portfolio_col)
                    overlay_groups = (
                        ov.groupby(["_pkey", "Tier 1 Group"], dropna=False)["_asset_to_portfolio_contribution_num"]
                        .sum()
                        .reset_index()
                        .rename(columns={"_asset_to_portfolio_contribution_num": "DAssetReturn Asset to Portfolio Contribution"})
                    )

        merged = pd.merge(dat_groups, overlay_groups, on=["_pkey", "Tier 1 Group"], how="outer")
        if merged.empty:
            driver_map: Dict[str, str] = {}
        else:
            dar_contrib = pd.to_numeric(merged.get("DAssetReturn Asset to Portfolio Contribution", pd.Series(dtype="float64")), errors="coerce")
            dat_contrib = pd.to_numeric(merged.get("Contribution", pd.Series(dtype="float64")), errors="coerce")
            merged["Contribution"] = dar_contrib.where(dar_contrib.notna(), dat_contrib)
            merged["Abs Contribution"] = pd.to_numeric(merged["Contribution"], errors="coerce").abs().fillna(0.0)
            merged = merged[merged["Abs Contribution"] > 0].copy()
            ranked = merged.sort_values(["_pkey", "Abs Contribution", "Tier 1 Group"], ascending=[True, False, True]).drop_duplicates("_pkey") if not merged.empty else pd.DataFrame()
            driver_map = dict(zip(ranked["_pkey"].astype(str), ranked["Tier 1 Group"].astype(str))) if not ranked.empty else {}

        cash_keys = [k for k, v in driver_map.items() if v == "Liquidity / Cash"]
        if cash_keys:
            row_by_key = {str(r["_pkey"]): r for _, r in work_port.iterrows()}
            for k in cash_keys:
                try:
                    if _portfolio_has_non_aud_cash_overlay(dar, row_by_key.get(k, pd.Series(dtype="object"))):
                        driver_map[k] = "FX and non AUD cash"
                    else:
                        driver_map[k] = "Liquidity / Cash (AUD only)"
                except Exception:
                    driver_map[k] = "Liquidity / Cash (AUD only)"
        for k, v in list(driver_map.items()):
            if v == "FX":
                driver_map[k] = "FX and non AUD cash"

        display_df = pd.DataFrame(index=hot_df.index)
        display_df["Portfolio code"] = hot_df.get("Portfolio code", "")
        display_df["Portfolio Name"] = hot_df.get("Portfolio Name", "")
        display_df["FDV Valuation(Current Day)"] = hot_df.get("FDV Valuation(Current Day) Num", pd.Series(dtype="float64")).map(_excel_currency_string)
        display_df["Benchmark Code"] = hot_df.get("Benchmark Code", "")
        display_df["Benchmark Name"] = hot_df.get("Benchmark Name", "")
        display_df["ARC Asset Type of portfolio"] = hot_df.get("ARC Asset Type of portfolio", "")
        display_df["Hot / Cold"] = hot_df.get("Hot / Cold", "")
        display_df["Actual Return"] = hot_df.get("Actual Return Decimal", pd.Series(dtype="float64")).map(_percent_string_1dp)
        display_df["Benchmark Return"] = hot_df.get("Benchmark Return Decimal", pd.Series(dtype="float64")).map(_percent_string_1dp)
        display_df["Calculated Actual v Benchmark Diff"] = hot_df.get("Calculated Actual v Benchmark Diff Num", pd.Series(dtype="float64")).map(_percent_string_1dp)
        display_df["Tolerance"] = hot_df.get("Tolerance Decimal", pd.Series(dtype="float64")).map(_percent_string_1dp)
        display_df["Volatility over Tolerance"] = hot_df.get("Volatility over Tolerance Num", pd.Series(dtype="float64")).map(_percent_string_1dp)
        display_df["ARC Error Risk Ratio"] = hot_df["ARC Error Risk Ratio Decimal"].map(_percent_string_1dp) if "ARC Error Risk Ratio Decimal" in hot_df.columns else ""
        keys = normalise_join_key_series(hot_df[port_col].astype(str).str.strip())
        display_df["Largest Tier 1 driver"] = keys.map(driver_map).fillna("No DAssetTypeReturn")

        timing_df = pd.DataFrame([{
            "Portfolio code": "<vectorized>",
            "Portfolio Name": "All OUT portfolios",
            "Hot / Cold": "Mixed",
            "Largest Tier 1 driver": "vectorized assignment map",
            "ElapsedSeconds": round(float(time.perf_counter() - started_total), 4),
            "DAT rows": int(len(dat_frame)) if isinstance(dat_frame, pd.DataFrame) else 0,
            "DAR rows": int(len(dar_frame)) if isinstance(dar_frame, pd.DataFrame) else 0,
            "DAssetReturn contribution basis": "Asset to Portfolio Contribution",
            "Status": "Done",
            "Error": "",
        }])
        return display_df[base_cols], timing_df
    except Exception as exc:
        display_df = pd.DataFrame(index=hot_df.index)
        display_df["Portfolio code"] = hot_df.get("Portfolio code", "") if isinstance(hot_df, pd.DataFrame) else ""
        display_df["Portfolio Name"] = hot_df.get("Portfolio Name", "") if isinstance(hot_df, pd.DataFrame) else ""
        display_df["Largest Tier 1 driver"] = "No DAssetTypeReturn"
        for col in base_cols:
            if col not in display_df.columns:
                display_df[col] = ""
        timing_df = pd.DataFrame([{
            "Portfolio code": "<vectorized>",
            "Portfolio Name": "All OUT portfolios",
            "Hot / Cold": "Mixed",
            "Largest Tier 1 driver": "No DAssetTypeReturn",
            "ElapsedSeconds": round(float(time.perf_counter() - started_total), 4),
            "DAT rows": 0,
            "DAR rows": 0,
            "DAssetReturn contribution basis": "Asset to Portfolio Contribution",
            "Status": "Error",
            "Error": f"{type(exc).__name__}: {exc}",
        }])
        return display_df[base_cols], timing_df


def _ensure_detail_indexes(bundle: Dict[str, object], include: Tuple[str, ...] = ("dat", "dar", "txn")) -> None:
    """Lazy-build detail indexes for detail-heavy views only."""
    if not isinstance(bundle, dict):
        return
    if "dat" in include and not bundle.get("dat_index"):
        bundle["dat_index"] = _build_portfolio_detail_index(bundle.get("dat", pd.DataFrame()) if isinstance(bundle.get("dat", pd.DataFrame()), pd.DataFrame) else pd.DataFrame())
    if "dar" in include and not bundle.get("dar_index"):
        bundle["dar_index"] = _build_portfolio_detail_index(bundle.get("dar", pd.DataFrame()) if isinstance(bundle.get("dar", pd.DataFrame()), pd.DataFrame) else pd.DataFrame())
    if "txn" in include and not bundle.get("txn_index"):
        txn_source = bundle.get("txn_eligible_df", pd.DataFrame())
        if txn_source is None or not isinstance(txn_source, pd.DataFrame) or txn_source.empty:
            txn_source = bundle.get("txn", pd.DataFrame())
        bundle["txn_index"] = _build_portfolio_detail_index(txn_source if isinstance(txn_source, pd.DataFrame) else pd.DataFrame())


def _portfolio_detail_rows(df_or_index: object, portfolio_code: str) -> pd.DataFrame:
    if not portfolio_code:
        return pd.DataFrame()
    portkey = normalise_join_key_series(pd.Series([str(portfolio_code).strip()], dtype="object")).iloc[0]
    if not str(portkey).strip():
        return pd.DataFrame()
    if isinstance(df_or_index, dict):
        rows = df_or_index.get(str(portkey), pd.DataFrame())
        return rows.copy() if isinstance(rows, pd.DataFrame) else pd.DataFrame()
    df = df_or_index
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame()
    port_col = find_col(df, ["Portfolio code", "Portfolio", "portfolio"])
    if port_col is None or port_col not in df.columns:
        return pd.DataFrame()
    tmp = df.copy()
    tmp[port_col] = _string_series(tmp, port_col).str.strip()
    tmp["portkey"] = normalise_join_key_series(tmp[port_col])
    out = tmp[tmp["portkey"] == portkey].drop(columns=["portkey"]).copy()
    return out


def _detail_rows_for_portfolio(
    bundle: Dict[str, object],
    source_key: str,
    index_key: str,
    selected_portfolio: str,
) -> pd.DataFrame:
    """Return detail rows for one selected portfolio without forcing a full index build.

    v306.1: detail-heavy sections use this helper so section open is cheap.
    It uses an existing index when available; otherwise it filters the source
    dataframe directly for the selected portfolio only.
    """
    if not isinstance(bundle, dict):
        return pd.DataFrame()
    try:
        selected_key = normalise_join_key_series(pd.Series([str(selected_portfolio or "").strip()], dtype="object")).iloc[0]
    except Exception:
        selected_key = str(selected_portfolio or "").strip().upper().replace(" ", "")
    if not str(selected_key).strip():
        return pd.DataFrame()

    existing_index = bundle.get(index_key)
    if isinstance(existing_index, dict) and existing_index:
        rows = existing_index.get(str(selected_key), pd.DataFrame())
        return rows.copy() if isinstance(rows, pd.DataFrame) else pd.DataFrame()

    source = bundle.get(source_key, pd.DataFrame())
    if source is None or not isinstance(source, pd.DataFrame) or source.empty:
        return pd.DataFrame()

    port_col = find_col(source, ["Portfolio code", "Portfolio", "PortfolioCode", "portfolio", "portfolio code"])
    if not port_col or port_col not in source.columns:
        return pd.DataFrame()

    keys = normalise_join_key_series(source[port_col].astype(str).str.strip())
    return source.loc[keys.eq(str(selected_key))].copy()


DEFAULT_ASSET_TYPE_DETAIL_TIER1_MAP = {
    "CN": "Market Assets",
    "CO": "Derivatives",
    "DS": "Liquidity / Cash",
    "FI": "Market Assets",
    "FU": "Derivatives",
    "OS": "Market Assets",
    "PO": "Derivatives",
    "RI": "Other / Events",
    "ZF": "FX",
    "ZL": "Liquidity / Cash",
}
ASSET_TYPE_DETAIL_TIER1_MAP = dict(DEFAULT_ASSET_TYPE_DETAIL_TIER1_MAP)

ALLOWED_TIER1_DRIVER_GROUPS = [
    "Market Assets",
    "Derivatives",
    "Liquidity / Cash",
    "FX",
    "Other / Events",
    "Unmapped",
]


def _normalise_asset_type_tier1_map(raw_map: object) -> Dict[str, str]:
    """Return a clean 2-letter asset-type-code to Tier 1 group map."""
    if not isinstance(raw_map, dict):
        return dict(DEFAULT_ASSET_TYPE_DETAIL_TIER1_MAP)
    out: Dict[str, str] = {}
    for raw_code, raw_group in raw_map.items():
        code = str(raw_code or "").strip().upper()[:2]
        group = str(raw_group or "").strip()
        if not code:
            continue
        if not group:
            group = "Unmapped"
        out[code] = group
    return out or dict(DEFAULT_ASSET_TYPE_DETAIL_TIER1_MAP)


def _load_asset_type_code_map_from_static_data() -> None:
    """v318: load the asset-type-code -> Tier 1 group map from Static Data
    ('asset_type_code_map' sheet: Code | Tier1Group | Active) and set the global
    used by Tier 1 driver assignment. The sidebar JSON editor was removed; the map
    is now config-only. Falls back to DEFAULT_ASSET_TYPE_DETAIL_TIER1_MAP if the
    sheet is unavailable."""
    global ASSET_TYPE_DETAIL_TIER1_MAP
    try:
        sb = _ensure_static_data_bundle_v306_13_13() if callable(globals().get("_ensure_static_data_bundle_v306_13_13")) else globals().get("STATIC_DATA_BUNDLE")
        tbl = None
        if callable(globals().get("_static_get_active_table_v306_13_8")):
            tbl = _static_get_active_table_v306_13_8(sb, "asset_type_code_map")
        if tbl is None and isinstance(sb, dict):
            tbl = sb.get("tables", {}).get("asset_type_code_map")
        if tbl is not None and hasattr(tbl, "columns") and not tbl.empty:
            cols = {str(c).strip().lower(): c for c in tbl.columns}
            cc, gc = cols.get("code"), cols.get("tier1group") or cols.get("tier 1 group")
            if cc and gc:
                raw = {str(r[cc]): str(r[gc]) for _, r in tbl.iterrows()}
                ASSET_TYPE_DETAIL_TIER1_MAP = _normalise_asset_type_tier1_map(raw)
                return
    except Exception:
        pass
    ASSET_TYPE_DETAIL_TIER1_MAP = dict(DEFAULT_ASSET_TYPE_DETAIL_TIER1_MAP)


# Back-compat alias (call site name unchanged); now loads from Static Data, no sidebar UI.
def _render_asset_type_code_map_sidebar() -> None:
    _load_asset_type_code_map_from_static_data()

ASSET_TYPE_DETAIL_DRIVER_LABEL_MAP = {
    "CN": "CN – Convertible Securities",
    "CO": "CO – Equity Call Options",
    "DS": "DS – Cash & Short-Term Securities",
    "FI": "FI – Fixed Income",
    "FU": "FU – Futures (Derivatives)",
    "OS": "OS – Listed Equities",
    "PO": "PO – Put Options",
    "RI": "RI – Corporate Actions",
    "ZF": "ZF – Foreign Exchange",
    "ZL": "ZL – Cash, Receivables & Payables",
}


def _resolve_asset_type_driver_code_col(df: Optional[pd.DataFrame]) -> Optional[str]:
    """Resolve the asset-type driver field without confusing Asset Code for Asset Type.

    v267 fix: DAssetReturn rows contain both `Asset Type` (for example ZF85/ZL01)
    and `Asset Code` (for example AUDEUR..., EURAUD..., USDAUD...). The old
    resolver allowed `Asset Code` to win, which truncated those instrument codes
    to AU/EU/US and surfaced them as an `Unmapped` Tier 1 driver.
    v306.5.6 fix: DAssetTypeReturn contains both `Asset Type Code` (for example OS03/ZL01)
    and the descriptive `Asset Type` (for example Unit Trust/Current Account). Prefer
    the coded field before the description so Tier 1 driver mapping uses OS/ZL, not UN/CU.
    Use Asset Code only as a last-resort fallback.
    """
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return None
    for aliases in [
        ["Asset Type Code", "AssetTypeCode", "Asset type code"],
        ["Driver Code", "DriverCode", "Driver code"],
        ["Asset Type", "AssetType", "Asset type"],
    ]:
        col = find_exact_normalized_col(df, aliases) or find_col(df, aliases)
        if col:
            return col
    return find_exact_normalized_col(df, ["Asset Code", "AssetCode", "Asset code"]) or find_col(df, ["Asset Code", "AssetCode", "Asset code"])

ASSET_TYPE_DETAIL_COLUMNS = [
    "Portfolio code",
    "Tier 1 Group",
    "Underlying Driver Codes",
    "Underlying Driver Labels",
    "FDV Valuation(Previous Day)",
    "FDV Cashflow",
    "FDV Valuation(Current Day)",
    "Calculated Movement ex Cashflow",
    "Calculated Tier 1 Return %",
    "Break Contribution %",
    "Abs Break Contribution",
    "Return Contribution %",
    "Calculated Contribution %",
    "Abs Contribution",
    "Contribution Rank",
    "Contribution % of Explained Total",
    "Include in Explained Total?",
    "Exception Note",
]


def _asset_type_detail_empty_result() -> Dict[str, object]:
    return {
        "narrative": "No DAssetTypeReturn rows were found for the selected portfolio.",
        "summary_df": pd.DataFrame(columns=["Measure", "Value"]),
        "detail_df": pd.DataFrame(columns=ASSET_TYPE_DETAIL_COLUMNS),
        "driver_rank_df": pd.DataFrame(columns=["Tier 1 Group", "Break Contribution", "Abs Break Contribution", "Contribution", "Abs Contribution", "Contribution Rank"]),
        "diagnostic_df": pd.DataFrame(columns=["Check", "Result"]),
    }


def _asset_type_detail_portfolio_prev_fdv_num(portfolio_row: pd.Series) -> float:
    portfolio_prev_fdv_num = pd.to_numeric(portfolio_row.get("FDV Valuation(Previous Day) Num", pd.NA), errors="coerce")
    if pd.isna(portfolio_prev_fdv_num):
        portfolio_prev_fdv_num = pd.to_numeric(portfolio_row.get("FDV Valuation(Previous Day)", pd.NA), errors="coerce")
    return float(portfolio_prev_fdv_num) if pd.notna(portfolio_prev_fdv_num) else float('nan')


def _prepare_asset_type_detail_rows(dat_rows: pd.DataFrame) -> Tuple[pd.DataFrame, Optional[str], Optional[str], Optional[str], Optional[str], Optional[str]]:
    rows = dat_rows.copy()

    asset_type_code_col = _resolve_asset_type_driver_code_col(rows)
    asset_type_desc_col = resolve_col(rows, COLUMN_ALIASES["asset_type_desc"]) or resolve_driver_label_col(rows)
    fdv_prev_col = resolve_col(rows, COLUMN_ALIASES["fdv_prev"])
    fdv_curr_col = resolve_col(rows, COLUMN_ALIASES["fdv_curr"])
    cashflow_col = resolve_col(rows, COLUMN_ALIASES["cashflow"])
    excess_contribution_col = find_col(rows, ["Excess Contribution", "ExcessContribution", "Excess contribution", "Return Deviation", "Tol Deviation"])

    code_series = _string_series(rows, asset_type_code_col).str.strip().str.upper()
    desc_series = _string_series(rows, asset_type_desc_col).str.strip()
    fdv_prev_num = num(rows, fdv_prev_col)
    fdv_curr_num = num(rows, fdv_curr_col)
    cashflow_num = num(rows, cashflow_col)
    break_contribution_num = num(rows, excess_contribution_col) if excess_contribution_col else pd.Series(float("nan"), index=rows.index, dtype="float64")

    rows["_asset_type_code"] = code_series
    rows["_asset_type_desc"] = desc_series
    rows["_driver_code"] = rows["_asset_type_code"].str[:2].fillna("")
    # v270: Treat pandas stringified null-like driver values as blank so subtotal/portfolio-total rows do not become artificial Unmapped drivers.
    rows["_driver_code"] = rows["_driver_code"].astype(str).str.strip().str.upper().replace({"NAN": "", "NONE": "", "<NA>": "", "NA": "", "NAT": ""})
    rows["_driver_label"] = rows["_driver_code"].map(ASSET_TYPE_DETAIL_DRIVER_LABEL_MAP).fillna(rows["_driver_code"].where(rows["_driver_code"] != "", "Unmapped"))
    rows["_driver_label"] = rows["_driver_label"].map(_clean_mojibake_text)
    rows["_tier1_group"] = rows["_driver_code"].map(ASSET_TYPE_DETAIL_TIER1_MAP).fillna("Unmapped")
    rows["_fdv_prev_num"] = fdv_prev_num
    rows["_fdv_curr_num"] = fdv_curr_num
    rows["_cashflow_num"] = cashflow_num
    rows["_movement_ex_cf_num"] = rows["_fdv_curr_num"] - rows["_fdv_prev_num"] - rows["_cashflow_num"]
    rows["_asset_type_return_num"] = rows["_movement_ex_cf_num"] / rows["_fdv_prev_num"].replace({0.0: float('nan')})
    rows["_break_contribution_num"] = break_contribution_num
    rows["_is_blank_key"] = rows["_driver_code"].astype(str).str.strip().str.upper().isin(["", "NAN", "NONE", "<NA>", "NA", "NAT"])
    rows["_is_subtotal_like"] = rows["_asset_type_desc"].str.lower().str.contains(r"total|subtotal|grand total", regex=True, na=False)
    rows["_has_required_values"] = rows["_fdv_prev_num"].notna() & rows["_fdv_curr_num"].notna()
    rows["_prev_day_non_zero"] = rows["_fdv_prev_num"].notna() & (rows["_fdv_prev_num"].abs() > 0)
    duplicate_counts = rows["_driver_code"].value_counts(dropna=False)
    rows["_duplicate_count"] = rows["_driver_code"].map(duplicate_counts).fillna(0).astype(int)

    return rows, asset_type_code_col, asset_type_desc_col, fdv_prev_col, fdv_curr_col, cashflow_col


def _classify_asset_type_detail_source_rows(rows: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    rows = rows.copy()
    rows["Include in Explained Total?"] = "Yes"
    rows["Exception Note"] = ""
    rows.loc[rows["_is_blank_key"], ["Include in Explained Total?", "Exception Note"]] = ["No", "Missing driver code"]
    rows.loc[~rows["_driver_code"].astype(str).str.strip().str.upper().isin(set(ASSET_TYPE_DETAIL_TIER1_MAP.keys())) & (rows["Include in Explained Total?"] == "Yes"), ["Include in Explained Total?", "Exception Note"]] = ["No", "Unknown / unmapped driver code"]
    rows.loc[~rows["_has_required_values"] & (rows["Include in Explained Total?" ] == "Yes"), ["Include in Explained Total?", "Exception Note"]] = ["No", "Missing FDV valuation fields"]
    rows.loc[~rows["_prev_day_non_zero"] & (rows["Include in Explained Total?"] == "Yes"), ["Include in Explained Total?", "Exception Note"]] = ["No", "Previous day FDV is zero / blank"]
    rows.loc[rows["_is_subtotal_like"] & (rows["Include in Explained Total?"] == "Yes"), ["Include in Explained Total?", "Exception Note"]] = ["No", "Subtotal / total style row"]
    rows.loc[pd.isna(rows.get("_break_contribution_num", pd.Series(float("nan"), index=rows.index))) & pd.isna(rows["_contribution_num"]) & (rows["Include in Explained Total?"] == "Yes"), ["Include in Explained Total?", "Exception Note"]] = ["No", "Break and return contribution unavailable"]

    included_source = rows[rows["Include in Explained Total?"] == "Yes"].copy()
    excluded_source = rows[rows["Include in Explained Total?"] != "Yes"].copy().sort_values(["Exception Note", "_asset_type_desc"], ascending=[True, True]).reset_index(drop=True)
    return rows, included_source, excluded_source


def _build_asset_type_detail_grouped_view(included_source: pd.DataFrame) -> Tuple[pd.DataFrame, float, float]:
    if not included_source.empty:
        grouped = (
            included_source.groupby("_tier1_group", dropna=False)
            .agg(
                FDVPrev=("_fdv_prev_num", "sum"),
                FDVCashflow=("_cashflow_num", "sum"),
                FDVCurr=("_fdv_curr_num", "sum"),
                MovementExCashflow=("_movement_ex_cf_num", "sum"),
                ReturnContribution=("_contribution_num", "sum"),
                BreakContribution=("_break_contribution_num", "sum"),
            )
            .reset_index()
            .rename(columns={"_tier1_group": "Tier 1 Group"})
        )
        grouped["Underlying Driver Codes"] = grouped["Tier 1 Group"].map(
            included_source.groupby("_tier1_group")["_driver_code"].apply(lambda s: ", ".join(sorted({x for x in s.tolist() if str(x).strip()}))).to_dict()
        ).fillna("")
        grouped["Underlying Driver Labels"] = grouped["Tier 1 Group"].map(
            included_source.groupby("_tier1_group")["_driver_label"].apply(lambda s: "; ".join(sorted({_clean_mojibake_text(x) for x in s.tolist() if str(x).strip()}))).to_dict()
        ).fillna("")
        grouped["Underlying Driver Labels"] = grouped["Underlying Driver Labels"].map(_clean_mojibake_text)
        grouped["Calculated Tier 1 Return %"] = grouped["MovementExCashflow"] / grouped["FDVPrev"].replace({0.0: float('nan')})
        grouped["Break Contribution"] = pd.to_numeric(grouped["BreakContribution"], errors="coerce")
        grouped["Return Contribution"] = pd.to_numeric(grouped["ReturnContribution"], errors="coerce")
        # Control dashboard: the primary driver is the largest absolute control-break contribution.
        # Use summed Excess Contribution where available; fall back to return contribution only where break contribution is unavailable.
        grouped["Contribution"] = grouped["Break Contribution"].where(grouped["Break Contribution"].notna(), grouped["Return Contribution"])
        grouped["Abs Break Contribution"] = grouped["Break Contribution"].abs().fillna(0.0)
        grouped["Abs Contribution"] = pd.to_numeric(grouped["Contribution"], errors="coerce").abs().fillna(0.0)
        # v270: remove artificial blank-code Unmapped total/subtotal rows with no break contribution from portfolio drill-through.
        if {"Tier 1 Group", "Underlying Driver Codes", "Abs Contribution"}.issubset(grouped.columns):
            _blank_unmapped = grouped["Tier 1 Group"].astype(str).str.strip().eq("Unmapped") & grouped["Underlying Driver Codes"].astype(str).str.strip().eq("") & pd.to_numeric(grouped["Abs Contribution"], errors="coerce").fillna(0.0).le(1e-12)
            grouped = grouped.loc[~_blank_unmapped].copy()
        grouped = grouped.sort_values(["Abs Contribution", "Tier 1 Group"], ascending=[False, True]).reset_index(drop=True)
        grouped["Contribution Rank"] = range(1, len(grouped) + 1)
        explained_total_num = float(grouped["Contribution"].sum())
        share_denom = abs(explained_total_num) if pd.notna(explained_total_num) and abs(explained_total_num) > 0 else float('nan')
        grouped["Contribution % of Explained Total"] = grouped["Contribution"] / share_denom if pd.notna(share_denom) else float('nan')
        included = grouped.copy()
    else:
        explained_total_num = 0.0
        share_denom = float('nan')
        included = pd.DataFrame(columns=[
            "Tier 1 Group", "Underlying Driver Codes", "Underlying Driver Labels", "FDVPrev", "FDVCashflow",
            "FDVCurr", "MovementExCashflow", "Calculated Tier 1 Return %", "Break Contribution", "Return Contribution", "Contribution", "Contribution Rank",
            "Contribution % of Explained Total"
        ])
    return included, explained_total_num, share_denom




def _percent_point_string_4dp(value: object) -> str:
    value_num = pd.to_numeric(value, errors="coerce")
    if pd.isna(value_num):
        return ""
    return f"{float(value_num):,.4f}%"


def _asset_type_detail_dassetreturn_overlay(dar_rows: Optional[pd.DataFrame]) -> pd.DataFrame:
    empty = pd.DataFrame(columns=[
        "Tier 1 Group", "DAssetReturn Break Contribution", "DAssetReturn Rows",
        "DAssetReturn Driver Codes", "DAssetReturn Driver Labels",
    ])
    if dar_rows is None or not isinstance(dar_rows, pd.DataFrame) or dar_rows.empty:
        return empty
    asset_type_col = _resolve_asset_type_driver_code_col(dar_rows)
    excess_col = find_col(dar_rows, ["Excess Contribution", "ExcessContribution", "Excess contribution"])
    if asset_type_col is None or excess_col is None:
        return empty
    work = dar_rows[[asset_type_col, excess_col]].copy()
    work["_driver_code"] = _string_series(work, asset_type_col).str.strip().str.upper().str[:2]
    work = work[work["_driver_code"].astype(str).str.strip().ne("")].copy()
    if work.empty:
        return empty
    # v267: DAssetReturn overlay should only contribute recognised asset-type drivers.
    # Unknown prefixes are excluded here instead of creating an `Unmapped` driver row.
    work = work[work["_driver_code"].isin(set(ASSET_TYPE_DETAIL_TIER1_MAP.keys()))].copy()
    if work.empty:
        return empty
    work["Tier 1 Group"] = work["_driver_code"].map(ASSET_TYPE_DETAIL_TIER1_MAP)
    work["_driver_label"] = work["_driver_code"].map(ASSET_TYPE_DETAIL_DRIVER_LABEL_MAP).fillna(work["_driver_code"])
    work["_driver_label"] = work["_driver_label"].map(_clean_mojibake_text)
    work["_excess_num"] = num(work, excess_col)
    grouped = (
        work.groupby("Tier 1 Group", dropna=False)
        .agg(
            **{
                "DAssetReturn Break Contribution": ("_excess_num", "sum"),
                "DAssetReturn Rows": ("_excess_num", "count"),
                "DAssetReturn Driver Codes": ("_driver_code", lambda s: ", ".join(sorted({str(x).strip() for x in s.tolist() if str(x).strip()}))),
                "DAssetReturn Driver Labels": ("_driver_label", lambda s: "; ".join(sorted({_clean_mojibake_text(x) for x in s.tolist() if str(x).strip()}))),
            }
        )
        .reset_index()
    )
    return grouped


def _apply_dassetreturn_break_overlay_to_tier1(included: pd.DataFrame, dar_rows: Optional[pd.DataFrame]) -> Tuple[pd.DataFrame, bool, float, float]:
    out = included.copy() if isinstance(included, pd.DataFrame) else pd.DataFrame()
    overlay = _asset_type_detail_dassetreturn_overlay(dar_rows)
    if overlay.empty:
        explained_total_num = float(pd.to_numeric(out.get("Contribution", pd.Series(dtype="float64")), errors="coerce").sum()) if not out.empty else 0.0
        share_denom = abs(explained_total_num) if pd.notna(explained_total_num) and abs(explained_total_num) > 0 else float('nan')
        return out, False, explained_total_num, share_denom
    if out.empty:
        out = overlay[["Tier 1 Group"]].copy()
        out["Underlying Driver Codes"] = overlay["DAssetReturn Driver Codes"]
        out["Underlying Driver Labels"] = overlay["DAssetReturn Driver Labels"]
        for col in ["FDVPrev", "FDVCashflow", "FDVCurr", "MovementExCashflow", "Calculated Tier 1 Return %", "Return Contribution", "Break Contribution"]:
            out[col] = float('nan')
    out = out.merge(overlay, on="Tier 1 Group", how="outer")
    for col in ["Underlying Driver Codes", "Underlying Driver Labels"]:
        if col not in out.columns:
            out[col] = ""
    if "DAssetReturn Driver Codes" in out.columns:
        out["Underlying Driver Codes"] = out["DAssetReturn Driver Codes"].where(out["DAssetReturn Driver Codes"].astype(str).str.strip().ne(""), out["Underlying Driver Codes"])
    if "DAssetReturn Driver Labels" in out.columns:
        out["Underlying Driver Labels"] = out["DAssetReturn Driver Labels"].where(out["DAssetReturn Driver Labels"].astype(str).str.strip().ne(""), out["Underlying Driver Labels"])
    dasset_break = pd.to_numeric(out.get("DAssetReturn Break Contribution", pd.Series(dtype="float64")), errors="coerce")
    old_break = pd.to_numeric(out.get("Break Contribution", pd.Series(dtype="float64")), errors="coerce")
    out["Break Contribution"] = dasset_break.where(dasset_break.notna(), old_break)
    out["Break Contribution Source"] = "DAssetReturn Excess Contribution"
    out["Contribution"] = out["Break Contribution"].where(out["Break Contribution"].notna(), pd.to_numeric(out.get("Return Contribution", pd.Series(dtype="float64")), errors="coerce"))
    out["Abs Break Contribution"] = out["Break Contribution"].abs().fillna(0.0)
    out["Abs Contribution"] = pd.to_numeric(out["Contribution"], errors="coerce").abs().fillna(0.0)
    out = out.sort_values(["Abs Contribution", "Tier 1 Group"], ascending=[False, True]).reset_index(drop=True)
    out["Contribution Rank"] = range(1, len(out) + 1)
    explained_total_num = float(pd.to_numeric(out["Contribution"], errors="coerce").sum())
    share_denom = abs(explained_total_num) if pd.notna(explained_total_num) and abs(explained_total_num) > 0 else float('nan')
    out["Contribution % of Explained Total"] = out["Contribution"] / share_denom if pd.notna(share_denom) else float('nan')
    return out, True, explained_total_num, share_denom

def _summarise_asset_type_detail_reconciliation(
    portfolio_row: pd.Series,
    included: pd.DataFrame,
    fdv_prev_col: Optional[str],
    fdv_curr_col: Optional[str],
    explained_total_num: float,
) -> Dict[str, object]:
    uses_dassetreturn_break = (
        isinstance(included, pd.DataFrame)
        and "Break Contribution Source" in included.columns
        and included["Break Contribution Source"].astype(str).str.contains("DAssetReturn", case=False, na=False).any()
    )
    if uses_dassetreturn_break:
        target_label = "Target control-break basis"
        target_value_is_percent_point = True
        target_value_num = float('nan')
        for col in ["Source Calculated over/under", "Transaction-aware Control Break", "Over/Under", "Actual vs Benchmark"]:
            value = pd.to_numeric(portfolio_row.get(col, pd.NA), errors="coerce")
            if pd.notna(value):
                target_value_num = float(value)
                break
        residual_num = (target_value_num - explained_total_num) if pd.notna(target_value_num) else float('nan')
        green_threshold = 0.01
        amber_threshold = 0.03
    else:
        target_label = "Target DDetailed Asset return %"
        target_value_is_percent_point = False
        target_value_num = pd.to_numeric(portfolio_row.get("Asset return % Decimal", pd.NA), errors="coerce")
        if pd.isna(target_value_num):
            raw_pct = portfolio_row.get("Asset return %", pd.NA)
            raw_num = pd.to_numeric(raw_pct, errors='coerce')
            target_value_num = float(raw_num) / 100.0 if pd.notna(raw_num) else float('nan')
        target_value_num = float(target_value_num) if pd.notna(target_value_num) else float('nan')
        residual_num = (target_value_num - explained_total_num) if pd.notna(target_value_num) else float('nan')
        green_threshold = 0.0001
        amber_threshold = 0.0003
    if pd.isna(residual_num):
        residual_status = "No target basis"
    elif abs(float(residual_num)) <= green_threshold:
        residual_status = "Green"
    elif abs(float(residual_num)) <= amber_threshold:
        residual_status = "Amber"
    else:
        residual_status = "Red"
    if not included.empty:
        top_row = included.iloc[0]
        top_driver = str(top_row.get("Tier 1 Group", "")).strip()
        top_contribution_num = pd.to_numeric(top_row.get("Contribution", 0.0), errors="coerce")
        top_contribution_num = float(top_contribution_num) if pd.notna(top_contribution_num) else float('nan')
    else:
        top_driver = ""
        top_contribution_num = float('nan')
    if not included.empty and residual_status == "Green":
        driver_confidence = "High"
    elif not included.empty and residual_status in {"Green", "Amber"}:
        driver_confidence = "Medium"
    else:
        driver_confidence = "Low"
    fmt = _percent_point_string_4dp if target_value_is_percent_point else _percent_string_1dp
    if not included.empty and residual_status == "Green":
        narrative = f"Top tier 1 break driver: {top_driver} ({fmt(top_contribution_num)}). Signed tier 1 break contributions reconcile to the target basis."
    elif not included.empty and residual_status == "Amber":
        narrative = f"Top tier 1 break driver: {top_driver} ({fmt(top_contribution_num)}). Signed tier 1 contributions provide a usable explanation, but there is a small residual gap to the target basis."
    elif not included.empty and residual_status == "Red":
        narrative = f"Largest signed tier 1 driver: {top_driver} ({fmt(top_contribution_num)}), but the tier 1 contribution view does not reconcile well to the target basis. Treat attribution as low confidence."
    elif fdv_prev_col is None or fdv_curr_col is None:
        narrative = "The asset-type report does not expose the FDV valuation fields needed to calculate tier 1 contributions."
    else:
        narrative = "No usable asset-type rows were available to calculate tier 1 contributions."
    return {
        "target_asset_return_num": target_value_num,
        "target_label": target_label,
        "target_value_is_percent_point": target_value_is_percent_point,
        "residual_num": residual_num,
        "residual_status": residual_status,
        "top_driver": top_driver,
        "top_contribution_num": top_contribution_num,
        "driver_confidence": driver_confidence,
        "narrative": narrative,
    }


def _build_asset_type_detail_df(included: pd.DataFrame, portfolio_code: str) -> pd.DataFrame:
    detail_df = pd.DataFrame(index=included.index)
    if included.empty:
        return pd.DataFrame(columns=ASSET_TYPE_DETAIL_COLUMNS)

    detail_df["Portfolio code"] = portfolio_code
    detail_df["Tier 1 Group"] = included.get("Tier 1 Group", pd.Series(dtype="object"))
    detail_df["Underlying Driver Codes"] = included.get("Underlying Driver Codes", pd.Series(dtype="object"))
    detail_df["Underlying Driver Labels"] = included.get("Underlying Driver Labels", pd.Series(dtype="object"))
    detail_df["FDV Valuation(Previous Day)"] = included.get("FDVPrev", pd.Series(dtype="float64"))
    detail_df["FDV Cashflow"] = included.get("FDVCashflow", pd.Series(dtype="float64"))
    detail_df["FDV Valuation(Current Day)"] = included.get("FDVCurr", pd.Series(dtype="float64"))
    detail_df["Calculated Movement ex Cashflow"] = included.get("MovementExCashflow", pd.Series(dtype="float64"))
    detail_df["Calculated Tier 1 Return %"] = included.get("Calculated Tier 1 Return %", pd.Series(dtype="float64")).map(_percent_string_1dp)
    detail_df["Break Contribution %"] = included.get("Break Contribution", included.get("Contribution", pd.Series(dtype="float64"))).map(_percent_point_string_4dp)
    detail_df["Abs Break Contribution"] = included.get("Abs Break Contribution", included.get("Abs Contribution", pd.Series(dtype="float64"))).map(_percent_point_string_4dp)
    detail_df["Return Contribution %"] = included.get("Return Contribution", pd.Series(dtype="float64")).map(_percent_string_1dp)
    detail_df["Calculated Contribution %"] = included.get("Contribution", pd.Series(dtype="float64")).map(_percent_point_string_4dp)
    detail_df["Abs Contribution"] = included.get("Abs Contribution", pd.Series(dtype="float64")).map(_percent_point_string_4dp)
    detail_df["Contribution Rank"] = included.get("Contribution Rank", pd.Series(dtype="Int64"))
    detail_df["Contribution % of Explained Total"] = included.get("Contribution % of Explained Total", pd.Series(dtype="float64")).map(_percent_string_1dp)
    detail_df["Include in Explained Total?"] = "Yes"
    detail_df["Exception Note"] = ""
    return detail_df[ASSET_TYPE_DETAIL_COLUMNS]


def _build_asset_type_summary_df(
    portfolio_code: str,
    portfolio_name: str,
    portfolio_prev_fdv_num: float,
    target_asset_return_num: float,
    explained_total_num: float,
    residual_num: float,
    residual_status: str,
    top_driver: str,
    top_contribution_num: float,
    driver_confidence: str,
    target_label: str = "Target DDetailed Asset return %",
    target_value_is_percent_point: bool = False,
) -> pd.DataFrame:
    fmt = _percent_point_string_4dp if bool(target_value_is_percent_point) else _percent_string_1dp
    return pd.DataFrame([
        {"Measure": "Portfolio code", "Value": portfolio_code},
        {"Measure": "Portfolio name", "Value": portfolio_name},
        {"Measure": "Portfolio previous day FDV", "Value": _excel_currency_string(portfolio_prev_fdv_num)},
        {"Measure": target_label, "Value": fmt(target_asset_return_num)},
        {"Measure": "Sum of signed tier 1 break contributions", "Value": fmt(explained_total_num)},
        {"Measure": "Residual", "Value": fmt(residual_num)},
        {"Measure": "Residual Status", "Value": residual_status},
        {"Measure": "Largest Tier 1 Break Driver", "Value": top_driver},
        {"Measure": "Largest Break Driver Contribution", "Value": fmt(top_contribution_num)},
        {"Measure": "Driver Confidence", "Value": driver_confidence},
    ])


def _build_asset_type_diagnostic_df(
    asset_type_code_col: Optional[str],
    asset_type_desc_col: Optional[str],
    fdv_prev_col: Optional[str],
    fdv_curr_col: Optional[str],
    cashflow_col: Optional[str],
    rows: pd.DataFrame,
    included_source: pd.DataFrame,
    excluded_source: pd.DataFrame,
    included: pd.DataFrame,
    share_denom: float,
) -> pd.DataFrame:
    return pd.DataFrame([
        {"Check": "Asset Type Code present", "Result": "Yes" if asset_type_code_col else "No"},
        {"Check": "Asset Type Description present", "Result": "Yes" if asset_type_desc_col else "No"},
        {"Check": "Resolved FDV Prev column", "Result": fdv_prev_col or "No"},
        {"Check": "Resolved FDV Curr column", "Result": fdv_curr_col or "No"},
        {"Check": "Resolved Cashflow column", "Result": cashflow_col or "No"},
        {"Check": "Row count in DAssetTypeReturn", "Result": int(len(rows))},
        {"Check": "Included source rows", "Result": int(len(included_source))},
        {"Check": "Excluded / caveated source rows", "Result": int(len(excluded_source))},
        {"Check": "Tier 1 groups returned", "Result": int(len(included))},
        {"Check": "Duplicate 2-letter driver codes", "Result": int((rows["_duplicate_count"] > 1).sum())},
        {"Check": "Missing / blank driver code rows", "Result": int(rows["_is_blank_key"].sum())},
        {"Check": "Contribution share denominator", "Result": _percent_string_1dp(share_denom)},
        {"Check": "Reconciliation threshold (Green)", "Result": _percent_string_1dp(0.0001)},
        {"Check": "Reconciliation threshold (Amber)", "Result": _percent_string_1dp(0.0003)},
    ])


def _asset_type_detail_control(dat_rows: pd.DataFrame, portfolio_row: pd.Series, dar_rows: Optional[pd.DataFrame] = None) -> Dict[str, object]:
    result = _asset_type_detail_empty_result()
    if dat_rows is None or dat_rows.empty:
        return result

    portfolio_code = str(portfolio_row.get("Portfolio code", "")).strip()
    portfolio_name = str(portfolio_row.get("Portfolio Name", "")).strip()
    rows, asset_type_code_col, asset_type_desc_col, fdv_prev_col, fdv_curr_col, cashflow_col = _prepare_asset_type_detail_rows(dat_rows)

    portfolio_prev_fdv_num = _asset_type_detail_portfolio_prev_fdv_num(portfolio_row)
    if pd.notna(portfolio_prev_fdv_num) and abs(float(portfolio_prev_fdv_num)) > 0:
        rows["_contribution_num"] = rows["_movement_ex_cf_num"] / float(portfolio_prev_fdv_num)
    else:
        rows["_contribution_num"] = float('nan')

    rows, included_source, excluded_source = _classify_asset_type_detail_source_rows(rows)
    included, explained_total_num, share_denom = _build_asset_type_detail_grouped_view(included_source)
    included, overlay_used, explained_total_num, share_denom = _apply_dassetreturn_break_overlay_to_tier1(included, dar_rows)
    reconciliation = _summarise_asset_type_detail_reconciliation(
        portfolio_row=portfolio_row,
        included=included,
        fdv_prev_col=fdv_prev_col,
        fdv_curr_col=fdv_curr_col,
        explained_total_num=explained_total_num,
    )

    detail_df = _build_asset_type_detail_df(included, portfolio_code)
    summary_df = _build_asset_type_summary_df(
        portfolio_code=portfolio_code,
        portfolio_name=portfolio_name,
        portfolio_prev_fdv_num=portfolio_prev_fdv_num,
        target_asset_return_num=reconciliation["target_asset_return_num"],
        explained_total_num=explained_total_num,
        residual_num=reconciliation["residual_num"],
        residual_status=reconciliation["residual_status"],
        top_driver=reconciliation["top_driver"],
        top_contribution_num=reconciliation["top_contribution_num"],
        driver_confidence=reconciliation["driver_confidence"],
        target_label=reconciliation.get("target_label", "Target DDetailed Asset return %"),
        target_value_is_percent_point=bool(reconciliation.get("target_value_is_percent_point", False)),
    )
    diagnostic_df = _build_asset_type_diagnostic_df(
        asset_type_code_col=asset_type_code_col,
        asset_type_desc_col=asset_type_desc_col,
        fdv_prev_col=fdv_prev_col,
        fdv_curr_col=fdv_curr_col,
        cashflow_col=cashflow_col,
        rows=rows,
        included_source=included_source,
        excluded_source=excluded_source,
        included=included,
        share_denom=share_denom,
    )

    result.update({
        "narrative": reconciliation["narrative"],
        "summary_df": summary_df,
        "detail_df": detail_df,
        # Raw numeric source of truth for driver assignment. Do not parse formatted display percentages.
        "driver_rank_df": included.copy(),
        "diagnostic_df": pd.concat([diagnostic_df, pd.DataFrame([{"Check": "DAssetReturn break overlay used", "Result": "Yes" if overlay_used else "No"}])], ignore_index=True),
    })
    return result

def _current_python_file_details() -> Tuple[str, str]:
    """Return the resolved Python file path and filename for the running app."""
    try:
        file_path = str(Path(globals().get("__file__", Path.cwd() / "bnp_control_app_v162.py")).resolve())
    except Exception:
        try:
            file_path = str((Path.cwd() / "bnp_control_app_v162.py").resolve())
        except Exception:
            file_path = "bnp_control_app_v162.py"
    return file_path, Path(file_path).name




def _render_dashboard_section_explainer(section_key: str) -> None:
    """Plain-English review guidance for each dashboard section.

    v304.7: these explainers are intentionally written for handover/review users.
    They are not calculation engines; they describe what each section is for,
    which source reports feed it, and what reviewers should check.
    """
    explainers = {
        "bnp_report_reconciliation": """
**Purpose**

This section checks whether the dashboard's control-break calculation is consistent with the BNP source reports. Use it as the audit trail between the source-of-truth portfolio return in `DDetailedReturn` and the line-level contribution detail in `DAssetReturn`.

**What data is used**

- `DDetailedReturn` provides the portfolio-level result, including actual return, benchmark return, tolerance and OUT/within status.
- `DAssetReturn` provides line-level asset return and excess contribution detail used to rebuild or cross-check the portfolio break.
- Transaction-aware control-break fields are used where available so the dashboard can distinguish ordinary reported return movement from breaks that remain after transaction effects.

**How to review it**

1. Start with the summary/funnel. Confirm that the portfolio population and OUT counts look reasonable for the selected date.
2. Review unmatched or failed rows first. These are the portfolios where the source report and dashboard reconstruction do not line up cleanly.
3. For each exception, compare the reported `DDetailedReturn` actual return to the calculated or reconciled `DAssetReturn` contribution basis.
4. Use the diagnostic columns to decide whether the issue is a genuine data break, a missing source value, a cashflow/transaction timing effect, or a report-shape issue.

**What good looks like**

The best outcome is that the recalculated contribution basis closely agrees with the source return basis, and any remaining differences are explainable from the diagnostic fields rather than hidden in the calculation.
""",
        "portfolio_count": """
**Purpose**

This section gives the Portfolio Numbers population for the selected date. It is the starting point for daily review because it shows how many portfolios were loaded and how they split between within tolerance, outside tolerance, no ARC match, cold and hot.

**What data is used**

- `DDetailedReturn` provides the base portfolio population and the reported tolerance status.
- ARC data is used to help split outside-tolerance portfolios into no ARC, cold and hot populations.
- The dashboard applies the configured materiality and control-break logic before showing the executive counts.

**How to review it**

1. Confirm the selected date and total portfolio count look right for the BNP report pack.
2. Check that `Within tolerance + Cold portfolios + Hot portfolios = Total portfolios`.
3. Check that `No ARC + Cold portfolios + Hot portfolios = the legacy outside tolerance population`.
4. Review Hot portfolios as the population that flows through Auto Explained and Unexplained.
5. If totals do not reconcile, open the diagnostics and source-load sections before reviewing individual portfolios.

**What good looks like**

The count checks should reconcile exactly. A high hot count does not automatically mean the dashboard is wrong; it means more portfolios remain unexplained after the daily control logic.
""",
        "out_portfolios": """
**Purpose**

This section focuses on portfolios that are outside tolerance. It groups OUT portfolios so reviewers can see the main drivers behind the breaks and prioritise review work.

**What data is used**

- `DDetailedReturn` provides the OUT population and return/tolerance values.
- `DAssetTypeReturn` is used to attribute OUT portfolios to broad Tier 1 driver groups where possible.
- `DAssetReturn` can be used as supporting detail where the asset-type view is not enough to classify the driver.
- ARC information helps separate hot and cold review populations.

**How to review it**

1. Start with the largest driver groups by count or severity.
2. Open the relevant portfolios in drill-through to confirm the underlying asset lines support the assigned driver.
3. Pay particular attention to portfolios in `No DAssetTypeReturn`, `Unclassified`, or mixed-driver categories because these usually need more manual judgement.
4. Use this section for prioritisation, not final sign-off. Final sign-off should use the underlying detail tabs.

**What good looks like**

The largest driver groups should make business sense for the day. For example, large market moves should generally appear in market asset drivers, while FX-driven breaks should be picked up by the FX workflow.
""",
        "portfolio_drillthrough": """
**Purpose**

This section is the detailed audit view for a selected portfolio. It shows the source rows and derived calculations that support the dashboard's classification.

**What data is used**

- `DDetailedReturn` provides the portfolio-level return and tolerance context.
- `DAssetTypeReturn` provides asset-type or Tier 1 driver contribution detail.
- `DAssetReturn` provides line-level return and excess contribution detail.
- `TransactionListing` provides transaction rows where transaction explanation is relevant.

**How to review it**

1. Select a portfolio that appears in the hot, unexplained, auto-FX or transaction sections.
2. Review the summary first: portfolio code, name, status, return, benchmark, tolerance and control break.
3. Check the largest Tier 1 driver and the contribution detail supporting it.
4. Compare the driver narrative to the underlying rows. The explanation should be traceable to actual source rows, not just the summary label.
5. If the portfolio is unexplained, look for missing data, unmapped asset types, transaction timing, FX movement or source-report inconsistencies.

**What good looks like**

A reviewer should be able to follow the story from source rows to driver classification to final status without needing to inspect the Python code.
""",
        "auto_fx": """
**Purpose**

This section tests whether hot portfolios can be explained by foreign-exchange movement. It is applied before transaction-listing explanation in the hot portfolio waterfall.

**What data is used**

- `DAssetReturn` provides non-AUD or FX-related report lines.
- The independent exchange-rate source provides currency returns for the selected date.
- DDetailedReturn Actual vs Benchmark provides the starting break that is retested after removing FX effects.
- If Actual vs Benchmark is unavailable, the Auto FX starting break is blank; the app does not fall back to Over/Under, calculated over/under, or line-level Excess Contribution.

**How to review it**

1. Focus on portfolios marked `Auto Explained by FX = YES`.
2. Check that the portfolio has meaningful non-AUD or FX-related lines.
3. Review the independent FX rate match and whether the relevant currencies were available.
4. Review the FX removal waterfall: starting break, FX amount removed and residual break after FX removal.
5. Confirm that the residual moves back inside tolerance, or otherwise meets the dashboard's FX explanation rules.

**What good looks like**

The portfolio should have a clear FX footprint, matched independent exchange rates, and a residual break that is no longer material after FX is removed.
""",
        "auto_explained": """
**Purpose**

This section groups the automated HOT portfolio explanation buckets before residual manual review.

**What data is used**

- FX uses DAssetReturn non-AUD / FX-related report lines and the independent exchange-rate source.
- Nil actual return uses DDetailedReturn Actual Return and Benchmark Return after Auto FX removal.
- Current Account dominated uses DAssetReturn ZL01 current FDV divided by DDetailedReturn current FDV and the configured sidebar threshold.

**How to review it**

- Start with FX because it is the first automated explanation test in the waterfall.
- Then review Nil actual return portfolios.
- Then review Current Account dominated portfolios.
- Anything not explained by these automated buckets remains in Unexplained.

**What good looks like**

The automated explanation buckets should reduce the HOT population before Unexplained without changing the underlying waterfall counts or source-data audit trail.
""",
        "current_account_dominated": """**Purpose**  
This section identifies remaining hot portfolios where current account exposure dominates the portfolio after Auto FX and Nil actual return classifications have already been removed.  

**What data is used**
- DDetailedReturn provides the portfolio-level current FDV market value used as the denominator.
- DAssetReturn provides line-level current FDV market value. Rows where Asset Type Code is ZL01 are summed for the numerator.
- The sidebar Current Account dominance threshold controls the percentage required for classification.  

**How to review it**
- Confirm the DAssetReturn ZL01 current FDV is reasonable relative to DDetailedReturn current FDV.
- Review portfolios near the threshold carefully, especially where there are multiple current-account currency rows.
- Treat this bucket as a concentration-based explanation of the residual HOT portfolio, not as a TransactionListing explanation.  

**What good looks like**  
The portfolio should have most of its current FDV represented by ZL01 current-account rows, and the calculated percentage should be at or above the configured sidebar threshold.
""",
"unexplained": """
**Purpose**

This section shows hot portfolios that remain unexplained after the automated rules. It is the main manual-review worklist.

**What data is used**

- The starting population is hot portfolios.
- Portfolios auto explained by FX are removed first.
- Nil actual return portfolios are removed next.
- Remaining hot portfolios are tested for Current Account dominance using DAssetReturn ZL01 current FDV divided by DDetailedReturn current FDV and the configured sidebar threshold.
- Anything left is shown as unexplained.

**How to review it**

1. Prioritise by driver group, size of break, materiality or operational importance.
2. Open the portfolio drill-through for each residual portfolio.
3. Check whether the issue is missing source data, unmapped asset types, unusual transactions, missing FX rates, benchmark behaviour, ARC status or report timing.
4. Add manual commentary outside the app where required by the review process.
5. Use repeated unexplained drivers as feedback for improving future automation rules.

**What good looks like**

The unexplained list should be small enough for manual review and should contain only portfolios that genuinely need judgement after FX and transaction explanations have been applied.
""",
    }
    text = explainers.get(str(section_key or "").strip())
    if not text:
        return
    with st.expander("How to review and audit this section", expanded=False):
        st.markdown(text)

def _v332_render_static_data_paths(bundle: Dict[str, object]) -> "pd.DataFrame":
    """v332: show ALL configured inputs from Static Data - the 'paths' sheet -
    so Input Sources lists every input in one place. v362: returns the
    (possibly annotated) paths dataframe so the caller can include it in the
    combined 'Download all' workbook, and flags any LOCAL machine-specific
    path (e.g. a C:\\Users\\<username>\\... entry) as not portable, since it will
    only resolve on the machine it was configured on."""
    try:
        sb = bundle.get("static_data") if isinstance(bundle, dict) else None
        get = globals().get("_static_get_active_table_v306_13_8")
        def _tbl(name):
            try:
                return get(sb, name) if callable(get) else pd.DataFrame()
            except Exception:
                return pd.DataFrame()
        paths = _tbl("paths")
        st.markdown("**Configured paths (Static Data)**")
        if isinstance(paths, pd.DataFrame) and not paths.empty:
            cols = [c for c in ["ConfigKey", "ConfigValue", "Description", "Active"] if c in paths.columns]
            disp = paths[cols].copy() if cols else paths.copy()
            # v362: flag local (this-machine-only) paths - e.g. a per-user
            # C:\Users\<name>\... path - so it's clear why it may not resolve
            # for other users/sessions (option 1, per the reviewer: keep in
            # 'paths' but flag visually; revisit centralising it later).
            if "ConfigValue" in disp.columns:
                _is_local = disp["ConfigValue"].astype(str).str.match(r"(?i)^[A-Z]:\\Users\\", na=False)
                if _is_local.any():
                    if "Description" not in disp.columns:
                        disp["Description"] = ""
                    disp.loc[_is_local, "Description"] = disp.loc[_is_local, "Description"].astype(str).where(
                        disp.loc[_is_local, "Description"].astype(str).str.strip().ne(""), ""
                    )
                    _flag = "Local (this machine only) - not portable"
                    disp.loc[_is_local, "Description"] = disp.loc[_is_local].apply(
                        lambda r: f"{r['Description']} [{_flag}]".strip(" []").replace("[]", "").strip()
                        if str(r.get("Description", "")).strip() else _flag, axis=1
                    )
            show_df(disp, hide_index=True)
            return disp
        else:
            st.caption("No 'paths' table found in Static Data.")
            return pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def _render_input_sources_tab(bundle: Dict[str, object], metric_view: str) -> None:
    """v362: new top-level 'Input Sources' tab (renamed from the former
    Portfolio Numbers -> 'Data Sources' sub-section, moved BEFORE Portfolio
    Numbers). The former 'Source details' expander is REMOVED (content kept,
    layout restructured): a compact header strip, a 4-metric health row, then
    each block under its own heading (no longer collapsed), plus a single
    'Download all' button producing one combined workbook - consistent with
    the 'Download full <Control> pack' pattern used elsewhere in the app.
    """
    _render_dashboard_section_explainer("portfolio_count")
    if isinstance(bundle, dict):
        try:
            if callable(globals().get("_afx148_rebuild_auto_fx_after_basis_impact")):
                bundle = _afx148_rebuild_auto_fx_after_basis_impact(bundle, stage="before dashboard portfolio_df bind", force=False)
                try:
                    st.session_state[dashboard_bundle_cache_key] = {"key": bundle_cache_lookup_key, "bundle": bundle}
                except Exception:
                    pass
        except Exception:
            pass
    portfolio_df = bundle["portfolio_df"]
    arc_bundle = bundle.get("arc", {})
    if portfolio_df.empty:
        st.warning("No portfolio detail is available for the selected day.")
        return

    st.subheader("Input Sources")
    st.caption("All inputs feeding the control view - configured paths (Static Data), BNP source files, "
               "FDV valuation, Error Risk and Exchange-rate sources.")
    paths_df = _v332_render_static_data_paths(bundle)

    exchange_rate_bundle = bundle.get("exchange_rates", {})
    file_meta_df = bundle.get("file_meta_df", pd.DataFrame()) if isinstance(bundle, dict) else pd.DataFrame()
    if (file_meta_df is None or not isinstance(file_meta_df, pd.DataFrame) or file_meta_df.empty) and isinstance(bundle.get("out", {}), dict):
        file_meta_df = bundle.get("out", {}).get("file_meta_df", pd.DataFrame())

    # --- validation status (unchanged logic) ---------------------------------
    validation_errors: List[str] = []
    validation_warnings: List[str] = []
    if portfolio_df is None or portfolio_df.empty:
        validation_errors.append("No portfolio rows loaded")
    if isinstance(file_meta_df, pd.DataFrame) and not file_meta_df.empty and {"Keyword", "Loaded"}.issubset(file_meta_df.columns):
        required_missing = file_meta_df[file_meta_df["Keyword"].astype(str).isin(REQUIRED_FILE_KEYWORDS) & ~file_meta_df["Loaded"].fillna(False).astype(bool)]
        optional_missing = file_meta_df[file_meta_df["Keyword"].astype(str).isin(OPTIONAL_FILE_KEYWORDS) & ~file_meta_df["Loaded"].fillna(False).astype(bool)]
        if not required_missing.empty:
            validation_errors.append("Required BNP source file missing: " + ", ".join(required_missing["Keyword"].astype(str).tolist()))
        if not optional_missing.empty:
            validation_warnings.append("Optional BNP source file missing: " + ", ".join(optional_missing["Keyword"].astype(str).tolist()))
    else:
        validation_warnings.append("BNP source file metadata unavailable")
    if isinstance(arc_bundle, dict):
        if not arc_bundle.get("arc_file", ""):
            validation_warnings.append("Error Risk source (BP Impact Tool) not selected")
    else:
        validation_warnings.append("Error Risk source bundle unavailable")
    if isinstance(exchange_rate_bundle, dict):
        if not exchange_rate_bundle.get("source_file", ""):
            validation_warnings.append("Exchange-rate workbook not selected")
        if str(exchange_rate_bundle.get("status", "")).strip().lower() != "exchange rates extracted":
            validation_warnings.append("Exchange-rate source status: " + str(exchange_rate_bundle.get("status", "")))
    else:
        validation_warnings.append("Exchange-rate bundle unavailable")
    validation_status = "FAIL" if validation_errors else "WARN" if validation_warnings else "PASS"

    # --- 1. compact header strip ---------------------------------------------
    st.caption(
        f"Validation status: **{validation_status}** | Errors: {len(validation_errors)} | Warnings: {len(validation_warnings)} | "
        f"App version: {APP_PYTHON_VERSION} | Source day folder: {bundle.get('folder', '')} | "
        f"Loaded portfolios: {int(len(portfolio_df)):,} | "
        f"Independent FX match tolerance: ${float(bundle.get('fx_line_match_tolerance_dollar', 100.0)):,.2f}"
    )
    if validation_errors:
        st.error("; ".join(validation_errors))
    elif validation_warnings:
        st.warning("; ".join(validation_warnings))
    else:
        st.success("Source validation checks passed.")

    # --- prepare each block's dataframe up front (shared by metrics, display, download-all) ---
    _bnp = pd.DataFrame()
    if isinstance(file_meta_df, pd.DataFrame) and not file_meta_df.empty:
        _bnp = file_meta_df.copy()
        if "LoadedPaths" in _bnp.columns:
            import os as _os2
            _bnp["Files loaded"] = _bnp["LoadedPaths"].astype(str).apply(
                lambda s: " | ".join(_os2.path.basename(p) for p in s.split(" | ") if p.strip()))
        _bnp_cols = [c for c in ["Keyword", "Files loaded", "Loaded", "Rows", "Columns", "MatchedFiles", "LoadedFiles", "HeaderValidation", "Error"] if c in _bnp.columns]
        _bnp = _bnp[_bnp_cols].copy() if _bnp_cols else _bnp

    _fdv = bundle.get("fdv_files") if isinstance(bundle, dict) else None
    _fdv_df = pd.DataFrame()
    if isinstance(_fdv, (list, tuple)) and _fdv:
        import os as _os3
        _fdv_df = pd.DataFrame([{"File": _os3.path.basename(str(p)), "Path": str(p)} for p in _fdv])

    _er_rows = []
    if isinstance(arc_bundle, dict):
        _er_rows.append({"Field": "Status", "Value": arc_bundle.get("status", "")})
        if arc_bundle.get("arc_file", ""):
            _er_rows.append({"Field": "File", "Value": arc_bundle.get("arc_file", "")})
        arc_match_df = arc_bundle.get("arc_match_df", pd.DataFrame())
        if isinstance(arc_match_df, pd.DataFrame) and not arc_match_df.empty:
            _er_rows.append({"Field": "Date matches found", "Value": int(len(arc_match_df))})
    _er_df = pd.DataFrame(_er_rows)

    _fx_rows = []
    if isinstance(exchange_rate_bundle, dict):
        _fx_rows.append({"Field": "Status", "Value": exchange_rate_bundle.get("status", "")})
        if exchange_rate_bundle.get("source_file", ""):
            _fx_rows.append({"Field": "Workbook", "Value": exchange_rate_bundle.get("source_file", "")})
        if exchange_rate_bundle.get("sheet_used", ""):
            _fx_rows.append({"Field": "Sheet", "Value": exchange_rate_bundle.get("sheet_used", "")})
            _fx_rows.append({"Field": "Rows extracted", "Value": int(len(exchange_rate_bundle.get("exchange_rate_df", pd.DataFrame())))})
    _fx_df = pd.DataFrame(_fx_rows)

    def _cache_status(_key):
        _d = bundle.get(_key, pd.DataFrame()) if isinstance(bundle, dict) else pd.DataFrame()
        if isinstance(_d, pd.DataFrame) and not _d.empty:
            return str(_d.iloc[0].get("Status", ""))
        return "-"
    _cache_df = pd.DataFrame([
        {"Cache": "BNP source", "Status": _cache_status("bnp_source_cache_status_df")},
        {"Cache": "process_day", "Status": _cache_status("process_day_cache_status_df")},
        {"Cache": "Executive summary (session)", "Status": ("Hit" if (hasattr(st, "session_state") and isinstance(st.session_state.get("_bnp_dashboard_executive_summary_cache_v306_4_1"), dict)) else "-")},
        {"Cache": "Date-folder manifest", "Status": _cache_status("date_folder_manifest_status_df")},
    ])

    # --- 2. four-column health metric row -------------------------------------
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("BNP files loaded", int(_bnp["Loaded"].fillna(False).astype(bool).sum()) if "Loaded" in _bnp.columns else "-")
    m2.metric("FDV files loaded", int(len(_fdv_df)))
    m3.metric("Error Risk status", str(arc_bundle.get("status", "-")) if isinstance(arc_bundle, dict) else "-")
    m4.metric("Exchange-rate status", str(exchange_rate_bundle.get("status", "-")) if isinstance(exchange_rate_bundle, dict) else "-")

    # --- 3. "Download all" - one combined workbook, one tab per block ----------
    try:
        from io import BytesIO as _BytesIO
        _out = _BytesIO()
        with pd.ExcelWriter(_out, engine="openpyxl") as _writer:
            (paths_df if isinstance(paths_df, pd.DataFrame) and not paths_df.empty else pd.DataFrame(columns=["No data"])).to_excel(_writer, sheet_name="Configured paths", index=False)
            (_bnp if not _bnp.empty else pd.DataFrame(columns=["No data"])).to_excel(_writer, sheet_name="BNP day files", index=False)
            (_fdv_df if not _fdv_df.empty else pd.DataFrame(columns=["No data"])).to_excel(_writer, sheet_name="FDV valuation", index=False)
            (_er_df if not _er_df.empty else pd.DataFrame(columns=["No data"])).to_excel(_writer, sheet_name="Error Risk source", index=False)
            (_fx_df if not _fx_df.empty else pd.DataFrame(columns=["No data"])).to_excel(_writer, sheet_name="Exchange-rate source", index=False)
            _cache_df.to_excel(_writer, sheet_name="Caches", index=False)
            for _ws in _writer.book.worksheets:
                _ws.freeze_panes = "A2"
                for _cells in _ws.columns:
                    try:
                        _width = max(len(str(_c.value or "")) for _c in _cells[:250]) + 2
                        _ws.column_dimensions[_cells[0].column_letter].width = min(max(_width, 10), 60)
                    except Exception:
                        pass
        st.download_button(
            "Download all (Input Sources)",
            data=_out.getvalue(),
            file_name="input_sources_full_pack.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="input_sources_download_all",
        )
    except Exception as _exc:
        st.caption(f"Download all unavailable: {type(_exc).__name__}: {_exc}")

    # --- 4. each block under its own heading (no longer collapsed) ------------
    st.markdown("### BNP Day Files")
    st.caption("Files loaded from the source day folder.")
    if not _bnp.empty:
        show_df(_bnp, hide_index=True)
    else:
        st.caption("BNP source file metadata unavailable.")

    st.markdown("### FDV Valuation")
    st.caption("DetailedValuationFDV - current day (T) + previous day (T-1), needed for the UUT weighted "
               "return (CurrentPrice_T / PreviousPrice_T-1 - 1). Loads via the UUT look-through side-path.")
    if not _fdv_df.empty:
        show_df(_fdv_df, hide_index=True)
    else:
        st.caption("Not loaded this run.")

    st.markdown("### Error Risk Source")
    st.caption("BP Impact Tool.")
    if not _er_df.empty:
        show_df(_er_df, hide_index=True)
    else:
        st.caption("Error Risk source bundle unavailable.")

    st.markdown("### Exchange-Rate Source")
    if not _fx_df.empty:
        show_df(_fx_df, hide_index=True)
    else:
        st.caption("Exchange-rate bundle unavailable.")

    st.markdown("### Caches")
    show_df(_cache_df, hide_index=True)



def _render_within_tolerance_portfolios_content(bundle: Dict[str, object]) -> None:
    """Render portfolios that are within tolerance under Portfolio Numbers."""
    portfolio_df = bundle.get("portfolio_df", pd.DataFrame()) if isinstance(bundle, dict) else pd.DataFrame()
    if portfolio_df is None or not isinstance(portfolio_df, pd.DataFrame) or portfolio_df.empty:
        st.info("No portfolio detail is available for the selected day.")
        return
    within_df = portfolio_df[portfolio_df["Within Tolerance"] == True].copy() if "Within Tolerance" in portfolio_df.columns else pd.DataFrame()

    def _display_df(source_df: pd.DataFrame) -> pd.DataFrame:
        if source_df is None or source_df.empty:
            return pd.DataFrame()
        display_df = pd.DataFrame(index=source_df.index)
        display_df["Portfolio code"] = source_df.get("Portfolio code", "")
        display_df["Portfolio Name"] = source_df.get("Portfolio Name", "")
        display_df["FDV Valuation(Current Day)"] = source_df.get("FDV Valuation(Current Day) Num", pd.Series(dtype="float64")).map(_excel_currency_string)
        display_df["Benchmark Code"] = source_df.get("Benchmark Code", "")
        display_df["Benchmark Name"] = source_df.get("Benchmark Name", "")
        display_df["Status"] = source_df.get("Status", "")
        display_df["Actual Return"] = source_df.get("Actual Return Decimal", pd.Series(dtype="float64")).map(_percent_string_1dp)
        display_df["Benchmark Return"] = source_df.get("Benchmark Return Decimal", pd.Series(dtype="float64")).map(_percent_string_1dp)
        display_df["Tolerance"] = source_df.get("Tolerance Decimal", pd.Series(dtype="float64")).map(_percent_string_1dp)
        display_df["Volatility over Tolerance"] = source_df.get("Volatility over Tolerance Num", pd.Series(dtype="float64")).map(_percent_string_1dp)
        return display_df

    st.markdown(f"##### Within tolerance ({int(len(within_df)):,})")
    if within_df.empty:
        st.info("No within tolerance portfolios for the selected day.")
    else:
        show_df(_display_df(within_df), hide_index=True)


def _render_control_break_source_mismatches_v356(bundle: Dict[str, object]) -> None:
    """v356: surface the control-break source-integrity mismatches (the 'N DAssetReturn
    control-break mismatches' warning) as a read-only, reviewable table under Portfolio
    Numbers -> Portfolios. This is DISPLAY-ONLY - no logic, tolerance or classification
    changes. It reuses the per-portfolio A-vs-B data already computed by process_day in
    bundle['control_break_audit_df']:
      A = 'DDetailedReturn Actual Return' (portfolio-level actual return)
      B = 'DAssetReturn Asset to Portfolio Contribution Total' (sum of asset-level
          contributions to the portfolio return)
    A portfolio is flagged 'Mismatch' when |A - B| > 0.01pp (1bp) - i.e. the parts don't
    add up to the whole. This turns the opaque count into a ranked list so a reviewer can
    eyeball whether the gaps are benign rounding/timing (tiny) or worth a closer look
    (large). v357: replaced the prior excess-basis (Over/Under vs Excess Contribution)
    with this Actual-Return basis."""
    try:
        if "st" not in globals() or st is None or not isinstance(bundle, dict):
            return
        audit = bundle.get("control_break_audit_df", pd.DataFrame())
        if not isinstance(audit, pd.DataFrame) or audit.empty:
            return
        status_col = "Source vs DAssetReturn Match Status"
        a_col = "DDetailedReturn Actual Return"
        b_col = "DAssetReturn Asset to Portfolio Contribution Total"
        gap_col = "Actual Return vs DAssetReturn Contribution Difference"
        if status_col not in audit.columns:
            return
        mism = audit[audit[status_col].astype(str).str.strip().eq("Mismatch")].copy()
        st.markdown("##### Control-break source mismatches (Actual Return vs DAssetReturn contributions)")
        if mism.empty:
            st.caption("No control-break source mismatches for the selected date "
                       "(every portfolio's Actual Return reconciles to its summed asset "
                       "contributions within 0.01pp / 1bp).")
            return
        # build a tidy, sorted display frame
        name_col = None
        for c in ["Portfolio Name", "PortfolioName", "Portfolio code", "Portfolio"]:
            if c in audit.columns:
                name_col = c
                break
        cols = {}
        cols["Portfolio"] = mism["Portfolio"].astype(str) if "Portfolio" in mism.columns else ""
        if name_col and name_col not in ("Portfolio",):
            cols["Portfolio Name"] = mism[name_col].astype(str)
        cols["Actual Return (A) pp"] = pd.to_numeric(mism.get(a_col), errors="coerce").round(4)
        cols["DAssetReturn contributions \u03a3 (B) pp"] = pd.to_numeric(mism.get(b_col), errors="coerce").round(4)
        gap = pd.to_numeric(mism.get(gap_col), errors="coerce")
        cols["Gap (A-B) pp"] = gap.round(4)
        disp = pd.DataFrame(cols)
        disp["_absgap"] = gap.abs()
        disp = disp.sort_values("_absgap", ascending=False, na_position="last").drop(columns=["_absgap"]).reset_index(drop=True)
        st.caption(
            f"{len(disp):,} portfolio(s) where the DDetailedReturn Actual Return (A) and the summed "
            "DAssetReturn Asset-to-Portfolio Contributions (B) differ by more than 0.01pp (1bp) - i.e. the "
            "asset-level contributions do not add up to the portfolio's actual return. This is a source-"
            "integrity review flag between the two BNP reports (rounding / cashflow-timing / income-tax "
            "staging / FX / a missing DAssetReturn line), NOT a dashboard calculation error - the "
            "classifications are unaffected. Review the largest gaps first."
        )
        show_df(disp, hide_index=True)
        try:
            st.download_button(
                "Download control-break source mismatches",
                disp.to_csv(index=False).encode("utf-8"),
                "control_break_source_mismatches_last_run.csv",
                "text/csv",
                key="control_break_source_mismatches_dl_v356",
            )
        except Exception:
            pass
    except Exception as exc:
        try:
            if bool(globals().get("SHOW_DEBUG", False)):
                st.caption(f"Control-break mismatch panel failed: {type(exc).__name__}: {exc}")
        except Exception:
            pass


def _price_integrity_frames_v358_3(bundle: Dict[str, object]):
    """Build once, cache both frames, and return (stale, material, summary, status)."""
    stale = bundle.get("stale_price_df") if isinstance(bundle, dict) else None
    material = bundle.get("material_movement_df") if isinstance(bundle, dict) else None
    summary = bundle.get("price_integrity_summary", {}) if isinstance(bundle, dict) else {}
    if isinstance(stale, pd.DataFrame) and isinstance(material, pd.DataFrame):
        return stale, material, summary if isinstance(summary, dict) else {}, "OK"
    if not callable(globals().get("_build_price_integrity_v358_3")):
        return pd.DataFrame(), pd.DataFrame(), {}, "Builder unavailable"
    res = _build_price_integrity_v358_3(bundle)
    stale = getattr(res, "stale_df", pd.DataFrame())
    material = getattr(res, "material_df", pd.DataFrame())
    summary = getattr(res, "summary", {})
    if isinstance(bundle, dict):
        bundle["stale_price_df"] = stale
        bundle["material_movement_df"] = material
        bundle["price_integrity_summary"] = summary
    return stale, material, summary if isinstance(summary, dict) else {}, getattr(res, "status", "OK")


def _render_stale_price_v358_3(bundle: Dict[str, object]) -> None:
    stale, _material, summary, status = _price_integrity_frames_v358_3(bundle)
    st.markdown("**Stale Price Check**")
    st.caption("BNP DStalePrice rows where un-priced business days exceed the expected pricing frequency.")
    if status != "OK":
        st.warning(f"Stale Price Check unavailable: {status}")
        return
    c1, c2 = st.columns(2)
    c1.metric("Stale-report rows", summary.get("stale_report_rows", len(stale) if isinstance(stale, pd.DataFrame) else 0))
    flagged = int(stale["Stale Price Check"].astype(str).str.strip().eq("Stale").sum()) if isinstance(stale, pd.DataFrame) and "Stale Price Check" in stale.columns else summary.get("stale_flagged", 0)
    c2.metric("Stale flagged", flagged)
    if isinstance(stale, pd.DataFrame) and not stale.empty:
        st.download_button("Download Stale Price Check CSV", data=stale.to_csv(index=False).encode("utf-8-sig"), file_name="stale_price_check.csv", mime="text/csv", key="download_stale_price_check_v358_3")
        st.dataframe(stale, width="stretch", hide_index=True)
    else:
        st.info("No stale-price rows were produced for the selected date.")


def _render_material_price_mvt_v358_3(bundle: Dict[str, object]) -> None:
    _stale, material, summary, status = _price_integrity_frames_v358_3(bundle)
    st.markdown("**UUT Material Price MVT**")
    st.caption("Two-day DetailedValuationFDV price movements flagged where price return is greater than +1% or less than -0.5% (price calculation and thresholds unchanged). "
               "v358.4: population scoped to DetailedValuationFDV GLGroupName in {AUD Unlisted Trusts, AUD Unlisted Equity, Unlist Intl Equities, Unlist Intl Trust}, "
               "excluding PortfolioCode M2STT2 / M2STT4 - replacing the prior hard-coded AssetSubClassName UUT-scope rule for this control only "
               "(the Advisor-UUT Check's population is unaffected).")
    if status != "OK":
        st.warning(f"UUT Material Price MVT unavailable: {status}")
        return
    count = int(len(material)) if isinstance(material, pd.DataFrame) else int(summary.get("material_movements", 0))
    st.metric("Material movements", count)
    if isinstance(material, pd.DataFrame) and not material.empty:
        st.download_button("Download UUT Material Price MVT CSV", data=material.to_csv(index=False).encode("utf-8-sig"), file_name="uut_material_price_mvt.csv", mime="text/csv", key="download_material_price_mvt_v358_3")
        st.dataframe(material, width="stretch", hide_index=True)
    else:
        st.info("No material price movements were produced for the selected date.")


def _render_pn_arc_panel(name: str, bundle: Dict[str, object]) -> None:
    """v323/v335: render one ARC check panel as a Portfolio Numbers sub-section
    (content only, no expander). v335: no longer fails silently - if a panel's
    render function is missing it says so, and if it raises the error is shown
    (so a sub-section can never appear as a blank). The panel content itself is
    unchanged."""
    if "st" not in globals() or st is None:
        return
    g = globals().get
    # map each sub-section to the render function it needs, so we can report a
    # clear message when that function isn't available (import failed).
    _fn_for = {
        "Reconciliation export": "_render_recon_export_v315",
        "Portfolios": "_render_portfolios_recon_gav_v359",
        "GAV": "_render_gav_section_v309",
        "Advisor Return": "_render_advisor_return_gav_v359",
        "Advisor-UUT": "_render_advisor_uut_gav_v359",
        "Investment Clearing": "_render_investment_clearing_gav_v359",
        "Cash Clearing": "_render_cash_clearing_gav_v359",
        "Negative NAV": "_render_negative_nav_gav_v359",
        "Liquidity": "_render_liquidity_gav_v361",
        "Stale Price Check": "_render_stale_price_gav_v359",
        "UUT Material Price MVT": "_render_uut_material_mvt_gav_v359",
        "Control summary": "_render_outputs_v314",
    }
    _needed = _fn_for.get(name)
    if _needed is not None and not callable(g(_needed)):
        st.warning(f"'{name}' renderer is unavailable ({_needed} not loaded). "
                   f"Check that its helper module imported correctly.")
        return
    try:
        if name == "Reconciliation export" and callable(g("_render_recon_export_v315")):
            # v315: one-click ARC-named "Download everything" workbook.
            _render_recon_export_v315(st, bundle)
            return
        if name == "Portfolios" and callable(g("_render_portfolios_recon_gav_v359")):
            # v359: GAV-style template (matched / missing / unmapped / excluded).
            _render_portfolios_recon_gav_v359(st, bundle)
            # v356: display-only control-break source-integrity mismatch review table.
            try:
                _render_control_break_source_mismatches_v356(bundle)
            except Exception:
                pass
        elif name == "GAV" and callable(g("_render_gav_section_v309")):
            _render_gav_section_v309(st, bundle)
        elif name == "Advisor Return" and callable(g("_render_advisor_return_gav_v359")):
            # v359: GAV-style template (population/Check/Ok/Excluded + full pack).
            _render_advisor_return_gav_v359(st, bundle)
        elif name == "Advisor-UUT" and callable(g("_render_advisor_uut_gav_v359")):
            # v344: reset the UUT internal step timers, render, then drain the per-step
            # timings into the deep-timing run-log so the ~24s breaks down by phase.
            try:
                if callable(globals().get("_uut_reset_timings_v344")):
                    _uut_reset_timings_v344()
            except Exception:
                pass
            # v330: ensure the base advisor_uut_df exists (built silently) before the corrected panel.
            if not (isinstance(bundle, dict) and isinstance(bundle.get("advisor_uut_df"), pd.DataFrame) and not bundle.get("advisor_uut_df").empty) and callable(g("_render_uut_section_v311")):
                try:
                    class _NS:
                        def __getattr__(s, n): return s._c
                        def _c(s, *a, **k): return s
                        def columns(s, spec, *a, **k):
                            n = spec if isinstance(spec, int) else (len(spec) if hasattr(spec, "__len__") else 2)
                            return [_NS() for _ in range(max(1, int(n)))]
                        def __enter__(s): return s
                        def __exit__(s, *a): return False
                    _render_uut_section_v311(_NS(), bundle)
                except Exception:
                    pass
            # v359: GAV-style template, reusing the same v311.1-corrected population.
            _render_advisor_uut_gav_v359(st, bundle)
            _drain_uut_internal_timings_v344()
        elif name == "Investment Clearing" and callable(g("_render_investment_clearing_gav_v359")):
            _render_investment_clearing_gav_v359(st, bundle)
        elif name == "Cash Clearing" and callable(g("_render_cash_clearing_gav_v359")):
            _render_cash_clearing_gav_v359(st, bundle)
        elif name == "Negative NAV" and callable(g("_render_negative_nav_gav_v359")):
            _render_negative_nav_gav_v359(st, bundle)
        elif name == "Liquidity" and callable(g("_render_liquidity_gav_v361")):
            # v361: Liquidity rebuilt to the full GAV-style template per the
            # reviewer's instruction - Investment Clearing / Cash Clearing /
            # Negative NAV are their own dedicated tabs now (no longer
            # duplicated here); Liquidity shows its own population split into
            # =100% / >=80%<100% / the rest / excluded (NAV unavailable).
            _render_liquidity_gav_v361(st, bundle)
        elif name == "Stale Price Check" and callable(g("_render_stale_price_gav_v359")):
            # v359: GAV-style template (population/Check/Ok/Excluded + full pack).
            _render_stale_price_gav_v359(st, bundle)
        elif name == "UUT Material Price MVT" and callable(g("_render_uut_material_mvt_gav_v359")):
            # v359: GAV-style template (population/Check/Ok/Excluded + full pack).
            _render_uut_material_mvt_gav_v359(st, bundle)
        elif name == "Control summary" and callable(g("_render_outputs_v314")):
            _render_outputs_v314(st, bundle)
    except Exception as _exc:
        # v335: surface the failure instead of a silent blank.
        try:
            st.error(f"'{name}' could not render: {type(_exc).__name__}: {_exc}")
            if bool(globals().get("SHOW_DEBUG", False)):
                import traceback as _tb
                st.caption(_tb.format_exc())
        except Exception:
            pass


# v315: display labels that pair each app sub-section with its ARC sheet.
# Dispatch keys / stored session values are UNCHANGED - display only, no risk.
ARC_SECTION_DISPLAY = {
    "Reconciliation export":                 "Reconciliation export  (ARC workbook)",
    "Control summary":                       "Control summary  \u2192  SF / Trusts Checklist",
    "Portfolios":                            "Portfolios  \u2192  Central Mapping List",
    "GAV":                                   "GAV Check  \u2192  GAV Check - SF / Trust",
    "Advisor Return":                        "Advisor Return  \u2192  Unison vs BNP return check",
    "Advisor-UUT":                           "Advisor-UUT  \u2192  Advisor-UUT Check / UUT Return",
    "Investment Clearing":                   "Investment Clearing",
    "Cash Clearing":                         "Cash Clearing",
    "Negative NAV":                          "Negative NAV  \u2192  Unison vs BNP return check",
    "Liquidity":                             "Liquidity  \u2192  Acc Balance - Liquidity",
    "Stale Price Check":                     "Stale Price Check",
    "UUT Material Price MVT":                "UUT Material Price MVT",
}


def _arc_section_label(key: str) -> str:
    """Display label for a Portfolio Numbers sub-section (ARC-aligned where known;
    otherwise the key is shown unchanged)."""
    return ARC_SECTION_DISPLAY.get(str(key), str(key))


def _render_overview_tab_core(bundle: Dict[str, object], metric_view: str):
    """Render Portfolio Numbers as a parent section with dashboard-aligned sub-sections.

    v362: trimmed to ONLY the 5 portfolio-population views (Within tolerance,
    Outside tolerance, No Error Risk, Cold portfolios, Hot portfolios). The 13
    ARC/GAV-style control sub-sections moved to the new top-level "Control
    checks" tab (see _render_control_checks_tab), and "Data Sources" moved to
    the new top-level "Input Sources" tab (see _render_input_sources_tab) -
    both per the reviewer's confirmed v362 layout.
    """
    valid_sections = [
        "Within tolerance",
        "Outside tolerance",
        "No Error Risk",
        "Cold portfolios",
        "Hot portfolios",
    ]
    legacy_map = {
        "Overview": "Within tolerance",
        "Total portfolios": "Within tolerance",
        "Data Sources": "Within tolerance",
        "OUT Portfolios": "Outside tolerance",
        "Hot Portfolios": "Hot portfolios",
        "Cold": "Cold portfolios",
        # v362: any of the 13 former Portfolio Numbers ARC sub-sections now live
        # under Control checks - redirect stale session state there instead.
        "Reconciliation export": "Within tolerance", "Control summary": "Within tolerance",
        "Portfolios": "Within tolerance", "GAV": "Within tolerance", "Advisor Return": "Within tolerance",
        "Advisor-UUT": "Within tolerance", "Investment Clearing": "Within tolerance",
        "Cash Clearing": "Within tolerance", "Negative NAV": "Within tolerance",
        "Liquidity": "Within tolerance", "Stale Price Check": "Within tolerance",
        "UUT Material Price MVT": "Within tolerance",
        "Stale Price + Material Movement": "Within tolerance",
        "Clearing + Negative NAV + Liquidity": "Within tolerance",
    }
    portfolio_count_sub_section_key = "portfolio_count_sub_section"
    current_sub_section = st.session_state.get(portfolio_count_sub_section_key, "Within tolerance")
    if current_sub_section in legacy_map:
        st.session_state[portfolio_count_sub_section_key] = legacy_map[current_sub_section]
    elif current_sub_section not in valid_sections and portfolio_count_sub_section_key in st.session_state:
        st.session_state[portfolio_count_sub_section_key] = "Within tolerance"

    portfolio_count_radio_kwargs = {
        "label": "Portfolio Numbers sub-section",
        "options": valid_sections,
        "horizontal": True,
        "key": portfolio_count_sub_section_key,
        "format_func": _arc_section_label,  # v315: ARC-aligned display only; keys unchanged.
        "help": f"Hot portfolios: {HOT_PORTFOLIO_TOOLTIP} Cold portfolios: {COLD_PORTFOLIO_TOOLTIP}",
    }
    if portfolio_count_sub_section_key not in st.session_state:
        portfolio_count_radio_kwargs["index"] = valid_sections.index("Within tolerance")
    sub_section = st.radio(**portfolio_count_radio_kwargs)
    # v336: scope the Portfolio Numbers sub-sections to the SAME portfolio group as
    # the executive card (On UNISON / Off UNISON / IISL), so Within/Outside/Hot/Cold
    # etc. match the card exactly (was 149 vs 151 because the sub-sections were global
    # while the card was On-UNISON only).
    _pn_bundle = bundle
    try:
        _grp = st.session_state.get("exec_dashboard_group") if hasattr(st, "session_state") else None
        if _grp and callable(globals().get("_v328_group_map")):
            _gmap = _v328_group_map(bundle)
            _pf = bundle.get("portfolio_df", pd.DataFrame()) if isinstance(bundle, dict) else pd.DataFrame()
            if _grp == "IISL mandates" or _grp == "IISL":
                _scoped = _pf.iloc[0:0].copy() if isinstance(_pf, pd.DataFrame) else pd.DataFrame()
            else:
                _scoped = _v328_filter_to_group(_pf, _grp, _gmap)
            # v337 FIX: only swap to the scoped bundle when it actually resolved to
            # rows. If the group filter comes back EMPTY (e.g. group key mismatch, or
            # a group whose feed isn't loaded), keep the GLOBAL bundle so the
            # sub-sections still display instead of going blank. IISL (feed pending)
            # is handled explicitly so it can show its empty-state note.
            if isinstance(_scoped, pd.DataFrame) and not _scoped.empty:
                _pn_bundle = dict(bundle); _pn_bundle["portfolio_df"] = _scoped
                st.caption(f"Scoped to portfolio group: {_grp} ({int(len(_scoped)):,} portfolios).")
            elif _grp in ("IISL", "IISL mandates"):
                _pn_bundle = dict(bundle); _pn_bundle["portfolio_df"] = _pf.iloc[0:0].copy() if isinstance(_pf, pd.DataFrame) else pd.DataFrame()
                st.caption(f"Scoped to portfolio group: {_grp} (0 portfolios - separate feed pending).")
            else:
                # scoped came back empty for a group that SHOULD have rows -> do not
                # blank the section; render global and say so.
                _pn_bundle = bundle
                st.caption(f"Group '{_grp}' scoping unavailable this run - showing all loaded portfolios.")
    except Exception:
        _pn_bundle = bundle
    # v341: guard the sub-section dispatch so a throw on the On UNISON path (e.g. a
    # scoped frame missing an expected column feeding the hot-driver builders)
    # surfaces st.error() instead of blanking the sub-section.
    # v342 (Option B): each sub-section is also deep-timed.
    try:
        _pn_rows = int(len(_pn_bundle.get("portfolio_df", pd.DataFrame()))) if isinstance(_pn_bundle, dict) and isinstance(_pn_bundle.get("portfolio_df"), pd.DataFrame) else ""
        with _deep_timer(bundle, "Portfolio Numbers sub-section", sub_section, rows=_pn_rows):
            if sub_section == "Within tolerance":
                _render_within_tolerance_portfolios_content(_pn_bundle)
            elif sub_section == "Outside tolerance":
                _render_out_portfolios_content(_pn_bundle, metric_view, focus="all")
            elif sub_section == "No Error Risk":
                _render_out_portfolios_content(_pn_bundle, metric_view, focus="no_arc")
            elif sub_section == "Cold portfolios":
                _render_out_portfolios_content(_pn_bundle, metric_view, focus="cold")
            else:
                _render_out_portfolios_content(_pn_bundle, metric_view, focus="hot")
    except Exception as _exc:
        try:
            st.error(f"'{sub_section}' could not render: {type(_exc).__name__}: {_exc}")
            if bool(globals().get("SHOW_DEBUG", False)):
                import traceback as _tb
                st.caption(_tb.format_exc())
        except Exception:
            pass


def _render_control_checks_tab(bundle: Dict[str, object]) -> None:
    """v362: new top-level 'Control checks' tab. Hosts the 13 ARC/GAV-style
    control sub-sections that previously lived inside Portfolio Numbers
    (Reconciliation export, Control summary, Portfolios, GAV, Advisor Return,
    Advisor-UUT, Investment Clearing, Cash Clearing, Negative NAV, Liquidity,
    Stale Price Check, UUT Material Price MVT). v368: Parity Matrix removed at
    user request (bnp_helpers_parity.py deleted). Dispatch reuses the EXACT
    SAME _render_pn_arc_panel() function used before the split - no change to
    any control's underlying logic, only its parent tab location.
    """
    arc_sections = [
        "Reconciliation export",
        "Control summary",
        "Portfolios",
        "GAV",
        "Advisor Return",
        "Advisor-UUT",
        "Investment Clearing",
        "Cash Clearing",
        "Negative NAV",
        "Liquidity",
        "Stale Price Check",
        "UUT Material Price MVT",
    ]
    control_checks_sub_section_key = "control_checks_sub_section"
    # v328 behaviour retained: land on Reconciliation export on first load (the
    # eager warm-up has already populated every check frame at prepare time).
    current_sub_section = st.session_state.get(control_checks_sub_section_key, "Reconciliation export")
    if current_sub_section not in arc_sections and control_checks_sub_section_key in st.session_state:
        st.session_state[control_checks_sub_section_key] = "Reconciliation export"

    control_checks_radio_kwargs = {
        "label": "Control checks sub-section",
        "options": arc_sections,
        "horizontal": True,
        "key": control_checks_sub_section_key,
        "format_func": _arc_section_label,  # v315: ARC-aligned display only; keys unchanged.
    }
    if control_checks_sub_section_key not in st.session_state:
        control_checks_radio_kwargs["index"] = arc_sections.index("Reconciliation export")
    sub_section = st.radio(**control_checks_radio_kwargs)

    # v336: same portfolio-group scoping as Portfolio Numbers, carried over
    # unchanged from the pre-split behaviour (these controls were previously
    # scoped identically inside _render_overview_tab_core).
    _cc_bundle = bundle
    try:
        _grp = st.session_state.get("exec_dashboard_group") if hasattr(st, "session_state") else None
        if _grp and callable(globals().get("_v328_group_map")):
            _gmap = _v328_group_map(bundle)
            _pf = bundle.get("portfolio_df", pd.DataFrame()) if isinstance(bundle, dict) else pd.DataFrame()
            if _grp == "IISL mandates" or _grp == "IISL":
                _scoped = _pf.iloc[0:0].copy() if isinstance(_pf, pd.DataFrame) else pd.DataFrame()
            else:
                _scoped = _v328_filter_to_group(_pf, _grp, _gmap)
            if isinstance(_scoped, pd.DataFrame) and not _scoped.empty:
                _cc_bundle = dict(bundle); _cc_bundle["portfolio_df"] = _scoped
                st.caption(f"Scoped to portfolio group: {_grp} ({int(len(_scoped)):,} portfolios).")
            elif _grp in ("IISL", "IISL mandates"):
                _cc_bundle = dict(bundle); _cc_bundle["portfolio_df"] = _pf.iloc[0:0].copy() if isinstance(_pf, pd.DataFrame) else pd.DataFrame()
                st.caption(f"Scoped to portfolio group: {_grp} (0 portfolios - separate feed pending).")
            else:
                _cc_bundle = bundle
                st.caption(f"Group '{_grp}' scoping unavailable this run - showing all loaded portfolios.")
    except Exception:
        _cc_bundle = bundle

    with _deep_timer(bundle, "Control checks sub-section", f"ARC: {sub_section}"):
        _render_pn_arc_panel(sub_section, _cc_bundle)


def _render_overview_tab(bundle: Dict[str, object], metric_view: str):
    """v327: single collapsed pipeline replacing the 7 render-side monkey-patch
    wrappers (source-load diagnostics v306.13.11/12/14, non-ARC BP Impact
    classification 17/18/19, and the er-runtime diag). Same call order and same
    behaviour as the wrapper chain. The prepare-side BP Impact wrappers on
    _prepare_out_dashboard_bundle are a separate concern and are left unchanged.
    (The classification functions mutate the bundle in place and return it, so the
    before/after diag see the same object - verified.)"""
    # pre: er-runtime diag (before)
    _er_runtime_write_diag(bundle, stage="before _render_overview_tab")
    # v344 (Part 2 - memoise per-click overhead): the three non-ARC BP-Impact
    # classification passes mutate the bundle IN PLACE and are deterministic for a
    # given (date). They were re-running on EVERY Portfolio Numbers click (~1.5s of
    # fixed overhead per click, seen in the run-log as the gap between the tab timer
    # and its sub-section). Run them ONCE per date and skip on repeat clicks.
    try:
        _date_key = str(bundle.get("selected_date_label", "")) if isinstance(bundle, dict) else ""
    except Exception:
        _date_key = ""
    _already_classified = isinstance(bundle, dict) and bundle.get("_bpimpact_classified_v344") == _date_key and _date_key != ""
    if _already_classified:
        with _deep_timer(bundle, "Overview tab overhead", "BP-Impact classification (cached)", cache_hit=True):
            pass
    else:
        with _deep_timer(bundle, "Overview tab overhead", "BP-Impact classification (compute x3)", cache_hit=False):
            # v364: was 3 sequential calls (_19 -> _18 -> _17). All three names now
            # resolve to the same function, _apply_basis_impact_error_risk_
            # classification_v306_14_5 (see the alias-recreation block near the end
            # of this file) - the v306.13.17/18/19 bodies were dead code, removed in
            # v364 (see CHANGELOG.md). Calling the real function once, directly,
            # instead of the same classifier 3x under different aliases.
            bundle = _apply_basis_impact_error_risk_classification_v306_14_5(bundle)
        if isinstance(bundle, dict) and _date_key:
            bundle["_bpimpact_classified_v344"] = _date_key
    # core render
    _render_overview_tab_core(bundle, metric_view)
    # v342 Phase 1: collapse the THREE near-identical source-load diagnostic
    # renderers (v306_13_11 / _12 / _14) into ONE. Previously the loop drew three
    # identical "Diagnostic support - source load checks" expanders and re-ran the
    # same show_df work 3x on every Portfolio Numbers render - a direct contributor
    # to the slow render. The single kept renderer (v306_13_14, the most complete -
    # it reuses the _12 summary and adds ARC-aware Error Risk rows) now also folds in
    # the former "Diagnostics / support" tables and the Option B deep-timing run-log.
    try:
        _render_source_load_checks_under_portfolio_numbers_v306_13_14(bundle)
    except Exception as exc:
        if bool(globals().get("SHOW_DEBUG", False)):
            try:
                with st.expander("Diagnostic support - source load checks", expanded=False):
                    st.warning(f"Source load diagnostic render failed: {type(exc).__name__}: {exc}")
            except Exception:
                pass
    # post: er-runtime diag (after)
    _er_runtime_write_diag(bundle, stage="after _render_overview_tab")



def _portfolio_has_non_aud_cash_overlay(dar: Optional[pd.DataFrame], portfolio_row: pd.Series) -> bool:
    portfolio_code = str(portfolio_row.get("Portfolio code", "")).strip()
    if not portfolio_code:
        return False
    rows = _portfolio_detail_rows(dar, portfolio_code)
    if rows is None or rows.empty:
        return False

    text_parts = []
    for candidate in [
        find_exact_normalized_col(rows, ["Asset Name", "Security Name", "Description", "Asset Type Description", "Asset Type Name", "Holding"]),
        find_col(rows, ["Asset Name", "Security Name", "Description", "Asset Type Description", "Asset Type Name", "Holding"]),
        find_exact_normalized_col(rows, ["Currency", "Currency Code", "CCY", "Ccy"]),
        find_col(rows, ["Currency", "Currency Code", "CCY", "Ccy"]),
    ]:
        if candidate and candidate in rows.columns:
            text_parts.append(rows[candidate].astype(str))

    asset_type_code_col = find_exact_normalized_col(rows, ["Asset Type Code", "AssetTypeCode", "Driver Code", "Asset Code"]) or find_col(rows, ["Asset Type Code", "AssetTypeCode", "Driver Code", "Asset Code"])
    if asset_type_code_col and asset_type_code_col in rows.columns:
        code_series = rows[asset_type_code_col].astype(str).str.upper().str.strip()
    else:
        code_series = pd.Series([""] * len(rows), index=rows.index, dtype="object")

    combined_text = pd.Series([""] * len(rows), index=rows.index, dtype="object")
    for s in text_parts:
        combined_text = (combined_text + " | " + s.astype(str).str.upper().str.strip()).str.strip()

    has_ccy = combined_text.str.contains(r"CCY|CURRENCY", regex=True, na=False)
    has_non_aud = combined_text.str.contains(r"USD|EUR|GBP|JPY|NZD|CAD|CHF|HKD|SGD|CNH|CNY", regex=True, na=False)
    has_aud = combined_text.str.contains(r"AUD", regex=True, na=False)

    cash_like = code_series.str.startswith("ZL") | code_series.str.startswith("DS") | has_ccy | combined_text.str.contains(r"CASH", regex=True, na=False)
    non_aud_cash_like = cash_like & (has_ccy | has_non_aud) & ~has_aud
    return bool(non_aud_cash_like.any())


def _portfolio_detail_row_count_for_diagnostics(df_or_index: object, portfolio_code: str) -> int:
    """Cheap row count for portfolio detail diagnostics."""
    if not portfolio_code:
        return 0
    try:
        portkey = normalise_join_key_series(pd.Series([str(portfolio_code).strip()], dtype="object")).iloc[0]
    except Exception:
        portkey = str(portfolio_code).strip()
    if isinstance(df_or_index, dict):
        rows = df_or_index.get(str(portkey), pd.DataFrame())
        return int(len(rows)) if isinstance(rows, pd.DataFrame) else 0
    try:
        rows = _portfolio_detail_rows(df_or_index, portfolio_code)
        return int(len(rows)) if isinstance(rows, pd.DataFrame) else 0
    except Exception:
        return 0


def _build_hot_largest_tier1_driver_table(hot_df: pd.DataFrame, dat: Optional[pd.DataFrame], dar: Optional[pd.DataFrame]) -> Tuple[pd.DataFrame, pd.DataFrame]:
    assignments_df, _tier1_timing_df = _build_tier1_driver_assignments_vectorized(hot_df, dat, dar)
    if assignments_df is None or assignments_df.empty:
        return pd.DataFrame(columns=["Largest Tier 1 driver", "Row Total"]), pd.DataFrame()

    # v341: the scoped (On UNISON) frame is filtered while dat/dar/ARC companions
    # stay global, so a non-empty assignments frame can come back MISSING the
    # "Largest Tier 1 driver" or "ARC Asset Type of portfolio" columns. Guard both
    # so pd.crosstab can't raise a raw KeyError that aborts the whole section.
    if "Largest Tier 1 driver" not in assignments_df.columns:
        assignments_df = assignments_df.copy()
        assignments_df["Largest Tier 1 driver"] = "Unknown"
    if "ARC Asset Type of portfolio" not in assignments_df.columns:
        assignments_df = assignments_df.copy()
        assignments_df["ARC Asset Type of portfolio"] = "Blank / Unmapped ARC Asset Type"

    matrix = pd.crosstab(assignments_df["Largest Tier 1 driver"], assignments_df["ARC Asset Type of portfolio"], dropna=False)
    preferred_rows = ["Market Assets", "Derivatives", "FX and non AUD cash", "Liquidity / Cash (AUD only)", "Other / Events", "Unmapped", "No DAssetTypeReturn", "Unknown"]
    preferred_cols = ["Currency Overlay", "Derivative Overlay", "External UUT", "International Equity", "Blank / Unmapped ARC Asset Type"]
    ordered_rows = [r for r in preferred_rows if r in matrix.index] + [r for r in matrix.index if r not in preferred_rows]
    ordered_cols = [c for c in preferred_cols if c in matrix.columns] + [c for c in matrix.columns if c not in preferred_cols]
    matrix = matrix.reindex(index=ordered_rows, columns=ordered_cols, fill_value=0)
    matrix["Row Total"] = matrix.sum(axis=1)
    total_row = matrix.sum(axis=0).to_frame().T
    total_row.index = ["Total"]
    matrix = pd.concat([matrix, total_row], axis=0)
    matrix = matrix.reset_index().rename(columns={matrix.index.name or "index": "Largest Tier 1 driver"})
    for col in matrix.columns:
        if col != "Largest Tier 1 driver":
            matrix[col] = pd.to_numeric(matrix[col], errors="coerce").fillna(0).astype(int)
    return matrix, assignments_df


def _largest_tier1_driver_mapping_df() -> pd.DataFrame:
    return pd.DataFrame([
        {"Largest Tier 1 driver": "Market Assets", "Asset type codes and inclusion rule": "CN, FI, OS"},
        {"Largest Tier 1 driver": "Derivatives", "Asset type codes and inclusion rule": "CO, FU, PO"},
        {"Largest Tier 1 driver": "FX and non AUD cash", "Asset type codes and inclusion rule": "ZF. Also include DS and ZL where DAssetReturn indicates CCY or non-AUD cash."},
        {"Largest Tier 1 driver": "Liquidity / Cash (AUD only)", "Asset type codes and inclusion rule": "DS, ZL where DAssetReturn indicates AUD cash only."},
        {"Largest Tier 1 driver": "Other / Events", "Asset type codes and inclusion rule": "RI"},
    ])



def _render_out_portfolios_content(bundle: Dict[str, object], metric_view: str, focus: str = "all"):
    """Render outside-tolerance review content for Portfolio Numbers sub-sections."""
    portfolio_df = bundle["portfolio_df"]
    dat = bundle.get("dat")
    dar = bundle.get("dar")
    dat_source = bundle.get("dat_index") or dat
    dar_source = bundle.get("dar_index") or dar

    if portfolio_df.empty:
        st.info("No portfolio detail is available for the selected day.")
        return

    def _display_df(source_df: pd.DataFrame) -> pd.DataFrame:
        if source_df is None or source_df.empty:
            return pd.DataFrame()
        display_df = pd.DataFrame(index=source_df.index)
        display_df["Portfolio code"] = source_df.get("Portfolio code", "")
        display_df["Portfolio Name"] = source_df.get("Portfolio Name", "")
        display_df["FDV Valuation(Current Day)"] = source_df.get("FDV Valuation(Current Day) Num", pd.Series(dtype="float64")).map(_excel_currency_string)
        display_df["Benchmark Code"] = source_df.get("Benchmark Code", "")
        display_df["Benchmark Name"] = source_df.get("Benchmark Name", "")
        display_df["Status"] = source_df.get("Status", "")
        display_df["Hot / Cold"] = source_df.get("Hot / Cold", "")
        display_df["Actual Return"] = source_df.get("Actual Return Decimal", pd.Series(dtype="float64")).map(_percent_string_1dp)
        display_df["Benchmark Return"] = source_df.get("Benchmark Return Decimal", pd.Series(dtype="float64")).map(_percent_string_1dp)
        display_df["Tolerance"] = source_df.get("Tolerance Decimal", pd.Series(dtype="float64")).map(_percent_string_1dp)
        display_df["Volatility over Tolerance"] = source_df.get("Volatility over Tolerance Num", pd.Series(dtype="float64")).map(_percent_string_1dp)
        if "ARC Error Risk Ratio Decimal" in source_df.columns:
            display_df["ARC Error Risk Ratio"] = source_df["ARC Error Risk Ratio Decimal"].map(_percent_string_1dp)
        display_df["Auto Explained by Transaction Listing"] = source_df.get("Auto Explained by Transaction Listing", "")
        display_df["Transaction Listing Case Type"] = source_df.get("Transaction Listing Case Type", "")
        return display_df

    out_df = portfolio_df[portfolio_df["Within Tolerance"] == False].copy() if "Within Tolerance" in portfolio_df.columns else pd.DataFrame()
    tiny_df = portfolio_df[portfolio_df.get("mv_bucket", pd.Series(dtype="object")).astype(str) == "MV Tiny"].copy() if "mv_bucket" in portfolio_df.columns else pd.DataFrame()
    hot_subset = out_df[out_df.get("Hot / Cold", pd.Series(dtype="object")).astype(str) == "Hot"].copy() if not out_df.empty and "Hot / Cold" in out_df.columns else pd.DataFrame()
    cold_subset = out_df[out_df.get("Hot / Cold", pd.Series(dtype="object")).astype(str) == "Cold"].copy() if not out_df.empty and "Hot / Cold" in out_df.columns else pd.DataFrame()
    no_arc_subset = out_df[out_df.get("Hot / Cold", pd.Series(dtype="object")).astype(str).str.strip().isin(["No ARC match", "No BP Impact row", "No Error Risk row"])].copy() if not out_df.empty and "Hot / Cold" in out_df.columns else pd.DataFrame()

    def _render_hot_subset() -> None:
        st.markdown(f"<h5 title='{_html_safe(HOT_PORTFOLIO_TOOLTIP)}'>Hot portfolios ({int(len(hot_subset)):,})</h5>", unsafe_allow_html=True)
        if hot_subset.empty:
            st.info("No Hot portfolios for the selected day.")
            return
        _hot_tier_matrix_df, hot_tier_assignments_df = _build_hot_largest_tier1_driver_table(hot_subset, dat_source, dar_source)
        if hot_tier_assignments_df is None or hot_tier_assignments_df.empty or "Largest Tier 1 driver" not in hot_tier_assignments_df.columns:
            show_df(_display_df(hot_subset), hide_index=True)
            return
        preferred_order = ["FX and non AUD cash", "Derivatives", "Market Assets", "Liquidity / Cash (AUD only)", "Other / Events", "Unmapped", "No DAssetTypeReturn", "Unknown"]
        preferred_rank = {driver: idx for idx, driver in enumerate(preferred_order)}
        group_counts = hot_tier_assignments_df["Largest Tier 1 driver"].astype(str).fillna("Unknown").value_counts().to_dict()
        ordered_groups = sorted(
            group_counts.keys(),
            key=lambda g: (-int(group_counts.get(g, 0)), preferred_rank.get(str(g), len(preferred_order)), str(g)),
        )
        for tier_group in ordered_groups:
            tier_df = hot_tier_assignments_df[hot_tier_assignments_df["Largest Tier 1 driver"].astype(str) == str(tier_group)].copy()
            with st.expander(f"{tier_group} ({int(len(tier_df)):,})", expanded=False):
                show_df(tier_df, hide_index=True)

    def _render_simple_subset(title: str, subset: pd.DataFrame, empty_label: str, tooltip: str = "") -> None:
        if tooltip:
            st.markdown(f"<h5 title='{_html_safe(tooltip)}'>{_html_safe(title)} ({int(len(subset)):,})</h5>", unsafe_allow_html=True)
        else:
            st.markdown(f"##### {title} ({int(len(subset)):,})")
        if subset.empty:
            st.info(f"No {empty_label} portfolios for the selected day.")
            return
        show_df(_display_df(subset), hide_index=True)

    focus = str(focus or "all").strip().lower()
    if focus == "hot":
        _render_hot_subset()
        return
    if focus == "no_arc":
        _render_simple_subset("No Error Risk portfolios", no_arc_subset, "No Error Risk")
        return
    if focus == "cold":
        _render_simple_subset("Cold portfolios", cold_subset, "Cold", tooltip=COLD_PORTFOLIO_TOOLTIP)
        return

    st.markdown(f"##### Outside tolerance ({int(len(out_df)):,})")
    st.caption("Full list of portfolios outside tolerance. Use the No Error Risk, Cold portfolios and Hot portfolios sub-sections for focused review slices.")
    if out_df.empty:
        st.info("No outside tolerance portfolios for the selected day.")
    else:
        show_df(_display_df(out_df), hide_index=True)


def _render_hot_cold_tab(bundle: Dict[str, object], metric_view: str):
    _render_dashboard_section_explainer("out_portfolios")
    _render_out_portfolios_content(bundle, metric_view, focus="all")



def _render_portfolio_drillthrough_tab(bundle: Dict[str, object]):
    _render_dashboard_section_explainer("portfolio_drillthrough")
    portfolio_df = bundle["portfolio_df"]
    st.subheader("Single Portfolio Drill-through")
    if portfolio_df.empty:
        st.info("No portfolio detail is available for the selected day.")
        return

    options_df = portfolio_df[["Portfolio label", "Portfolio code"]].drop_duplicates().sort_values("Portfolio label")
    selected_label = st.selectbox("Select portfolio", options_df["Portfolio label"].tolist(), key="out_dashboard_selected_portfolio")
    selected_code = options_df.loc[options_df["Portfolio label"] == selected_label, "Portfolio code"].iloc[0]
    row = portfolio_df[portfolio_df["Portfolio code"] == selected_code].head(1)
    if row.empty:
        st.info("No portfolio detail available for the selected portfolio.")
        return
    r = row.iloc[0]

    summary_df = pd.DataFrame([
        {"Field": "Portfolio code", "Value": r.get("Portfolio code", "")},
        {"Field": "Portfolio name", "Value": r.get("Portfolio Name", "")},
        {"Field": "Status", "Value": r.get("Status", "")},
        {"Field": "Within tolerance", "Value": "Yes" if bool(r.get("Within Tolerance", False)) else "No"},
        {"Field": "MV bucket", "Value": r.get("mv_bucket", "")},
        {"Field": "Regular type", "Value": r.get("regular_type", "") or "N/A"},
        {"Field": "Benchmark code", "Value": r.get("Benchmark Code", "")},
        {"Field": "Benchmark name", "Value": r.get("Benchmark Name", "") or "Check BM Mapping"},
        {"Field": "Hot / Cold", "Value": r.get("Hot / Cold", "")},
        {"Field": "Current FDV", "Value": _excel_currency_string(r.get("FDV Valuation(Current Day) Num", pd.NA))},
        {"Field": "Actual Return", "Value": _percent_string_1dp(r.get("Actual Return Decimal", pd.NA))},
        {"Field": "Benchmark Return", "Value": _percent_string_1dp(r.get("Benchmark Return Decimal", pd.NA))},
        {"Field": "Calculated Actual v Benchmark Diff", "Value": _percent_string_1dp(r.get("Calculated Actual v Benchmark Diff Num", pd.NA))},
        {"Field": "Tolerance", "Value": _percent_string_1dp(r.get("Tolerance Decimal", pd.NA))},
        {"Field": "Volatility over Tolerance", "Value": _percent_string_1dp(r.get("Volatility over Tolerance Num", pd.NA))},
        {"Field": "Error Risk", "Value": _percent_string_1dp(r.get("ARC Error Risk Ratio Decimal", pd.NA))},
    ])
    overview_tab, detail_tab, dar_tab, txn_tab = st.tabs(["Overview", "Asset type detail", "DAssetReturn rows", "Transaction rows"])

    with overview_tab:
        st.markdown("### Overview")
        show_df(_format_auto_fx_summary_for_display(bundle, summary_df), hide_index=True)

    with detail_tab:
        dat_rows = _detail_rows_for_portfolio(bundle, "dat", "dat_index", selected_code)
        dar_rows_for_overlay = _detail_rows_for_portfolio(bundle, "dar", "dar_index", selected_code)
        st.markdown("### Asset type detail")
        if dat_rows is None or dat_rows.empty:
            st.info("No DAssetTypeReturn rows were found for the selected portfolio.")
        else:
            control = _asset_type_detail_control(dat_rows, r, dar_rows_for_overlay)
            summary_out = control.get("summary_df", pd.DataFrame())
            detail_out = control.get("detail_df", pd.DataFrame())
            diagnostic_out = control.get("diagnostic_df", pd.DataFrame())
            narrative = str(control.get("narrative", "")).strip()
            if narrative:
                st.caption(narrative)
            if isinstance(summary_out, pd.DataFrame) and not summary_out.empty:
                show_df(summary_out, hide_index=True)
            if isinstance(detail_out, pd.DataFrame) and not detail_out.empty:
                show_df(detail_out, hide_index=True)
            if isinstance(diagnostic_out, pd.DataFrame) and not diagnostic_out.empty:
                pass  # v274 auto-repair empty block left by UI removal

    with dar_tab:
        st.markdown("### DAssetReturn rows")
        dar_rows = _detail_rows_for_portfolio(bundle, "dar", "dar_index", selected_code)
        if dar_rows is None or dar_rows.empty:
            st.info("No DAssetReturn rows were found for the selected portfolio.")
        else:
            show_df(dar_rows, hide_index=True)

    with txn_tab:
        st.markdown("### Transaction rows")
        txn_source_key = "txn_eligible_df" if isinstance(bundle.get("txn_eligible_df", pd.DataFrame()), pd.DataFrame) and not bundle.get("txn_eligible_df", pd.DataFrame()).empty else "txn"
        txn_rows = _detail_rows_for_portfolio(bundle, txn_source_key, "txn_index", selected_code)
        if txn_rows is None or txn_rows.empty:
            st.info("No TransactionListing rows were found for the selected portfolio.")
        else:
            show_df(txn_rows, hide_index=True)


def _auto_fx_removal_mix(row: pd.Series) -> str:
    total = abs(float(pd.to_numeric(row.get("Total FX Removal Applied", row.get("Matched FX Excess Contribution Removed", 0.0)), errors="coerce") or 0.0))
    full = abs(float(pd.to_numeric(row.get("FX-Pure Full Excess Removed", row.get("Matched FX Full Excess Contribution Removed", 0.0)), errors="coerce") or 0.0))
    fx_only = abs(float(pd.to_numeric(row.get("Price-Bearing FX-only Removed", row.get("Matched FX-only Contribution Removed", 0.0)), errors="coerce") or 0.0))
    if total <= 1e-12:
        return "No FX removal"
    if fx_only / total >= 0.80:
        return "Mostly price-bearing FX-only"
    if full / total >= 0.80:
        return "Mostly FX-pure full excess"
    return "Mixed full-excess and FX-only"


def _prepare_auto_fx_summary_display(bundle: Dict[str, object], summary_df: pd.DataFrame) -> pd.DataFrame:
    out = _apply_tier1_driver_assignments_to_fx_summary(bundle, summary_df)
    if out is None or not isinstance(out, pd.DataFrame) or out.empty:
        return pd.DataFrame()
    out = out.copy()
    if "Portfolio" in out.columns and "Portfolio code" in out.columns:
        out = out.drop(columns=["Portfolio"])

    def _num_col(name: str, default=0.0) -> pd.Series:
        if name in out.columns:
            return pd.to_numeric(out[name], errors="coerce").fillna(default)
        return pd.Series([default] * len(out), index=out.index, dtype="float64")

    if "Price-Bearing Non-AUD Lines" not in out.columns:
        out["Price-Bearing Non-AUD Lines"] = (_num_col("FX Matched Line Count", 0).astype(int) - _num_col("FX Price Nil Line Count", 0).astype(int)).clip(lower=0)
    if "Total FX Removal Applied" not in out.columns:
        out["Total FX Removal Applied"] = _num_col("Matched FX Excess Contribution Removed")
    if "Residual Actual vs Benchmark After FX Removal" not in out.columns:
        out["Residual Actual vs Benchmark After FX Removal"] = _num_col("Remaining Actual vs Benchmark After FX Removal")
    if "FX Removal Mix" not in out.columns:
        out["FX Removal Mix"] = out.apply(_auto_fx_removal_mix, axis=1)

    if "Largest Tier 1 driver" in out.columns:
        out["Driver Portfolio Count"] = out.groupby("Largest Tier 1 driver")["Largest Tier 1 driver"].transform("size").astype(int)
        sort_cols = ["Largest Tier 1 driver"] + (["Portfolio code"] if "Portfolio code" in out.columns else [])
        out = out.sort_values(sort_cols, kind="mergesort").reset_index(drop=True)

    rename_map = {
        "FX Line Count": "Non-AUD Lines Analysed",
        "FX Matched Line Count": "Non-AUD Lines Matched to FX Rate",
        "FX Price Nil Line Count": "Price-Nil Non-AUD Lines",
        "FX Ignored Line Count": "Non-AUD Lines Excluded",
        "Compared Currency Count": "Distinct Currencies Compared",
        "Matched FX Full Excess Contribution Removed": "FX-Pure Full Excess Removed",
        "Matched FX-only Contribution Removed": "Price-Bearing FX-only Removed",
        "Matched FX Excess Contribution Removed": "Legacy Total FX Removal Amount",
                "Matched FX Dollar Difference": "Net FX $ Difference vs Independent",
        "Sum Abs FX Dollar Difference": "Gross Absolute FX $ Difference",
        "Largest Abs Line FX Dollar Difference": "Largest Line FX $ Difference",
    }
    out = out.rename(columns={k: v for k, v in rename_map.items() if k in out.columns})

    # Force line-count columns to whole-number text so Streamlit does not show 2 dp.
    count_cols = ["Driver Portfolio Count", "Non-AUD Lines Analysed", "Non-AUD Lines Matched to FX Rate", "Price-Nil Non-AUD Lines", "Price-Bearing Non-AUD Lines", "Non-AUD Lines Excluded", "Distinct Currencies Compared"]
    for col in count_cols:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0).astype(int).map(lambda v: f"{int(v):,}")

    percent_point_cols = ["Actual Portfolio Return", "Benchmark Return", "Actual vs Benchmark", "Tolerance", "Calculated Outside Tolerance", "ARC Error Risk Ratio", "FX-Pure Full Excess Removed", "Price-Bearing FX-only Removed", "Total FX Removal Applied", "Legacy Total FX Removal Amount", "Residual Actual vs Benchmark After FX Removal", "Remaining Actual vs Benchmark After FX Removal", "Remaining Outside Tolerance", "Remaining Outside ARC Error Risk"]
    dollar_cols = ["Net FX $ Difference vs Independent", "Gross Absolute FX $ Difference", "Largest Line FX $ Difference"]
    for col in percent_point_cols:
        if col in out.columns:
            out[col] = out[col].map(_format_percent_point_for_display)
    for col in dollar_cols:
        if col in out.columns:
            out[col] = out[col].map(_excel_currency_string)
    return out


def _auto_fx_section_cols(section: str) -> List[str]:
    sections = {
        "A": ["Largest Tier 1 driver", "Driver Portfolio Count", "Portfolio code", "Portfolio Name", "Auto Explained by FX", "Post FX Retest Status", "FX Removal Mix"],
        "B": ["Portfolio code", "Actual Portfolio Return", "Benchmark Return", "Actual vs Benchmark", "Tolerance", "Calculated Outside Tolerance", "ARC Error Risk Ratio", "Starting Break Basis"],
        "C": ["Portfolio code", "Non-AUD Lines Analysed", "Non-AUD Lines Matched to FX Rate", "Price-Nil Non-AUD Lines", "Price-Bearing Non-AUD Lines", "Non-AUD Lines Excluded", "Distinct Currencies Compared"],
        "D": ["Portfolio code", "FX-Pure Full Excess Removed", "Price-Bearing FX-only Removed", "Total FX Removal Applied", "Residual Actual vs Benchmark After FX Removal", "Remaining Actual vs Benchmark After FX Removal", "Remaining Outside Tolerance", "Remaining Within Tolerance", "Remaining Outside ARC Error Risk", "Remaining Within ARC Error Risk"],
        "E": ["Portfolio code", "Net FX $ Difference vs Independent", "Gross Absolute FX $ Difference", "Largest Line FX $ Difference"],
    }
    return sections.get(section, [])


def _auto_fx_section_display_df(display_df: pd.DataFrame, section_key: str) -> pd.DataFrame:
    cols = [c for c in _auto_fx_section_cols(section_key) if c in display_df.columns]
    section_df = display_df[cols].copy() if cols else pd.DataFrame()
    if section_key == "D" and not section_df.empty:
        section_df = section_df.rename(columns={
            "FX-Pure Full Excess Removed": "FX-Pure\nFull Excess\nRemoved",
            "Price-Bearing FX-only Removed": "Price-Bearing\nFX-only\nRemoved",
            "Total FX Removal Applied": "Total FX\nRemoval\nApplied",
            "Residual Actual vs Benchmark After FX Removal": "Residual\nActual vs Benchmark\nAfter FX\nRemoval",
            "Remaining Actual vs Benchmark After FX Removal": "Remaining\nActual vs Benchmark\nAfter FX\nRemoval",
            "Remaining Outside Tolerance": "Remaining\nOutside\nTolerance",
            "Remaining Within Tolerance": "Remaining\nWithin\nTolerance",
            "Remaining Outside ARC Error Risk": "Remaining\nOutside ARC\nError Risk",
            "Remaining Within ARC Error Risk": "Remaining\nWithin ARC\nError Risk",
        })
    return section_df


def _auto_fx_grouped_export_df(display_df: pd.DataFrame) -> pd.DataFrame:
    titles = {"A":"A. Hot Portfolio / outcome", "B":"B. Starting break", "C":"C. Non-AUD scope and matching", "D":"D. FX removal waterfall", "E":"E. FX dollar diagnostics"}
    frames = []
    used = set()
    for key, title in titles.items():
        cols = [c for c in _auto_fx_section_cols(key) if c in display_df.columns and c not in used]
        used.update(cols)
        if cols:
            part = display_df[cols].copy()
            part.columns = [f"{title} | {c}" for c in part.columns]
            frames.append(part)
    extras = [c for c in display_df.columns if c not in used and c not in {"Portfolio", "Price-Bearing FX-only Contribution Amount"}]
    if extras:
        part = display_df[extras].copy()
        part.columns = [f"Other / diagnostic | {c}" for c in part.columns]
        frames.append(part)
    return pd.concat(frames, axis=1) if frames else pd.DataFrame()


def _render_auto_fx_summary_sections(bundle: Dict[str, object], summary_df: pd.DataFrame) -> None:
    display_df = bundle.get("auto_fx_summary_display_df", pd.DataFrame()) if isinstance(bundle, dict) else pd.DataFrame()
    if display_df is None or not isinstance(display_df, pd.DataFrame) or display_df.empty:
        display_df = _prepare_auto_fx_summary_display(bundle, summary_df)
    if display_df.empty:
        st.info("No portfolio-level FX validation summary was produced. Check Exchange-rate diagnostics.")
        return
    prebuilt_sections = bundle.get("auto_fx_section_frames", {}) if isinstance(bundle, dict) else {}
    sections = [
        ("A. Hot Portfolio / outcome", "Portfolio explained, the driver context, and final explanation outcome.", "A"),
        ("B. Starting break", "DDetailedReturn Actual vs Benchmark is used for the FX retest. No Over/Under, calculated over/under, or line-level Excess Contribution fallback is applied.", "B"),
        ("C. Non-AUD scope and matching", "Line counts for non-AUD DAssetReturn rows considered for FX, matched to independent rates, and split between price-nil and price-bearing lines.", "C"),
        ("D. FX removal waterfall", "Full-excess removal for price-nil rows plus calculated price-bearing FX-only contribution, then the residual Actual vs Benchmark after FX removal.", "D"),
        ("E. FX dollar diagnostics", "Dollar-level independent FX comparison diagnostics for matched non-AUD lines.", "E"),
    ]
    for heading, caption, key in sections:
        st.markdown(f"##### {heading}")
        st.caption(caption)
        section_df = prebuilt_sections.get(key) if isinstance(prebuilt_sections, dict) else None
        # v306.14.8: after Auto FX is rebuilt post-Basis-Impact, prebuilt section
        # frames can be stale/empty even though the current FX summary has rows.
        # Recompute any missing or empty section from the current display_df.
        if section_df is None or not isinstance(section_df, pd.DataFrame) or section_df.empty:
            section_df = _auto_fx_section_display_df(display_df, key)
        if not section_df.empty:
            show_df(section_df, hide_index=True)
        else:
            st.caption("No rows for this section after the current Auto FX filters.")

def _render_portfolio_fx_validation_tab(bundle: Dict[str, object]):
    _render_dashboard_section_explainer("auto_fx")
    exchange_rate_bundle = bundle.get("exchange_rates", {}) if isinstance(bundle, dict) else {}
    if not isinstance(exchange_rate_bundle, dict):
        st.info("Exchange-rate bundle is not available.")
        return
    summary_df = exchange_rate_bundle.get("portfolio_fx_summary_df", pd.DataFrame())
    detail_df = exchange_rate_bundle.get("portfolio_fx_detail_df", pd.DataFrame())
    st.subheader("Auto explained by FX")
    st.caption("Compares DAssetReturn report FX Return to independent FX and aggregates the dollar difference by portfolio.")
    portfolio_summary_tab, line_detail_tab = st.tabs(["Portfolio summary", "Line detail"])
    with portfolio_summary_tab:
        if isinstance(summary_df, pd.DataFrame) and not summary_df.empty:
            _render_auto_fx_summary_sections(bundle, summary_df)
        else:
            st.info("No portfolio-level FX validation summary was produced. Check Exchange-rate diagnostics.")
    with line_detail_tab:
        if isinstance(detail_df, pd.DataFrame) and not detail_df.empty:
            portfolios = ["Select portfolio"] + sorted(detail_df.get("Portfolio", pd.Series(dtype="object")).dropna().astype(str).unique().tolist())
            selected_portfolio = st.selectbox("Portfolio", portfolios, key="portfolio_fx_validation_selected_portfolio")
            if selected_portfolio == "Select portfolio":
                st.info("Select a portfolio to view FX line detail.")
            else:
                if "Portfolio" in detail_df.columns:
                    detail_view = detail_df.loc[detail_df["Portfolio"].astype(str).eq(selected_portfolio)].copy()
                else:
                    detail_view = pd.DataFrame()
                show_df(detail_view, hide_index=True)
        else:
            st.info("No portfolio FX line detail available.")
def _control_break_audit_df_from_bundle(bundle: Dict[str, object]) -> pd.DataFrame:
    if not isinstance(bundle, dict):
        return pd.DataFrame()
    audit = bundle.get("control_break_audit_df", pd.DataFrame())
    return audit.copy() if isinstance(audit, pd.DataFrame) and not audit.empty else pd.DataFrame()


def _control_break_diagnostic_df(bundle: Dict[str, object]) -> pd.DataFrame:
    if not isinstance(bundle, dict):
        return pd.DataFrame([{"Check": "Dashboard bundle", "Result": "Missing or not a dict", "Action": "Re-run dashboard processing."}])
    audit = bundle.get("control_break_audit_df", None)
    out_payload = bundle.get("out", {}) if isinstance(bundle.get("out", {}), dict) else {}
    out_audit = out_payload.get("control_break_audit_df", None)
    portfolio_df = bundle.get("portfolio_df", pd.DataFrame())
    summary_df = bundle.get("summary_df", pd.DataFrame())
    return pd.DataFrame([
        {"Check": "APP_PYTHON_VERSION", "Result": globals().get("APP_PYTHON_VERSION", "Unknown"), "Action": "Should be v236."},
        {"Check": "CACHE_VERSION", "Result": globals().get("CACHE_VERSION", "Unknown"), "Action": "Should be v63_force_ddetailed_control_break_tab."},
        {"Check": "control_break_audit_df in dashboard bundle", "Result": "Yes" if isinstance(audit, pd.DataFrame) else "No", "Action": "If No, bundle pass-through failed."},
        {"Check": "control_break_audit_df rows in dashboard bundle", "Result": int(len(audit)) if isinstance(audit, pd.DataFrame) else 0, "Action": "If 0, check Pass 1 processing output and cache."},
        {"Check": "control_break_audit_df in raw process_day output", "Result": "Yes" if isinstance(out_audit, pd.DataFrame) else "No", "Action": "If Yes here but No above, bundle pass-through failed."},
        {"Check": "control_break_audit_df rows in raw process_day output", "Result": int(len(out_audit)) if isinstance(out_audit, pd.DataFrame) else 0, "Action": "If 0, processing is not producing the audit frame."},
        {"Check": "portfolio_df has control-break columns", "Result": "Yes" if isinstance(portfolio_df, pd.DataFrame) and ({"OUT - Control Break Flag", "Transaction-aware Control Break"} & set(portfolio_df.columns)) else "No", "Action": "If No, operational portfolio_df is still pre-control-break."},
        {"Check": "summary_df has control-break counts", "Result": "Yes" if isinstance(summary_df, pd.DataFrame) and ({"ControlBreakOutPortfolios", "DDetailedReturnOutPortfolios"} & set(summary_df.columns)) else "No", "Action": "If No, processing summary predates Pass 1 or was not passed through."},
        {"Check": "Dashboard bundle keys", "Result": ", ".join(sorted([str(k) for k in bundle.keys()]))[:500], "Action": "Should include control_break_audit_df."},
    ])




def _coerce_percent_point_numeric(value: object) -> object:
    """Coerce percent-point values without changing units.

    This is deliberately used only for canonical percent-point fields such as
    Actual Return Num / Benchmark Return Num where cached or displayed values may
    still contain a percent sign. Example: "-0.1752%" -> -0.1752.
    """
    if isinstance(value, pd.DataFrame):
        value = value.iloc[:, 0] if value.shape[1] else pd.Series(dtype="object")
    if isinstance(value, pd.Series):
        raw = value.astype(str).str.strip()
        neg = raw.str.startswith("(") & raw.str.endswith(")")
        cleaned = (
            raw.str.replace("%", "", regex=False)
               .str.replace(",", "", regex=False)
               .str.replace("(", "", regex=False)
               .str.replace(")", "", regex=False)
        )
        parsed = pd.to_numeric(cleaned, errors="coerce")
        parsed = parsed.where(~neg, -parsed.abs())
        direct = pd.to_numeric(value, errors="coerce")
        return parsed.where(parsed.notna(), direct)
    raw = "" if value is None else str(value).strip()
    neg = raw.startswith("(") and raw.endswith(")")
    cleaned = raw.replace("%", "").replace(",", "").replace("(", "").replace(")", "")
    parsed = pd.to_numeric(cleaned, errors="coerce")
    if pd.isna(parsed):
        return parsed
    return -abs(float(parsed)) if neg else float(parsed)







def _dedupe_columns_first(df: object) -> object:
    """Return a DataFrame with duplicate column labels coalesced, preserving first column order.

    Vendor extracts can contain duplicate headers. Keeping the first duplicate can be wrong when
    the first duplicate is blank and a later duplicate contains the populated value. This helper
    coalesces duplicate-labelled columns row-wise, taking the first non-blank/non-null value.
    """
    if not isinstance(df, pd.DataFrame) or not df.columns.duplicated().any():
        return df

    out = pd.DataFrame(index=df.index)
    seen = []
    for col in df.columns:
        if col in seen:
            continue
        seen.append(col)
        same = df.loc[:, df.columns == col]
        if same.shape[1] == 1:
            out[col] = same.iloc[:, 0]
            continue
        # Treat empty strings as missing for coalescing, but keep the first original column
        # if every duplicate value is blank/null for the row.
        same_for_merge = same.replace(r"^\s*$", pd.NA, regex=True)
        merged = same_for_merge.bfill(axis=1).iloc[:, 0]
        fallback = same.iloc[:, 0]
        out[col] = merged.where(merged.notna(), fallback)
    return out

def _first_series_from_columnish(value: object, index: Optional[pd.Index] = None) -> pd.Series:
    """Return a 1-D Series from a Series/DataFrame/scalar value.

    If a duplicate-column selection produces a DataFrame, coalesce across columns row-wise so
    populated later duplicates are not lost.
    """
    if isinstance(value, pd.DataFrame):
        if value.shape[1] == 0:
            return pd.Series(pd.NA, index=index if index is not None else None)
        if value.shape[1] == 1:
            s = value.iloc[:, 0]
        else:
            tmp = value.replace(r"^\s*$", pd.NA, regex=True)
            s = tmp.bfill(axis=1).iloc[:, 0]
            fallback = value.iloc[:, 0]
            s = s.where(s.notna(), fallback)
        return s.reindex(index) if index is not None and not s.index.equals(index) else s
    if isinstance(value, pd.Series):
        return value.reindex(index) if index is not None and not value.index.equals(index) else value
    if index is not None:
        return pd.Series(value, index=index)
    return pd.Series([value])


def _coerce_bool_flag_series(value: object, index: Optional[pd.Index] = None) -> pd.Series:
    """Robust bool coercion for dataframe flags that may be bool, numeric, or text.

    Avoids the pandas pitfall where Series(["False"]).astype(bool) becomes True.
    """
    s = _first_series_from_columnish(value, index=index)
    if str(getattr(s, "dtype", "")).lower() == "bool":
        return s.fillna(False).astype(bool)
    if pd.api.types.is_numeric_dtype(s):
        return pd.to_numeric(s, errors="coerce").fillna(0).ne(0)
    txt = s.astype(str).str.strip().str.upper()
    true_tokens = {"TRUE", "T", "YES", "Y", "1", "MATCH", "MATCHED"}
    return txt.isin(true_tokens)


def _cashflow_adjusted_match_flag_series(recon_df: pd.DataFrame, match_tolerance_pp: float = 0.015) -> pd.Series:
    """Single source of truth for Step 3 / unmatched panel recalculated-contribution match status.

    v284 keeps the existing function name for compatibility, but the canonical match
    basis is now DDetailedReturn Actual Return vs recalculated DAssetReturn line
    contribution, using line Variance / cashflow-adjusted portfolio denominator.
    """
    if recon_df is None or not isinstance(recon_df, pd.DataFrame) or recon_df.empty:
        return pd.Series(dtype="bool")
    for col in [
        "Diagnostic calculated contribution matches actual return",
        "Contribution matches actual return",
    ]:
        if col in recon_df.columns:
            return _coerce_bool_flag_series(recon_df[col], index=recon_df.index)

    actual = _coerce_percent_point_numeric(_first_series_from_columnish(recon_df.get("DDetailedReturn Actual Return", pd.Series(pd.NA, index=recon_df.index)), index=recon_df.index))
    calculated = _coerce_percent_point_numeric(_first_series_from_columnish(recon_df.get("Diagnostic Calculated Contribution Sum", pd.Series(pd.NA, index=recon_df.index)), index=recon_df.index))
    return (actual - calculated).abs().lt(float(match_tolerance_pp)).fillna(False)

def _coerce_money_numeric(value: object) -> object:
    """Coerce currency-like values without changing units.

    Handles numeric values, strings with commas/currency symbols, and accounting negatives like ($1,234.56).
    """
    if isinstance(value, pd.DataFrame):
        value = value.iloc[:, 0] if value.shape[1] else pd.Series(dtype="object")
    if isinstance(value, pd.Series):
        raw = value.astype(str).str.strip()
        neg = raw.str.startswith("(") & raw.str.endswith(")")
        cleaned = (
            raw.str.replace("$", "", regex=False)
               .str.replace(",", "", regex=False)
               .str.replace("(", "", regex=False)
               .str.replace(")", "", regex=False)
               .str.replace("%", "", regex=False)
        )
        parsed = pd.to_numeric(cleaned, errors="coerce")
        parsed = parsed.where(~neg, -parsed.abs())
        direct = pd.to_numeric(value, errors="coerce")
        return parsed.where(parsed.notna(), direct)
    raw = "" if value is None else str(value).strip()
    neg = raw.startswith("(") and raw.endswith(")")
    cleaned = raw.replace("$", "").replace(",", "").replace("(", "").replace(")", "").replace("%", "")
    parsed = pd.to_numeric(cleaned, errors="coerce")
    if pd.isna(parsed):
        return parsed
    return -abs(float(parsed)) if neg else float(parsed)

def _dassetreturn_calculated_contribution_detail_df(bundle: Dict[str, object], match_tolerance_pp: float = 0.015) -> pd.DataFrame:
    """Line-level DAssetReturn contribution diagnostics.

    v283 primary report-to-report reconciliation uses BNP's reported DAssetReturn
    Asset to Portfolio Contribution. This function keeps the reconstructed line
    calculation as diagnostic evidence only:
    - diagnostic contribution = line Variance / ABS(portfolio previous FDV + portfolio cashflow) * 100

    Movement fields are retained as diagnostics, but do not drive match/unmatched status.
    """
    dar = _dedupe_columns_first(bundle.get("dar", pd.DataFrame()) if isinstance(bundle, dict) else pd.DataFrame())
    portfolio_df = _dedupe_columns_first(bundle.get("portfolio_df", pd.DataFrame()) if isinstance(bundle, dict) else pd.DataFrame())
    if dar is None or not isinstance(dar, pd.DataFrame) or dar.empty:
        return pd.DataFrame()
    if portfolio_df is None or not isinstance(portfolio_df, pd.DataFrame) or portfolio_df.empty:
        return pd.DataFrame()

    dar_port_col = find_col(dar, ["Portfolio code", "Portfolio", "PortfolioCode", "portfolio", "portfolio code"])
    if not dar_port_col:
        return pd.DataFrame()

    line_asset_type_col = find_col(dar, ["Asset Type", "AssetType", "asset type"])
    line_asset_code_col = find_col(dar, ["Asset Code", "AssetCode", "asset code"])
    line_asset_name_col = find_col(dar, ["Asset Name", "AssetName", "asset name"])
    line_ccy_col = find_col(dar, ["CCY", "Currency", "currency"])
    fdv_prev_col = find_col(dar, ["FDV Valuation Prev_Day", "FDV Valuation(Previous Day)", "FDV Valuation Previous Day", "Valuation Prev_Day", "Valuation Previous Day"])
    fdv_curr_col = find_col(dar, ["FDV Valuation Curr_Day", "FDV Valuation(Current Day)", "FDV Valuation Current Day", "Valuation Curr_Day", "Valuation Current Day"])
    variance_col = find_col(dar, ["Variance", "variance", "Movement"])
    reported_contrib_col = find_col(dar, ["Asset to Portfolio Contributions", "Asset to Portfolio Contribution", "Contribution to Portfolio", "Portfolio Contribution", "Return Contribution", "Contribution %", "Contribution"])
    transactions_col = find_col(dar, ["Transactions"])
    all_transactions_col = find_col(dar, ["All Transactions", "All transactions", "AllTransactions"])
    income_col = find_col(dar, ["Income"])
    cashflow_col = find_col(dar, ["Cashflow", "Cash Flow"])

    # No synthetic fallback is used for the reported reconciliation basis. If the
    # DAssetReturn reported contribution is absent, the row cannot be matched by this basis.
    if not reported_contrib_col:
        return pd.DataFrame()

    detail = _dedupe_columns_first(dar.copy())
    detail["_pkey"] = normalise_join_key_series(detail[dar_port_col].astype(str).str.strip())
    detail["Portfolio"] = detail[dar_port_col].astype(str).str.strip()

    detail["DAssetReturn Line Previous FDV Valuation"] = _coerce_money_numeric(_first_series_from_columnish(detail[fdv_prev_col], index=detail.index)) if fdv_prev_col else pd.NA
    detail["DAssetReturn Line Current FDV Valuation"] = _coerce_money_numeric(_first_series_from_columnish(detail[fdv_curr_col], index=detail.index)) if fdv_curr_col else pd.NA
    detail["DAssetReturn Line Variance"] = _coerce_money_numeric(_first_series_from_columnish(detail[variance_col], index=detail.index)) if variance_col else pd.NA
    detail["DAssetReturn Reported Asset to Portfolio Contribution"] = _coerce_percent_point_numeric(_first_series_from_columnish(detail[reported_contrib_col], index=detail.index))
    detail["DAssetReturn Transactions"] = _coerce_money_numeric(_first_series_from_columnish(detail[transactions_col], index=detail.index)) if transactions_col else pd.NA
    detail["DAssetReturn All Transactions"] = _coerce_money_numeric(_first_series_from_columnish(detail[all_transactions_col], index=detail.index)) if all_transactions_col else pd.NA
    detail["DAssetReturn Income"] = _coerce_money_numeric(_first_series_from_columnish(detail[income_col], index=detail.index)) if income_col else pd.NA
    detail["DAssetReturn Cashflow"] = _coerce_money_numeric(_first_series_from_columnish(detail[cashflow_col], index=detail.index)) if cashflow_col else pd.NA

    # Diagnostic movement only: useful for explaining exceptions, not for primary match status.
    detail["DAssetReturn Line Movement Diagnostic"] = (
        pd.to_numeric(detail["DAssetReturn Line Current FDV Valuation"], errors="coerce")
        - pd.to_numeric(detail["DAssetReturn Line Previous FDV Valuation"], errors="coerce")
        - pd.to_numeric(detail["DAssetReturn Cashflow"], errors="coerce").fillna(0.0)
    )

    portfolio_prev_fv = detail.groupby("_pkey", dropna=False)["DAssetReturn Line Previous FDV Valuation"].sum(min_count=1)
    portfolio_cashflow = detail.groupby("_pkey", dropna=False)["DAssetReturn Cashflow"].sum(min_count=1)
    detail["DAssetReturn Portfolio Previous FDV Valuation"] = detail["_pkey"].map(portfolio_prev_fv)
    detail["DAssetReturn Portfolio Cashflow"] = detail["_pkey"].map(portfolio_cashflow).fillna(0.0)
    detail["Diagnostic Cashflow-adjusted Portfolio Denominator"] = pd.to_numeric(detail["DAssetReturn Portfolio Previous FDV Valuation"], errors="coerce") + pd.to_numeric(detail["DAssetReturn Portfolio Cashflow"], errors="coerce").fillna(0.0)

    diagnostic_denominator = pd.to_numeric(detail["Diagnostic Cashflow-adjusted Portfolio Denominator"], errors="coerce").abs()
    line_variance = pd.to_numeric(detail["DAssetReturn Line Variance"], errors="coerce")
    detail["Diagnostic Calculated Contribution - Variance / Cashflow-adjusted Denominator"] = (line_variance / diagnostic_denominator.replace(0, pd.NA)) * 100.0
    detail["Diagnostic Calculated vs Reported Difference"] = pd.to_numeric(detail["DAssetReturn Reported Asset to Portfolio Contribution"], errors="coerce") - pd.to_numeric(detail["Diagnostic Calculated Contribution - Variance / Cashflow-adjusted Denominator"], errors="coerce")
    detail["Abs Contribution Calculation Difference"] = detail["Diagnostic Calculated vs Reported Difference"].abs()
    detail["Transaction-bearing line"] = (
        detail["DAssetReturn All Transactions"].fillna(0).ne(0)
        | detail["DAssetReturn Transactions"].fillna(0).ne(0)
        | detail["DAssetReturn Income"].fillna(0).ne(0)
        | detail["DAssetReturn Cashflow"].fillna(0).ne(0)
    )

    pf = _dedupe_columns_first(portfolio_df.copy())
    pf_port_col = find_col(pf, ["Portfolio code", "Portfolio", "PortfolioCode", "portfolio", "portfolio code"])
    if pf_port_col and "Actual Return Num" in pf.columns:
        pf["_pkey"] = normalise_join_key_series(pf[pf_port_col].astype(str).str.strip())
        actual_by_key = _coerce_percent_point_numeric(pf["Actual Return Num"]).groupby(pf["_pkey"]).first()
        detail["DDetailedReturn Actual Return"] = detail["_pkey"].map(actual_by_key)

    if line_asset_type_col and line_asset_type_col in detail.columns:
        detail["Asset Type"] = detail[line_asset_type_col]
    if line_asset_code_col and line_asset_code_col in detail.columns:
        detail["Asset Code"] = detail[line_asset_code_col]
    if line_asset_name_col and line_asset_name_col in detail.columns:
        detail["Asset Name"] = detail[line_asset_name_col]
    if line_ccy_col and line_ccy_col in detail.columns:
        detail["CCY"] = detail[line_ccy_col]

    cols = [
        "Portfolio", "Asset Type", "Asset Code", "Asset Name", "CCY",
        "DAssetReturn Line Previous FDV Valuation", "DAssetReturn Line Current FDV Valuation", "DAssetReturn Line Variance",
        "DAssetReturn Line Movement Diagnostic", "DAssetReturn Portfolio Previous FDV Valuation", "DAssetReturn Portfolio Cashflow", "Diagnostic Cashflow-adjusted Portfolio Denominator",
        "DAssetReturn Reported Asset to Portfolio Contribution", "Diagnostic Calculated Contribution - Variance / Cashflow-adjusted Denominator",
        "Diagnostic Calculated vs Reported Difference", "Abs Contribution Calculation Difference",
        "DAssetReturn Transactions", "DAssetReturn All Transactions", "DAssetReturn Income", "DAssetReturn Cashflow",
        "Transaction-bearing line", "DDetailedReturn Actual Return",
    ]
    return detail[[c for c in cols if c in detail.columns]].copy()

def _render_kpi_tile(label: str, value: object, gradient: str) -> None:
    st.markdown(
        f"""
        <div style="background:{gradient};color:white;border-radius:16px;padding:0.95rem 1.05rem;min-height:108px;box-shadow:0 8px 22px rgba(15,23,42,0.12);">
            <div style="font-size:2.1rem;line-height:1;font-weight:800;margin-bottom:0.35rem;">{value}</div>
            <div style="font-size:0.9rem;opacity:0.94;">{label}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )



def _driver_col_for_breakdown(df: pd.DataFrame) -> Optional[str]:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return None
    return find_col(df, [
        "Largest Tier 1 driver", "Largest Tier 1 Break Driver", "Tier 1 driver", "Largest Driver",
        "Composition", "Top asset types",
    ])


def _portfolio_key_col(df: pd.DataFrame) -> Optional[str]:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return None
    return find_col(df, ["Portfolio", "Portfolio code", "PortfolioCode", "portfolio", "portfolio code"])


def _driver_count_frame(df: pd.DataFrame, *, portfolio_df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame(columns=["Largest Tier 1 driver", "Portfolio count"])
    work = df.copy()
    driver_col = _driver_col_for_breakdown(work)
    if driver_col is None and isinstance(portfolio_df, pd.DataFrame) and not portfolio_df.empty:
        left_col = _portfolio_key_col(work)
        right_col = _portfolio_key_col(portfolio_df)
        pf_driver_col = _driver_col_for_breakdown(portfolio_df)
        if left_col and right_col and pf_driver_col:
            join = portfolio_df[[right_col, pf_driver_col]].copy()
            join["_pkey"] = normalise_join_key_series(join[right_col].astype(str).str.strip())
            join = join[["_pkey", pf_driver_col]].drop_duplicates("_pkey")
            work["_pkey"] = normalise_join_key_series(work[left_col].astype(str).str.strip())
            work = work.merge(join, on="_pkey", how="left")
            driver_col = pf_driver_col
    if driver_col is None or driver_col not in work.columns:
        work["Largest Tier 1 driver"] = "Unclassified"
        driver_col = "Largest Tier 1 driver"
    out = (
        work.assign(**{"Largest Tier 1 driver": work[driver_col].astype(str).str.strip().replace("", "Unclassified")})
        .groupby("Largest Tier 1 driver", dropna=False)
        .size()
        .reset_index(name="Portfolio count")
        .sort_values("Portfolio count", ascending=False)
        .reset_index(drop=True)
    )
    return out.head(8)


def _render_driver_count_panel(title: str, df: pd.DataFrame) -> None:
    try:
        boxed = st.container(border=True)
    except TypeError:
        boxed = st.container()
    with boxed:
        st.markdown(f"**{title}**")
        if df is None or df.empty:
            st.caption("No portfolios")
            return
        max_count = max(1, int(pd.to_numeric(df["Portfolio count"], errors="coerce").fillna(0).max()))
        for _, r in df.iterrows():
            driver = str(r.get("Largest Tier 1 driver", "Unclassified") or "Unclassified")
            count = int(pd.to_numeric(pd.Series([r.get("Portfolio count", 0)]), errors="coerce").fillna(0).iloc[0])
            width = max(4, int(100 * count / max_count))
            st.markdown(
                f"<div style='display:flex;gap:0.5rem;align-items:center;margin:0.15rem 0;'>"
                f"<div style='width:42%;font-size:0.82rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;'>{driver}</div>"
                f"<div style='flex:1;background:#e5e7eb;border-radius:999px;height:0.7rem;'>"
                f"<div style='width:{width}%;background:#2563eb;border-radius:999px;height:0.7rem;'></div></div>"
                f"<div style='width:2.5rem;text-align:right;font-weight:600;'>{count}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )


def _render_driver_breakdown_row(portfolio_df: pd.DataFrame, auto_fx_summary_df: pd.DataFrame) -> None:
    if portfolio_df is None or not isinstance(portfolio_df, pd.DataFrame) or portfolio_df.empty:
        return

    # v304.5: sequential waterfall for driver panels.
    # HOT -> Auto explained by FX -> remaining HOT tested/countable for transactions -> unexplained.
    hot_df = portfolio_df[
        portfolio_df.get("Hot / Cold", pd.Series(dtype="object")).astype(str).str.strip().eq("Hot")
    ].copy() if "Hot / Cold" in portfolio_df.columns else pd.DataFrame()

    auto_fx_df = _portfolio_subset_from_fx_yes(portfolio_df, auto_fx_summary_df)
    fx_keys = _portfolio_keys(auto_fx_df)

    remaining_after_fx_df = hot_df.copy()
    hot_key_col = find_col(hot_df, ["Portfolio code", "Portfolio", "PortfolioCode", "portfolio", "portfolio code"])
    if hot_key_col and not hot_df.empty and fx_keys:
        remaining_after_fx_df = hot_df.copy()
        remaining_after_fx_df["_pkey"] = normalise_join_key_series(remaining_after_fx_df[hot_key_col].astype(str).str.strip())
        remaining_after_fx_df = remaining_after_fx_df[~remaining_after_fx_df["_pkey"].isin(fx_keys)].drop(columns=["_pkey"], errors="ignore").copy()

    current_account_df = remaining_after_fx_df[
        remaining_after_fx_df["Auto Explained by Transaction Listing"].astype(str).eq("Candidate")
    ].copy() if not remaining_after_fx_df.empty and "Auto Explained by Transaction Listing" in remaining_after_fx_df.columns else pd.DataFrame()

    st.markdown("#### Driver breakdown")
    st.caption("Sequential waterfall: HOT portfolios are tested for FX first; only remaining HOT portfolios are counted as transaction-listing explanations.")
    c1, c2, c3 = st.columns(3)
    with c1:
        _render_driver_count_panel("HOT portfolios", _driver_count_frame(hot_df))
    with c2:
        _render_driver_count_panel("Auto explained by FX", _driver_count_frame(auto_fx_df, portfolio_df=portfolio_df))
    with c3:
        _render_driver_count_panel("Current Account dominated", _driver_count_frame(current_account_df))

def _format_percent_point_for_display(value: object, dp: int = 2) -> str:
    num_value = pd.to_numeric(value, errors="coerce")
    if pd.isna(num_value):
        return ""
    return f"{float(num_value):,.{dp}f}%"


def _apply_tier1_driver_assignments_to_fx_summary(bundle: Dict[str, object], summary_df: pd.DataFrame) -> pd.DataFrame:
    """Replace FX-summary driver labels with the same Tier 1 assignment used by the Tier 1 Group summary."""
    if summary_df is None or not isinstance(summary_df, pd.DataFrame) or summary_df.empty or not isinstance(bundle, dict):
        return pd.DataFrame() if summary_df is None else summary_df.copy()
    portfolio_df = bundle.get("portfolio_df", pd.DataFrame())
    if portfolio_df is None or not isinstance(portfolio_df, pd.DataFrame) or portfolio_df.empty:
        return summary_df.copy()
    assignments_df = bundle.get("tier1_assignments_df", pd.DataFrame())
    if assignments_df is None or not isinstance(assignments_df, pd.DataFrame) or assignments_df.empty:
        dat_source = bundle.get("dat_index") or bundle.get("dat")
        dar_source = bundle.get("dar_index") or bundle.get("dar")
        hot_df = portfolio_df[portfolio_df.get("Hot / Cold", pd.Series(dtype="object")).astype(str).str.strip().eq("Hot")].copy() if "Hot / Cold" in portfolio_df.columns else portfolio_df.copy()
        assignments_df, _tier1_diag_df = _build_tier1_driver_assignments_vectorized(hot_df, dat_source, dar_source)
    if assignments_df is None or not isinstance(assignments_df, pd.DataFrame) or assignments_df.empty:
        return summary_df.copy()
    assign_port_col = find_col(assignments_df, ["Portfolio code", "Portfolio", "PortfolioCode", "portfolio", "portfolio code"])
    assign_driver_col = find_col(assignments_df, ["Largest Tier 1 driver", "Largest Tier 1 Break Driver"])
    summary_port_col = find_col(summary_df, ["Portfolio", "Portfolio code", "PortfolioCode", "portfolio", "portfolio code"])
    if not assign_port_col or not assign_driver_col or not summary_port_col:
        return summary_df.copy()
    mapping = assignments_df[[assign_port_col, assign_driver_col]].copy()
    mapping["_pkey"] = normalise_join_key_series(mapping[assign_port_col].astype(str).str.strip())
    mapping = mapping[["_pkey", assign_driver_col]].drop_duplicates("_pkey")
    out = summary_df.copy()
    out["_pkey"] = normalise_join_key_series(out[summary_port_col].astype(str).str.strip())
    out = out.merge(mapping, on="_pkey", how="left", suffixes=("", "_Tier1Corrected"))
    corrected_col = f"{assign_driver_col}_Tier1Corrected" if f"{assign_driver_col}_Tier1Corrected" in out.columns else assign_driver_col
    if corrected_col in out.columns:
        if "Largest Tier 1 driver" not in out.columns:
            out["Largest Tier 1 driver"] = ""
        out["Largest Tier 1 driver"] = out[corrected_col].where(out[corrected_col].astype(str).str.strip().ne(""), out["Largest Tier 1 driver"])
    return out.drop(columns=[c for c in ["_pkey", corrected_col] if c in out.columns and c != "Largest Tier 1 driver"], errors="ignore")


def _format_auto_fx_summary_for_display(bundle: Dict[str, object], df: pd.DataFrame) -> pd.DataFrame:
    out = _apply_tier1_driver_assignments_to_fx_summary(bundle, df)
    if out is None or not isinstance(out, pd.DataFrame) or out.empty:
        return pd.DataFrame()
    percent_point_cols = ["Actual vs Benchmark", "Tolerance", "Calculated Outside Tolerance", "ARC Error Risk Ratio", "Matched FX Excess Contribution Removed", "Remaining Actual vs Benchmark After FX Removal", "Remaining Outside Tolerance", "Remaining Outside ARC Error Risk"]
    dollar_cols = ["Matched FX Dollar Difference", "Sum Abs FX Dollar Difference", "Largest Abs Line FX Dollar Difference"]
    for col in percent_point_cols:
        if col in out.columns:
            out[col] = out[col].map(_format_percent_point_for_display)
    for col in dollar_cols:
        if col in out.columns:
            out[col] = out[col].map(_excel_currency_string)
    return out


def _portfolio_subset_from_fx_yes(portfolio_df: pd.DataFrame, auto_fx_summary_df: pd.DataFrame) -> pd.DataFrame:
    if portfolio_df is None or not isinstance(portfolio_df, pd.DataFrame) or portfolio_df.empty or auto_fx_summary_df is None or not isinstance(auto_fx_summary_df, pd.DataFrame) or auto_fx_summary_df.empty:
        return pd.DataFrame()
    if "Auto Explained by FX" not in auto_fx_summary_df.columns:
        return pd.DataFrame()
    fx_yes = auto_fx_summary_df[auto_fx_summary_df["Auto Explained by FX"].astype(str).str.strip().str.upper().eq("YES")].copy()
    fx_port_col = find_col(fx_yes, ["Portfolio", "Portfolio code", "PortfolioCode", "portfolio", "portfolio code"])
    port_col = find_col(portfolio_df, ["Portfolio code", "Portfolio", "PortfolioCode", "portfolio", "portfolio code"])
    if fx_yes.empty or fx_port_col is None or port_col is None:
        return pd.DataFrame()
    wanted = set(normalise_join_key_series(fx_yes[fx_port_col].astype(str).str.strip()).dropna().tolist())
    work = _dedupe_columns_first(portfolio_df.copy())
    work["_pkey"] = normalise_join_key_series(work[port_col].astype(str).str.strip())
    return work[work["_pkey"].isin(wanted)].drop(columns=["_pkey"]).copy()


def _portfolio_keys(df: pd.DataFrame) -> set:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return set()
    col = find_col(df, ["Portfolio code", "Portfolio", "PortfolioCode", "portfolio", "portfolio code"])
    if col is None:
        return set()
    return set(normalise_join_key_series(df[col].astype(str).str.strip()).dropna().tolist())





def _current_account_empty_analysis() -> pd.DataFrame:
    return pd.DataFrame(columns=[
        "Portfolio code", "Portfolio Name", "DDetailed Current FDV", "Current Account ZL01 Current FDV",
        "% Current Account", "Current Account threshold %", "Current Account dominated?",
        "Current Account ZL01 row count", "Current Account dominance note",
    ])


def _attach_current_account_dominance_metrics(portfolio_df: pd.DataFrame, dar_source: object, threshold_pct: float) -> pd.DataFrame:
    """Attach Current Account dominance metrics to portfolio_df.

    Numerator: sum of DAssetReturn current FDV where Asset Type Code is exactly ZL01.
    Denominator: DDetailedReturn portfolio current FDV market value from portfolio_df.
    The ratio uses absolute values so the dominance test measures concentration rather than accounting sign.
    """
    if portfolio_df is None or not isinstance(portfolio_df, pd.DataFrame) or portfolio_df.empty:
        return pd.DataFrame() if portfolio_df is None else portfolio_df
    out = portfolio_df.copy()
    try:
        threshold_pct = float(threshold_pct)
    except Exception:
        threshold_pct = float(DEFAULT_CURRENT_ACCOUNT_DOMINANCE_THRESHOLD_PCT)
    threshold_pct = max(0.0, min(100.0, threshold_pct))
    port_col = find_col(out, ["Portfolio code", "Portfolio", "PortfolioCode", "portfolio", "portfolio code"])
    if not port_col:
        out["DDetailed Current FDV"] = float("nan")
        out["Current Account ZL01 Current FDV"] = 0.0
        out["% Current Account"] = float("nan")
        out["Current Account threshold %"] = threshold_pct
        out["Current Account dominated?"] = "No"
        out["Current Account ZL01 row count"] = 0
        out["Current Account dominance note"] = "Portfolio code column not found"
        return out

    dd_current_col = "FDV Valuation(Current Day) Num" if "FDV Valuation(Current Day) Num" in out.columns else resolve_fdv_current_value_col(out)
    if dd_current_col and dd_current_col in out.columns:
        out["DDetailed Current FDV"] = num(out, dd_current_col)
    else:
        out["DDetailed Current FDV"] = float("nan")

    wanted_df = out[[port_col]].copy()
    wanted_df["_pkey"] = normalise_join_key_series(wanted_df[port_col].astype(str).str.strip())
    wanted_keys = set(wanted_df["_pkey"].replace("", pd.NA).dropna().astype(str).tolist())
    dar_rows = _frame_for_portfolio_subset(dar_source, out)
    detail_summary = pd.DataFrame(columns=["_pkey", "Current Account ZL01 Current FDV", "Current Account ZL01 row count"])
    note = ""
    if dar_rows is None or not isinstance(dar_rows, pd.DataFrame) or dar_rows.empty:
        note = "No DAssetReturn rows available"
    else:
        dar_port_col = find_col(dar_rows, ["Portfolio code", "Portfolio", "PortfolioCode", "portfolio", "portfolio code"])
        asset_type_col = _resolve_asset_type_driver_code_col(dar_rows)
        dar_current_col = find_col(dar_rows, [
            "FDV Valuation Curr_Day", "FDV Valuation Curr Day", "FDV Valuation(Current Day)",
            "FDV Valuation Current Day", "FDVCurrentDayValuation", "FDVCurrentValuation",
            "Current FDV", "Current Market Value", "Market Value", "Current Value", "FDV Current Value",
        ]) or resolve_fdv_current_value_col(dar_rows)
        if not dar_port_col:
            note = "DAssetReturn portfolio column not found"
        elif not asset_type_col:
            note = "DAssetReturn Asset Type Code column not found"
        elif not dar_current_col:
            note = "DAssetReturn current FDV column not found"
        else:
            work = dar_rows[[dar_port_col, asset_type_col, dar_current_col]].copy()
            work["_pkey"] = normalise_join_key_series(work[dar_port_col].astype(str).str.strip())
            work = work[work["_pkey"].isin(wanted_keys)].copy()
            work["_asset_type_code"] = work[asset_type_col].astype(str).str.strip().str.upper()
            work = work[work["_asset_type_code"].eq(CURRENT_ACCOUNT_ASSET_TYPE_CODE)].copy()
            if not work.empty:
                work["_current_fdv_num"] = num(work, dar_current_col)
                detail_summary = (
                    work.groupby("_pkey", dropna=False)
                    .agg(**{
                        "Current Account ZL01 Current FDV": ("_current_fdv_num", "sum"),
                        "Current Account ZL01 row count": ("_current_fdv_num", "count"),
                    })
                    .reset_index()
                )
            note = "Calculated from DAssetReturn ZL01 current FDV"

    out["_pkey"] = normalise_join_key_series(out[port_col].astype(str).str.strip())
    out = out.merge(detail_summary, on="_pkey", how="left")
    out["Current Account ZL01 Current FDV"] = pd.to_numeric(out.get("Current Account ZL01 Current FDV", 0.0), errors="coerce").fillna(0.0)
    out["Current Account ZL01 row count"] = pd.to_numeric(out.get("Current Account ZL01 row count", 0), errors="coerce").fillna(0).astype(int)
    denom = pd.to_numeric(out["DDetailed Current FDV"], errors="coerce").abs()
    numerator = pd.to_numeric(out["Current Account ZL01 Current FDV"], errors="coerce").abs()
    out["% Current Account"] = (numerator / denom.replace({0.0: pd.NA})) * 100.0
    out["Current Account threshold %"] = threshold_pct
    out["Current Account dominated?"] = out["% Current Account"].ge(threshold_pct).map({True: "Yes", False: "No"})
    missing_denom = denom.isna() | denom.le(0)
    out.loc[missing_denom, "Current Account dominated?"] = "No"
    out["Current Account dominance note"] = note
    out.loc[missing_denom, "Current Account dominance note"] = "DDetailedReturn current FDV is blank or zero"
    return out.drop(columns=["_pkey"], errors="ignore")


def _current_account_dominated_subset(remaining_hot_df: pd.DataFrame) -> pd.DataFrame:
    if remaining_hot_df is None or not isinstance(remaining_hot_df, pd.DataFrame) or remaining_hot_df.empty:
        return pd.DataFrame()
    if "Current Account dominated?" not in remaining_hot_df.columns:
        return pd.DataFrame()
    return remaining_hot_df[remaining_hot_df["Current Account dominated?"].astype(str).str.strip().str.upper().eq("YES")].copy()

def _nil_actual_return_subset(remaining_hot_df: pd.DataFrame) -> pd.DataFrame:
    """Return remaining HOT portfolios where Actual Return is zero/nil and Benchmark Return is non-zero.

    Waterfall position: after Auto FX and before Current Account dominated.
    Classification rule:
    - Remaining HOT after FX
    - DDetailedReturn Actual Return is zero/nil
    - DDetailedReturn Benchmark Return is non-zero
    """
    if remaining_hot_df is None or not isinstance(remaining_hot_df, pd.DataFrame) or remaining_hot_df.empty:
        return pd.DataFrame()
    actual_col = find_col(remaining_hot_df, ["Actual Return", "actual return"])
    benchmark_col = find_col(remaining_hot_df, ["Benchmark Return", "benchmark return"])
    if actual_col is None or benchmark_col is None:
        return pd.DataFrame()
    work = remaining_hot_df.copy()
    actual_raw = work[actual_col]
    benchmark_raw = work[benchmark_col]
    actual_num = actual_raw.map(_coerce_percent_point_numeric)
    benchmark_num = benchmark_raw.map(_coerce_percent_point_numeric)
    actual_text = actual_raw.astype(str).str.strip().str.upper()
    nil_text_tokens = {"", "NIL", "NULL", "NONE", "NAN", "NA", "N/A", "#N/A", "-"}
    actual_is_zero_or_nil = (
        actual_num.abs().le(float(NIL_ACTUAL_RETURN_ZERO_TOLERANCE_PP)).fillna(False)
        | actual_text.isin(nil_text_tokens)
    )
    benchmark_is_non_zero = benchmark_num.notna() & benchmark_num.abs().gt(float(NIL_ACTUAL_RETURN_ZERO_TOLERANCE_PP))
    out = work[actual_is_zero_or_nil & benchmark_is_non_zero].copy()
    if out.empty:
        return out
    out["Nil actual return reason"] = NIL_ACTUAL_RETURN_REASON
    out["Nil actual return Actual Return source"] = actual_raw.reindex(out.index)
    out["Nil actual return Benchmark Return source"] = benchmark_raw.reindex(out.index)
    return out


def _hot_resolution_sets(bundle: Dict[str, object], auto_fx_summary_df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return HOT population split sequentially into Auto FX, Nil actual return, Current Account dominated, and Unexplained.

    v306.8.0 waterfall rule:
    1. Start with all HOT portfolios.
    2. Remove portfolios auto explained by FX.
    3. Classify remaining HOT portfolios as Nil actual return where Actual Return is zero/nil and Benchmark Return is non-zero.
    4. Classify remaining HOT portfolios as Current Account dominated where DAssetReturn ZL01 current FDV / DDetailedReturn current FDV meets the sidebar threshold.
    5. Unexplained is the residual after FX, Nil actual return, and Current Account dominated rules.
    """
    portfolio_df = _dedupe_columns_first(bundle.get("portfolio_df", pd.DataFrame()) if isinstance(bundle, dict) else pd.DataFrame())
    if portfolio_df is None or not isinstance(portfolio_df, pd.DataFrame) or portfolio_df.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    hot_df = portfolio_df[
        portfolio_df.get("Hot / Cold", pd.Series(dtype="object")).astype(str).str.strip().eq("Hot")
    ].copy() if "Hot / Cold" in portfolio_df.columns else pd.DataFrame()

    auto_fx_df = _portfolio_subset_from_fx_yes(portfolio_df, auto_fx_summary_df)
    fx_keys = _portfolio_keys(auto_fx_df)

    remaining_after_fx_df = pd.DataFrame()
    hot_key_col = find_col(hot_df, ["Portfolio code", "Portfolio", "PortfolioCode", "portfolio", "portfolio code"])
    if hot_key_col and not hot_df.empty:
        tmp = hot_df.copy()
        tmp["_pkey"] = normalise_join_key_series(tmp[hot_key_col].astype(str).str.strip())
        remaining_after_fx_df = tmp[~tmp["_pkey"].isin(fx_keys)].drop(columns=["_pkey"], errors="ignore").copy()

    nil_actual_return_df = _nil_actual_return_subset(remaining_after_fx_df)
    nil_keys = _portfolio_keys(nil_actual_return_df)

    remaining_after_nil_df = pd.DataFrame()
    remaining_key_col = find_col(remaining_after_fx_df, ["Portfolio code", "Portfolio", "PortfolioCode", "portfolio", "portfolio code"])
    if remaining_key_col and not remaining_after_fx_df.empty:
        tmp = remaining_after_fx_df.copy()
        tmp["_pkey"] = normalise_join_key_series(tmp[remaining_key_col].astype(str).str.strip())
        remaining_after_nil_df = tmp[~tmp["_pkey"].isin(nil_keys)].drop(columns=["_pkey"], errors="ignore").copy()

    current_account_df = _current_account_dominated_subset(remaining_after_nil_df)
    current_account_keys = _portfolio_keys(current_account_df)

    unexplained_df = pd.DataFrame()
    remaining_nil_key_col = find_col(remaining_after_nil_df, ["Portfolio code", "Portfolio", "PortfolioCode", "portfolio", "portfolio code"])
    if remaining_nil_key_col and not remaining_after_nil_df.empty:
        tmp = remaining_after_nil_df.copy()
        tmp["_pkey"] = normalise_join_key_series(tmp[remaining_nil_key_col].astype(str).str.strip())
        unexplained_df = tmp[~tmp["_pkey"].isin(current_account_keys)].drop(columns=["_pkey"], errors="ignore").copy()

    return hot_df, auto_fx_df, nil_actual_return_df, current_account_df, unexplained_df


def _driver_lines_html(df: pd.DataFrame, max_rows: int = 4) -> str:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return "<div style='font-size:0.76rem;opacity:0.9;margin-top:0.35rem;'>No portfolios</div>"
    rows = []
    for _, r in df.head(max_rows).iterrows():
        driver = str(r.get("Largest Tier 1 driver", "Unclassified") or "Unclassified")
        count = int(pd.to_numeric(pd.Series([r.get("Portfolio count", 0)]), errors="coerce").fillna(0).iloc[0])
        rows.append(
            f"<div style='display:flex;justify-content:space-between;gap:8px;margin:3px 0;font-size:0.75rem;'>"
            f"<span style='white-space:nowrap;overflow:hidden;text-overflow:ellipsis;'>{driver}</span><b>{count}</b></div>"
        )
    return "".join(rows)


def _render_nil_actual_return_tab(bundle: Dict[str, object], auto_fx_summary_df: pd.DataFrame) -> None:
    """Render Nil actual return HOT population using the same Tier 1 drilldown pattern as Unexplained."""
    st.subheader("Nil actual return")
    _render_dashboard_section_explainer("nil_actual_return")
    dat_source = bundle.get("dat_index") or bundle.get("dat") if isinstance(bundle, dict) else pd.DataFrame()
    dar_source = bundle.get("dar_index") or bundle.get("dar") if isinstance(bundle, dict) else pd.DataFrame()
    _hot_df, _auto_fx_df, nil_actual_return_df, _current_account_df, _unexplained_df = _hot_resolution_sets(bundle, auto_fx_summary_df)
    shared_assignments_df = bundle.get("tier1_assignments_df", pd.DataFrame()) if isinstance(bundle, dict) else pd.DataFrame()

    st.markdown(f"##### Nil actual return portfolio summary ({len(nil_actual_return_df):,})")
    if nil_actual_return_df.empty:
        st.info("No remaining HOT portfolios met the Nil actual return rule after Auto FX removal.")
    else:
        cols = [
            "Largest Tier 1 driver", "Portfolio code", "Portfolio Name", "Actual Return", "Benchmark Return",
            "Actual vs Benchmark", "Tolerance", "Hot / Cold", "Nil actual return reason",
        ]
        display = nil_actual_return_df[[c for c in cols if c in nil_actual_return_df.columns]].copy()
        if display.empty:
            display = nil_actual_return_df.copy()
        show_df(display, hide_index=True)

    st.caption("Driver note: `No DAssetTypeReturn` means the shared Tier 1 driver assignment did not find usable DAssetTypeReturn contribution rows for the portfolio, so it cannot allocate the portfolio to Market Assets, FX, Derivatives or Cash from DAssetTypeReturn. The Nil actual return classification itself is still driven only by Actual Return being zero/nil and Benchmark Return being non-zero after Auto FX removal.")

    if nil_actual_return_df.empty:
        return

    if isinstance(shared_assignments_df, pd.DataFrame) and not shared_assignments_df.empty:
        tier_count_df = _tier1_count_frame_from_assignments(nil_actual_return_df, shared_assignments_df)
        tier_matrix_df = tier_count_df.rename(columns={"Portfolio count": "Row Total"})
        subset_keys = _portfolio_keys(nil_actual_return_df)
        assign_port_col = find_col(shared_assignments_df, ["Portfolio code", "Portfolio", "PortfolioCode", "portfolio", "portfolio code"])
        if assign_port_col:
            tier_assignments_df = shared_assignments_df.copy()
            tier_assignments_df["_pkey"] = normalise_join_key_series(tier_assignments_df[assign_port_col].astype(str).str.strip())
            tier_assignments_df = tier_assignments_df[tier_assignments_df["_pkey"].isin(subset_keys)].copy()
            nil_cols = [c for c in ["Portfolio code", "Portfolio Name", "Actual Return", "Benchmark Return", "Actual vs Benchmark", "Tolerance", "Nil actual return reason"] if c in nil_actual_return_df.columns]
            nil_join_col = find_col(nil_actual_return_df, ["Portfolio code", "Portfolio", "PortfolioCode", "portfolio", "portfolio code"])
            if nil_join_col and nil_cols:
                nil_details = nil_actual_return_df[[nil_join_col] + [c for c in nil_cols if c != nil_join_col]].copy()
                nil_details["_pkey"] = normalise_join_key_series(nil_details[nil_join_col].astype(str).str.strip())
                tier_assignments_df = tier_assignments_df.merge(nil_details.drop_duplicates("_pkey"), on="_pkey", how="left", suffixes=("", "_Nil"))
                tier_assignments_df = tier_assignments_df.drop(columns=["_pkey"], errors="ignore")
        else:
            tier_assignments_df = pd.DataFrame()
    else:
        tier_matrix_df, tier_assignments_df = _build_hot_largest_tier1_driver_table(nil_actual_return_df, dat_source, dar_source)


    if tier_assignments_df is not None and isinstance(tier_assignments_df, pd.DataFrame) and not tier_assignments_df.empty and "Largest Tier 1 driver" in tier_assignments_df.columns:
        for driver, group in tier_assignments_df.groupby("Largest Tier 1 driver", dropna=False):
            with st.expander(f"{driver} ({len(group):,})", expanded=False):
                show_df(group, hide_index=True)



def _subset_source_rows_for_portfolios(source: object, portfolio_subset_df: pd.DataFrame, *, source_name: str = "") -> pd.DataFrame:
    """Return all source rows whose portfolio belongs to the supplied portfolio subset.

    Supports either the full source dataframe or the deferred per-portfolio detail index
    introduced for faster dashboard navigation. This is intentionally read-only/display-only:
    it does not alter the HOT waterfall classification logic.
    """
    keys = _portfolio_keys(portfolio_subset_df)
    if not keys:
        return pd.DataFrame()

    frames: List[pd.DataFrame] = []
    if isinstance(source, dict):
        for key in sorted(keys):
            df = source.get(key)
            if isinstance(df, pd.DataFrame) and not df.empty:
                frames.append(df.copy())
        if not frames:
            return pd.DataFrame()
        out = pd.concat(frames, ignore_index=True, sort=False)
    elif isinstance(source, pd.DataFrame) and not source.empty:
        port_col = find_col(source, ["Portfolio code", "Portfolio", "PortfolioCode", "portfolio", "portfolio code"])
        if port_col is None or port_col not in source.columns:
            return pd.DataFrame()
        tmp = source.copy()
        tmp["_pkey"] = normalise_join_key_series(tmp[port_col].astype(str).str.strip())
        out = tmp[tmp["_pkey"].isin(keys)].drop(columns=["_pkey"], errors="ignore").copy()
    else:
        return pd.DataFrame()

    if out.empty:
        return out

    port_col = find_col(out, ["Portfolio code", "Portfolio", "PortfolioCode", "portfolio", "portfolio code"])
    if port_col and port_col in out.columns:
        ordered = [port_col] + [c for c in out.columns if c != port_col]
        out = out[ordered].copy()

    out = out.loc[:, ~pd.Index(out.columns).duplicated()].copy()
    return out.reset_index(drop=True)


def _sort_unexplained_dasset_rows_for_review(df: pd.DataFrame) -> pd.DataFrame:
    """Sort DAssetReturn rows by the largest available contribution-style field."""
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame()
    out = df.copy()
    sort_candidates = [
        "Asset to Portfolio Contributions",
        "Excess Contribution",
        "Trust Contribution",
        "Benchmark Contribution",
        "Actual Return",
        "Return Deviation",
    ]
    sort_col = find_col(out, sort_candidates)
    if sort_col and sort_col in out.columns:
        out["_abs_review_sort"] = num(out, sort_col).abs()
        port_col = find_col(out, ["Portfolio code", "Portfolio", "PortfolioCode", "portfolio", "portfolio code"])
        sort_by = ([port_col] if port_col else []) + ["_abs_review_sort"]
        ascending = ([True] if port_col else []) + [False]
        out = out.sort_values(sort_by, ascending=ascending, na_position="last").drop(columns=["_abs_review_sort"], errors="ignore")
    return out.reset_index(drop=True)


def _sort_unexplained_transaction_rows_for_review(df: pd.DataFrame) -> pd.DataFrame:
    """Sort TransactionListing rows by portfolio then largest net-consideration-style field."""
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return pd.DataFrame()
    out = df.copy()
    sort_col = find_col(out, ["NetConsideration", "LocalNetConsideration", "CapitalProceeds", "HistoricalCost"])
    port_col = find_col(out, ["Portfolio code", "PortfolioCode", "Portfolio", "portfolio", "portfolio code"])
    if sort_col and sort_col in out.columns:
        out["_abs_review_sort"] = num(out, sort_col).abs()
        sort_by = ([port_col] if port_col else []) + ["_abs_review_sort"]
        ascending = ([True] if port_col else []) + [False]
        out = out.sort_values(sort_by, ascending=ascending, na_position="last").drop(columns=["_abs_review_sort"], errors="ignore")
    return out.reset_index(drop=True)


def _render_unexplained_source_row_sections(bundle: Dict[str, object], unexplained_df: pd.DataFrame) -> None:
    """Render full source-row extracts for all unexplained portfolios.

    These two extracts are deliberately broad so reviewers can analyse common holdings
    and common transaction patterns across the whole residual unexplained population.
    """
    if unexplained_df is None or not isinstance(unexplained_df, pd.DataFrame) or unexplained_df.empty:
        return

    dar_source = bundle.get("dar_index") or bundle.get("dar") if isinstance(bundle, dict) else pd.DataFrame()
    txn_source = pd.DataFrame()
    if isinstance(bundle, dict):
        txn_source = bundle.get("txn_eligible_df", pd.DataFrame())
        if txn_source is None or not isinstance(txn_source, pd.DataFrame) or txn_source.empty:
            txn_source = bundle.get("txn_index") or bundle.get("txn")

    all_dasset_rows_df = _sort_unexplained_dasset_rows_for_review(
        _subset_source_rows_for_portfolios(dar_source, unexplained_df, source_name="DAssetReturn")
    )
    all_transaction_rows_df = _sort_unexplained_transaction_rows_for_review(
        _subset_source_rows_for_portfolios(txn_source, unexplained_df, source_name="TransactionListing")
    )

    with st.expander(f"All DAssetReturn rows for unexplained portfolios ({len(all_dasset_rows_df):,})", expanded=False):
        st.caption("Complete DAssetReturn row extract for the residual unexplained portfolio population. Use this to identify common holdings, recurring asset codes, contribution concentration and repeated driver patterns across unexplained portfolios.")
        if all_dasset_rows_df.empty:
            st.info("No DAssetReturn rows matched the unexplained portfolio population.")
        else:
            show_df(all_dasset_rows_df, hide_index=True)
            st.download_button(
                "Download unexplained DAssetReturn rows CSV",
                data=all_dasset_rows_df.to_csv(index=False).encode("utf-8-sig"),
                file_name="unexplained_all_dassetreturn_rows.csv",
                mime="text/csv",
                key="download_unexplained_all_dassetreturn_rows_csv",
            )

    with st.expander(f"All transaction rows for unexplained portfolios ({len(all_transaction_rows_df):,})", expanded=False):
        st.caption("Complete TransactionListing row extract for the residual unexplained portfolio population. Where the eligibility-prepared transaction table is available, the extract includes the control-break eligibility columns.")
        if all_transaction_rows_df.empty:
            st.info("No TransactionListing rows matched the unexplained portfolio population.")
        else:
            show_df(all_transaction_rows_df, hide_index=True)
            st.download_button(
                "Download unexplained transaction rows CSV",
                data=all_transaction_rows_df.to_csv(index=False).encode("utf-8-sig"),
                file_name="unexplained_all_transaction_rows.csv",
                mime="text/csv",
                key="download_unexplained_all_transaction_rows_csv",
            )


def _minval_empty_outputs() -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    summary_cols = [
        "Portfolio code", "Portfolio Name", "ARC Asset Type of portfolio", "Benchmark Code", "Benchmark Name",
        "Actual Return", "Benchmark Return", "Actual vs Benchmark", "Validation Direction",
        "ARC / threshold", "Threshold Source", "Same-direction candidate rows",
        "Minimum validation rows", "Selected contribution total", "Residual after selected rows",
        "Direction threshold met", "Selected Asset Codes",
        "Selected Asset Names", "Minimum validation status", "Starting Break Source",
    ]
    candidate_cols = [
        "Portfolio code", "Portfolio Name", "Validation Direction", "Starting Actual vs Benchmark",
        "ARC / threshold", "Threshold Source", "Candidate Rank", "Asset Code", "Asset Name",
        "Asset Type", "CCY", "Asset to Portfolio Contribution", "Abs Contribution",
        "Cumulative selected contribution", "Residual after this row", "Direction threshold met after this row",
        "Is minimum selected row", "Is additional same-direction row", "Residual overshoot diagnostic removed",
    ]
    diagnostic_cols = ["Check", "Result", "Detail"]
    return pd.DataFrame(columns=summary_cols), pd.DataFrame(columns=candidate_cols), pd.DataFrame(columns=diagnostic_cols)


def _minval_num(value: object) -> float:
    try:
        out = _coerce_percent_point_numeric(value)
        return float(out) if pd.notna(out) else float("nan")
    except Exception:
        try:
            return float(pd.to_numeric(value, errors="coerce"))
        except Exception:
            return float("nan")


def _minval_first_numeric(row: pd.Series, candidates: List[str]) -> Tuple[float, str]:
    for col in candidates:
        if col in row.index:
            val = _minval_num(row.get(col, pd.NA))
            if pd.notna(val):
                return float(val), col
    return float("nan"), ""


def _minval_direction(value: float) -> Tuple[int, str]:
    if pd.isna(value) or abs(float(value)) <= 1e-12:
        return 0, "Flat"
    return (1, "Positive") if float(value) > 0 else (-1, "Negative")


def _minval_threshold(row: pd.Series) -> Tuple[float, str]:
    return _minval_first_numeric(row, [
        "ARC Error Risk Ratio Pct", "ARC Error Risk Ratio", "ARC Error Risk Ratio Raw", "Tolerance Num", "Tolerance"
    ])


def build_unexplained_minimum_validation_sets(unexplained_df: pd.DataFrame, dar_source: object) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """v306.7.0 diagnostic engine for minimum same-direction validation rows.

    For each unexplained portfolio, rank DAssetReturn Asset to Portfolio Contributions
    that have the same sign as Actual vs Benchmark. Select the smallest ranked prefix
    that would bring the residual break within ARC Error Risk / fallback threshold.
    """
    empty_summary, empty_candidates, empty_diag = _minval_empty_outputs()
    diag_rows: List[Dict[str, object]] = []
    if unexplained_df is None or not isinstance(unexplained_df, pd.DataFrame) or unexplained_df.empty:
        return empty_summary, empty_candidates, pd.DataFrame([{"Check":"Input unexplained portfolios","Result":0,"Detail":"No unexplained portfolios supplied."}], columns=empty_diag.columns)
    port_col = find_col(unexplained_df, ["Portfolio code", "Portfolio", "PortfolioCode", "portfolio", "portfolio code"])
    if not port_col:
        return empty_summary, empty_candidates, pd.DataFrame([{"Check":"Portfolio column","Result":"Missing","Detail":"Cannot build minimum validation sets without a portfolio column."}], columns=empty_diag.columns)

    all_dar_rows = _subset_source_rows_for_portfolios(dar_source, unexplained_df, source_name="DAssetReturn")
    if all_dar_rows is None or not isinstance(all_dar_rows, pd.DataFrame) or all_dar_rows.empty:
        return empty_summary, empty_candidates, pd.DataFrame([{"Check":"DAssetReturn rows","Result":0,"Detail":"No DAssetReturn rows matched the unexplained population."}], columns=empty_diag.columns)

    dar_port_col = find_col(all_dar_rows, ["Portfolio", "Portfolio code", "PortfolioCode", "portfolio", "portfolio code"])
    contrib_col = find_col(all_dar_rows, ["Asset to Portfolio Contributions", "Asset to Portfolio Contribution", "AssetToPortfolioContributions"])
    asset_code_col = find_col(all_dar_rows, ["Asset Code", "AssetCode", "Security Code"])
    asset_name_col = find_col(all_dar_rows, ["Asset Name", "AssetName", "SecurityLongName", "Security Name", "Security Description"])
    asset_type_col = find_col(all_dar_rows, ["Asset Type description", "Asset Type Description", "Asset Type", "AssetTypeDescription"])
    ccy_col = find_col(all_dar_rows, ["CCY", "Currency", "LocalCurrency"])
    diag_rows.extend([
        {"Check":"Input unexplained portfolios","Result":int(len(unexplained_df)),"Detail":"Residual HOT portfolios after existing auto rules."},
        {"Check":"Matched DAssetReturn rows","Result":int(len(all_dar_rows)),"Detail":"Rows available for same-direction contribution ranking."},
        {"Check":"Resolved DAssetReturn portfolio column","Result":dar_port_col or "Missing","Detail":"Used to join rows to unexplained portfolios."},
        {"Check":"Resolved contribution column","Result":contrib_col or "Missing","Detail":"Expected Asset to Portfolio Contributions."},
    ])
    if not dar_port_col or not contrib_col:
        return empty_summary, empty_candidates, pd.DataFrame(diag_rows, columns=empty_diag.columns)

    dar_work = all_dar_rows.copy()
    dar_work["_pkey"] = normalise_join_key_series(dar_work[dar_port_col].astype(str).str.strip())
    dar_work["_contribution_num"] = num(dar_work, contrib_col)
    dar_work = dar_work[dar_work["_pkey"].astype(str).str.strip().ne("")].copy()

    unexplained_work = unexplained_df.copy()
    unexplained_work["_pkey"] = normalise_join_key_series(unexplained_work[port_col].astype(str).str.strip())
    unexplained_work = unexplained_work[unexplained_work["_pkey"].astype(str).str.strip().ne("")].drop_duplicates("_pkey", keep="first")
    summary_rows: List[Dict[str, object]] = []
    candidate_rows: List[Dict[str, object]] = []

    for _, prow in unexplained_work.iterrows():
        portkey = str(prow.get("_pkey", "")).strip()
        portfolio_code = str(prow.get(port_col, portkey)).strip()
        portfolio_name = str(prow.get("Portfolio Name", "")).strip()
        start_break, start_source = _minval_first_numeric(prow, ["Actual vs Benchmark Num", "Calculated Actual v Benchmark Diff Num", "Actual vs Benchmark", "Calculated over/under", "Over/Under Num"])
        threshold, threshold_source = _minval_threshold(prow)
        direction_sign, direction_label = _minval_direction(start_break)
        rows = dar_work[dar_work["_pkey"].astype(str).eq(portkey)].copy()
        rows = rows[pd.notna(rows["_contribution_num"]) & rows["_contribution_num"].ne(0)].copy()
        if direction_sign:
            rows["_direction"] = rows["_contribution_num"].map(lambda x: 1 if x > 0 else -1 if x < 0 else 0)
            same = rows[rows["_direction"].eq(direction_sign)].copy()
        else:
            same = rows.iloc[0:0].copy()
        same["_abs_contribution_num"] = same["_contribution_num"].abs()
        same = same.sort_values("_abs_contribution_num", ascending=False, na_position="last").reset_index(drop=True)

        selected_count = 0
        cumulative = 0.0
        residual = start_break
        selected_codes: List[str] = []
        selected_names: List[str] = []
        within_after = False
        if pd.isna(start_break):
            status = "No starting Actual vs Benchmark value"
        elif pd.isna(threshold):
            status = "No ARC / threshold available"
        elif direction_sign == 0:
            within_after = abs(float(start_break)) <= abs(float(threshold))
            status = "Flat starting break"
        elif abs(float(start_break)) <= abs(float(threshold)):
            within_after = True
            status = "Already within threshold"
        elif same.empty:
            status = "No same-direction DAssetReturn candidates"
        else:
            # Directional-support rule: select same-direction rows until their cumulative
            # absolute contribution is enough to support the anomaly allowing ARC risk.
            # Overshoot is acceptable and does not cause failure.
            required_support = max(0.0, abs(float(start_break)) - abs(float(threshold)))
            for rank, (_, drow) in enumerate(same.iterrows(), start=1):
                contribution = float(drow.get("_contribution_num", 0.0) or 0.0)
                would_select = abs(float(cumulative)) < required_support
                cumulative_after = cumulative + (contribution if would_select else 0.0)
                residual_after = float(start_break) - cumulative_after
                row_within = abs(float(cumulative_after)) >= required_support
                if would_select:
                    selected_count += 1
                    cumulative = cumulative_after
                    residual = residual_after
                    within_after = row_within
                    code_text = str(drow.get(asset_code_col, "")).strip() if asset_code_col else ""
                    name_text = str(drow.get(asset_name_col, "")).strip() if asset_name_col else ""
                    if code_text:
                        selected_codes.append(code_text)
                    if name_text:
                        selected_names.append(name_text)
                candidate_rows.append({
                    "Portfolio code": portfolio_code,
                    "Portfolio Name": portfolio_name,
                    "Validation Direction": direction_label,
                    "Starting Actual vs Benchmark": float(start_break),
                    "ARC / threshold": float(threshold),
                    "Threshold Source": threshold_source,
                    "Candidate Rank": int(rank),
                    "Asset Code": str(drow.get(asset_code_col, "")).strip() if asset_code_col else "",
                    "Asset Name": str(drow.get(asset_name_col, "")).strip() if asset_name_col else "",
                    "Asset Type": str(drow.get(asset_type_col, "")).strip() if asset_type_col else "",
                    "CCY": str(drow.get(ccy_col, "")).strip() if ccy_col else "",
                    "Asset to Portfolio Contribution": contribution,
                    "Abs Contribution": abs(contribution),
                    "Cumulative selected contribution": cumulative_after,
                    "Residual after this row": residual_after,
                    "Direction threshold met after this row": bool(row_within),
                    "Is minimum selected row": bool(would_select),
                    "Is additional same-direction row": bool(not would_select),
                })
            status = "Direction threshold met" if within_after else "Partial directional support only"

        summary_rows.append({
            "Portfolio code": portfolio_code,
            "Portfolio Name": portfolio_name,
            "ARC Asset Type of portfolio": str(prow.get("ARC Asset Type of portfolio", "")).strip(),
            "Benchmark Code": str(prow.get("Benchmark Code", "")).strip(),
            "Benchmark Name": str(prow.get("Benchmark Name", "")).strip(),
            "Actual Return": prow.get("Actual Return", ""),
            "Benchmark Return": prow.get("Benchmark Return", ""),
            "Actual vs Benchmark": start_break,
            "Validation Direction": direction_label,
            "ARC / threshold": threshold,
            "Threshold Source": threshold_source,
            "Same-direction candidate rows": int(len(same)),
            "Minimum validation rows": int(selected_count),
            "Selected contribution total": float(cumulative),
            "Residual after selected rows": float(residual) if pd.notna(residual) else float("nan"),
            "Direction threshold met": bool(within_after),
            "Selected Asset Codes": " | ".join(selected_codes[:12]),
            "Selected Asset Names": " | ".join(selected_names[:8]),
            "Minimum validation status": status,
            "Starting Break Source": start_source,
        })

    summary_df = pd.DataFrame(summary_rows, columns=empty_summary.columns)
    candidate_df = pd.DataFrame(candidate_rows, columns=empty_candidates.columns)
    clear_count = int(summary_df.get("Direction threshold met", pd.Series(dtype="bool")).fillna(False).astype(bool).sum()) if not summary_df.empty else 0
    diag_rows.extend([
        {"Check":"Portfolios assessed","Result":int(len(summary_df)),"Detail":"One row per unexplained portfolio with a portfolio code."},
        {"Check":"Portfolios within threshold after selected rows","Result":clear_count,"Detail":"Based on same-direction Asset to Portfolio Contribution rows only."},
        {"Check":"Portfolios still outside / not assessed","Result":int(len(summary_df)-clear_count),"Detail":"See status column for missing data, no candidates or insufficient candidates."},
        {"Check":"Candidate rows returned","Result":int(len(candidate_df)),"Detail":"All same-direction rows are returned; minimum selected rows are flagged."},
    ])
    return summary_df, candidate_df, pd.DataFrame(diag_rows, columns=empty_diag.columns)



def _validation_candidate_action(asset_type: object, asset_name: object = "", asset_code: object = "") -> str:
    text = " ".join([str(asset_type or ""), str(asset_name or ""), str(asset_code or "")]).strip().lower()
    if any(tok in text for tok in ["foreign exchange", "fx", "currency", "usd", "aud", "forward"]):
        return "Validate FX / currency holding contribution direction and materiality"
    if any(tok in text for tok in ["future", "futures", "bond future", "index future"]):
        return "Validate futures holding contribution direction and market movement"
    if any(tok in text for tok in ["unit trust", "trust", "fund"]):
        return "Validate unit trust contribution and benchmark relationship"
    if any(tok in text for tok in ["ordinary", "equity", "share", "stock"]):
        return "Validate equity holding contribution direction and materiality"
    if any(tok in text for tok in ["cash", "deposit", "receivable", "payable", "margin"]):
        return "Validate cash / margin / accrual contribution if material"
    return "Validate holding contribution direction and materiality"


def build_unexplained_common_validation_candidates(candidate_df: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "Validation Priority Rank", "Asset Code", "Asset Name", "Asset Type", "Validation Direction",
        "Portfolios impacted", "Portfolio list", "Selected row count", "Sum selected contribution",
        "Sum absolute selected contribution", "Max single portfolio contribution", "Suggested validation focus",
    ]
    if candidate_df is None or not isinstance(candidate_df, pd.DataFrame) or candidate_df.empty:
        return pd.DataFrame(columns=cols)
    required = {"Portfolio code", "Asset Code", "Asset Name", "Asset Type", "Validation Direction", "Asset to Portfolio Contribution", "Is minimum selected row"}
    if not required.issubset(set(candidate_df.columns)):
        return pd.DataFrame(columns=cols)

    selected = candidate_df[candidate_df["Is minimum selected row"].fillna(False).astype(bool)].copy()
    if selected.empty:
        return pd.DataFrame(columns=cols)
    selected["Asset Code"] = selected["Asset Code"].astype(str).str.strip()
    selected["Asset Name"] = selected["Asset Name"].astype(str).str.strip()
    selected["Asset Type"] = selected["Asset Type"].astype(str).str.strip()
    selected["Validation Direction"] = selected["Validation Direction"].astype(str).str.strip()
    selected["Portfolio code"] = selected["Portfolio code"].astype(str).str.strip()
    selected["_contribution_num"] = pd.to_numeric(selected["Asset to Portfolio Contribution"], errors="coerce").fillna(0.0)
    selected["_abs_contribution_num"] = selected["_contribution_num"].abs()

    grouped = (
        selected.groupby(["Asset Code", "Asset Name", "Asset Type", "Validation Direction"], dropna=False)
        .agg(
            **{
                "Portfolios impacted": ("Portfolio code", lambda s: int(pd.Series(s).astype(str).str.strip().replace("", pd.NA).dropna().nunique())),
                "Portfolio list": ("Portfolio code", lambda s: ", ".join(sorted({str(x).strip() for x in s.tolist() if str(x).strip()}))),
                "Selected row count": ("Portfolio code", "count"),
                "Sum selected contribution": ("_contribution_num", "sum"),
                "Sum absolute selected contribution": ("_abs_contribution_num", "sum"),
                "Max single portfolio contribution": ("_abs_contribution_num", "max"),
            }
        )
        .reset_index()
    )
    grouped = grouped.sort_values(
        ["Portfolios impacted", "Sum absolute selected contribution", "Max single portfolio contribution"],
        ascending=[False, False, False],
        na_position="last",
    ).reset_index(drop=True)
    grouped.insert(0, "Validation Priority Rank", range(1, len(grouped) + 1))
    grouped["Suggested validation focus"] = grouped.apply(
        lambda r: _validation_candidate_action(r.get("Asset Type", ""), r.get("Asset Name", ""), r.get("Asset Code", "")), axis=1
    )
    return grouped[cols]


def build_unexplained_portfolio_validation_plan(summary_df: pd.DataFrame) -> pd.DataFrame:
    cols = [
        "Portfolio code", "Portfolio Name", "ARC Asset Type of portfolio", "Benchmark Code", "Benchmark Name",
        "Actual vs Benchmark", "Validation Direction", "ARC / threshold", "Same-direction candidate rows",
        "Minimum validation rows", "Selected Asset Codes", "Selected Asset Names", "Selected contribution total",
        "Directional gap after selected rows", "Direction threshold met", "Directional validation status",
    ]
    if summary_df is None or not isinstance(summary_df, pd.DataFrame) or summary_df.empty:
        return pd.DataFrame(columns=cols)
    out = summary_df.copy()
    if "Minimum validation status" in out.columns:
        out["Directional validation status"] = out["Minimum validation status"].astype(str).str.strip()
    elif "Directional validation status" not in out.columns:
        out["Directional validation status"] = ""
    for col in cols:
        if col not in out.columns:
            out[col] = ""
    try:
        out["_direction_met_sort"] = out["Direction threshold met"].fillna(False).astype(bool)
        out["_rows_sort"] = pd.to_numeric(out["Minimum validation rows"], errors="coerce").fillna(999999)
        out = out.sort_values(["_direction_met_sort", "_rows_sort", "Portfolio code"], ascending=[True, True, True]).drop(columns=["_direction_met_sort", "_rows_sort"], errors="ignore")
    except Exception:
        pass
    return out[cols].reset_index(drop=True)



def _validation_candidate_portfolios(value: object) -> List[str]:
    raw = str(value or "")
    out: List[str] = []
    for part in re.split(r"[,;|]", raw):
        p = str(part or "").strip()
        if p:
            out.append(p)
    return out


def _validation_portfolio_set_from_common(common_df: pd.DataFrame, *, recurring_only: bool = False) -> set:
    if common_df is None or not isinstance(common_df, pd.DataFrame) or common_df.empty or "Portfolio list" not in common_df.columns:
        return set()
    work = common_df.copy()
    if recurring_only and "Portfolios impacted" in work.columns:
        work = work[pd.to_numeric(work["Portfolios impacted"], errors="coerce").fillna(0).gt(1)].copy()
    covered = set()
    for val in work["Portfolio list"].dropna().tolist():
        covered.update(_validation_candidate_portfolios(val))
    return {str(p).strip() for p in covered if str(p).strip()}


def _validation_all_portfolio_set(summary_df: pd.DataFrame) -> set:
    if summary_df is None or not isinstance(summary_df, pd.DataFrame) or summary_df.empty or "Portfolio code" not in summary_df.columns:
        return set()
    return {str(p).strip() for p in summary_df["Portfolio code"].dropna().astype(str).tolist() if str(p).strip()}


def _validation_row_numeric(row: pd.Series, col: str) -> float:
    if col not in row.index:
        return float("nan")
    try:
        return float(_minval_num(row.get(col, pd.NA)))
    except Exception:
        try:
            return float(pd.to_numeric(row.get(col, pd.NA), errors="coerce"))
        except Exception:
            return float("nan")


def _near_zero_actual_benchmark_mask(summary_df: pd.DataFrame, candidate_covered_ports: set, *, near_zero_actual_pp: float = 0.05) -> pd.Series:
    if summary_df is None or not isinstance(summary_df, pd.DataFrame) or summary_df.empty or "Portfolio code" not in summary_df.columns:
        return pd.Series(False, index=getattr(summary_df, "index", pd.Index([])))
    out = []
    for _, row in summary_df.iterrows():
        port = str(row.get("Portfolio code", "")).strip()
        if not port or port in candidate_covered_ports:
            out.append(False)
            continue
        actual = _validation_row_numeric(row, "Actual Return")
        benchmark = _validation_row_numeric(row, "Benchmark Return")
        avb = _validation_row_numeric(row, "Actual vs Benchmark")
        threshold = _validation_row_numeric(row, "ARC / threshold")
        if pd.isna(threshold) or abs(threshold) <= 0:
            threshold = _validation_row_numeric(row, "Tolerance")
        if pd.isna(threshold) or abs(threshold) <= 0:
            threshold = 0.30
        is_near_zero_actual = pd.notna(actual) and abs(float(actual)) <= float(near_zero_actual_pp)
        benchmark_material = pd.notna(benchmark) and abs(float(benchmark)) > abs(float(threshold))
        break_material = pd.notna(avb) and abs(float(avb)) > abs(float(threshold))
        out.append(bool(is_near_zero_actual and benchmark_material and break_material))
    return pd.Series(out, index=summary_df.index)


def build_unexplained_validation_coverage_summary(summary_df: pd.DataFrame, common_df: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    summary_cols = ["Coverage measure", "Portfolio count", "Coverage %", "Portfolio list", "Review focus"]
    category_cols = ["Review category", "Portfolio count", "Portfolio %", "Portfolio list", "Review focus"]
    detail_cols = [
        "Portfolio code", "Portfolio Name", "ARC Asset Type of portfolio", "Benchmark Code", "Benchmark Name",
        "Actual Return", "Benchmark Return", "Actual vs Benchmark", "Directional validation status", "Coverage category", "Review focus",
    ]
    all_ports = _validation_all_portfolio_set(summary_df)
    total = len(all_ports)
    covered_ports = _validation_portfolio_set_from_common(common_df, recurring_only=False)
    uncovered_ports = all_ports - covered_ports

    near_zero_mask = _near_zero_actual_benchmark_mask(summary_df, covered_ports)
    near_zero_ports = set(summary_df.loc[near_zero_mask, "Portfolio code"].astype(str).str.strip().tolist()) if isinstance(summary_df, pd.DataFrame) and not summary_df.empty and "Portfolio code" in summary_df.columns else set()
    other_ports = uncovered_ports - near_zero_ports

    def pct(n: int) -> float:
        return round((float(n) / float(total) * 100.0), 1) if total else 0.0
    def plist(values: set) -> str:
        return ", ".join(sorted({str(v).strip() for v in values if str(v).strip()}))

    coverage_summary_df = pd.DataFrame([
        {"Coverage measure": "Summary", "Portfolio count": total, "Coverage %": 100.0 if total else 0.0, "Portfolio list": plist(all_ports), "Review focus": "Total residual unexplained population"},
        {"Coverage measure": "Common validation candidates", "Portfolio count": len(covered_ports), "Coverage %": pct(len(covered_ports)), "Portfolio list": plist(covered_ports), "Review focus": "Validate selected same-direction holdings"},
        {"Coverage measure": "Near zero actual yet benchmark movement", "Portfolio count": len(near_zero_ports), "Coverage %": pct(len(near_zero_ports)), "Portfolio list": plist(near_zero_ports), "Review focus": "Review benchmark mapping / benchmark application / valuation basis"},
        {"Coverage measure": "Other", "Portfolio count": len(other_ports), "Coverage %": pct(len(other_ports)), "Portfolio list": plist(other_ports), "Review focus": "Check source data, inclusion logic, or portfolio-specific driver"},
    ], columns=summary_cols)

    category_df = pd.DataFrame([
        {"Review category": "Common validation candidates", "Portfolio count": len(covered_ports), "Portfolio %": pct(len(covered_ports)), "Portfolio list": plist(covered_ports), "Review focus": "Validate selected same-direction holdings from DAssetReturn"},
        {"Review category": "Near zero actual yet benchmark movement", "Portfolio count": len(near_zero_ports), "Portfolio %": pct(len(near_zero_ports)), "Portfolio list": plist(near_zero_ports), "Review focus": "Actual return is near flat while benchmark return is material; review benchmark mapping / application"},
        {"Review category": "Other", "Portfolio count": len(other_ports), "Portfolio %": pct(len(other_ports)), "Portfolio list": plist(other_ports), "Review focus": "Manual review; not covered by selected holdings or near-zero actual category"},
    ], columns=category_cols)

    detail_rows: List[Dict[str, object]] = []
    if isinstance(summary_df, pd.DataFrame) and not summary_df.empty and "Portfolio code" in summary_df.columns:
        for _, row in summary_df.iterrows():
            port = str(row.get("Portfolio code", "")).strip()
            if not port or port in covered_ports:
                continue
            if port in near_zero_ports:
                cat = "Near zero actual yet benchmark movement"
                focus = "Actual return is near flat while benchmark movement is material; review benchmark mapping / application rather than individual holdings"
            else:
                cat = "Other"
                focus = "Manual review required; not explained by common candidate holdings or near-zero actual pattern"
            detail_rows.append({
                "Portfolio code": port,
                "Portfolio Name": row.get("Portfolio Name", ""),
                "ARC Asset Type of portfolio": row.get("ARC Asset Type of portfolio", ""),
                "Benchmark Code": row.get("Benchmark Code", ""),
                "Benchmark Name": row.get("Benchmark Name", ""),
                "Actual Return": row.get("Actual Return", ""),
                "Benchmark Return": row.get("Benchmark Return", ""),
                "Actual vs Benchmark": row.get("Actual vs Benchmark", ""),
                "Directional validation status": row.get("Minimum validation status", row.get("Directional validation status", "")),
                "Coverage category": cat,
                "Review focus": focus,
            })
    uncovered_detail_df = pd.DataFrame(detail_rows, columns=detail_cols)
    return coverage_summary_df, category_df, uncovered_detail_df


def add_cumulative_coverage_to_common_candidates(common_df: pd.DataFrame, summary_df: pd.DataFrame) -> pd.DataFrame:
    if common_df is None or not isinstance(common_df, pd.DataFrame) or common_df.empty:
        return pd.DataFrame() if common_df is None else common_df
    out = common_df.copy()
    total_ports = _validation_all_portfolio_set(summary_df)
    denom = max(1, len(total_ports))
    covered_so_far: set = set()
    new_counts: List[int] = []
    new_lists: List[str] = []
    cumulative_counts: List[int] = []
    cumulative_percentages: List[float] = []
    cumulative_lists: List[str] = []
    rank_col = "Validation Priority Rank" if "Validation Priority Rank" in out.columns else None
    if rank_col:
        out = out.sort_values(rank_col, ascending=True, na_position="last").reset_index(drop=True)
    for _, row in out.iterrows():
        row_ports = set(_validation_candidate_portfolios(row.get("Portfolio list", "")))
        new_ports = row_ports - covered_so_far
        covered_so_far.update(row_ports)
        new_counts.append(len(new_ports))
        new_lists.append(", ".join(sorted(new_ports)))
        cumulative_counts.append(len(covered_so_far))
        cumulative_percentages.append(round((len(covered_so_far) / denom) * 100.0, 1))
        cumulative_lists.append(", ".join(sorted(covered_so_far)))
    insert_after = "Portfolios impacted" if "Portfolios impacted" in out.columns else out.columns[-1]
    insert_pos = list(out.columns).index(insert_after) + 1
    out.insert(insert_pos, "New portfolios covered", new_counts)
    out.insert(insert_pos + 1, "New portfolio list", new_lists)
    out.insert(insert_pos + 2, "Cumulative portfolios covered", cumulative_counts)
    out.insert(insert_pos + 3, "Cumulative coverage %", cumulative_percentages)
    out.insert(insert_pos + 4, "Cumulative portfolio list", cumulative_lists)
    return out


def _copilot_prompt_clean(value: object, default: str = "Not supplied") -> str:
    """Return display-safe prompt text without treating blank values as facts."""
    try:
        if value is None or pd.isna(value):
            return default
    except Exception:
        if value is None:
            return default
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "nat"}:
        return default
    return text


def _copilot_prompt_first(row: pd.Series, candidates: List[str], default: str = "Not supplied") -> str:
    for col in candidates:
        if col in row.index:
            value = _copilot_prompt_clean(row.get(col), "")
            if value:
                return value
    return default


def _copilot_prompt_has_real_benchmark(value: object) -> bool:
    text = _copilot_prompt_clean(value, "").strip()
    if not text:
        return False
    return text.upper() not in {"N/A", "NA", "NONE", "NOT SUPPLIED", "NOT APPLICABLE", "UBSCASH", "CASH"}


def _copilot_security_prompt_from_row(row: pd.Series, reporting_date: str) -> str:
    """Build one security-level Copilot Researcher prompt.

    Deliberately excludes portfolio identifiers/lists. If security return or benchmark
    fields are not present in the candidate export, the prompt only states what is
    available from the security-level candidate row.
    """
    security_name = _copilot_prompt_first(row, ["Asset Name", "Security Name", "Security", "Name"])
    security_code = _copilot_prompt_first(row, ["Asset Code", "Security Code", "Security code", "Code"])
    security_type = _copilot_prompt_first(row, ["Asset Type", "Security Type", "Security type", "Type"])
    security_return = _copilot_prompt_first(row, ["Security Return", "Security return", "Asset Return", "Asset return", "Return"], "")
    direction = _copilot_prompt_first(row, ["Validation Direction", "Direction", "Movement direction"])
    movement_value = _copilot_prompt_first(row, ["Max single portfolio contribution", "Sum selected contribution", "Security movement value", "Movement value", "Asset to Portfolio Contribution"], "Not supplied")
    review_focus = _copilot_prompt_first(row, ["Suggested validation focus", "Review focus"], "Validate whether the security movement is reasonable for the security type.")
    benchmark_code = _copilot_prompt_first(row, ["Benchmark Code", "Relevant benchmark", "Benchmark", "Benchmark code"], "")
    benchmark_return = _copilot_prompt_first(row, ["Benchmark Return", "Benchmark return", "Relevant benchmark return"], "")

    lines = [
        "Recommended Copilot mode: Researcher",
        f"Reporting date: {reporting_date}",
        "",
        "Please review this security-level movement.",
        "",
        f"Security: {security_name}",
        f"Security code: {security_code}",
        f"Security type: {security_type}",
    ]
    if security_return:
        lines.append(f"Security return: {security_return}")
    else:
        lines.append("Security return: Not supplied in this security-level export.")
    lines.append(f"Security movement direction: {direction}")
    lines.append(f"Security movement value available from dashboard export: {movement_value}")
    if _copilot_prompt_has_real_benchmark(benchmark_code):
        lines.append(f"Relevant benchmark: {benchmark_code}")
        if benchmark_return:
            lines.append(f"Benchmark return: {benchmark_return}")
    lines.extend([
        "",
        f"Review focus: {review_focus}",
        "",
        "Please assess whether the movement appears reasonable for the security type on the reporting date. Use cited market, fund, security, pricing, valuation, FX, currency, futures, yield, or source-data evidence where relevant. Keep the review at security level only and separate cited evidence from assumptions.",
    ])
    return "\n".join(lines)


def _build_unexplained_security_prompt_docx(common_view_df: pd.DataFrame, bundle: Dict[str, object]) -> Tuple[Optional[bytes], int, str]:
    """Create a Word document containing security-level Copilot prompts."""
    if common_view_df is None or not isinstance(common_view_df, pd.DataFrame) or common_view_df.empty:
        return None, 0, ""
    try:
        from io import BytesIO
        from docx import Document
    except Exception:
        return None, 0, ""

    reporting_date = _copilot_prompt_clean(
        bundle.get("selected_date_label", bundle.get("selected_date", "")) if isinstance(bundle, dict) else "",
        "Selected reporting date not supplied",
    )
    work = common_view_df.copy()
    if "Validation Priority Rank" in work.columns:
        try:
            work["_rank_sort"] = pd.to_numeric(work["Validation Priority Rank"], errors="coerce").fillna(999999)
            work = work.sort_values(["_rank_sort", "Asset Name"], na_position="last").drop(columns=["_rank_sort"], errors="ignore")
        except Exception:
            pass

    document = Document()
    document.add_heading("Security-level Copilot Researcher prompts", level=1)
    document.add_paragraph(f"Reporting date: {reporting_date}")
    document.add_paragraph("Use these prompts in Copilot Researcher. They are generated from security-level selected validation candidates and intentionally exclude portfolio identifiers/lists.")

    prompt_count = 0
    for _, row in work.iterrows():
        security_name = _copilot_prompt_first(row, ["Asset Name", "Security Name", "Security", "Name"], "Security")
        security_code = _copilot_prompt_first(row, ["Asset Code", "Security Code", "Security code", "Code"], "")
        heading = f"Prompt {prompt_count + 1}: {security_name}" + (f" ({security_code})" if security_code else "")
        document.add_heading(heading, level=2)
        prompt_text = _copilot_security_prompt_from_row(row, reporting_date)
        for para in prompt_text.split("\n\n"):
            document.add_paragraph(para)
        prompt_count += 1

    bio = BytesIO()
    document.save(bio)
    return bio.getvalue(), prompt_count, reporting_date




def _standard_validation_prompt_text() -> str:
    """Standard prompt text embedded into Excel prompt templates."""
    return """I have attached a CSV containing a DAssetReturn local price validation population and blank evidence fields.
Use the attached CSV as the only validation population. Do not add or remove securities.
Objective:
Independently validate the local share price movement for each security using web-based market data. Do not validate FX. Spot FX is validated separately. Do not validate holdings, valuation, weights, contribution or benchmark fields.
For each row:
1. Use the DAssetReturn fields to identify the security:
   - Asset Code
   - Asset Name
   - CCY
   - Asset Type description
2. Independently source the local market price for:
   - Asset Price Prev_Day
   - Asset Price Curr_Day
3. Use the Effective_date as the current report date. Treat Asset Price Prev_Day as the prior trading/report day price and Asset Price Curr_Day as the current trading/report day price.
4. Use reputable web sources where possible, such as:
   - relevant stock exchange
   - company investor relations market data
   - Yahoo Finance
   - MarketWatch
   - Nasdaq
   - London Stock Exchange
   - SIX Swiss Exchange
   - Nasdaq Copenhagen
   - another reputable market data source
Only a single source per security is necessary
5. Populate the evidence fields for all securities in the CSV:
   - Independent Source Name
   - Independent Source URL
   - Independent Source Accessed Date
   - Independent Prev_Day Local Price
   - Independent Curr_Day Local Price
   - Independent Calculated Price Return
   - Price Return Difference vs DAssetReturn
   - Prev_Day Price Difference vs DAssetReturn
   - Curr_Day Price Difference vs DAssetReturn
   - Price Unit Checked
   - Security Identity Validated
   - Currency Validated
   - Price Dates Validated
   - Price Movement Direction Validated
   - Return Recalculation Validated
   - Validation Result
   - Validation Notes
   - Reviewer
   - Review Date
6. Calculate independent price return as:
   (Independent Curr_Day Local Price / Independent Prev_Day Local Price - 1) * 100
7. Compare this result to the DAssetReturn field:
   - Price Return
8. If a source quotes in cents or pence, convert to the same price unit before comparing.
9. Use the following values for Validation Result:
   - Pass
   - Pass with explanation
   - Follow-up required
   - Fail
10. In Validation Notes, explain any differences due to rounding, close-price convention, stale pricing, corporate action, price unit, or source limitation.
Important:
- Do not perform FX validation.
- Do not compare to AUD/base-currency prices.
- Do not use portfolio holdings, valuation, weights, contribution or benchmark logic.
- Keep the original DAssetReturn fields unchanged.
- Return the completed CSV-style table with all evidence fields populated.
"""


def _build_excel_prompt_template_bytes(candidates_df: pd.DataFrame, *, prompt_text: Optional[str] = None) -> bytes:
    """Build the two-sheet prompt workbook requested for local storage/reuse."""
    from io import BytesIO
    output = BytesIO()
    prompt_text = prompt_text if prompt_text is not None else _standard_validation_prompt_text()
    candidate_table = candidates_df.copy() if isinstance(candidates_df, pd.DataFrame) else pd.DataFrame()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        pd.DataFrame({"Standard Prompt": [prompt_text]}).to_excel(writer, sheet_name=STANDARD_PROMPT_SHEET_NAME, index=False)
        candidate_table.to_excel(writer, sheet_name=COMMON_VALIDATION_CANDIDATES_SHEET_NAME, index=False)
        try:
            workbook = writer.book
            for sheet_name in [STANDARD_PROMPT_SHEET_NAME, COMMON_VALIDATION_CANDIDATES_SHEET_NAME]:
                ws = workbook[sheet_name]
                ws.freeze_panes = "A2"
                for cell in ws[1]:
                    cell.style = "Headline 4"
                for column_cells in ws.columns:
                    try:
                        letter = column_cells[0].column_letter
                        max_len = max(len(str(c.value or "")) for c in column_cells[:200])
                        ws.column_dimensions[letter].width = min(max(max_len + 2, 12), 60)
                    except Exception:
                        pass
                if sheet_name == STANDARD_PROMPT_SHEET_NAME:
                    from openpyxl.styles import Alignment
                    ws["A2"].alignment = Alignment(wrap_text=True, vertical="top")
                    ws.row_dimensions[2].height = 420
        except Exception:
            pass
    return output.getvalue()



def _load_user_settings() -> Dict[str, object]:
    try:
        p = Path(USER_SETTINGS_FILE)
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}

def _save_user_settings(settings: Dict[str, object]) -> None:
    try:
        Path(USER_SETTINGS_FILE).parent.mkdir(parents=True, exist_ok=True)
        Path(USER_SETTINGS_FILE).write_text(json.dumps(settings or {}, indent=2), encoding="utf-8")
    except Exception:
        pass

def _get_persistent_user_setting(key: str, default: object = "") -> object:
    return _load_user_settings().get(str(key), default)

def _set_persistent_user_setting(key: str, value: object) -> None:
    s = _load_user_settings(); s[str(key)] = value; _save_user_settings(s)

def _persistent_template_filepath_input() -> str:
    key = "copilot_prompt_package_template_filepath_input"
    default = str(_get_persistent_user_setting(COPILOT_TEMPLATE_FILEPATH_SETTING_KEY, LOCAL_PRICE_VALIDATION_TEMPLATE_DEFAULT) or LOCAL_PRICE_VALIDATION_TEMPLATE_DEFAULT)
    # v363: default now comes from Static Data 'paths'/local_price_validation_template
    # (via _set_path_global at config-apply time), pointing at the template copy kept
    # in the app folder alongside the .py files - no personal machine-specific path.
    value = st.text_input("Copilot prompt package template filepath (.xlsx, include filename)", value=str(st.session_state.get(key, default) or default), key=key, help="Defaults to 'local_price_validation_evidence_template.xlsx' in the app folder (Static Data 'paths'). Override here if you keep your own copy elsewhere - include the .xlsx filename.")
    _set_persistent_user_setting(COPILOT_TEMPLATE_FILEPATH_SETTING_KEY, value)
    return str(value or "")

def _normalise_copilot_template_filepath(path_value: object) -> Tuple[bool, str, str]:
    raw = str(path_value or "").strip().strip('"')
    if not raw:
        return False, "", "Please provide the full .xlsx filepath, including filename."
    p = Path(raw).expanduser()
    if p.suffix.lower() != ".xlsx":
        return False, str(p), "Please provide the full .xlsx filepath, including filename."
    if p.exists() and p.is_dir():
        return False, str(p), "The template filepath points to a folder. Please include the .xlsx filename."
    if not p.exists():
        return False, str(p), f"Template file not found: {p}"
    return True, str(p), ""

def _safe_filename_slug(value: object, fallback: str = "value") -> str:
    raw = str(value or fallback).strip() or fallback
    slug = re.sub(r"[^A-Za-z0-9]+", "_", raw).strip("_")
    return slug[:80] or fallback

def _build_local_price_validation_evidence_from_candidates(asset_df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(columns=LOCAL_PRICE_VALIDATION_EVIDENCE_COLUMNS)
    if asset_df is None or not isinstance(asset_df, pd.DataFrame) or asset_df.empty:
        return out
    src = _remove_common_candidate_cumulative_fields(asset_df).copy()
    rows = []
    for _, row in src.iterrows():
        base = {c: "" for c in LOCAL_PRICE_VALIDATION_EVIDENCE_COLUMNS}
        def first(cols):
            for c in cols:
                if c in row.index and pd.notna(row.get(c)) and str(row.get(c)).strip():
                    return row.get(c)
            return ""
        base["Effective_date"] = first(["Effective_date", "Effective Date", "RunDate", "Reporting Date"])
        base["Portfolio"] = first(["Portfolio", "Portfolio code", "Portfolio Code", "Portfolio list"])
        base["Asset Type description"] = first(["Asset Type description", "Asset Type Description", "Asset Type"])
        base["Asset Code"] = first(["Asset Code", "AssetCode"])
        base["Asset Name"] = first(["Asset Name", "AssetName"])
        base["CCY"] = first(["CCY", "Currency", "Local Currency"])
        base["Asset Price Prev_Day"] = first(["Asset Price Prev_Day", "Asset Price Prev Day", "Asset Price Previous Day", "Price Prev_Day"])
        base["Asset Price Curr_Day"] = first(["Asset Price Curr_Day", "Asset Price Curr Day", "Asset Price Current Day", "Price Curr_Day"])
        base["Actual Return"] = first(["Actual Return", "Actual return"])
        base["Price Return"] = first(["Price Return", "Local Price Return", "Asset Price Return"])
        rows.append(base)
    out = pd.DataFrame(rows, columns=LOCAL_PRICE_VALIDATION_EVIDENCE_COLUMNS)
    subset = [c for c in ["Effective_date", "Portfolio", "Asset Type description", "Asset Code", "Asset Name"] if c in out.columns]
    if subset:
        out = out.drop_duplicates(subset=subset, keep="first").reset_index(drop=True)
    return out

def _build_copilot_prompt_package_from_template_bytes(template_path_value: object, evidence_df: pd.DataFrame) -> Tuple[bool, bytes, str]:
    ok, template_path, msg = _normalise_copilot_template_filepath(template_path_value)
    if not ok:
        return False, b"", msg
    try:
        from io import BytesIO
        from openpyxl import load_workbook
        wb = load_workbook(template_path)
        if "Prompt" not in wb.sheetnames:
            return False, b"", "Template workbook must include a 'Prompt' sheet."
        if LOCAL_PRICE_VALIDATION_EVIDENCE_SHEET not in wb.sheetnames:
            return False, b"", f"Template workbook must include a '{LOCAL_PRICE_VALIDATION_EVIDENCE_SHEET}' sheet."
        ws = wb[LOCAL_PRICE_VALIDATION_EVIDENCE_SHEET]
        headers = [str(ws.cell(row=1, column=c).value or "").strip() for c in range(1, ws.max_column + 1)]
        missing = [c for c in LOCAL_PRICE_VALIDATION_EVIDENCE_COLUMNS if c not in headers]
        if missing:
            return False, b"", "Template evidence sheet is missing required columns: " + ", ".join(missing[:8]) + ("..." if len(missing) > 8 else "")
        if ws.max_row > 1:
            ws.delete_rows(2, ws.max_row - 1)
        evidence = evidence_df.copy() if isinstance(evidence_df, pd.DataFrame) else pd.DataFrame(columns=LOCAL_PRICE_VALIDATION_EVIDENCE_COLUMNS)
        for col in LOCAL_PRICE_VALIDATION_EVIDENCE_COLUMNS:
            if col not in evidence.columns:
                evidence[col] = ""
        evidence = evidence[LOCAL_PRICE_VALIDATION_EVIDENCE_COLUMNS].fillna("")
        hmap = {h: i + 1 for i, h in enumerate(headers)}
        for r_idx, (_, row) in enumerate(evidence.iterrows(), start=2):
            for col_name in LOCAL_PRICE_VALIDATION_EVIDENCE_COLUMNS:
                c_idx = hmap.get(col_name)
                if c_idx:
                    ws.cell(row=r_idx, column=c_idx).value = row.get(col_name, "")
        try:
            ws.freeze_panes = "A2"
            if len(evidence) > 0: ws.auto_filter.ref = ws.dimensions
        except Exception:
            pass
        bio = BytesIO(); wb.save(bio)
        return True, bio.getvalue(), ""
    except Exception as exc:
        return False, b"", f"{type(exc).__name__}: {exc}"

def _write_excel_prompt_template_to_path(path_value: object, candidates_df: pd.DataFrame) -> Tuple[bool, str]:
    """Write prompt workbook to the supplied local path when the app is running locally."""
    path_text = str(path_value or "").strip().strip('"')
    if not path_text:
        return False, "No template filepath supplied."
    try:
        out_path = Path(path_text).expanduser()
        if out_path.suffix.lower() != ".xlsx":
            out_path = out_path.with_suffix(".xlsx")
        if out_path.parent and not out_path.parent.exists():
            out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(_build_excel_prompt_template_bytes(candidates_df))
        return True, str(out_path)
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _asset_type_group_col(df: pd.DataFrame) -> Optional[str]:
    return find_col(df, ["Asset Type description", "Asset Type Description", "Asset Type", "AssetTypeDescription", "Asset Type Name"])



def _remove_common_candidate_cumulative_fields(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or not isinstance(df, pd.DataFrame):
        return pd.DataFrame()
    drop_cols = ["Cumulative portfolios covered", "Cumulative coverage %", "Cumulative portfolio list"]
    return df.drop(columns=[c for c in drop_cols if c in df.columns], errors="ignore").copy()


def _common_candidate_portfolio_set(df: pd.DataFrame) -> set:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return set()
    covered = set()
    if "Portfolio list" in df.columns:
        for val in df["Portfolio list"].dropna().tolist():
            try:
                covered.update(_validation_candidate_portfolios(val))
            except Exception:
                for part in re.split(r"[,;|]", str(val or "")):
                    p = str(part or "").strip()
                    if p:
                        covered.add(p)
    return {str(p).strip() for p in covered if str(p).strip()}


def _common_candidate_security_count(df: pd.DataFrame) -> int:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return 0
    for col in ["Asset Code", "Asset Name"]:
        if col in df.columns:
            vals = {str(v).strip() for v in df[col].dropna().tolist() if str(v).strip()}
            if vals:
                return int(len(vals))
    return int(len(df))


def _common_candidate_asset_type_heading(asset_type: object, asset_df: pd.DataFrame) -> str:
    asset_label = str(asset_type or "Unknown asset type").strip() or "Unknown asset type"
    sec_count = _common_candidate_security_count(asset_df)
    port_count = len(_common_candidate_portfolio_set(asset_df))
    security_word = "Security" if sec_count == 1 else "Securities"
    portfolio_word = "portfolio" if port_count == 1 else "portfolios"
    return f"{asset_label} - {sec_count:,} {security_word} - {port_count:,} {portfolio_word} covered"


def _common_validation_candidates_by_asset_type_df(common_df: pd.DataFrame) -> pd.DataFrame:
    cols = ["Asset Type", "Number of Securities", "Number of Portfolios covered"]
    if common_df is None or not isinstance(common_df, pd.DataFrame) or common_df.empty:
        return pd.DataFrame(columns=cols)
    work = common_df.copy()
    asset_col = _asset_type_group_col(work) or ("Asset Type" if "Asset Type" in work.columns else None)
    if asset_col is None or asset_col not in work.columns:
        work["Asset Type"] = "Unknown asset type"
        asset_col = "Asset Type"
    rows = []
    for asset_type, sub_df in work.groupby(asset_col, dropna=False):
        rows.append({
            "Asset Type": str(asset_type or "Unknown asset type").strip() or "Unknown asset type",
            "Number of Securities": _common_candidate_security_count(sub_df),
            "Number of Portfolios covered": len(_common_candidate_portfolio_set(sub_df)),
        })
    return pd.DataFrame(rows, columns=cols).sort_values(["Number of Portfolios covered", "Number of Securities", "Asset Type"], ascending=[False, False, True]).reset_index(drop=True)

def _render_common_validation_candidate_asset_type_tables(common_view_df: pd.DataFrame, bundle: Optional[Dict[str, object]] = None) -> None:
    # v320: ONE consolidated section (asset-type split removed) - one enriched
    # table and one Copilot prompt pack across all common candidates. Rows are
    # enriched with FDV holdings detail (security name, class, price, price date,
    # rating, etc.) to give Copilot more context for validation.
    if common_view_df is None or not isinstance(common_view_df, pd.DataFrame) or common_view_df.empty:
        st.info("No common validation candidates were produced from selected same-direction rows.")
        return
    display_df = _remove_common_candidate_cumulative_fields(common_view_df)
    display_df = _v321_strip_arc_asset_type(display_df)
    display_df = _v320_enrich(bundle, display_df)
    template_path = _persistent_template_filepath_input()
    ok_template, _path_norm, template_msg = _normalise_copilot_template_filepath(template_path)
    if not ok_template:
        st.warning(template_msg)
    show_df(display_df, hide_index=True)
    evidence_df = _build_local_price_validation_evidence_from_candidates(display_df)
    evidence_df = _v320_enrich(bundle, evidence_df)
    if evidence_df is None or evidence_df.empty:
        st.info("No rows are available for the Copilot prompt package.")
        return
    package_ok, package_bytes, package_msg = _build_copilot_prompt_package_from_template_bytes(template_path, evidence_df)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    package_name = f"local_price_validation_evidence_{timestamp}.xlsx"
    st.caption(f"Copilot package rows: {len(evidence_df):,} (all common validation candidates, FDV-enriched). Template filepath must include the .xlsx filename.")
    if package_ok:
        st.download_button("Generate Copilot prompt package", data=package_bytes, file_name=package_name, mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key=f"download_copilot_prompt_package_all_{timestamp}")
    else:
        st.error(f"Copilot prompt package could not be generated: {package_msg}")

def _v320_fdv_lookup(bundle):
    """Build (once, cached on the bundle) the FDV enrichment lookup from
    bundle['fdv_files'] (the DetailedValuationFDV paths resolved by v311).

    v343: the lookup is now a vectorised DataFrame (indexed by the normalised join
    key) rather than a dict. The cache check and empties are updated accordingly."""
    if not isinstance(bundle, dict):
        return None
    cached = bundle.get("_fdv_enrichment_lookup_v320")
    # v343: accept a cached DataFrame (new) OR dict (legacy) - both are valid caches,
    # including a cached EMPTY frame (means "already tried, no FDV files").
    if isinstance(cached, pd.DataFrame) or isinstance(cached, dict):
        return cached
    lookup = None
    try:
        files = bundle.get("fdv_files")
        if files and callable(globals().get("_fdv_load_lookup_v320")):
            # current-day (T) files first so they win on first-occurrence.
            files = sorted(files, reverse=True)
            lookup = _fdv_load_lookup_v320(files)
    except Exception:
        lookup = None
    if lookup is None:
        lookup = pd.DataFrame()
    bundle["_fdv_enrichment_lookup_v320"] = lookup
    return lookup


def _fdv_lookup_is_empty(lookup) -> bool:
    """True when the FDV lookup has nothing to join (None / empty frame / empty dict)."""
    if lookup is None:
        return True
    if isinstance(lookup, pd.DataFrame):
        return lookup.empty
    if isinstance(lookup, dict):
        return len(lookup) == 0
    return False


def _v320_build_fdv_lookup_at_load(bundle):
    """v343 (Part B): build the FDV lookup ONCE at load-time, alongside the other BNP
    reports, so render-side enrich calls are instant (no lazy first-click cost). Safe
    no-op if the module or FDV files are unavailable; result is cached on the bundle
    exactly where the render path expects it."""
    try:
        if isinstance(bundle, dict) and callable(globals().get("_fdv_load_lookup_v320")):
            _v320_fdv_lookup(bundle)
    except Exception:
        pass
    return bundle


def _v320_enrich(bundle, df, code_col="Asset Code"):
    """Attach the 15 curated FDV columns to a df that has an 'Asset Code' column.
    Safe no-op if the enrichment module or FDV files are unavailable."""
    try:
        if not callable(globals().get("_fdv_enrich_v320")):
            return df
        if not isinstance(df, pd.DataFrame) or df.empty or code_col not in df.columns:
            return df
        lookup = _v320_fdv_lookup(bundle)
        if _fdv_lookup_is_empty(lookup):
            return df
        return _fdv_enrich_v320(df, lookup, code_col=code_col)
    except Exception:
        return df


def _v321_strip_arc_asset_type(df):
    """v321: drop the 'ARC Asset Type of portfolio' column from unexplained
    sub-section display tables / downloads (it is blank at source now). Operates
    on a copy so upstream frames are untouched."""
    try:
        import pandas as _pd
        if isinstance(df, _pd.DataFrame) and "ARC Asset Type of portfolio" in df.columns:
            return df.drop(columns=["ARC Asset Type of portfolio"])
    except Exception:
        pass
    return df


def _render_unexplained_validation_review_tables(bundle: Dict[str, object], summary_df: pd.DataFrame, candidate_df: pd.DataFrame) -> None:
    """Render Unexplained review with required v306.13.0 sub-sections."""
    common_df = build_unexplained_common_validation_candidates(candidate_df)
    common_view_df = add_cumulative_coverage_to_common_candidates(common_df, summary_df)
    coverage_summary_df, category_df, uncovered_detail_df = build_unexplained_validation_coverage_summary(summary_df, common_df)

    if isinstance(bundle, dict):
        bundle["unexplained_common_validation_candidates_df"] = common_view_df
        # Portfolio validation plan intentionally removed from the daily dashboard in v306.13.0.
        bundle.pop("unexplained_portfolio_validation_plan_df", None)
        bundle["unexplained_validation_coverage_summary_df"] = coverage_summary_df
        bundle["unexplained_validation_review_category_df"] = category_df
        bundle["unexplained_uncovered_portfolio_detail_df"] = uncovered_detail_df

    st.markdown("##### Summary")
    st.caption("Validation coverage summary using the required daily dashboard review buckets.")
    show_df(_v321_strip_arc_asset_type(coverage_summary_df), hide_index=True)
    st.download_button(
        "Download unexplained validation coverage summary CSV",
        data=_v321_strip_arc_asset_type(coverage_summary_df).to_csv(index=False).encode("utf-8-sig"),
        file_name="unexplained_validation_coverage_summary.csv",
        mime="text/csv",
        key="download_unexplained_validation_coverage_summary_v306_13_0_csv",
    )

    st.markdown("##### Common validation candidates")
    st.caption("Aggregates selected same-direction DAssetReturn rows across unexplained portfolios, enriched with FDV holdings detail. One consolidated table and one Copilot prompt pack.")
    _render_common_validation_candidate_asset_type_tables(common_view_df, bundle)
    if common_view_df is not None and isinstance(common_view_df, pd.DataFrame) and not common_view_df.empty:
        st.download_button(
            "Download common validation candidates CSV",
            data=_v320_enrich(bundle, _v321_strip_arc_asset_type(_remove_common_candidate_cumulative_fields(common_view_df))).to_csv(index=False).encode("utf-8-sig"),
            file_name="unexplained_common_validation_candidates.csv",
            mime="text/csv",
            key="download_unexplained_common_validation_candidates_v306_13_0_csv",
        )

    st.markdown("##### near zero actual yet benchmark movement")
    st.caption("Portfolios not covered by common candidates where actual return is near zero while benchmark movement is material.")
    near_zero_df = pd.DataFrame()
    if uncovered_detail_df is not None and isinstance(uncovered_detail_df, pd.DataFrame) and not uncovered_detail_df.empty and "Coverage category" in uncovered_detail_df.columns:
        near_zero_df = uncovered_detail_df[uncovered_detail_df["Coverage category"].astype(str).str.strip().eq("near zero actual yet benchmark movement")].copy()
    if near_zero_df.empty:
        st.info("No portfolios fell into the near zero actual yet benchmark movement bucket.")
    else:
        show_df(near_zero_df, hide_index=True)
        st.download_button(
            "Download near zero actual yet benchmark movement CSV",
            data=_v320_enrich(bundle, near_zero_df).to_csv(index=False).encode("utf-8-sig"),
            file_name="unexplained_near_zero_actual_yet_benchmark_movement.csv",
            mime="text/csv",
            key="download_unexplained_near_zero_actual_yet_benchmark_movement_v306_13_0_csv",
        )

    st.markdown("##### Other")
    st.caption("Residual unexplained portfolios not covered by common validation candidates or the near-zero actual/benchmark pattern.")
    other_df = pd.DataFrame()
    if uncovered_detail_df is not None and isinstance(uncovered_detail_df, pd.DataFrame) and not uncovered_detail_df.empty and "Coverage category" in uncovered_detail_df.columns:
        other_df = uncovered_detail_df[uncovered_detail_df["Coverage category"].astype(str).str.strip().eq("Other")].copy()
    if other_df.empty:
        st.info("No portfolios remain in Other.")
    else:
        show_df(other_df, hide_index=True)
        st.download_button(
            "Download Other unexplained portfolios CSV",
            data=_v320_enrich(bundle, other_df).to_csv(index=False).encode("utf-8-sig"),
            file_name="unexplained_other.csv",
            mime="text/csv",
            key="download_unexplained_other_v306_13_0_csv",
        )

def _render_unexplained_minimum_validation_diagnostics(bundle: Dict[str, object], unexplained_df: pd.DataFrame) -> None:
    """Render v306.7.0 diagnostic output for minimum validation set engine."""
    if unexplained_df is None or not isinstance(unexplained_df, pd.DataFrame) or unexplained_df.empty:
        return
    dar_source = bundle.get("dar_index") or bundle.get("dar") if isinstance(bundle, dict) else pd.DataFrame()
    summary_df, candidate_df, diagnostic_df = build_unexplained_minimum_validation_sets(unexplained_df, dar_source)
    if isinstance(bundle, dict):
        bundle["unexplained_min_validation_summary_df"] = summary_df
        bundle["unexplained_min_validation_candidate_rows_df"] = candidate_df
        bundle["unexplained_min_validation_diagnostic_df"] = diagnostic_df
    _render_unexplained_validation_review_tables(bundle, summary_df, candidate_df)

    with st.expander("Minimum validation set diagnostics (v306.7.3)", expanded=False):
        st.caption("Diagnostic-only v306.7.3 output. For each unexplained portfolio, the engine ranks same-direction DAssetReturn Asset to Portfolio Contributions and flags the smallest ranked prefix whose cumulative contribution supports the Actual vs Benchmark anomaly direction. Overshoot is allowed and residual crossing zero is not tested or displayed.")
        st.markdown("##### Diagnostic checks")
        show_df(diagnostic_df, hide_index=True)
        st.markdown("##### Portfolio minimum validation summary")
        if summary_df.empty:
            st.info("No minimum validation summary was produced.")
        else:
            show_df(summary_df, hide_index=True)
            st.download_button("Download v306.7.3 minimum validation summary CSV", data=summary_df.to_csv(index=False).encode("utf-8-sig"), file_name="unexplained_minimum_validation_summary_v306_7_3.csv", mime="text/csv", key="download_unexplained_minimum_validation_summary_v306_7_3_csv")
        st.markdown("##### Same-direction candidate rows")
        if candidate_df.empty:
            st.info("No same-direction DAssetReturn candidate rows were produced.")
        else:
            show_df(candidate_df, hide_index=True)
            st.download_button("Download v306.7.3 minimum validation candidate rows CSV", data=candidate_df.to_csv(index=False).encode("utf-8-sig"), file_name="unexplained_minimum_validation_candidate_rows_v306_7_3.csv", mime="text/csv", key="download_unexplained_minimum_validation_candidate_rows_v306_7_3_csv")



def _render_auto_explained_tab(bundle: Dict[str, object], auto_fx_summary_df: pd.DataFrame) -> None:
    """Render automated explanation buckets as one top-level dashboard section.

    v306.8.6 consolidates Auto FX, Nil actual return, and Current Account dominated
    into a single Auto Explained parent while preserving the existing child renderers
    and waterfall logic.
    """
    st.subheader("Daily Movements - Auto explained")
    valid_sections = ["FX", "Nil actual return", "Current Account dominated"]
    auto_explained_sub_section_key = "auto_explained_sub_section"
    if auto_explained_sub_section_key in st.session_state and st.session_state.get(auto_explained_sub_section_key) not in valid_sections:
        st.session_state[auto_explained_sub_section_key] = "FX"
    auto_explained_radio_kwargs = {
        "label": "Auto Explained sub-section",
        "options": valid_sections,
        "horizontal": True,
        "key": auto_explained_sub_section_key,
    }
    if auto_explained_sub_section_key not in st.session_state:
        auto_explained_radio_kwargs["index"] = valid_sections.index("FX")
    sub_section = st.radio(**auto_explained_radio_kwargs)
    if sub_section == "FX":
        _render_portfolio_fx_validation_tab(bundle)
    elif sub_section == "Nil actual return":
        _render_nil_actual_return_tab(bundle, auto_fx_summary_df)
    else:
        _render_current_account_dominated_tab(bundle, auto_fx_summary_df)


def _render_current_account_dominated_tab(bundle: Dict[str, object], auto_fx_summary_df: pd.DataFrame) -> None:
    """Render Current Account dominated HOT population from the v306.8.0 waterfall."""
    st.subheader("Current Account dominated")
    _hot_df, _auto_fx_df, _nil_actual_return_df, current_account_df, _unexplained_df = _hot_resolution_sets(bundle, auto_fx_summary_df)
    st.markdown(f"##### Current Account dominated portfolio summary ({len(current_account_df):,})")
    if current_account_df is None or not isinstance(current_account_df, pd.DataFrame) or current_account_df.empty:
        st.info("No remaining HOT portfolios met the Current Account dominance rule after Auto FX and Nil actual return removal.")
    else:
        cols = [
            "Largest Tier 1 driver", "Portfolio code", "Portfolio Name", "DDetailed Current FDV",
            "Current Account ZL01 Current FDV", "% Current Account", "Current Account threshold %",
            "Current Account ZL01 row count", "Hot / Cold", "Current Account dominance note",
        ]
        display = current_account_df[[c for c in cols if c in current_account_df.columns]].copy()
        if display.empty:
            display = current_account_df.copy()
        show_df(display, hide_index=True)

    dar_source = bundle.get("dar_index") or bundle.get("dar") if isinstance(bundle, dict) else pd.DataFrame()
    if isinstance(current_account_df, pd.DataFrame) and not current_account_df.empty:
        with st.expander("Underlying ZL01 DAssetReturn rows", expanded=False):
            zl01_rows = pd.DataFrame()
            try:
                source_for_rows = dar_source
                if isinstance(source_for_rows, dict):
                    source_for_rows = _frame_for_portfolio_subset(source_for_rows, current_account_df)
                if isinstance(source_for_rows, pd.DataFrame) and not source_for_rows.empty:
                    port_col = find_col(current_account_df, ["Portfolio code", "Portfolio", "PortfolioCode", "portfolio", "portfolio code"])
                    dar_port_col = find_col(source_for_rows, ["Portfolio code", "Portfolio", "PortfolioCode", "portfolio", "portfolio code"])
                    asset_type_col = _resolve_asset_type_driver_code_col(source_for_rows)
                    if port_col and dar_port_col and asset_type_col:
                        wanted = set(current_account_df[port_col].astype(str).str.strip())
                        zl01_rows = source_for_rows[source_for_rows[dar_port_col].astype(str).str.strip().isin(wanted)].copy()
                        zl01_rows = zl01_rows[zl01_rows[asset_type_col].astype(str).str.strip().str.upper().eq(CURRENT_ACCOUNT_ASSET_TYPE_CODE)].copy()
            except Exception as exc:
                zl01_rows = pd.DataFrame([{"Current Account source rows error": f"{type(exc).__name__}: {exc}"}])
            if zl01_rows is None or not isinstance(zl01_rows, pd.DataFrame) or zl01_rows.empty:
                st.info("No ZL01 DAssetReturn source rows were found for the Current Account dominated portfolios.")
            else:
                show_df(zl01_rows, hide_index=True)


def _render_unexplained_tab(bundle: Dict[str, object], auto_fx_summary_df: pd.DataFrame) -> None:
    """Render unexplained HOT portfolio population using a four-section review layout."""
    st.subheader("Daily Movements - Unexplained")
    _render_dashboard_section_explainer("unexplained")
    _hot_df, _auto_fx_df, _nil_actual_return_df, _current_account_df, unexplained_df = _hot_resolution_sets(bundle, auto_fx_summary_df)

    if unexplained_df is None or not isinstance(unexplained_df, pd.DataFrame) or unexplained_df.empty:
        st.info("No unexplained HOT portfolios remain after auto rules for the selected day.")
        return

    dar_source = bundle.get("dar_index") or bundle.get("dar") if isinstance(bundle, dict) else pd.DataFrame()
    summary_df, candidate_df, diagnostic_df = build_unexplained_minimum_validation_sets(unexplained_df, dar_source)
    common_df = build_unexplained_common_validation_candidates(candidate_df)
    common_view_df = add_cumulative_coverage_to_common_candidates(common_df, summary_df)
    coverage_summary_df, category_df, uncovered_detail_df = build_unexplained_validation_coverage_summary(summary_df, common_df)

    if isinstance(bundle, dict):
        bundle["unexplained_min_validation_summary_df"] = summary_df
        bundle["unexplained_min_validation_candidate_rows_df"] = candidate_df
        bundle["unexplained_min_validation_diagnostic_df"] = diagnostic_df
        bundle["unexplained_common_validation_candidates_df"] = common_view_df
        bundle.pop("unexplained_portfolio_validation_plan_df", None)
        bundle["unexplained_validation_coverage_summary_df"] = coverage_summary_df
        bundle["unexplained_validation_review_category_df"] = category_df
        bundle["unexplained_uncovered_portfolio_detail_df"] = uncovered_detail_df

    valid_sections = ["Summary", "Common validation candidates", "Near zero actual yet benchmark movement", "Other"]
    section_key = "unexplained_review_sub_section_v306_13_1"
    if section_key in st.session_state and st.session_state.get(section_key) not in valid_sections:
        st.session_state[section_key] = "Summary"
    radio_kwargs = {
        "label": "Unexplained sub-section",
        "options": valid_sections,
        "horizontal": True,
        "key": section_key,
    }
    if section_key not in st.session_state:
        radio_kwargs["index"] = valid_sections.index("Summary")
    sub_section = st.radio(**radio_kwargs)

    if sub_section == "Summary":
        st.markdown("##### Summary")
        st.caption("Validation coverage summary for the unexplained population. Diagnostics and source-row extracts are grouped here so the other sub-sections stay focused on reviewer action tables.")
        show_df(coverage_summary_df, hide_index=True)
        st.download_button(
            "Download unexplained validation coverage summary CSV",
            data=coverage_summary_df.to_csv(index=False).encode("utf-8-sig"),
            file_name="unexplained_validation_coverage_summary.csv",
            mime="text/csv",
            key="download_unexplained_validation_coverage_summary_v306_13_1_csv",
        )
        with st.expander("Minimum validation set diagnostics (v306.7.3)", expanded=False):
            st.caption("Diagnostic-only output. The engine ranks same-direction DAssetReturn Asset to Portfolio Contributions and flags the smallest ranked prefix whose cumulative contribution supports the Actual vs Benchmark anomaly direction.")
            st.markdown("##### Diagnostic checks")
            show_df(diagnostic_df, hide_index=True)
            st.markdown("##### Portfolio minimum validation summary")
            if summary_df.empty:
                st.info("No minimum validation summary was produced.")
            else:
                show_df(summary_df, hide_index=True)
                st.download_button("Download minimum validation summary CSV", data=summary_df.to_csv(index=False).encode("utf-8-sig"), file_name="unexplained_minimum_validation_summary.csv", mime="text/csv", key="download_unexplained_minimum_validation_summary_v306_13_1_csv")
            st.markdown("##### Same-direction candidate rows")
            if candidate_df.empty:
                st.info("No same-direction DAssetReturn candidate rows were produced.")
            else:
                show_df(candidate_df, hide_index=True)
                st.download_button("Download minimum validation candidate rows CSV", data=candidate_df.to_csv(index=False).encode("utf-8-sig"), file_name="unexplained_minimum_validation_candidate_rows.csv", mime="text/csv", key="download_unexplained_minimum_validation_candidate_rows_v306_13_1_csv")
        _render_unexplained_source_row_sections(bundle, unexplained_df)
        return

    if sub_section == "Common validation candidates":
        st.markdown("##### Common validation candidates")
        st.caption("Aggregates selected same-direction DAssetReturn rows across unexplained portfolios. Tables are separated by Asset Type.")
        _render_common_validation_candidate_asset_type_tables(common_view_df)
        if common_view_df is not None and isinstance(common_view_df, pd.DataFrame) and not common_view_df.empty:
            st.download_button(
                "Download common validation candidates CSV",
                data=_remove_common_candidate_cumulative_fields(common_view_df).to_csv(index=False).encode("utf-8-sig"),
                file_name="unexplained_common_validation_candidates.csv",
                mime="text/csv",
                key="download_unexplained_common_validation_candidates_v306_13_1_csv",
            )
        return

    if sub_section == "Near zero actual yet benchmark movement":
        st.markdown("##### Near zero actual yet benchmark movement")
        st.caption("Portfolios not covered by common candidates where actual return is near zero while benchmark movement is material.")
        near_zero_df = pd.DataFrame()
        if uncovered_detail_df is not None and isinstance(uncovered_detail_df, pd.DataFrame) and not uncovered_detail_df.empty and "Coverage category" in uncovered_detail_df.columns:
            near_zero_df = uncovered_detail_df[uncovered_detail_df["Coverage category"].astype(str).str.strip().eq("Near zero actual yet benchmark movement")].copy()
        if near_zero_df.empty:
            st.info("No portfolios fell into the Near zero actual yet benchmark movement bucket.")
        else:
            show_df(near_zero_df, hide_index=True)
            st.download_button(
                "Download Near zero actual yet benchmark movement CSV",
                data=near_zero_df.to_csv(index=False).encode("utf-8-sig"),
                file_name="unexplained_near_zero_actual_yet_benchmark_movement.csv",
                mime="text/csv",
                key="download_unexplained_near_zero_actual_yet_benchmark_movement_v306_13_1_csv",
            )
        return

    st.markdown("##### Other")
    st.caption("Residual unexplained portfolios not covered by common validation candidates or the near-zero actual/benchmark pattern.")
    other_df = pd.DataFrame()
    if uncovered_detail_df is not None and isinstance(uncovered_detail_df, pd.DataFrame) and not uncovered_detail_df.empty and "Coverage category" in uncovered_detail_df.columns:
        other_df = uncovered_detail_df[uncovered_detail_df["Coverage category"].astype(str).str.strip().eq("Other")].copy()
    if other_df.empty:
        st.info("No portfolios remain in Other.")
    else:
        show_df(_v321_strip_arc_asset_type(other_df), hide_index=True)
        st.download_button(
            "Download Other unexplained portfolios CSV",
            data=_v321_strip_arc_asset_type(other_df).to_csv(index=False).encode("utf-8-sig"),
            file_name="unexplained_other.csv",
            mime="text/csv",
            key="download_unexplained_other_v306_13_1_csv",
        )

def _tier1_count_frame_from_assignments(subset_df: pd.DataFrame, assignments_df: pd.DataFrame) -> pd.DataFrame:
    """Fast driver count from precomputed portfolio-level Tier 1 assignments.

    v306.5.9: count from the precomputed vectorised assignment table.
    This keeps executive and section driver counts on one source of truth.
    """
    if subset_df is None or not isinstance(subset_df, pd.DataFrame) or subset_df.empty:
        return pd.DataFrame(columns=["Largest Tier 1 driver", "Portfolio count"])
    if assignments_df is None or not isinstance(assignments_df, pd.DataFrame) or assignments_df.empty:
        return pd.DataFrame(columns=["Largest Tier 1 driver", "Portfolio count"])

    subset_port_col = find_col(subset_df, ["Portfolio code", "Portfolio", "PortfolioCode", "portfolio", "portfolio code"])
    assign_port_col = find_col(assignments_df, ["Portfolio code", "Portfolio", "PortfolioCode", "portfolio", "portfolio code"])
    assign_driver_col = find_col(assignments_df, ["Largest Tier 1 driver", "Largest Tier 1 Break Driver"])
    if not subset_port_col or not assign_port_col or not assign_driver_col:
        return pd.DataFrame(columns=["Largest Tier 1 driver", "Portfolio count"])

    subset = subset_df[[subset_port_col]].copy()
    subset["_pkey"] = normalise_join_key_series(subset[subset_port_col].astype(str).str.strip())
    subset = subset[subset["_pkey"].astype(str).str.strip().ne("")].drop_duplicates("_pkey")

    assignments = assignments_df[[assign_port_col, assign_driver_col]].copy()
    assignments["_pkey"] = normalise_join_key_series(assignments[assign_port_col].astype(str).str.strip())
    assignments = assignments[["_pkey", assign_driver_col]].drop_duplicates("_pkey")

    joined = subset.merge(assignments, on="_pkey", how="left")
    joined["Largest Tier 1 driver"] = joined[assign_driver_col].astype(str).str.strip().replace({"": "Unclassified", "nan": "Unclassified", "None": "Unclassified", "<NA>": "Unclassified"})
    out = (
        joined.groupby("Largest Tier 1 driver", dropna=False)
        .size()
        .reset_index(name="Portfolio count")
        .sort_values("Portfolio count", ascending=False)
        .reset_index(drop=True)
    )
    return out[out["Portfolio count"] > 0].copy()




def _html_safe(value: object) -> str:
    text = "" if value is None else str(value)
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _pct_of_total(value: object, total: object) -> str:
    try:
        denom = float(total or 0)
        num_value = float(value or 0)
        if denom <= 0:
            return "0.0%"
        return f"{(num_value / denom) * 100.0:.1f}%"
    except Exception:
        return "0.0%"


def _count_for_driver(df: Optional[pd.DataFrame], driver: str) -> int:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return 0
    if "Largest Tier 1 driver" not in df.columns or "Portfolio count" not in df.columns:
        return 0
    mask = df["Largest Tier 1 driver"].astype(str).str.strip().eq(str(driver).strip())
    if not mask.any():
        return 0
    return int(pd.to_numeric(df.loc[mask, "Portfolio count"], errors="coerce").fillna(0).sum())


def _sum_driver_counts(df: Optional[pd.DataFrame]) -> int:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty or "Portfolio count" not in df.columns:
        return 0
    return int(pd.to_numeric(df["Portfolio count"], errors="coerce").fillna(0).sum())


def _driver_stage_matrix_rows_data(driver_views: Dict[str, pd.DataFrame]) -> Tuple[List[Dict[str, object]], Dict[str, int]]:
    """v355 (native-card prototype): same ordering/selection logic as
    _driver_stage_matrix_rows_html, but returns structured rows + a totals dict for the
    native-widget renderer (instead of an HTML string). Keeping this a separate function
    means the existing HTML path is untouched (parity for the default card)."""
    stage_keys = ["hot", "auto_fx", "nil_actual_return", "current_account", "unexplained"]
    drivers = []
    for key in stage_keys:
        df = driver_views.get(key)
        if df is not None and isinstance(df, pd.DataFrame) and not df.empty and "Largest Tier 1 driver" in df.columns:
            drivers.extend(df["Largest Tier 1 driver"].dropna().astype(str).str.strip().tolist())
    ordered = []
    seen = set()
    for driver in drivers:
        if not driver or driver.upper() == "TOTAL" or driver in seen:
            continue
        seen.add(driver)
        ordered.append(driver)
    ordered = sorted(ordered, key=lambda d: (-_count_for_driver(driver_views.get("hot"), d), -_count_for_driver(driver_views.get("unexplained"), d), d))
    rows: List[Dict[str, object]] = []
    for driver in ordered[:10]:
        rows.append({
            "Driver": driver,
            "Hot portfolios": _count_for_driver(driver_views.get("hot"), driver),
            "Auto explained by FX": _count_for_driver(driver_views.get("auto_fx"), driver),
            "Nil actual return": _count_for_driver(driver_views.get("nil_actual_return"), driver),
            "Current Account dominated": _count_for_driver(driver_views.get("current_account"), driver),
            "Unexplained": _count_for_driver(driver_views.get("unexplained"), driver),
        })
    totals = {
        "Hot portfolios": _sum_driver_counts(driver_views.get("hot")),
        "Auto explained by FX": _sum_driver_counts(driver_views.get("auto_fx")),
        "Nil actual return": _sum_driver_counts(driver_views.get("nil_actual_return")),
        "Current Account dominated": _sum_driver_counts(driver_views.get("current_account")),
        "Unexplained": _sum_driver_counts(driver_views.get("unexplained")),
    }
    return rows, totals


def _driver_stage_matrix_rows_html(driver_views: Dict[str, pd.DataFrame]) -> str:
    stage_keys = ["hot", "auto_fx", "nil_actual_return", "current_account", "unexplained"]
    drivers = []
    for key in stage_keys:
        df = driver_views.get(key)
        if df is not None and isinstance(df, pd.DataFrame) and not df.empty and "Largest Tier 1 driver" in df.columns:
            drivers.extend(df["Largest Tier 1 driver"].dropna().astype(str).str.strip().tolist())
    ordered = []
    seen = set()
    for driver in drivers:
        if not driver or driver.upper() == "TOTAL" or driver in seen:
            continue
        seen.add(driver)
        ordered.append(driver)
    ordered = sorted(ordered, key=lambda d: (-_count_for_driver(driver_views.get("hot"), d), -_count_for_driver(driver_views.get("unexplained"), d), d))
    rows = []
    if ordered:
        for driver in ordered[:10]:
            hot = _count_for_driver(driver_views.get("hot"), driver)
            fx = _count_for_driver(driver_views.get("auto_fx"), driver)
            nil_actual = _count_for_driver(driver_views.get("nil_actual_return"), driver)
            current_account = _count_for_driver(driver_views.get("current_account"), driver)
            unexplained = _count_for_driver(driver_views.get("unexplained"), driver)
            rows.append("<tr>" f"<td class='es-driver'>{_html_safe(driver)}</td>" f"<td><span class='es-pill es-hot'>{hot:,}</span></td>" f"<td><span class='es-pill es-fx'>{fx:,}</span></td>" f"<td><span class='es-pill es-nil'>{nil_actual:,}</span></td>" f"<td><span class='es-pill es-current-account'>{current_account:,}</span></td>" f"<td><span class='es-pill es-unexplained'>{unexplained:,}</span></td>" "</tr>")
    else:
        rows.append("<tr><td colspan='6' class='es-empty'>No driver movement data</td></tr>")
    total_hot = _sum_driver_counts(driver_views.get("hot"))
    total_fx = _sum_driver_counts(driver_views.get("auto_fx"))
    total_nil = _sum_driver_counts(driver_views.get("nil_actual_return"))
    total_current_account = _sum_driver_counts(driver_views.get("current_account"))
    total_unexplained = _sum_driver_counts(driver_views.get("unexplained"))
    rows.append("<tr class='es-total'>" "<td class='es-driver'>Total</td>" f"<td><span class='es-pill es-hot'>{total_hot:,}</span></td>" f"<td><span class='es-pill es-fx'>{total_fx:,}</span></td>" f"<td><span class='es-pill es-nil'>{total_nil:,}</span></td>" f"<td><span class='es-pill es-current-account'>{total_current_account:,}</span></td>" f"<td><span class='es-pill es-unexplained'>{total_unexplained:,}</span></td>" "</tr>")
    return "".join(rows)



# ========================================================
# EXECUTIVE TREND SNAPSHOT FOUNDATION (v306.9.0)
# ========================================================

def _trend_safe_int(value: object, default: int = 0) -> int:
    """Return an int for count-style values without raising on blanks/NaN."""
    try:
        if value is None or pd.isna(value):
            return int(default)
    except Exception:
        if value is None:
            return int(default)
    try:
        return int(float(value))
    except Exception:
        return int(default)


def _trend_safe_float(value: object, default: float = 0.0) -> float:
    """Return a float for trend ratios/thresholds without raising on blanks/NaN."""
    try:
        if value is None or pd.isna(value):
            return float(default)
    except Exception:
        if value is None:
            return float(default)
    try:
        return float(value)
    except Exception:
        return float(default)


def _trend_pct(numerator: object, denominator: object) -> float:
    """Return a 0-100 percentage for trend display/export."""
    denom = _trend_safe_float(denominator, 0.0)
    num_value = _trend_safe_float(numerator, 0.0)
    if denom <= 0:
        return 0.0
    return round((num_value / denom) * 100.0, 4)


def _settings_hash_for_trend(
    tiny_upper: float,
    fx_line_match_tolerance_dollar: float,
    current_account_dominance_threshold_pct: float,
) -> str:
    """Hash the business settings that can change an executive trend snapshot.

    v306.9.0 only creates selected-date snapshots. The same hash is also the
    forward-compatible key component for v306.10.0 persisted trend history.
    """
    try:
        asset_type_map = dict(sorted((globals().get("ASSET_TYPE_DETAIL_TIER1_MAP") or {}).items()))
    except Exception:
        asset_type_map = {}
    payload = {
        "tiny_upper": round(_trend_safe_float(tiny_upper, DEFAULT_EXCLUDE_AMOUNT), 6),
        "fx_line_match_tolerance_dollar": round(_trend_safe_float(fx_line_match_tolerance_dollar, 100.0), 6),
        "current_account_dominance_threshold_pct": round(_trend_safe_float(current_account_dominance_threshold_pct, DEFAULT_CURRENT_ACCOUNT_DOMINANCE_THRESHOLD_PCT), 6),
        "asset_type_code_map": asset_type_map,
    }
    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.md5(raw.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _trend_stage_metadata() -> Dict[str, str]:
    """Canonical stage labels for export/charting."""
    return {
        "out": "Outside tolerance",
        "no_arc": "No Error Risk",
        "cold": "Cold portfolios",
        "hot": "Hot portfolios",
        "auto_fx": "Auto explained by FX",
        "nil_actual_return": "Nil actual return",
        "current_account": "Current Account dominated",
        "unexplained": "Unexplained",
    }


def _driver_stage_count_snapshot_df(
    run_date_value: object,
    folder: str,
    folder_fp: str,
    executive_driver_views: Dict[str, pd.DataFrame],
    *,
    settings_hash: str,
    tiny_upper: float,
    fx_line_match_tolerance_dollar: float,
    current_account_dominance_threshold_pct: float,
) -> pd.DataFrame:
    """Create export/chart-ready long-form driver movement rows.

    The rendered executive dashboard stays HTML-only; this dataframe is the data
    contract that v306.10+ can persist and v306.11+ can chart.
    """
    stage_labels = _trend_stage_metadata()
    run_date_str = _date_string_yyyy_mm_dd(run_date_value)
    rows: List[Dict[str, object]] = []
    if not isinstance(executive_driver_views, dict):
        executive_driver_views = {}
    for stage_key, stage_label in stage_labels.items():
        stage_df = executive_driver_views.get(stage_key, pd.DataFrame())
        if stage_df is None or not isinstance(stage_df, pd.DataFrame) or stage_df.empty:
            continue
        if "Largest Tier 1 driver" not in stage_df.columns or "Portfolio count" not in stage_df.columns:
            continue
        cleaned = stage_df[["Largest Tier 1 driver", "Portfolio count"]].copy()
        cleaned["Largest Tier 1 driver"] = cleaned["Largest Tier 1 driver"].astype(str).str.strip().replace({"": "Unclassified", "nan": "Unclassified", "None": "Unclassified", "<NA>": "Unclassified"})
        cleaned["Portfolio count"] = pd.to_numeric(cleaned["Portfolio count"], errors="coerce").fillna(0).astype(int)
        cleaned = cleaned[cleaned["Portfolio count"].gt(0)].copy()
        for _, row in cleaned.iterrows():
            rows.append({
                "RunDate": run_date_str,
                "StageKey": stage_key,
                "Stage": stage_label,
                "Driver": str(row.get("Largest Tier 1 driver", "Unclassified") or "Unclassified"),
                "Portfolio count": int(row.get("Portfolio count", 0) or 0),
                "IsTotal": False,
                "SourceFolder": str(folder or ""),
                "FolderFingerprint": str(folder_fp or ""),
                "CacheVersion": globals().get("CACHE_VERSION", ""),
                "AppPythonVersion": globals().get("APP_PYTHON_VERSION", ""),
                "SettingsHash": settings_hash,
                "MV Tiny Upper Bound": _trend_safe_float(tiny_upper, DEFAULT_EXCLUDE_AMOUNT),
                "FX Line Match Tolerance Dollar": _trend_safe_float(fx_line_match_tolerance_dollar, 100.0),
                "Current Account Dominance Threshold Pct": _trend_safe_float(current_account_dominance_threshold_pct, DEFAULT_CURRENT_ACCOUNT_DOMINANCE_THRESHOLD_PCT),
            })
        total_count = int(pd.to_numeric(cleaned.get("Portfolio count", pd.Series(dtype="float64")), errors="coerce").fillna(0).sum()) if not cleaned.empty else 0
        if total_count > 0:
            rows.append({
                "RunDate": run_date_str,
                "StageKey": stage_key,
                "Stage": stage_label,
                "Driver": "TOTAL",
                "Portfolio count": total_count,
                "IsTotal": True,
                "SourceFolder": str(folder or ""),
                "FolderFingerprint": str(folder_fp or ""),
                "CacheVersion": globals().get("CACHE_VERSION", ""),
                "AppPythonVersion": globals().get("APP_PYTHON_VERSION", ""),
                "SettingsHash": settings_hash,
                "MV Tiny Upper Bound": _trend_safe_float(tiny_upper, DEFAULT_EXCLUDE_AMOUNT),
                "FX Line Match Tolerance Dollar": _trend_safe_float(fx_line_match_tolerance_dollar, 100.0),
                "Current Account Dominance Threshold Pct": _trend_safe_float(current_account_dominance_threshold_pct, DEFAULT_CURRENT_ACCOUNT_DOMINANCE_THRESHOLD_PCT),
            })
    columns = [
        "RunDate", "StageKey", "Stage", "Driver", "Portfolio count", "IsTotal",
        "SourceFolder", "FolderFingerprint", "CacheVersion", "AppPythonVersion", "SettingsHash",
        "MV Tiny Upper Bound", "FX Line Match Tolerance Dollar", "Current Account Dominance Threshold Pct",
    ]
    return pd.DataFrame(rows, columns=columns) if rows else pd.DataFrame(columns=columns)


def _build_executive_trend_snapshot_from_bundle(
    run_date_value: object,
    folder: str,
    folder_fp: str,
    bundle: Dict[str, object],
    auto_fx_summary_df: Optional[pd.DataFrame] = None,
    executive_driver_views: Optional[Dict[str, pd.DataFrame]] = None,
) -> Dict[str, pd.DataFrame]:
    """Create selected-date executive trend snapshot dataframes.

    v306.9.0 scope:
    - one selected-date summary dataframe;
    - long-form driver movement dataframe;
    - diagnostic checks proving the snapshot reconciles to the dashboard counts.

    No parquet persistence is performed here. v306.10.0 will persist these
    exact dataframes across a selected date range.
    """
    if not isinstance(bundle, dict):
        empty_summary = pd.DataFrame()
        empty_driver = pd.DataFrame()
        diagnostic = pd.DataFrame([{"Check": "Bundle available", "Result": False, "Detail": "Bundle is missing or not a dict"}])
        return {"summary_df": empty_summary, "driver_df": empty_driver, "diagnostic_df": diagnostic}

    portfolio_df = _dedupe_columns_first(bundle.get("portfolio_df", pd.DataFrame()))
    if auto_fx_summary_df is None:
        if isinstance(bundle, dict):
            try:
                if callable(globals().get("_afx148_rebuild_auto_fx_after_basis_impact")):
                    bundle = _afx148_rebuild_auto_fx_after_basis_impact(bundle, stage="before executive Auto FX summary bind", force=False)
            except Exception:
                pass
        exchange_rate_bundle = bundle.get("exchange_rates", {}) if isinstance(bundle, dict) else {}
        auto_fx_summary_df = exchange_rate_bundle.get("portfolio_fx_summary_df", pd.DataFrame()) if isinstance(exchange_rate_bundle, dict) else pd.DataFrame()
    if executive_driver_views is None or not isinstance(executive_driver_views, dict):
        executive_driver_views = dict(bundle.get("tier1_driver_count_frames", {}) or {})

    tiny_upper = _trend_safe_float(bundle.get("tiny_upper", DEFAULT_EXCLUDE_AMOUNT), DEFAULT_EXCLUDE_AMOUNT)
    fx_tol = _trend_safe_float(bundle.get("fx_line_match_tolerance_dollar", 100.0), 100.0)
    current_account_threshold = _trend_safe_float(bundle.get("current_account_dominance_threshold_pct", DEFAULT_CURRENT_ACCOUNT_DOMINANCE_THRESHOLD_PCT), DEFAULT_CURRENT_ACCOUNT_DOMINANCE_THRESHOLD_PCT)
    settings_hash = _settings_hash_for_trend(tiny_upper, fx_tol, current_account_threshold)
    run_date_str = _date_string_yyyy_mm_dd(run_date_value)
    processed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if portfolio_df is None or not isinstance(portfolio_df, pd.DataFrame) or portfolio_df.empty:
        summary_cols = ["RunDate", "Total portfolios", "Within tolerance", "Outside tolerance", "Hot portfolios", "Unexplained"]
        summary_df = pd.DataFrame(columns=summary_cols)
        driver_df = _driver_stage_count_snapshot_df(run_date_value, folder, folder_fp, executive_driver_views, settings_hash=settings_hash, tiny_upper=tiny_upper, fx_line_match_tolerance_dollar=fx_tol, current_account_dominance_threshold_pct=current_account_threshold)
        diagnostic_df = pd.DataFrame([{"RunDate": run_date_str, "Check": "Portfolio dataframe available", "Result": False, "Detail": "No portfolio_df rows found"}])
        return {"summary_df": summary_df, "driver_df": driver_df, "diagnostic_df": diagnostic_df}

    hot_df, auto_fx_df, nil_actual_df, current_account_df, unexplained_df = _hot_resolution_sets(bundle, auto_fx_summary_df)

    total_count = int(len(portfolio_df))
    within_count = int(portfolio_df["Within Tolerance"].sum()) if "Within Tolerance" in portfolio_df.columns else 0
    out_count = int((~portfolio_df["Within Tolerance"].fillna(False).astype(bool)).sum()) if "Within Tolerance" in portfolio_df.columns else max(0, total_count - within_count)
    hot_count = int(len(hot_df)) if isinstance(hot_df, pd.DataFrame) else 0
    auto_fx_count = int(len(auto_fx_df)) if isinstance(auto_fx_df, pd.DataFrame) else 0
    nil_actual_count = int(len(nil_actual_df)) if isinstance(nil_actual_df, pd.DataFrame) else 0
    current_account_count = int(len(current_account_df)) if isinstance(current_account_df, pd.DataFrame) else 0
    unexplained_count = int(len(unexplained_df)) if isinstance(unexplained_df, pd.DataFrame) else 0

    no_arc_count = _sum_driver_counts(executive_driver_views.get("no_arc")) if isinstance(executive_driver_views, dict) else 0
    cold_count = _sum_driver_counts(executive_driver_views.get("cold")) if isinstance(executive_driver_views, dict) else 0
    if no_arc_count == 0 and "Hot / Cold" in portfolio_df.columns:
        no_arc_count = int(portfolio_df["Hot / Cold"].astype(str).str.strip().eq("No ARC match").sum())
    if cold_count == 0 and "Hot / Cold" in portfolio_df.columns:
        cold_count = int(portfolio_df["Hot / Cold"].astype(str).str.strip().eq("Cold").sum())

    summary_source = bundle.get("summary_df", pd.DataFrame())
    run_validation_state = ""
    error_count = 0
    warning_count = 0
    if isinstance(summary_source, pd.DataFrame) and not summary_source.empty:
        first = summary_source.iloc[0]
        run_validation_state = str(first.get("RunValidationState", "") or "")
        error_count = _trend_safe_int(first.get("ErrorCount", 0), 0)
        warning_count = _trend_safe_int(first.get("WarningCount", 0), 0)

    check_within_out_total = bool((within_count + out_count) == total_count)
    check_out_split = bool((no_arc_count + cold_count + hot_count) == out_count)
    check_hot_waterfall = bool((auto_fx_count + nil_actual_count + current_account_count + unexplained_count) == hot_count)

    summary_df = pd.DataFrame([{
        "RunDate": run_date_str,
        "SourceFolder": str(folder or bundle.get("folder", "") or ""),
        "FolderFingerprint": str(folder_fp or ""),
        "CacheVersion": globals().get("CACHE_VERSION", ""),
        "AppPythonVersion": globals().get("APP_PYTHON_VERSION", ""),
        "SettingsHash": settings_hash,
        "MV Tiny Upper Bound": tiny_upper,
        "FX Line Match Tolerance Dollar": fx_tol,
        "Current Account Dominance Threshold Pct": current_account_threshold,
        "Total portfolios": total_count,
        "Within tolerance": within_count,
        "Outside tolerance": out_count,
        "No Error Risk": no_arc_count,
        "Cold portfolios": cold_count,
        "Hot portfolios": hot_count,
        "Auto explained by FX": auto_fx_count,
        "Nil actual return": nil_actual_count,
        "Current Account dominated": current_account_count,
        "Unexplained": unexplained_count,
        "Pct outside tolerance": _trend_pct(out_count, total_count),
        "Pct hot portfolios": _trend_pct(hot_count, total_count),
        "Pct auto explained of hot": _trend_pct(auto_fx_count + nil_actual_count + current_account_count, hot_count),
        "Pct unexplained of hot": _trend_pct(unexplained_count, hot_count),
        "Check Within + Outside = Total": check_within_out_total,
        "Check No ARC + Cold + Hot = Outside": check_out_split,
        "Check Hot Waterfall = Hot": check_hot_waterfall,
        "RunValidationState": run_validation_state,
        "ErrorCount": error_count,
        "WarningCount": warning_count,
        "ProcessedAt": processed_at,
    }])

    driver_df = _driver_stage_count_snapshot_df(
        run_date_value,
        str(folder or bundle.get("folder", "") or ""),
        folder_fp,
        executive_driver_views,
        settings_hash=settings_hash,
        tiny_upper=tiny_upper,
        fx_line_match_tolerance_dollar=fx_tol,
        current_account_dominance_threshold_pct=current_account_threshold,
    )

    diagnostic_df = pd.DataFrame([
        {"RunDate": run_date_str, "Check": "Within + Outside = Total", "Result": check_within_out_total, "Expected": total_count, "Actual": within_count + out_count, "Detail": f"within={within_count}; outside={out_count}; total={total_count}"},
        {"RunDate": run_date_str, "Check": "No ARC + Cold + Hot = Outside", "Result": check_out_split, "Expected": out_count, "Actual": no_arc_count + cold_count + hot_count, "Detail": f"no_arc={no_arc_count}; cold={cold_count}; hot={hot_count}; outside={out_count}"},
        {"RunDate": run_date_str, "Check": "Hot Waterfall = Hot", "Result": check_hot_waterfall, "Expected": hot_count, "Actual": auto_fx_count + nil_actual_count + current_account_count + unexplained_count, "Detail": f"fx={auto_fx_count}; nil_actual={nil_actual_count}; current_account={current_account_count}; unexplained={unexplained_count}; hot={hot_count}"},
        {"RunDate": run_date_str, "Check": "Driver movement rows created", "Result": bool(isinstance(driver_df, pd.DataFrame)), "Expected": "DataFrame", "Actual": int(len(driver_df)) if isinstance(driver_df, pd.DataFrame) else 0, "Detail": "Includes driver rows plus TOTAL rows for each populated stage."},
    ])

    return {"summary_df": summary_df, "driver_df": driver_df, "diagnostic_df": diagnostic_df}


def _attach_executive_trend_snapshot_to_bundle(
    bundle: Dict[str, object],
    run_date_value: object,
    folder: str,
    folder_fp: str,
    auto_fx_summary_df: Optional[pd.DataFrame],
    executive_driver_views: Dict[str, pd.DataFrame],
) -> Dict[str, pd.DataFrame]:
    """Build and store v306.9.0 selected-date executive trend snapshot frames."""
    snapshot = _build_executive_trend_snapshot_from_bundle(
        run_date_value,
        folder,
        folder_fp,
        bundle,
        auto_fx_summary_df=auto_fx_summary_df,
        executive_driver_views=executive_driver_views,
    )
    if isinstance(bundle, dict):
        bundle["executive_trend_summary_snapshot_df"] = snapshot.get("summary_df", pd.DataFrame())
        bundle["executive_trend_driver_snapshot_df"] = snapshot.get("driver_df", pd.DataFrame())
        bundle["executive_trend_diagnostic_snapshot_df"] = snapshot.get("diagnostic_df", pd.DataFrame())
    return snapshot


def _render_executive_trend_snapshot_debug(bundle: Dict[str, object]) -> None:
    """v340: removed. This dev-only debug dump ("Executive trend snapshot data -
    v306.9.0") rendered a large multi-table block beneath the executive dashboard
    when Show Debug was on, and if it threw mid-render it killed the section radio
    (and every section below). No longer needed - now a no-op."""
    return


# ========================================================
# EXECUTIVE TREND PERSISTED CACHE / INDEX (v306.10.0)
# ========================================================

def _trend_cache_manifest_paths() -> Dict[str, str]:
    """Return the persisted executive trend cache paths used by v306.10+."""
    return {
        "summary": SUMMARY_FILE,
        "driver": DRIVER_FILE,
        "common_candidates": COMMON_VALIDATION_CANDIDATES_FILE,
        "diagnostic": DIAGNOSTIC_FILE,
        "exception": EXCEPTION_FILE,
        "index": INDEX_FILE,
    }


def _trend_summary_columns() -> List[str]:
    return [
        "RunDate", "SourceFolder", "FolderFingerprint", "CacheVersion", "AppPythonVersion", "SettingsHash",
        "MV Tiny Upper Bound", "FX Line Match Tolerance Dollar", "Current Account Dominance Threshold Pct",
        "Total portfolios", "Within tolerance", "Outside tolerance", "No Error Risk", "Cold portfolios", "Hot portfolios",
        "Auto explained by FX", "Nil actual return", "Current Account dominated", "Unexplained",
        "Pct outside tolerance", "Pct hot portfolios", "Pct auto explained of hot", "Pct unexplained of hot",
        "Check Within + Outside = Total", "Check No ARC + Cold + Hot = Outside", "Check Hot Waterfall = Hot",
        "RunValidationState", "ErrorCount", "WarningCount", "ProcessedAt",
    ]



def _trend_common_candidate_columns() -> List[str]:
    return ["RunDate", "Asset Type", "Number of Securities", "Number of Portfolios covered", "SourceFolder", "FolderFingerprint", "CacheVersion", "AppPythonVersion", "SettingsHash", "MV Tiny Upper Bound", "FX Line Match Tolerance Dollar", "Current Account Dominance Threshold Pct", "ProcessedAt"]


def _empty_trend_common_candidate_df() -> pd.DataFrame:
    return pd.DataFrame(columns=_trend_common_candidate_columns())


# v365: removed the FIRST (dead) definition of _trend_common_candidate_snapshot_df.
# Python re-binds this name at each top-level 'def' as the module loads; a later
# plain redefinition further down this file (kept) is the one actually bound at
# render time, so this earlier body never executed. See CHANGELOG.md v365.

def _trend_common_candidate_chart_long_df(common_candidate_df: pd.DataFrame) -> pd.DataFrame:
    cols = ["RunDate", "DateLabel", "Measure", "Asset Type", "Value", "_DateSort"]
    if common_candidate_df is None or not isinstance(common_candidate_df, pd.DataFrame) or common_candidate_df.empty:
        return pd.DataFrame(columns=cols)
    required = {"RunDate", "Asset Type", "Number of Securities", "Number of Portfolios covered"}
    if not required.issubset(set(common_candidate_df.columns)):
        return pd.DataFrame(columns=cols)
    work = common_candidate_df.copy()
    work["RunDate"] = pd.to_datetime(work["RunDate"], errors="coerce")
    work = work.dropna(subset=["RunDate"])
    for c in ["Number of Securities", "Number of Portfolios covered"]:
        work[c] = pd.to_numeric(work[c], errors="coerce").fillna(0)
    work["DateLabel"] = work["RunDate"].dt.strftime("%d/%m/%y")
    work["_DateSort"] = work["RunDate"].dt.strftime("%Y%m%d")
    return work.melt(id_vars=["RunDate", "DateLabel", "_DateSort", "Asset Type"], value_vars=["Number of Securities", "Number of Portfolios covered"], var_name="Measure", value_name="Value")


# v365: removed the FIRST of three (dead) definitions of
# _render_common_candidate_trend_chart. Only the LAST definition further down
# this file (kept) is actually bound and invoked at render time. See
# CHANGELOG.md v365.
def _trend_driver_columns() -> List[str]:
    return [
        "RunDate", "StageKey", "Stage", "Driver", "Portfolio count", "IsTotal",
        "SourceFolder", "FolderFingerprint", "CacheVersion", "AppPythonVersion", "SettingsHash",
        "MV Tiny Upper Bound", "FX Line Match Tolerance Dollar", "Current Account Dominance Threshold Pct",
    ]


def _trend_diagnostic_columns() -> List[str]:
    return ["RunDate", "Check", "Result", "Expected", "Actual", "Detail", "SourceFolder", "FolderFingerprint", "CacheVersion", "AppPythonVersion", "SettingsHash", "ProcessedAt"]


def _trend_exception_columns() -> List[str]:
    return ["RunDate", "SourceFolder", "FolderFingerprint", "CacheVersion", "AppPythonVersion", "SettingsHash", "Status", "ExceptionType", "ExceptionMessage", "ProcessedAt"]


def _trend_index_columns() -> List[str]:
    return [
        "RunDate", "SourceFolder", "FolderFingerprint", "CacheVersion", "AppPythonVersion", "SettingsHash",
        "MV Tiny Upper Bound", "FX Line Match Tolerance Dollar", "Current Account Dominance Threshold Pct",
        "ProcessedAt", "Status", "SummaryRows", "DriverRows", "DiagnosticRows", "ExceptionRows",
        "ErrorCount", "WarningCount", "ExceptionMessage",
    ]


def _empty_trend_summary_df() -> pd.DataFrame:
    return pd.DataFrame(columns=_trend_summary_columns())


def _empty_trend_driver_df() -> pd.DataFrame:
    return pd.DataFrame(columns=_trend_driver_columns())


def _empty_trend_diagnostic_df() -> pd.DataFrame:
    return pd.DataFrame(columns=_trend_diagnostic_columns())


def _empty_trend_exception_df() -> pd.DataFrame:
    return pd.DataFrame(columns=_trend_exception_columns())


def _empty_trend_index_df() -> pd.DataFrame:
    return pd.DataFrame(columns=_trend_index_columns())


def _trend_read_frame(path: str, empty_factory) -> pd.DataFrame:
    """Read a trend cache dataframe, with pickle fallback for environments without parquet engines."""
    try:
        if path and os.path.exists(path):
            return _read_parquet_if_exists(path)
    except Exception:
        pass
    try:
        fallback_path = str(path or "") + ".pkl"
        if fallback_path and os.path.exists(fallback_path):
            return pd.read_pickle(fallback_path)
    except Exception:
        pass
    try:
        return empty_factory()
    except Exception:
        return pd.DataFrame()


def _trend_write_frame(path: str, df: pd.DataFrame) -> Tuple[str, str]:
    """Write a trend cache dataframe.

    Primary format is parquet. If the local environment does not have a parquet
    engine, write a .pkl fallback so the app still has a durable cache.
    """
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    except Exception:
        pass
    out_df = df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()
    try:
        out_df.to_parquet(path, index=False)
        return "parquet", path
    except Exception as parquet_exc:
        fallback_path = str(path or "") + ".pkl"
        try:
            out_df.to_pickle(fallback_path)
            return "pickle", f"{fallback_path} after parquet error {type(parquet_exc).__name__}: {parquet_exc}"
        except Exception as pickle_exc:
            raise RuntimeError(f"Failed to write trend cache '{path}': parquet {type(parquet_exc).__name__}: {parquet_exc}; pickle {type(pickle_exc).__name__}: {pickle_exc}") from pickle_exc


def _read_trend_cache() -> Dict[str, pd.DataFrame]:
    """Read persisted executive trend cache tables."""
    paths = _trend_cache_manifest_paths()
    return {
        "summary_df": _trend_read_frame(paths["summary"], _empty_trend_summary_df),
        "driver_df": _trend_read_frame(paths["driver"], _empty_trend_driver_df),
        "common_candidates_df": _trend_read_frame(paths.get("common_candidates", COMMON_VALIDATION_CANDIDATES_FILE), _empty_trend_common_candidate_df),
        "diagnostic_df": _trend_read_frame(paths["diagnostic"], _empty_trend_diagnostic_df),
        "exception_df": _trend_read_frame(paths["exception"], _empty_trend_exception_df),
        "index_df": _trend_read_frame(paths["index"], _empty_trend_index_df),
    }


def _write_trend_cache(
    summary_df: pd.DataFrame,
    driver_df: pd.DataFrame,
    common_candidates_df: pd.DataFrame,
    diagnostic_df: pd.DataFrame,
    exception_df: pd.DataFrame,
    index_df: pd.DataFrame,
) -> pd.DataFrame:
    """Write persisted executive trend cache tables and return write diagnostics."""
    paths = _trend_cache_manifest_paths()
    write_rows: List[Dict[str, object]] = []
    for name, path, df in [
        ("summary", paths["summary"], summary_df),
        ("driver", paths["driver"], driver_df),
        ("common_candidates", paths.get("common_candidates", COMMON_VALIDATION_CANDIDATES_FILE), common_candidates_df),
        ("diagnostic", paths["diagnostic"], diagnostic_df),
        ("exception", paths["exception"], exception_df),
        ("index", paths["index"], index_df),
    ]:
        started = time.perf_counter()
        try:
            fmt, detail = _trend_write_frame(path, df if isinstance(df, pd.DataFrame) else pd.DataFrame())
            write_rows.append({"Table": name, "Status": "Written", "Format": fmt, "Rows": int(len(df)) if isinstance(df, pd.DataFrame) else 0, "Path": detail, "ElapsedSeconds": round(float(time.perf_counter() - started), 4)})
        except Exception as exc:
            write_rows.append({"Table": name, "Status": "Error", "Format": "", "Rows": int(len(df)) if isinstance(df, pd.DataFrame) else 0, "Path": path, "ElapsedSeconds": round(float(time.perf_counter() - started), 4), "Error": f"{type(exc).__name__}: {exc}"})
    return pd.DataFrame(write_rows)


def _trend_normalised_date_string(value: object) -> str:
    return _date_string_yyyy_mm_dd(value)


def _trend_selected_range_mask(df: pd.DataFrame, start_date: object, end_date: object) -> pd.Series:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty or "RunDate" not in df.columns:
        return pd.Series(False, index=getattr(df, "index", pd.Index([])))
    dates = pd.to_datetime(df["RunDate"], errors="coerce")
    start_ts = pd.to_datetime(start_date, errors="coerce")
    end_ts = pd.to_datetime(end_date, errors="coerce")
    if pd.isna(start_ts):
        start_ts = dates.min()
    if pd.isna(end_ts):
        end_ts = dates.max()
    return dates.between(pd.Timestamp(start_ts).normalize(), pd.Timestamp(end_ts).normalize(), inclusive="both")


def _trend_filter_cache_range(cache: Dict[str, pd.DataFrame], start_date: object, end_date: object, settings_hash: str = "") -> Dict[str, pd.DataFrame]:
    """Return cache tables filtered to date range and optional current settings hash."""
    out: Dict[str, pd.DataFrame] = {}
    for key, df in (cache or {}).items():
        if df is None or not isinstance(df, pd.DataFrame) or df.empty or "RunDate" not in df.columns:
            out[key] = df.copy() if isinstance(df, pd.DataFrame) else pd.DataFrame()
            continue
        mask = _trend_selected_range_mask(df, start_date, end_date)
        if "CacheVersion" in df.columns:
            mask = mask & df["CacheVersion"].astype(str).eq(str(globals().get("CACHE_VERSION", "")))
        if "AppPythonVersion" in df.columns:
            mask = mask & df["AppPythonVersion"].astype(str).eq(str(globals().get("APP_PYTHON_VERSION", "")))
        if settings_hash and "SettingsHash" in df.columns:
            mask = mask & df["SettingsHash"].astype(str).eq(str(settings_hash))
        out[key] = df.loc[mask].copy().reset_index(drop=True)
    return out


def _trend_cache_existing_hit(
    index_df: pd.DataFrame,
    run_date_str: str,
    folder: str,
    folder_fp: str,
    settings_hash: str,
) -> bool:
    """Return True when a date snapshot is valid for current source/settings."""
    if index_df is None or not isinstance(index_df, pd.DataFrame) or index_df.empty:
        return False
    required = {"RunDate", "SourceFolder", "FolderFingerprint", "CacheVersion", "AppPythonVersion", "SettingsHash", "Status"}
    if not required.issubset(set(index_df.columns)):
        return False
    work = index_df.copy()
    mask = (
        work["RunDate"].astype(str).eq(str(run_date_str))
        & work["SourceFolder"].astype(str).eq(str(folder or ""))
        & work["FolderFingerprint"].astype(str).eq(str(folder_fp or ""))
        & work["CacheVersion"].astype(str).eq(str(globals().get("CACHE_VERSION", "")))
        & work["AppPythonVersion"].astype(str).eq(str(globals().get("APP_PYTHON_VERSION", "")))
        & work["SettingsHash"].astype(str).eq(str(settings_hash or ""))
        & work["Status"].astype(str).str.upper().eq("OK")
    )
    return bool(mask.any())


def _trend_dedupe_cache_frames(
    summary_df: pd.DataFrame,
    driver_df: pd.DataFrame,
    common_candidates_df: pd.DataFrame,
    diagnostic_df: pd.DataFrame,
    exception_df: pd.DataFrame,
    index_df: pd.DataFrame,
) -> Dict[str, pd.DataFrame]:
    """Dedupe persisted trend cache frames using stable identity columns."""
    identity = ["RunDate", "SourceFolder", "FolderFingerprint", "SettingsHash"]
    try:
        summary_df = _dedupe_history(summary_df, [c for c in identity if c in summary_df.columns], ["RunDate", "SourceFolder", "SettingsHash"])
    except Exception:
        summary_df = summary_df.copy() if isinstance(summary_df, pd.DataFrame) else _empty_trend_summary_df()
    try:
        driver_subset = [c for c in identity + ["StageKey", "Driver", "IsTotal"] if c in driver_df.columns]
        driver_df = _dedupe_history(driver_df, driver_subset, ["RunDate", "StageKey", "Driver"])
    except Exception:
        driver_df = driver_df.copy() if isinstance(driver_df, pd.DataFrame) else _empty_trend_driver_df()
    try:
        common_subset = [c for c in identity + ["Asset Type"] if c in common_candidates_df.columns]
        common_candidates_df = _dedupe_history(common_candidates_df, common_subset, ["RunDate", "Asset Type"])
    except Exception:
        common_candidates_df = common_candidates_df.copy() if isinstance(common_candidates_df, pd.DataFrame) else _empty_trend_common_candidate_df()

    try:
        diagnostic_subset = [c for c in identity + ["Check"] if c in diagnostic_df.columns]
        diagnostic_df = _dedupe_history(diagnostic_df, diagnostic_subset, ["RunDate", "Check"])
    except Exception:
        diagnostic_df = diagnostic_df.copy() if isinstance(diagnostic_df, pd.DataFrame) else _empty_trend_diagnostic_df()
    try:
        exception_subset = [c for c in identity + ["ExceptionType", "ExceptionMessage"] if c in exception_df.columns]
        exception_df = _dedupe_history(exception_df, exception_subset, ["RunDate", "ExceptionType"])
    except Exception:
        exception_df = exception_df.copy() if isinstance(exception_df, pd.DataFrame) else _empty_trend_exception_df()
    try:
        index_df = _dedupe_history(index_df, [c for c in identity if c in index_df.columns], ["RunDate", "SourceFolder", "SettingsHash"])
    except Exception:
        index_df = index_df.copy() if isinstance(index_df, pd.DataFrame) else _empty_trend_index_df()
    return {"summary_df": summary_df, "driver_df": driver_df, "common_candidates_df": common_candidates_df, "diagnostic_df": diagnostic_df, "exception_df": exception_df, "index_df": index_df}


def _augment_trend_diagnostics(
    diagnostic_df: pd.DataFrame,
    *,
    run_date_str: str,
    folder: str,
    folder_fp: str,
    settings_hash: str,
    processed_at: str,
) -> pd.DataFrame:
    out = diagnostic_df.copy() if isinstance(diagnostic_df, pd.DataFrame) else _empty_trend_diagnostic_df()
    for col in _trend_diagnostic_columns():
        if col not in out.columns:
            out[col] = ""
    out["RunDate"] = out["RunDate"].where(out["RunDate"].astype(str).str.strip().ne(""), run_date_str)
    out["SourceFolder"] = str(folder or "")
    out["FolderFingerprint"] = str(folder_fp or "")
    out["CacheVersion"] = globals().get("CACHE_VERSION", "")
    out["AppPythonVersion"] = globals().get("APP_PYTHON_VERSION", "")
    out["SettingsHash"] = str(settings_hash or "")
    out["ProcessedAt"] = str(processed_at or "")
    return out[_trend_diagnostic_columns()].copy()


def _build_or_refresh_executive_trend_history(
    root_folder: str,
    start_date: object,
    end_date: object,
    tiny_upper: float,
    fx_line_match_tolerance_dollar: float,
    current_account_dominance_threshold_pct: float,
    *,
    force_refresh: bool = False,
    progress_callback=None,
) -> Dict[str, pd.DataFrame]:
    """Build or refresh persisted executive trend snapshots for a date range.

    v306.10.0 is intentionally a data/cache layer only. v306.11.0 will add the
    visible Trend History UI/charts over these returned and persisted frames.
    """
    started_total = time.perf_counter()
    settings_hash = _settings_hash_for_trend(tiny_upper, fx_line_match_tolerance_dollar, current_account_dominance_threshold_pct)
    cache = _read_trend_cache()
    summary_cache = cache.get("summary_df", _empty_trend_summary_df())
    driver_cache = cache.get("driver_df", _empty_trend_driver_df())
    common_candidates_cache = cache.get("common_candidates_df", _empty_trend_common_candidate_df())
    diagnostic_cache = cache.get("diagnostic_df", _empty_trend_diagnostic_df())
    exception_cache = cache.get("exception_df", _empty_trend_exception_df())
    index_cache = cache.get("index_df", _empty_trend_index_df())

    build_log_rows: List[Dict[str, object]] = []
    try:
        folders = scan_folders(root_folder, force_refresh=False)
    except Exception as exc:
        folders = []
        build_log_rows.append({"RunDate": "", "Status": "Error", "Detail": f"scan_folders failed: {type(exc).__name__}: {exc}"})

    start_ts = pd.to_datetime(start_date, errors="coerce")
    end_ts = pd.to_datetime(end_date, errors="coerce")
    if pd.isna(start_ts):
        start_ts = pd.Timestamp.min
    if pd.isna(end_ts):
        end_ts = pd.Timestamp.max
    start_ts = pd.Timestamp(start_ts).normalize()
    end_ts = pd.Timestamp(end_ts).normalize()

    selected_folders: List[Tuple[date, str]] = []
    for run_dt, folder in folders:
        try:
            run_ts = pd.Timestamp(run_dt).normalize()
            if start_ts <= run_ts <= end_ts:
                selected_folders.append((pd.Timestamp(run_ts).date(), str(folder)))
        except Exception:
            continue

    new_summary_frames: List[pd.DataFrame] = []
    new_driver_frames: List[pd.DataFrame] = []
    common_candidate_frames: List[pd.DataFrame] = []
    new_diagnostic_frames: List[pd.DataFrame] = []
    new_exception_frames: List[pd.DataFrame] = []
    new_index_rows: List[Dict[str, object]] = []

    for idx, (run_dt, folder) in enumerate(selected_folders, start=1):
        run_started = time.perf_counter()
        run_date_str = _trend_normalised_date_string(run_dt)
        if progress_callback is not None:
            try:
                progress_callback(idx, len(selected_folders), run_date_str)
            except Exception:
                pass
        try:
            fp = folder_fingerprint(folder)
        except Exception:
            fp = ""
        processed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if not force_refresh and _trend_cache_existing_hit(index_cache, run_date_str, folder, fp, settings_hash):
            build_log_rows.append({"RunDate": run_date_str, "Status": "Cached", "Detail": "Valid persisted snapshot reused", "ElapsedSeconds": round(float(time.perf_counter() - run_started), 4)})
            continue
        try:
            bundle = _prepare_out_dashboard_bundle(
                folder,
                tiny_upper,
                progress_callback=None,
                fx_timing_callback=None,
                force_source_refresh=bool(force_refresh),
                force_process_refresh=bool(force_refresh),
                fx_line_match_tolerance_dollar=fx_line_match_tolerance_dollar,
                current_account_dominance_threshold_pct=current_account_dominance_threshold_pct,
            )
            exchange_rate_bundle = bundle.get("exchange_rates", {}) if isinstance(bundle, dict) else {}
            auto_fx_summary_df = exchange_rate_bundle.get("portfolio_fx_summary_df", pd.DataFrame()) if isinstance(exchange_rate_bundle, dict) else pd.DataFrame()
            executive_driver_views = dict(bundle.get("tier1_driver_count_frames", {}) or {}) if isinstance(bundle, dict) else {}
            if not executive_driver_views and isinstance(bundle, dict):
                # Fallback for bundles made before the shared driver frame cache was populated.
                hot_df, auto_fx_df, nil_actual_df, current_account_df, unexplained_df = _hot_resolution_sets(bundle, auto_fx_summary_df)
                assignments_df = bundle.get("tier1_assignments_df", pd.DataFrame())
                portfolio_df = bundle.get("portfolio_df", pd.DataFrame())
                no_arc_df = portfolio_df[portfolio_df.get("Hot / Cold", pd.Series(dtype="object")).astype(str).str.strip().eq("No ARC match")].copy() if isinstance(portfolio_df, pd.DataFrame) and "Hot / Cold" in portfolio_df.columns else pd.DataFrame()
                cold_df = portfolio_df[portfolio_df.get("Hot / Cold", pd.Series(dtype="object")).astype(str).str.strip().eq("Cold")].copy() if isinstance(portfolio_df, pd.DataFrame) and "Hot / Cold" in portfolio_df.columns else pd.DataFrame()
                out_df = pd.concat([no_arc_df, cold_df, hot_df], ignore_index=True) if not no_arc_df.empty or not cold_df.empty or not hot_df.empty else pd.DataFrame()
                executive_driver_views = {
                    "out": _tier1_count_frame_from_assignments(out_df, assignments_df),
                    "no_arc": _tier1_count_frame_from_assignments(no_arc_df, assignments_df),
                    "cold": _tier1_count_frame_from_assignments(cold_df, assignments_df),
                    "hot": _tier1_count_frame_from_assignments(hot_df, assignments_df),
                    "auto_fx": _tier1_count_frame_from_assignments(auto_fx_df, assignments_df),
                    "nil_actual_return": _tier1_count_frame_from_assignments(nil_actual_df, assignments_df),
                    "current_account": _tier1_count_frame_from_assignments(current_account_df, assignments_df),
                    "unexplained": _tier1_count_frame_from_assignments(unexplained_df, assignments_df),
                }
            snapshot = _build_executive_trend_snapshot_from_bundle(run_dt, folder, fp, bundle, auto_fx_summary_df=auto_fx_summary_df, executive_driver_views=executive_driver_views)
            summary_df = snapshot.get("summary_df", _empty_trend_summary_df())
            driver_df = snapshot.get("driver_df", _empty_trend_driver_df())
            diagnostic_df = _augment_trend_diagnostics(snapshot.get("diagnostic_df", _empty_trend_diagnostic_df()), run_date_str=run_date_str, folder=folder, folder_fp=fp, settings_hash=settings_hash, processed_at=processed_at)
            exception_df = _empty_trend_exception_df()

            # v306.13.6.8: build common validation candidate Trend snapshot for this date.
            try:
                common_candidate_df = _trend_common_candidate_snapshot_df(
                    run_dt,
                    folder,
                    fp,
                    bundle,
                    auto_fx_summary_df,
                    settings_hash=settings_hash,
                    tiny_upper=tiny_upper,
                    fx_line_match_tolerance_dollar=fx_line_match_tolerance_dollar,
                    current_account_dominance_threshold_pct=current_account_dominance_threshold_pct,
                    processed_at=processed_at,
                )
            except Exception as _common_candidate_exc:
                common_candidate_df = _empty_trend_common_candidate_df()
                try:
                    diagnostic_df = pd.concat([
                        diagnostic_df,
                        pd.DataFrame([{
                            "RunDate": run_date_str,
                            "Check": "Common validation candidate Trend snapshot",
                            "Result": "Error",
                            "Expected": "Snapshot generated",
                            "Actual": "Exception",
                            "Detail": f"{type(_common_candidate_exc).__name__}: {_common_candidate_exc}",
                            "SourceFolder": str(folder or ""),
                            "FolderFingerprint": str(fp or ""),
                            "CacheVersion": globals().get("CACHE_VERSION", ""),
                            "AppPythonVersion": globals().get("APP_PYTHON_VERSION", ""),
                            "SettingsHash": settings_hash,
                            "ProcessedAt": processed_at,
                        }])
                    ], ignore_index=True, sort=False)
                except Exception:
                    pass
            common_candidate_frames.append(common_candidate_df)

            error_count = 0
            warning_count = 0
            if isinstance(summary_df, pd.DataFrame) and not summary_df.empty:
                error_count = _trend_safe_int(summary_df.iloc[0].get("ErrorCount", 0), 0)
                warning_count = _trend_safe_int(summary_df.iloc[0].get("WarningCount", 0), 0)
            status = "OK"
            exception_message = ""
            new_summary_frames.append(summary_df)
            new_driver_frames.append(driver_df)
            new_diagnostic_frames.append(diagnostic_df)
            new_exception_frames.append(exception_df)
            new_index_rows.append({
                "RunDate": run_date_str,
                "SourceFolder": str(folder or ""),
                "FolderFingerprint": str(fp or ""),
                "CacheVersion": globals().get("CACHE_VERSION", ""),
                "AppPythonVersion": globals().get("APP_PYTHON_VERSION", ""),
                "SettingsHash": settings_hash,
                "MV Tiny Upper Bound": _trend_safe_float(tiny_upper, DEFAULT_EXCLUDE_AMOUNT),
                "FX Line Match Tolerance Dollar": _trend_safe_float(fx_line_match_tolerance_dollar, 100.0),
                "Current Account Dominance Threshold Pct": _trend_safe_float(current_account_dominance_threshold_pct, DEFAULT_CURRENT_ACCOUNT_DOMINANCE_THRESHOLD_PCT),
                "ProcessedAt": processed_at,
                "Status": status,
                "SummaryRows": int(len(summary_df)) if isinstance(summary_df, pd.DataFrame) else 0,
                "DriverRows": int(len(driver_df)) if isinstance(driver_df, pd.DataFrame) else 0,
                "DiagnosticRows": int(len(diagnostic_df)) if isinstance(diagnostic_df, pd.DataFrame) else 0,
                "ExceptionRows": 0,
                "ErrorCount": error_count,
                "WarningCount": warning_count,
                "ExceptionMessage": exception_message,
            })
            build_log_rows.append({"RunDate": run_date_str, "Status": "Rebuilt", "Detail": f"summary_rows={len(summary_df) if isinstance(summary_df, pd.DataFrame) else 0}; driver_rows={len(driver_df) if isinstance(driver_df, pd.DataFrame) else 0}; common_candidate_rows={len(common_candidate_df) if isinstance(common_candidate_df, pd.DataFrame) else 0}", "ElapsedSeconds": round(float(time.perf_counter() - run_started), 4)})
        except Exception as exc:
            exception_message = f"{type(exc).__name__}: {exc}"
            exception_row = pd.DataFrame([{
                "RunDate": run_date_str,
                "SourceFolder": str(folder or ""),
                "FolderFingerprint": str(fp or ""),
                "CacheVersion": globals().get("CACHE_VERSION", ""),
                "AppPythonVersion": globals().get("APP_PYTHON_VERSION", ""),
                "SettingsHash": settings_hash,
                "Status": "ERROR",
                "ExceptionType": type(exc).__name__,
                "ExceptionMessage": str(exc),
                "ProcessedAt": processed_at,
            }])
            new_exception_frames.append(exception_row)
            new_index_rows.append({
                "RunDate": run_date_str,
                "SourceFolder": str(folder or ""),
                "FolderFingerprint": str(fp or ""),
                "CacheVersion": globals().get("CACHE_VERSION", ""),
                "AppPythonVersion": globals().get("APP_PYTHON_VERSION", ""),
                "SettingsHash": settings_hash,
                "MV Tiny Upper Bound": _trend_safe_float(tiny_upper, DEFAULT_EXCLUDE_AMOUNT),
                "FX Line Match Tolerance Dollar": _trend_safe_float(fx_line_match_tolerance_dollar, 100.0),
                "Current Account Dominance Threshold Pct": _trend_safe_float(current_account_dominance_threshold_pct, DEFAULT_CURRENT_ACCOUNT_DOMINANCE_THRESHOLD_PCT),
                "ProcessedAt": processed_at,
                "Status": "ERROR",
                "SummaryRows": 0,
                "DriverRows": 0,
                "DiagnosticRows": 0,
                "ExceptionRows": 1,
                "ErrorCount": 1,
                "WarningCount": 0,
                "ExceptionMessage": exception_message,
            })
            build_log_rows.append({"RunDate": run_date_str, "Status": "Error", "Detail": exception_message, "ElapsedSeconds": round(float(time.perf_counter() - run_started), 4)})

    combined_summary = pd.concat([summary_cache] + new_summary_frames, ignore_index=True, sort=False) if new_summary_frames else summary_cache.copy()
    combined_driver = pd.concat([driver_cache] + new_driver_frames, ignore_index=True, sort=False) if new_driver_frames else driver_cache.copy()
    combined_diagnostic = pd.concat([diagnostic_cache] + new_diagnostic_frames, ignore_index=True, sort=False) if new_diagnostic_frames else diagnostic_cache.copy()
    combined_exception = pd.concat([exception_cache] + new_exception_frames, ignore_index=True, sort=False) if new_exception_frames else exception_cache.copy()
    index_updates = pd.DataFrame(new_index_rows, columns=_trend_index_columns()) if new_index_rows else _empty_trend_index_df()
    combined_index = pd.concat([index_cache, index_updates], ignore_index=True, sort=False) if not index_updates.empty else index_cache.copy()


    # v306.13.6.8: combine existing common candidate cache with newly rebuilt date snapshots.
    combined_common_candidates = pd.concat([common_candidates_cache] + common_candidate_frames, ignore_index=True, sort=False) if common_candidate_frames else common_candidates_cache.copy()

    deduped = _trend_dedupe_cache_frames(
        combined_summary,
        combined_driver,
        combined_common_candidates,
        combined_diagnostic,
        combined_exception,
        combined_index,
    )
    write_status_df = _write_trend_cache(deduped["summary_df"], deduped["driver_df"], deduped.get("common_candidates_df", _empty_trend_common_candidate_df()), deduped["diagnostic_df"], deduped["exception_df"], deduped["index_df"])
    filtered = _trend_filter_cache_range(deduped, start_ts, end_ts, settings_hash=settings_hash)
    build_log_df = pd.DataFrame(build_log_rows)
    if build_log_df.empty:
        build_log_df = pd.DataFrame([{"RunDate": "", "Status": "No dates", "Detail": "No date folders matched the selected range", "ElapsedSeconds": round(float(time.perf_counter() - started_total), 4)}])
    filtered["write_status_df"] = write_status_df
    filtered["build_log_df"] = build_log_df
    filtered["cache_status_df"] = pd.DataFrame([{
        "SelectedStartDate": _date_string_yyyy_mm_dd(start_ts),
        "SelectedEndDate": _date_string_yyyy_mm_dd(end_ts),
        "SettingsHash": settings_hash,
        "SelectedFolderCount": int(len(selected_folders)),
        "RebuiltCount": int((build_log_df.get("Status", pd.Series(dtype="object")).astype(str).eq("Rebuilt")).sum()) if not build_log_df.empty else 0,
        "CachedCount": int((build_log_df.get("Status", pd.Series(dtype="object")).astype(str).eq("Cached")).sum()) if not build_log_df.empty else 0,
        "ErrorCount": int((build_log_df.get("Status", pd.Series(dtype="object")).astype(str).eq("Error")).sum()) if not build_log_df.empty else 0,
        "ElapsedSeconds": round(float(time.perf_counter() - started_total), 4),
    }])
    return filtered



# ========================================================
# TREND HISTORY EXCEL EXPORT (v306.12.0)
# ========================================================



# ========================================================
# TREND HISTORY TIMING DIAGNOSTICS PATCH (v306.13.6)
# ========================================================

TREND_TIMING_DIAGNOSTICS_PATCH_VERSION = "v306.13.6_trend_timing_diagnostics"
_TREND_TIMING_DIAGNOSTIC_ROWS: List[Dict[str, object]] = []
_TREND_TIMING_CONTEXT: Dict[str, object] = {}


def _trend_timing_diag_reset() -> None:
    global _TREND_TIMING_DIAGNOSTIC_ROWS, _TREND_TIMING_CONTEXT
    _TREND_TIMING_DIAGNOSTIC_ROWS = []
    _TREND_TIMING_CONTEXT = {}


def _trend_timing_diag_context(**kwargs) -> None:
    try:
        _TREND_TIMING_CONTEXT.update({str(k): v for k, v in kwargs.items()})
    except Exception:
        pass


def _trend_timing_diag_run_date_from_folder(folder: object) -> str:
    try:
        parsed = parse_date_from_path(str(folder or ""))
        if parsed:
            return _trend_normalised_date_string(parsed)
    except Exception:
        pass
    return ""


def _trend_timing_diag_add(phase: str, started_at: float, *, status: str = "Done", run_date: object = "", folder: object = "", rows: object = "", detail: object = "", scope: str = "Trend History", source: str = "instrumentation") -> None:
    try:
        elapsed = round(float(time.perf_counter() - started_at), 4)
    except Exception:
        elapsed = 0.0
    try:
        run_date_text = _trend_normalised_date_string(run_date) if str(run_date or "").strip() else str(_TREND_TIMING_CONTEXT.get("RunDate", "") or "")
    except Exception:
        run_date_text = str(run_date or _TREND_TIMING_CONTEXT.get("RunDate", "") or "")
    try:
        folder_text = str(folder or _TREND_TIMING_CONTEXT.get("SourceFolder", "") or "")
    except Exception:
        folder_text = ""
    _TREND_TIMING_DIAGNOSTIC_ROWS.append({
        "RunDate": run_date_text,
        "Scope": str(scope or "Trend History"),
        "Phase": str(phase or ""),
        "Status": str(status or ""),
        "ElapsedSeconds": elapsed,
        "Rows": rows,
        "SourceFolder": folder_text,
        "Detail": str(detail or ""),
        "TimingSource": str(source or "instrumentation"),
        "RecordedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "PatchVersion": TREND_TIMING_DIAGNOSTICS_PATCH_VERSION,
    })


def _trend_timing_diag_df() -> pd.DataFrame:
    cols = ["RunDate", "Scope", "Phase", "Status", "ElapsedSeconds", "Rows", "SourceFolder", "Detail", "TimingSource", "RecordedAt", "PatchVersion"]
    return pd.DataFrame(_TREND_TIMING_DIAGNOSTIC_ROWS, columns=cols) if _TREND_TIMING_DIAGNOSTIC_ROWS else pd.DataFrame(columns=cols)


def _trend_timing_diag_write_csv(df: pd.DataFrame) -> None:
    try:
        if isinstance(df, pd.DataFrame) and not df.empty:
            os.makedirs(CACHE_DIR, exist_ok=True)
            pass  # [removed] diagnostic CSV write
    except Exception:
        pass


def _trend_timing_diag_count_rows(value: object) -> object:
    try:
        if isinstance(value, pd.DataFrame):
            return int(len(value))
        if isinstance(value, dict):
            return int(sum(len(v) for v in value.values() if isinstance(v, pd.DataFrame)))
    except Exception:
        pass
    return ""


def _trend_timing_diag_extract_bundle_timings(bundle: object, run_date: object = "", folder: object = "") -> None:
    if not isinstance(bundle, dict):
        return
    for key, value in list(bundle.items()):
        if not isinstance(value, pd.DataFrame) or value.empty or "ElapsedSeconds" not in value.columns:
            continue
        key_text = str(key or "")
        if "timing" not in key_text.lower() and "diagnostic" not in key_text.lower():
            continue
        for _, row in value.iterrows():
            try:
                elapsed = float(pd.to_numeric(row.get("ElapsedSeconds", 0.0), errors="coerce") or 0.0)
            except Exception:
                elapsed = 0.0
            label = ""
            for candidate in ["Sub-step", "Phase", "Step", "Stage", "Check"]:
                if candidate in row.index and str(row.get(candidate, "")).strip():
                    label = str(row.get(candidate, "")).strip()
                    break
            if not label:
                label = key_text
            _TREND_TIMING_DIAGNOSTIC_ROWS.append({
                "RunDate": _trend_normalised_date_string(run_date) if str(run_date or "").strip() else _trend_timing_diag_run_date_from_folder(folder),
                "Scope": "Daily dashboard bundle internals",
                "Phase": f"{key_text}: {label}",
                "Status": str(row.get("Status", "Done") if "Status" in row.index else "Done"),
                "ElapsedSeconds": round(elapsed, 4),
                "Rows": row.get("Rows", "") if "Rows" in row.index else "",
                "SourceFolder": str(folder or ""),
                "Detail": str(row.get("Detail", "") if "Detail" in row.index else ""),
                "TimingSource": f"bundle.{key_text}",
                "RecordedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "PatchVersion": TREND_TIMING_DIAGNOSTICS_PATCH_VERSION,
            })


def _trend_timing_diag_wrap_function(function_name: str, phase: str, *, run_date_arg: int = -1, folder_arg: int = -1, rows_from_result: bool = True):
    original = globals().get(function_name)
    if not callable(original) or getattr(original, "_trend_timing_wrapped", False):
        return
    def _wrapped(*args, **kwargs):
        started = time.perf_counter()
        run_date = args[run_date_arg] if run_date_arg >= 0 and len(args) > run_date_arg else ""
        folder = args[folder_arg] if folder_arg >= 0 and len(args) > folder_arg else ""
        if not run_date and folder:
            run_date = _trend_timing_diag_run_date_from_folder(folder)
        if run_date or folder:
            _trend_timing_diag_context(RunDate=_trend_normalised_date_string(run_date) if str(run_date or "").strip() else "", SourceFolder=str(folder or ""))
        try:
            result = original(*args, **kwargs)
            rows = _trend_timing_diag_count_rows(result) if rows_from_result else ""
            _trend_timing_diag_add(phase, started, status="Done", run_date=run_date, folder=folder, rows=rows, scope="Trend History function")
            if function_name == "_prepare_out_dashboard_bundle":
                _trend_timing_diag_extract_bundle_timings(result, run_date=run_date, folder=folder)
            return result
        except Exception as exc:
            _trend_timing_diag_add(phase, started, status="Error", run_date=run_date, folder=folder, detail=f"{type(exc).__name__}: {exc}", scope="Trend History function")
            raise
    _wrapped._trend_timing_wrapped = True
    _wrapped._trend_timing_original = original
    globals()[function_name] = _wrapped


_trend_timing_diag_wrap_function("_read_trend_cache", "cache.read_all_tables", rows_from_result=True)
_trend_timing_diag_wrap_function("_trend_filter_cache_range", "cache.filter_selected_range", rows_from_result=True)
_trend_timing_diag_wrap_function("_trend_cache_existing_hit", "cache.per_date_hit_check", run_date_arg=1, folder_arg=2, rows_from_result=False)
_trend_timing_diag_wrap_function("folder_fingerprint", "source.folder_fingerprint", folder_arg=0, rows_from_result=False)
_trend_timing_diag_wrap_function("_prepare_out_dashboard_bundle", "bundle.prepare_out_dashboard_bundle", folder_arg=0, rows_from_result=True)
_trend_timing_diag_wrap_function("_build_executive_trend_snapshot_from_bundle", "snapshot.executive_summary_and_driver", run_date_arg=0, folder_arg=1, rows_from_result=True)
_trend_timing_diag_wrap_function("_trend_common_candidate_snapshot_df", "snapshot.common_validation_candidates", run_date_arg=0, folder_arg=1, rows_from_result=True)
_trend_timing_diag_wrap_function("_trend_dedupe_cache_frames", "cache.dedupe_frames", rows_from_result=True)
_trend_timing_diag_wrap_function("_write_trend_cache", "cache.write_all_tables", rows_from_result=True)


if callable(globals().get("_build_or_refresh_executive_trend_history")) and not getattr(globals().get("_build_or_refresh_executive_trend_history"), "_trend_timing_wrapped", False):
    _trend_timing_original_build_or_refresh = _build_or_refresh_executive_trend_history
    def _build_or_refresh_executive_trend_history(*args, **kwargs) -> Dict[str, pd.DataFrame]:
        _trend_timing_diag_reset()
        total_started = time.perf_counter()
        try:
            result = _trend_timing_original_build_or_refresh(*args, **kwargs)
            _trend_timing_diag_add("trend_history.total_build_or_refresh", total_started, status="Done", rows=_trend_timing_diag_count_rows(result), scope="Trend History total")
        except Exception as exc:
            _trend_timing_diag_add("trend_history.total_build_or_refresh", total_started, status="Error", detail=f"{type(exc).__name__}: {exc}", scope="Trend History total")
            timing_df = _trend_timing_diag_df()
            _trend_timing_diag_write_csv(timing_df)
            raise
        timing_df = _trend_timing_diag_df()
        _trend_timing_diag_write_csv(timing_df)
        if isinstance(result, dict):
            result["trend_timing_diagnostics_df"] = timing_df
            try:
                if not timing_df.empty:
                    result["trend_timing_summary_df"] = (
                        timing_df.groupby(["Scope", "Phase", "Status"], dropna=False)
                        .agg(ElapsedSeconds=("ElapsedSeconds", "sum"), Count=("Phase", "count"))
                        .reset_index()
                        .sort_values("ElapsedSeconds", ascending=False)
                    )
            except Exception:
                pass
        return result
    _build_or_refresh_executive_trend_history._trend_timing_wrapped = True
    _build_or_refresh_executive_trend_history._trend_timing_original = _trend_timing_original_build_or_refresh


# ========================================================
# v366: COMMON VALIDATION CANDIDATE RUNTIME DIAGNOSTICS v306.13.6.7 - REMOVED
# ========================================================
# Untangled and confirmed fully dead/inert after tracing the whole chain:
#
# 1) SNAPSHOT wrap (of _trend_common_candidate_snapshot_df) was DEAD: this
#    name gets a later PLAIN top-level 'def' redefinition further down the
#    file (kept, unchanged), which completely overwrites this diagnostic
#    closure - it never ran. This also made the standalone
#    _common_candidate_runtime_preflight() helper dead (it was only called
#    from inside this unreachable wrapper).
#
# 2) WRITE_CACHE wrap (of _write_trend_cache) WAS live (no later
#    redefinition existed to shadow it), but only added two diagnostic log
#    entries around the real cache write - purely instrumentation, no
#    business-logic change. Removing it restores _write_trend_cache to its
#    single, real definition.
#
# 3) BUILD wrap (of _build_or_refresh_executive_trend_history) WAS live and
#    part of a genuine decorator chain (dar75 -> dar73 -> trend_perf ->
#    THIS -> trend_timing -> core). It only reset/logged diagnostic rows
#    and stored 'common_candidate_runtime_diagnostics_df' /
#    '..._summary_df' on the result dict - confirmed via full-file search
#    that neither key is ever read anywhere else, and their CSV writes were
#    already stubbed to no-ops in an earlier cleanup. Removing this link
#    from the chain is transparent: the next wrap up (trend_perf_profile)
#    now simply captures the trend_timing-wrapped version as its
#    '_original', exactly as it would have if this link had never existed.
#
# Net effect: zero behaviour change, one fewer link in the
# _build_or_refresh_executive_trend_history decorator chain, and the two
# real diagnostic-log calls per cache write removed. See CHANGELOG.md v366.

def _trend_excel_safe_sheet_name(name: object) -> str:
    """Return a valid Excel sheet name, max 31 chars."""
    raw = str(name or "Sheet").strip() or "Sheet"
    for bad in ['\\', '/', '*', '?', ':', '[', ']']:
        raw = raw.replace(bad, ' ')
    raw = re.sub(r"\s+", " ", raw).strip()
    return raw[:31] or "Sheet"


def _trend_excel_clean_df(df: object) -> pd.DataFrame:
    """Return an Excel-safe dataframe without mutating the source."""
    if df is None or not isinstance(df, pd.DataFrame):
        return pd.DataFrame()
    out = df.copy()
    if out.columns.duplicated().any():
        out = out.loc[:, ~pd.Index(out.columns).duplicated()].copy()
    for col in out.columns:
        try:
            if str(out[col].dtype) == "object":
                out[col] = out[col].map(lambda v: "" if pd.isna(v) else v)
        except Exception:
            pass
    return out


def _trend_driver_pivot_df(driver_df: pd.DataFrame) -> pd.DataFrame:
    """Build a wide driver/stage pivot for Excel review."""
    if driver_df is None or not isinstance(driver_df, pd.DataFrame) or driver_df.empty:
        return pd.DataFrame(columns=["RunDate", "Driver"])
    required = {"RunDate", "Driver", "Stage", "Portfolio count"}
    if not required.issubset(set(driver_df.columns)):
        return pd.DataFrame(columns=["RunDate", "Driver"])
    work = driver_df.copy()
    if "IsTotal" in work.columns:
        work = work[~work["IsTotal"].astype(bool)].copy()
    work["Portfolio count"] = pd.to_numeric(work["Portfolio count"], errors="coerce").fillna(0)
    pivot = (
        work.pivot_table(
            index=["RunDate", "Driver"],
            columns="Stage",
            values="Portfolio count",
            aggfunc="sum",
            fill_value=0,
        )
        .reset_index()
    )
    pivot.columns = [str(c) for c in pivot.columns]
    preferred = [
        "RunDate", "Driver", "Outside tolerance", "No Error Risk", "Cold portfolios", "Hot portfolios",
        "Auto explained by FX", "Nil actual return", "Current Account dominated", "Unexplained",
    ]
    ordered = [c for c in preferred if c in pivot.columns] + [c for c in pivot.columns if c not in preferred]
    return pivot[ordered].sort_values(["RunDate", "Driver"]).reset_index(drop=True)


def _trend_parameters_df(
    start_date_value: object,
    end_date_value: object,
    settings: Dict[str, float],
    settings_hash: str,
    result: Dict[str, pd.DataFrame],
) -> pd.DataFrame:
    """Build the parameters/audit sheet for Trend History Excel export."""
    cache_status_df = result.get("cache_status_df", pd.DataFrame()) if isinstance(result, dict) else pd.DataFrame()
    rows = [
        {"Parameter": "Exported at", "Value": datetime.now().strftime("%Y-%m-%d %H:%M:%S")},
        {"Parameter": "Start date", "Value": _date_string_yyyy_mm_dd(start_date_value)},
        {"Parameter": "End date", "Value": _date_string_yyyy_mm_dd(end_date_value)},
        {"Parameter": "Settings hash", "Value": str(settings_hash or "")},
        {"Parameter": "MV Tiny upper bound", "Value": float(settings.get("tiny_upper", DEFAULT_EXCLUDE_AMOUNT)) if isinstance(settings, dict) else ""},
        {"Parameter": "Independent FX match tolerance ($)", "Value": float(settings.get("fx_line_match_tolerance_dollar", 100.0)) if isinstance(settings, dict) else ""},
        {"Parameter": "Current Account dominance threshold %", "Value": float(settings.get("current_account_dominance_threshold_pct", DEFAULT_CURRENT_ACCOUNT_DOMINANCE_THRESHOLD_PCT)) if isinstance(settings, dict) else ""},
        {"Parameter": "CACHE_VERSION", "Value": globals().get("CACHE_VERSION", "")},
        {"Parameter": "APP_PYTHON_VERSION", "Value": globals().get("APP_PYTHON_VERSION", "")},
        {"Parameter": "Summary rows", "Value": len(result.get("summary_df", pd.DataFrame())) if isinstance(result, dict) and isinstance(result.get("summary_df", pd.DataFrame()), pd.DataFrame) else 0},
        {"Parameter": "Driver rows", "Value": len(result.get("driver_df", pd.DataFrame())) if isinstance(result, dict) and isinstance(result.get("driver_df", pd.DataFrame()), pd.DataFrame) else 0},
    ]
    if isinstance(cache_status_df, pd.DataFrame) and not cache_status_df.empty:
        first = cache_status_df.iloc[0]
        for key in ["SelectedFolderCount", "RebuiltCount", "CachedCount", "ErrorCount", "ElapsedSeconds"]:
            if key in first.index:
                rows.append({"Parameter": key, "Value": first.get(key, "")})
    return pd.DataFrame(rows, columns=["Parameter", "Value"])


def _build_executive_trend_excel_export(
    result: Dict[str, pd.DataFrame],
    *,
    start_date_value: object = None,
    end_date_value: object = None,
    settings: Optional[Dict[str, float]] = None,
    settings_hash: str = "",
) -> bytes:
    """Build the Trend History Excel workbook bytes.

    Sheets:
    - Executive Summary
    - Driver Movement
    - Driver Pivot
    - Parameters
    - Build Index
    - Diagnostics
    - Exceptions
    - Build Log
    - Write Status
    """
    from io import BytesIO

    settings = settings or {}
    result = result if isinstance(result, dict) else {}
    summary_df = _trend_excel_clean_df(result.get("summary_df", pd.DataFrame()))
    driver_df = _trend_excel_clean_df(result.get("driver_df", pd.DataFrame()))
    index_df = _trend_excel_clean_df(result.get("index_df", pd.DataFrame()))
    diagnostic_df = _trend_excel_clean_df(result.get("diagnostic_df", pd.DataFrame()))
    exception_df = _trend_excel_clean_df(result.get("exception_df", pd.DataFrame()))
    build_log_df = _trend_excel_clean_df(result.get("build_log_df", pd.DataFrame()))
    write_status_df = _trend_excel_clean_df(result.get("write_status_df", pd.DataFrame()))
    parameters_df = _trend_parameters_df(start_date_value, end_date_value, settings, settings_hash, result)
    pivot_df = _trend_driver_pivot_df(driver_df)

    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        sheets = [
            ("Executive Summary", summary_df),
            ("Driver Movement", driver_df),
            ("Driver Pivot", pivot_df),
            ("Parameters", parameters_df),
            ("Build Index", index_df),
            ("Diagnostics", diagnostic_df),
            ("Exceptions", exception_df),
            ("Build Log", build_log_df),
            ("Write Status", write_status_df),
        ]
        for sheet_name, df in sheets:
            safe_name = _trend_excel_safe_sheet_name(sheet_name)
            clean_df = _trend_excel_clean_df(df)
            clean_df.to_excel(writer, sheet_name=safe_name, index=False)
            try:
                ws = writer.book[safe_name]
                ws.freeze_panes = "A2"
                for cell in ws[1]:
                    cell.style = "Headline 4"
                for column_cells in ws.columns:
                    try:
                        letter = column_cells[0].column_letter
                        max_len = max(len(str(c.value or "")) for c in column_cells[:200])
                        ws.column_dimensions[letter].width = min(max(max_len + 2, 10), 45)
                    except Exception:
                        pass
            except Exception:
                pass
    return output.getvalue()


def _render_trend_excel_download(
    result: Dict[str, pd.DataFrame],
    *,
    start_date_value: object,
    end_date_value: object,
    settings: Dict[str, float],
    settings_hash: str,
) -> None:
    """Render Trend History Excel download button when data is available."""
    summary_df = result.get("summary_df", pd.DataFrame()) if isinstance(result, dict) else pd.DataFrame()
    driver_df = result.get("driver_df", pd.DataFrame()) if isinstance(result, dict) else pd.DataFrame()
    common_candidates_df = result.get("common_candidates_df", pd.DataFrame()) if isinstance(result, dict) else pd.DataFrame()
    if summary_df is None or not isinstance(summary_df, pd.DataFrame) or summary_df.empty:
        st.info("Excel export will appear after trend history has summary rows for the selected date range/settings.")
        return
    try:
        excel_bytes = _build_executive_trend_excel_export(
            result,
            start_date_value=start_date_value,
            end_date_value=end_date_value,
            settings=settings,
            settings_hash=settings_hash,
        )
        start_label = _date_string_yyyy_mm_dd(start_date_value).replace("-", "") or "start"
        end_label = _date_string_yyyy_mm_dd(end_date_value).replace("-", "") or "end"
        st.download_button(
            "Download trend history Excel",
            data=excel_bytes,
            file_name=f"bnp_executive_trend_history_{start_label}_{end_label}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="download_trend_history_excel_v306_12_0",
            help=f"Exports {len(summary_df):,} summary rows and {len(driver_df) if isinstance(driver_df, pd.DataFrame) else 0:,} driver movement rows.",
        )
    except Exception as exc:
        st.error(f"Excel export failed: {type(exc).__name__}: {exc}")

# ========================================================
# TREND HISTORY UI / CHARTS (v306.11.0)
# ========================================================



def _trend_date_availability_bounds(dates: object) -> Dict[str, object]:
    clean_dates = []
    try:
        iterator = list(dates or [])
    except Exception:
        iterator = []
    for value in iterator:
        try:
            ts = pd.to_datetime(value, errors='coerce')
            if pd.notna(ts):
                clean_dates.append(pd.Timestamp(ts).date())
        except Exception:
            pass
    clean_dates = sorted(set(clean_dates))
    return {'count': int(len(clean_dates)), 'from': clean_dates[0] if clean_dates else None, 'to': clean_dates[-1] if clean_dates else None, 'dates': clean_dates}


def _trend_date_label(value: object) -> str:
    try:
        ts = pd.to_datetime(value, errors='coerce')
        if pd.isna(ts):
            return 'N/A'
        return pd.Timestamp(ts).strftime('%Y/%m/%d')
    except Exception:
        return 'N/A'



def _trend_arc_date_from_filename(file_name: object) -> Optional[date]:
    name = os.path.basename(str(file_name or "")).strip()
    lower = name.lower()
    if lower.startswith("~$") or not lower.endswith((".xlsb", ".xlsx", ".xlsm", ".xls")):
        return None
    match = re.match(r"^advisors\s+return\s+check\s+(?P<d>\d{2})(?P<m>\d{2})(?P<y>\d{4})\b", lower, flags=re.I)
    if not match:
        return None
    try:
        return date(int(match.group("y")), int(match.group("m")), int(match.group("d")))
    except Exception:
        return None


@st.cache_data(show_spinner=False)
def _trend_scan_available_arc_dates(arc_root_folder: str, arc_archive_root: str, cache_version: str, app_python_version: str) -> Dict[str, object]:
    _ = cache_version, app_python_version
    started = time.perf_counter()
    dates_found = set()
    files_seen = 0
    arc_files_seen = 0
    roots = []
    for root in [arc_root_folder, arc_archive_root]:
        root_text = str(root or "").strip()
        if root_text and root_text not in roots:
            roots.append(root_text)
    for root in roots:
        try:
            if not os.path.exists(root):
                continue
            for _dirpath, _dirnames, filenames in os.walk(root):
                for name in filenames:
                    lower = str(name or "").lower()
                    if lower.startswith("~$") or not lower.endswith((".xlsb", ".xlsx", ".xlsm", ".xls")):
                        continue
                    files_seen += 1
                    parsed = _trend_arc_date_from_filename(name)
                    if parsed:
                        arc_files_seen += 1
                        dates_found.add(parsed)
        except Exception:
            continue
    dates_sorted = sorted(dates_found)
    return {"dates": dates_sorted, "count": int(len(dates_sorted)), "from": dates_sorted[0] if dates_sorted else None, "to": dates_sorted[-1] if dates_sorted else None, "elapsed": round(float(time.perf_counter() - started), 2), "files_seen": int(files_seen), "arc_files_seen": int(arc_files_seen)}

def _trend_render_availability_metric(label: str, bounds: Dict[str, object], *, extra: str = '') -> None:
    st.metric(label, f"{int(bounds.get('count', 0) or 0):,}")
    if int(bounds.get('count', 0) or 0) > 0:
        caption = f"From: {_trend_date_label(bounds.get('from'))}  |  To: {_trend_date_label(bounds.get('to'))}"
    else:
        caption = 'From: N/A  |  To: N/A'
    if str(extra or '').strip():
        caption = caption + '\n' + str(extra)
    st.caption(caption)


def _trend_render_selected_range_warnings(start_value: object, end_value: object, bnp_bounds: Dict[str, object], arc_bounds: Dict[str, object]) -> None:
    try:
        selected_start = pd.Timestamp(pd.to_datetime(start_value, errors='coerce')).date()
        selected_end = pd.Timestamp(pd.to_datetime(end_value, errors='coerce')).date()
    except Exception:
        return
    for label, bounds in [('BNP', bnp_bounds), ('ARC', arc_bounds)]:
        if not isinstance(bounds, dict) or not bounds.get('from') or not bounds.get('to'):
            st.warning(f'{label} availability range could not be determined for this session.')
            continue
        if selected_start < bounds.get('from') or selected_end > bounds.get('to'):
            st.warning(f"Selected Trend History range {_trend_date_label(selected_start)} to {_trend_date_label(selected_end)} is outside the available {label} range {_trend_date_label(bounds.get('from'))} to {_trend_date_label(bounds.get('to'))}.")

def _trend_default_date_range(available_dates: List[date]) -> Tuple[Optional[date], Optional[date]]:
    """Return a sensible default trend date range from scanned BNP dates."""
    if not available_dates:
        return None, None
    dates = sorted(available_dates)
    end_dt = dates[-1]
    try:
        preferred_start = pd.Timestamp(end_dt) - pd.Timedelta(days=30)
        candidates = [d for d in dates if pd.Timestamp(d) >= preferred_start]
        start_dt = candidates[0] if candidates else dates[0]
    except Exception:
        start_dt = dates[0]
    return start_dt, end_dt


def _trend_display_numeric_summary(summary_df: pd.DataFrame) -> pd.DataFrame:
    """Return selected executive trend columns for screen display."""
    if summary_df is None or not isinstance(summary_df, pd.DataFrame) or summary_df.empty:
        return pd.DataFrame()
    cols = [
        "RunDate", "Total portfolios", "Within tolerance", "Outside tolerance", "No Error Risk", "Cold portfolios", "Hot portfolios",
        "Auto explained by FX", "Nil actual return", "Current Account dominated", "Unexplained",
        "Pct outside tolerance", "Pct hot portfolios", "Pct auto explained of hot", "Pct unexplained of hot",
        "Check Within + Outside = Total", "Check No ARC + Cold + Hot = Outside", "Check Hot Waterfall = Hot",
        "RunValidationState", "ErrorCount", "WarningCount",
    ]
    out = summary_df[[c for c in cols if c in summary_df.columns]].copy()
    if "RunDate" in out.columns:
        out = out.sort_values("RunDate").reset_index(drop=True)
    return out


def _trend_line_chart_df(summary_df: pd.DataFrame, columns: List[str]) -> pd.DataFrame:
    if summary_df is None or not isinstance(summary_df, pd.DataFrame) or summary_df.empty or "RunDate" not in summary_df.columns:
        return pd.DataFrame()
    keep = [c for c in columns if c in summary_df.columns]
    if not keep:
        return pd.DataFrame()
    out = summary_df[["RunDate"] + keep].copy()
    out["RunDate"] = pd.to_datetime(out["RunDate"], errors="coerce")
    out = out.dropna(subset=["RunDate"]).sort_values("RunDate")
    for col in keep:
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0)
    if out.empty:
        return pd.DataFrame()
    return out.set_index("RunDate")[keep]


def _trend_driver_chart_df(driver_df: pd.DataFrame, stage_label: str, top_n: int = 8) -> pd.DataFrame:
    if driver_df is None or not isinstance(driver_df, pd.DataFrame) or driver_df.empty:
        return pd.DataFrame()
    required = {"RunDate", "Stage", "Driver", "Portfolio count"}
    if not required.issubset(set(driver_df.columns)):
        return pd.DataFrame()
    work = driver_df.copy()
    work = work[~work.get("IsTotal", pd.Series(False, index=work.index)).astype(bool)].copy()
    work = work[work["Stage"].astype(str).eq(str(stage_label))].copy()
    if work.empty:
        return pd.DataFrame()
    work["Portfolio count"] = pd.to_numeric(work["Portfolio count"], errors="coerce").fillna(0)
    top_drivers = (
        work.groupby("Driver", dropna=False)["Portfolio count"].sum()
        .sort_values(ascending=False)
        .head(int(top_n))
        .index.astype(str)
        .tolist()
    )
    work = work[work["Driver"].astype(str).isin(top_drivers)].copy()
    work["RunDate"] = pd.to_datetime(work["RunDate"], errors="coerce")
    pivot = work.pivot_table(index="RunDate", columns="Driver", values="Portfolio count", aggfunc="sum", fill_value=0)
    return pivot.sort_index()



def _trend_chart_long_df(summary_df: pd.DataFrame, columns: List[str]) -> pd.DataFrame:
    # Return long-form chart data with dd/mm/yy x-axis labels.
    # Use string DateLabel so charts do not show 06 AM / 12 PM ticks.
    if summary_df is None or not isinstance(summary_df, pd.DataFrame) or summary_df.empty or "RunDate" not in summary_df.columns:
        return pd.DataFrame(columns=["RunDate", "DateLabel", "Metric", "Value"])
    keep = [c for c in columns if c in summary_df.columns]
    if not keep:
        return pd.DataFrame(columns=["RunDate", "DateLabel", "Metric", "Value"])
    out = summary_df[["RunDate"] + keep].copy()
    out["RunDate"] = pd.to_datetime(out["RunDate"], errors="coerce")
    out = out.dropna(subset=["RunDate"]).sort_values("RunDate")
    for col in keep:
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0)
    if out.empty:
        return pd.DataFrame(columns=["RunDate", "DateLabel", "Metric", "Value"])
    out["DateLabel"] = out["RunDate"].dt.strftime("%d/%m/%y")
    long_df = out.melt(id_vars=["RunDate", "DateLabel"], value_vars=keep, var_name="Metric", value_name="Value")
    long_df["Value"] = pd.to_numeric(long_df["Value"], errors="coerce").fillna(0)
    long_df["_DateSort"] = long_df["RunDate"].dt.strftime("%Y%m%d")
    return long_df


def _trend_driver_chart_long_df(driver_df: pd.DataFrame, stage_label: str, top_n: int = 8) -> pd.DataFrame:
    # Return long-form driver chart data with dd/mm/yy x-axis labels.
    if driver_df is None or not isinstance(driver_df, pd.DataFrame) or driver_df.empty:
        return pd.DataFrame(columns=["RunDate", "DateLabel", "Driver", "Portfolio count"])
    required = {"RunDate", "Stage", "Driver", "Portfolio count"}
    if not required.issubset(set(driver_df.columns)):
        return pd.DataFrame(columns=["RunDate", "DateLabel", "Driver", "Portfolio count"])
    work = driver_df.copy()
    if "IsTotal" in work.columns:
        work = work[~work["IsTotal"].astype(bool)].copy()
    work = work[work["Stage"].astype(str).eq(str(stage_label))].copy()
    if work.empty:
        return pd.DataFrame(columns=["RunDate", "DateLabel", "Driver", "Portfolio count"])
    work["Portfolio count"] = pd.to_numeric(work["Portfolio count"], errors="coerce").fillna(0)
    top_drivers = (
        work.groupby("Driver", dropna=False)["Portfolio count"].sum()
        .sort_values(ascending=False)
        .head(int(top_n))
        .index.astype(str)
        .tolist()
    )
    work = work[work["Driver"].astype(str).isin(top_drivers)].copy()
    work["RunDate"] = pd.to_datetime(work["RunDate"], errors="coerce")
    work = work.dropna(subset=["RunDate"]).sort_values("RunDate")
    if work.empty:
        return pd.DataFrame(columns=["RunDate", "DateLabel", "Driver", "Portfolio count"])
    work["DateLabel"] = work["RunDate"].dt.strftime("%d/%m/%y")
    work["_DateSort"] = work["RunDate"].dt.strftime("%Y%m%d")
    return work[["RunDate", "DateLabel", "_DateSort", "Driver", "Portfolio count"]].copy()


def _render_stacked_column_chart(
    chart_df: pd.DataFrame,
    *,
    x_field: str,
    colour_field: str,
    y_field: str,
    y_title: str,
    tooltip_fields: Optional[List[str]] = None,
    category_order: Optional[List[str]] = None,
    colour_map: Optional[Dict[str, str]] = None,
) -> None:
    # Stacked column chart with explicitly calculated segment positions.
    # This avoids Altair/Vega stack-order surprises and lets labels sit in the
    # exact horizontal and vertical centre of each non-zero bar segment.
    if chart_df is None or not isinstance(chart_df, pd.DataFrame) or chart_df.empty:
        st.info("No chart data available.")
        return
    try:
        import altair as alt
        tooltip_fields = tooltip_fields or [x_field, colour_field, y_field]
        work = chart_df.copy()
        work[y_field] = pd.to_numeric(work[y_field], errors="coerce").fillna(0)

        if "_DateSort" in work.columns and x_field == "DateLabel":
            sort_df = work[[x_field, "_DateSort"]].drop_duplicates().sort_values("_DateSort")
            x_sort = sort_df[x_field].astype(str).tolist()
        else:
            x_sort = work[x_field].astype(str).drop_duplicates().tolist()

        if category_order is None:
            category_order = work[colour_field].astype(str).drop_duplicates().tolist()
        category_order = [str(x) for x in category_order if str(x) in set(work[colour_field].astype(str))]
        if not category_order:
            category_order = work[colour_field].astype(str).drop_duplicates().tolist()
        order_map = {name: idx for idx, name in enumerate(category_order)}

        work[colour_field] = work[colour_field].astype(str)
        work["_StackOrder"] = work[colour_field].map(order_map).fillna(len(order_map)).astype(int)
        sort_cols = []
        if "_DateSort" in work.columns:
            sort_cols.append("_DateSort")
        sort_cols.extend([x_field, "_StackOrder", colour_field])
        work = work.sort_values(sort_cols).copy()
        work["_y0"] = work.groupby(x_field, dropna=False)[y_field].cumsum() - work[y_field]
        work["_y1"] = work["_y0"] + work[y_field]
        work["_y_mid"] = work["_y0"] + (work[y_field] / 2.0)
        label_df = work[work[y_field].ne(0)].copy()

        tooltip = [
            alt.Tooltip(f"{field}:Q", format=",.0f") if field == y_field else alt.Tooltip(f"{field}:N")
            for field in tooltip_fields
            if field in work.columns
        ]
        colour_scale = None
        if isinstance(colour_map, dict) and colour_map:
            colour_domain = [name for name in category_order if name in colour_map]
            colour_range = [colour_map[name] for name in colour_domain]
            if colour_domain and colour_range:
                colour_scale = alt.Scale(domain=colour_domain, range=colour_range)
        if colour_scale is None:
            palette = list(globals().get("TREND_DEFAULT_COLOUR_RANGE", [])) or ["#1F77B4", "#FF7F0E", "#2CA02C", "#D62728", "#9467BD"]
            colour_domain = list(category_order)
            colour_range = [palette[idx % len(palette)] for idx, _name in enumerate(colour_domain)]
            colour_scale = alt.Scale(domain=colour_domain, range=colour_range)
        base = alt.Chart(work).encode(
            x=alt.X(f"{x_field}:N", title="Run date", sort=x_sort, axis=alt.Axis(labelAngle=0)),
            color=alt.Color(f"{colour_field}:N", title=colour_field, sort=category_order, scale=colour_scale),
            tooltip=tooltip,
        )
        bars = base.mark_bar().encode(
            y=alt.Y("_y1:Q", title=y_title),
            y2=alt.Y2("_y0:Q"),
        )
        labels = alt.Chart(label_df).mark_text(
            align="center",
            baseline="middle",
            dx=0,
            dy=0,
            color="#111827",
            fontSize=11,
        ).encode(
            x=alt.X(f"{x_field}:N", sort=x_sort),
            y=alt.Y("_y_mid:Q"),
            detail=alt.Detail(f"{colour_field}:N"),
            text=alt.Text(f"{y_field}:Q", format=",.0f"),
        )
        st.altair_chart((bars + labels).properties(height=380), width="stretch")
    except Exception as exc:
        st.warning(f"Stacked chart render failed ({type(exc).__name__}: {exc}). Showing data table instead.")
        show_df(chart_df, hide_index=True)


def _trend_portfolio_numbers_chart_df(summary_df: pd.DataFrame) -> pd.DataFrame:
    """Return chart data with legacy Outside tolerance split into Cold and Hot."""
    required = ["Cold portfolios", "Within tolerance", "Hot portfolios"]
    chart_df = _trend_chart_long_df(summary_df, required)
    if chart_df.empty:
        return chart_df
    chart_df["Metric"] = chart_df["Metric"].replace({"Cold portfolios": "Cold", "Hot portfolios": "Hot"})
    return chart_df


def _render_trend_history_charts(summary_df: pd.DataFrame, driver_df: pd.DataFrame, common_candidates_df: Optional[pd.DataFrame] = None) -> None:
    # v306.12.4: stacked column charts with labels; no Total portfolios; no % metrics chart.
    if summary_df is None or not isinstance(summary_df, pd.DataFrame) or summary_df.empty:
        st.info("No executive trend summary rows are available for the selected date range/settings. Build or refresh trend history first.")
        return

    st.markdown("### Trend charts")
    st.caption("Charts are stacked columns by reporting date. X-axis labels use dd/mm/yy. Segment labels show portfolio counts. Colours are fixed across Trend tabs for easier review.")
    chart_tab_1, chart_tab_2, chart_tab_3, chart_tab_4 = st.tabs(["Portfolio Numbers", "Hot waterfall", "Driver movement", "Common validation candidates"])

    with chart_tab_1:
        chart_df = _trend_portfolio_numbers_chart_df(summary_df)
        if chart_df.empty:
            st.info("No Portfolio Numbers chart data available.")
        else:
            _render_stacked_column_chart(
                chart_df,
                x_field="DateLabel",
                colour_field="Metric",
                y_field="Value",
                y_title="Portfolio count",
                tooltip_fields=["DateLabel", "Metric", "Value"],
                category_order=TREND_PORTFOLIO_NUMBER_ORDER,
                colour_map=TREND_PORTFOLIO_NUMBER_COLOURS,
            )

    with chart_tab_2:
        chart_df = _trend_chart_long_df(summary_df, ["Auto explained by FX", "Nil actual return", "Current Account dominated", "Unexplained"])
        if chart_df.empty:
            st.info("No HOT waterfall chart data available.")
        else:
            _render_stacked_column_chart(
                chart_df,
                x_field="DateLabel",
                colour_field="Metric",
                y_field="Value",
                y_title="Portfolio count",
                tooltip_fields=["DateLabel", "Metric", "Value"],
                category_order=["Auto explained by FX", "Nil actual return", "Current Account dominated", "Unexplained"],
                colour_map=TREND_HOT_WATERFALL_COLOURS,
            )

    with chart_tab_3:
        stage_options = ["Hot portfolios", "Auto explained by FX", "Nil actual return", "Current Account dominated", "Unexplained"]
        selected_stage = st.selectbox("Driver movement stage", stage_options, index=stage_options.index("Unexplained"), key="trend_driver_stage_select")
        top_n = st.slider("Top drivers", min_value=3, max_value=15, value=8, step=1, key="trend_driver_top_n")
        chart_df = _trend_driver_chart_long_df(driver_df, selected_stage, top_n=top_n)
        if chart_df.empty:
            st.info("No driver movement chart data available for the selected stage.")
        else:
            _render_stacked_column_chart(chart_df, x_field="DateLabel", colour_field="Driver", y_field="Portfolio count", y_title="Portfolio count", tooltip_fields=["DateLabel", "Driver", "Portfolio count"])


    with chart_tab_4:
        _render_common_candidate_trend_chart(common_candidates_df if isinstance(common_candidates_df, pd.DataFrame) else pd.DataFrame())

def _v317_cfg_threshold(key: str, default: float) -> float:
    """Read a business threshold from Static Data 'thresholds' (config-only; the
    sidebar widget was removed). Falls back to the previous default."""
    try:
        sb = _ensure_static_data_bundle_v306_13_13() if callable(globals().get("_ensure_static_data_bundle_v306_13_13")) else globals().get("STATIC_DATA_BUNDLE")
        if sb is not None and callable(globals().get("_static_get_threshold_value_v306_13_8")):
            v = _static_get_threshold_value_v306_13_8(sb, key, default)
            if v is not None and str(v).strip() != "":
                return float(v)
    except Exception:
        pass
    return float(default)


def _trend_current_settings_from_sidebar() -> Dict[str, float]:
    """Render/reuse the same persistent business settings in Trend History mode."""
    settings = load_sidebar_settings()
    # v317: config-only (Static Data 'thresholds'); sidebar widgets removed.
    tiny_upper = _v317_cfg_threshold("default_exclude_amount", DEFAULT_EXCLUDE_AMOUNT)
    fx_line_match_tolerance_dollar = _v317_cfg_threshold("fx_line_match_tolerance_dollar", 100.0)
    current_account_dominance_threshold_pct = _v317_cfg_threshold("current_account_dominance_threshold_pct", DEFAULT_CURRENT_ACCOUNT_DOMINANCE_THRESHOLD_PCT)
    return {
        "tiny_upper": float(tiny_upper),
        "fx_line_match_tolerance_dollar": float(fx_line_match_tolerance_dollar),
        "current_account_dominance_threshold_pct": float(current_account_dominance_threshold_pct),
    }


def _render_trend_history_tables(result: Dict[str, pd.DataFrame]) -> None:
    """Render trend cache/result tables."""
    summary_df = result.get("summary_df", pd.DataFrame()) if isinstance(result, dict) else pd.DataFrame()
    driver_df = result.get("driver_df", pd.DataFrame()) if isinstance(result, dict) else pd.DataFrame()
    index_df = result.get("index_df", pd.DataFrame()) if isinstance(result, dict) else pd.DataFrame()
    diagnostic_df = result.get("diagnostic_df", pd.DataFrame()) if isinstance(result, dict) else pd.DataFrame()
    exception_df = result.get("exception_df", pd.DataFrame()) if isinstance(result, dict) else pd.DataFrame()
    build_log_df = result.get("build_log_df", pd.DataFrame()) if isinstance(result, dict) else pd.DataFrame()
    write_status_df = result.get("write_status_df", pd.DataFrame()) if isinstance(result, dict) else pd.DataFrame()
    trend_timing_diagnostics_df = result.get("trend_timing_diagnostics_df", pd.DataFrame()) if isinstance(result, dict) else pd.DataFrame()
    trend_timing_summary_df = result.get("trend_timing_summary_df", pd.DataFrame()) if isinstance(result, dict) else pd.DataFrame()

    st.markdown("### Trend tables")
    tabs = st.tabs(["Executive Summary", "Driver Movement", "Build Index", "Diagnostics", "Exceptions", "Build / Write Log"])
    with tabs[0]:
        show_df(_trend_display_numeric_summary(summary_df), hide_index=True)
    with tabs[1]:
        show_df(driver_df, hide_index=True)
    with tabs[2]:
        show_df(index_df, hide_index=True)
    with tabs[3]:
        show_df(diagnostic_df, hide_index=True)
    with tabs[4]:
        show_df(exception_df, hide_index=True)
    with tabs[5]:
        st.markdown("##### Build log")
        show_df(build_log_df, hide_index=True)
        st.markdown("##### Write status")
        show_df(write_status_df, hide_index=True)



def _trend_date_input(label: str, key: str, default_value: Optional[date], min_value: date, max_value: date) -> date:
    """Render a Trend History date_input without Streamlit session-state/default warnings.

    Important Streamlit rule: do not both set st.session_state[key] directly and
    pass value= for the same widget key in the same run. If the key is absent,
    pass value= and let the widget initialise its own state. If the key already
    exists, omit value= so Streamlit uses the existing widget state.
    """
    if key not in st.session_state:
        return st.date_input(
            label,
            value=default_value,
            min_value=min_value,
            max_value=max_value,
            key=key,
        )
    return st.date_input(
        label,
        min_value=min_value,
        max_value=max_value,
        key=key,
    )



# ========================================================
# TREND HISTORY TIMING VISIBILITY HOTFIX (v306.13.6.1)
# ========================================================

def _render_trend_timing_diagnostics_from_result(result: Dict[str, pd.DataFrame]) -> None:
    """[removed] timing diagnostic - body intentionally emptied."""
    return None
def _render_trend_history_dashboard(root_folder: str) -> None:
    """User-facing Trend History mode for persisted executive snapshots.

    v306.11.0 adds date-range controls, manual build/refresh, cache status,
    charts and tables. Excel export is deliberately held for v306.12.0.
    """
    st.title("BNP Control App - Trend History")
    st.caption("Builds and reuses persisted executive dashboard snapshots for a selected date range. Manual refresh only; chart/table interactions use cached snapshot data.")

    scan_started = time.perf_counter()
    try:
        folders = scan_folders(root_folder, force_refresh=False)
    except Exception as exc:
        folders = []
        st.error(f"Unable to scan BNP date folders: {type(exc).__name__}: {exc}")
    available_dates = sorted([d for d, _folder in folders]) if folders else []
    scan_elapsed = round(float(time.perf_counter() - scan_started), 4)
    if not available_dates:
        st.warning("No BNP date folders were found. Check the configured ROOT_FOLDER and network access.")
        return

    default_start, default_end = _trend_default_date_range(available_dates)

    settings = _trend_current_settings_from_sidebar()
    settings_hash = _settings_hash_for_trend(
        settings["tiny_upper"],
        settings["fx_line_match_tolerance_dollar"],
        settings["current_account_dominance_threshold_pct"],
    )

    with st.container(border=True):
        c1, c2, c3, c4, c5 = st.columns([1.05, 1.05, 1.0, 1.0, 1.0])
        with c1:
            start_date_value = _trend_date_input(
                "Start date",
                "trend_start_date",
                default_start,
                available_dates[0],
                available_dates[-1],
            )
        with c2:
            end_date_value = _trend_date_input(
                "End date",
                "trend_end_date",
                default_end,
                available_dates[0],
                available_dates[-1],
            )
        with c3:
            force_refresh = st.checkbox("Force refresh", value=False, key="trend_force_refresh", help="Rebuild selected date snapshots even if the persisted cache looks current.")
        _trend_bnp_bounds = _trend_date_availability_bounds(available_dates)
        _trend_arc_bounds = _trend_scan_available_arc_dates(ARC_ROOT_FOLDER, ARC_ARCHIVE_ROOT, CACHE_VERSION, APP_PYTHON_VERSION)
        with c4:
            _trend_render_availability_metric('Available BNP dates', _trend_bnp_bounds, extra=f'Folder scan: {scan_elapsed:.2f}s' if 'scan_elapsed' in locals() else '')
        with c5:
            _trend_render_availability_metric('Available ARC dates', _trend_arc_bounds, extra=f'ARC scan: {_trend_arc_bounds.get('elapsed', 0):.2f}s | matched ARC files: {_trend_arc_bounds.get('arc_files_seen', 0):,}')
        _trend_render_selected_range_warnings(locals().get('start_date_value', locals().get('start_date', locals().get('trend_start_date'))), locals().get('end_date_value', locals().get('end_date', locals().get('trend_end_date'))), _trend_bnp_bounds, _trend_arc_bounds)

        if pd.to_datetime(start_date_value) > pd.to_datetime(end_date_value):
            st.warning("Start date is after end date. Swap the dates to build trend history.")
            return

        selected_date_count = len([d for d in available_dates if pd.Timestamp(start_date_value) <= pd.Timestamp(d) <= pd.Timestamp(end_date_value)])
        st.caption(
            f"Selected dates: {selected_date_count:,}. Settings hash: {settings_hash}. "
            f"MV tiny={settings['tiny_upper']:,.2f}; FX tolerance=${settings['fx_line_match_tolerance_dollar']:,.2f}; "
            f"Current Account threshold={settings['current_account_dominance_threshold_pct']:,.2f}%."
        )

        build_clicked = st.button("Build / refresh trend history", type="primary", key="trend_build_refresh_button")

    if build_clicked:
        progress_bar = st.progress(0)
        status_placeholder = st.empty()

        def _trend_progress(idx: int, total: int, run_date_label: str) -> None:
            try:
                pct = int((idx / max(total, 1)) * 100)
            except Exception:
                pct = 0
            progress_bar.progress(max(0, min(100, pct)))
            status_placeholder.info(f"Processing {idx:,} of {total:,}: {run_date_label}")

        result = _build_or_refresh_executive_trend_history(
            root_folder,
            start_date_value,
            end_date_value,
            settings["tiny_upper"],
            settings["fx_line_match_tolerance_dollar"],
            settings["current_account_dominance_threshold_pct"],
            force_refresh=bool(force_refresh),
            progress_callback=_trend_progress,
        )
        st.session_state["trend_history_result"] = result
        progress_bar.progress(100)
        status_placeholder.success("Trend history build/refresh complete.")
    else:
        cached = _read_trend_cache()
        result = _trend_filter_cache_range(cached, start_date_value, end_date_value, settings_hash=settings_hash)
        # Preserve any richer result from this session if it matches the current settings/date range.
        session_result = st.session_state.get("trend_history_result")
        if isinstance(session_result, dict):
            session_status = session_result.get("cache_status_df", pd.DataFrame())
            try:
                if isinstance(session_status, pd.DataFrame) and not session_status.empty and str(session_status.iloc[0].get("SettingsHash", "")) == str(settings_hash):
                    result = session_result
            except Exception:
                pass

    cache_status_df = result.get("cache_status_df", pd.DataFrame()) if isinstance(result, dict) else pd.DataFrame()
    summary_df = result.get("summary_df", pd.DataFrame()) if isinstance(result, dict) else pd.DataFrame()
    driver_df = result.get("driver_df", pd.DataFrame()) if isinstance(result, dict) else pd.DataFrame()

    if isinstance(cache_status_df, pd.DataFrame) and not cache_status_df.empty:
        status = cache_status_df.iloc[0]
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric("Dates selected", f"{_trend_safe_int(status.get('SelectedFolderCount', selected_date_count)):,}")
        with c2:
            st.metric("Rebuilt", f"{_trend_safe_int(status.get('RebuiltCount', 0)):,}")
        with c3:
            st.metric("Cached", f"{_trend_safe_int(status.get('CachedCount', 0)):,}")
        with c4:
            st.metric("Errors", f"{_trend_safe_int(status.get('ErrorCount', 0)):,}")
    else:
        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric("Summary rows", f"{len(summary_df) if isinstance(summary_df, pd.DataFrame) else 0:,}")
        with c2:
            st.metric("Driver rows", f"{len(driver_df) if isinstance(driver_df, pd.DataFrame) else 0:,}")
        with c3:
            st.metric("Settings hash", settings_hash)

    _render_trend_excel_download(
        result if isinstance(result, dict) else {},
        start_date_value=start_date_value,
        end_date_value=end_date_value,
        settings=settings,
        settings_hash=settings_hash,
    )
    # [removed] "Trend History timing diagnostics" section.
    _render_trend_history_charts(summary_df, driver_df, result.get("common_candidates_df", pd.DataFrame()) if isinstance(result, dict) else pd.DataFrame())
    _render_trend_history_tables(result if isinstance(result, dict) else {})

def _render_inline_html(html: str, *, height: int = 360) -> None:
    """Render trusted internally generated HTML.

    v352 FIX: prefer st.html() over st.iframe(data:URI). The executive card HTML is a
    tiny (~2 KB) internally-generated string, but the old path URL-encoded the whole
    doc and loaded it as a `data:text/html` URI into an iframe - which the v351 run-log
    showed costing ~3s per render ("15 render executive summary HTML"), on every
    interaction. st.html() renders the same trusted inline HTML natively (no iframe, no
    URL-encoding), which is ~30x faster. st.iframe is kept only as a fallback for
    Streamlit builds without st.html."""
    if hasattr(st, "html"):
        st.html(str(html or ""))
        return
    if hasattr(st, "iframe"):
        st.iframe("data:text/html;charset=utf-8," + quote(str(html or "")), height=height)
        return
    st.markdown(str(html or ""), unsafe_allow_html=True)

V328_GROUPS = ["On UNISON", "Off UNISON", "IISL"]


def _v328_norm(v) -> str:
    return "".join(ch for ch in str(v or "").upper().strip() if ch.isalnum())


def _v328_group_map(bundle: Dict[str, object]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not isinstance(bundle, dict):
        return out
    # v344 (Part 2 - memoise per-click overhead): the group map is derived from the
    # universe (which is fixed for a given date) via a row-by-row iterrows loop. It
    # was rebuilt on EVERY sub-section click that scopes by group. Cache it on the
    # bundle keyed by the selected date so repeat clicks reuse it.
    _date_key = str(bundle.get("selected_date_label", ""))
    _cache = bundle.get("_v328_group_map_cache_v344")
    if isinstance(_cache, dict) and _cache.get("key") == _date_key and isinstance(_cache.get("map"), dict):
        return _cache["map"]
    uni = bundle.get("_universe_result_v308")
    if uni is None and callable(globals().get("_load_universe_v328")):
        try:
            uni = _load_universe_v328(bundle.get("static_data"))
            bundle["_universe_result_v308"] = uni
        except Exception:
            uni = None
    udf = getattr(uni, "universe_df", None) if uni is not None else None
    if not isinstance(udf, pd.DataFrame) or udf.empty or "Source" not in udf.columns:
        return out
    src_to_group = {"unison active advisors": "On UNISON",
                    "off-unison active advisors": "Off UNISON",
                    "off unison active advisors": "Off UNISON"}
    hip = "Hiport Code" if "Hiport Code" in udf.columns else None
    adv = "Advisor Code" if "Advisor Code" in udf.columns else None
    for _, r in udf.iterrows():
        grp = src_to_group.get(str(r.get("Source", "")).strip().lower())
        if not grp:
            continue
        if hip and r.get(hip):
            out.setdefault(_v328_norm(r[hip]), grp)
        if adv and r.get(adv):
            out.setdefault(_v328_norm(r[adv]), grp)
    # v344: cache the built map for this date so later clicks skip the iterrows build.
    try:
        bundle["_v328_group_map_cache_v344"] = {"key": _date_key, "map": out}
    except Exception:
        pass
    return out


def _v328_filter_to_group(portfolio_df: pd.DataFrame, group: str, gmap: Dict[str, str]) -> pd.DataFrame:
    if not isinstance(portfolio_df, pd.DataFrame) or portfolio_df.empty:
        return portfolio_df.iloc[0:0].copy() if isinstance(portfolio_df, pd.DataFrame) else pd.DataFrame()
    if group == "IISL" or not gmap:
        return portfolio_df.iloc[0:0].copy()
    code = portfolio_df["Portfolio code"].map(_v328_norm) if "Portfolio code" in portfolio_df.columns else pd.Series("", index=portfolio_df.index)
    grp = code.map(lambda k: gmap.get(k, ""))
    if "External portfolio reference" in portfolio_df.columns:
        adv = portfolio_df["External portfolio reference"].map(_v328_norm)
        grp = grp.where(grp.ne(""), adv.map(lambda k: gmap.get(k, "")))
    return portfolio_df[grp.eq(group)].copy()


def _v330_resolve_path(bundle, config_key: str) -> str:
    """Resolve a workbook path from Static Data 'paths' and try G:/UNC variants."""
    import os
    p = ""
    try:
        sb = bundle.get("static_data") if isinstance(bundle, dict) else None
        if callable(globals().get("_static_get_config_value_v306_13_8")):
            p = str(_static_get_config_value_v306_13_8(sb, config_key, "") or "")
    except Exception:
        p = ""
    if not p:
        return ""
    bs = chr(92)
    cands = [p]
    if p.upper().startswith("G:" + bs):
        cands.append(bs + bs + "hq.local" + bs + "Corp" + bs + p[3:].lstrip(bs))
    elif p.lower().startswith((bs + bs + "hq.local" + bs + "corp" + bs).lower()):
        cands.append("G:" + bs + p[len(bs + bs + "hq.local" + bs + "Corp" + bs):])
    for c in cands:
        if c and os.path.exists(c):
            return c
    return p


def _v330_mapping_total(bundle: Dict[str, object], group: str) -> Optional[int]:
    """v330 (TEMPORARY) Total portfolios from the CENTRAL MAPPING files, read
    DIRECTLY from the referenced workbooks (get_active_table only sees sheets inside
    Static Data.xlsx, so external references were returning nothing - that is why
    IISL showed 0). Off UNISON and IISL are separate feeds (not in BNP), so both
    show their mapping-file population until real feeds are wired. Returns None if
    unavailable (caller keeps the BNP count)."""
    import os
    try:
        if group == "Off UNISON":
            path = _v330_resolve_path(bundle, "central_mapping_workbook")
            if not path or not os.path.exists(path):
                return None
            # sheet name confirmed against the real MLC file: "Off-Unison Active Funds".
            for sheet in ("Off-Unison Active Funds", "Off Unison Active Funds", "Off-Unison Active Advisors"):
                try:
                    df = pd.read_excel(path, sheet_name=sheet)
                except Exception:
                    continue
                if isinstance(df, pd.DataFrame) and not df.empty:
                    # count rows with a non-blank first identifier column
                    key = df.columns[0]
                    return int((df[key].astype(str).str.strip() != "").sum())
            return None
        elif group == "IISL":
            path = _v330_resolve_path(bundle, "central_mapping_iisl_workbook")
            if not path or not os.path.exists(path):
                return None
            try:
                df = pd.read_excel(path, sheet_name="Mandates")
            except Exception:
                return None
            if not isinstance(df, pd.DataFrame) or df.empty:
                return None
            cols = {str(c).strip().lower(): c for c in df.columns}
            sc = cols.get("status")
            mc = cols.get("mandate code") or cols.get("mandatecode")
            work = df
            if mc:
                work = work[work[mc].astype(str).str.strip() != ""]
            if sc:
                work = work[work[sc].astype(str).str.strip().str.lower() == "active"]
            return int(len(work))
    except Exception:
        return None
    return None


def _v328_scope_exec_inputs(bundle: Dict[str, object], group: str, gmap: Dict[str, str]) -> Dict[str, object]:
    pf = bundle.get("portfolio_df", pd.DataFrame()) if isinstance(bundle, dict) else pd.DataFrame()
    gdf = _v328_filter_to_group(pf, group, gmap)
    total = int(len(gdf))
    # v330 (TEMPORARY): Off UNISON + IISL are separate feeds (never in BNP), so show
    # their Central Mapping population as Total until real feeds land.
    _mapping_total = None
    if group in ("Off UNISON", "IISL"):
        _mapping_total = _v330_mapping_total(bundle, group)
        if _mapping_total is not None:
            total = int(_mapping_total)
    within = int(gdf["Within Tolerance"].fillna(False).astype(bool).sum()) if "Within Tolerance" in gdf.columns else 0
    out = total - within
    hc = gdf.get("Hot / Cold", pd.Series(dtype="object")).astype(str).str.strip() if "Hot / Cold" in gdf.columns else pd.Series(dtype="object")
    no_arc_df = gdf[hc.isin(["No ARC match", "No BP Impact row", "No Error Risk row"])].copy() if len(hc) else gdf.iloc[0:0].copy()
    cold_df = gdf[hc.eq("Cold")].copy() if len(hc) else gdf.iloc[0:0].copy()
    hot = int(hc.eq("Hot").sum()) if len(hc) else 0
    fx = nil = ca = unexpl = 0
    driver_views: Dict[str, object] = {}
    try:
        gbundle = dict(bundle); gbundle["portfolio_df"] = gdf
        afx = bundle.get("auto_fx_summary_display_df", pd.DataFrame()) if isinstance(bundle, dict) else pd.DataFrame()
        hot_df, auto_fx_df, nil_df, ca_df, unexpl_df = _hot_resolution_sets(gbundle, afx if isinstance(afx, pd.DataFrame) else pd.DataFrame())
        fx, nil, ca, unexpl = int(len(auto_fx_df)), int(len(nil_df)), int(len(ca_df)), int(len(unexpl_df))
        assignments_df = bundle.get("tier1_assignments_df", pd.DataFrame()) if isinstance(bundle, dict) else pd.DataFrame()
        _out_df = pd.concat([no_arc_df, cold_df, hot_df], ignore_index=True) if (len(no_arc_df) + len(cold_df) + len(hot_df)) > 0 else pd.DataFrame()
        driver_views = {
            "out": _tier1_count_frame_from_assignments(_out_df, assignments_df),
            "no_arc": _tier1_count_frame_from_assignments(no_arc_df, assignments_df),
            "cold": _tier1_count_frame_from_assignments(cold_df, assignments_df),
            "hot": _tier1_count_frame_from_assignments(hot_df, assignments_df),
            "auto_fx": _tier1_count_frame_from_assignments(auto_fx_df, assignments_df),
            "nil_actual_return": _tier1_count_frame_from_assignments(nil_df, assignments_df),
            "current_account": _tier1_count_frame_from_assignments(ca_df, assignments_df),
            "unexplained": _tier1_count_frame_from_assignments(unexpl_df, assignments_df),
        }
    except Exception:
        driver_views = {}
    driver_views["_portfolio_counts"] = {"no_error_risk": int(len(no_arc_df)), "cold": int(len(cold_df)), "hot": hot}
    if _mapping_total is not None:
        out = int(total - within)
    return {"total": total, "within": within, "out": out, "hot": hot,
            "fx": fx, "nil": nil, "ca": ca, "unexpl": unexpl,
            "driver_views": driver_views, "is_placeholder": group == "IISL",
            "mapping_total": _mapping_total}


def _v328_render_group_radio_and_scope(bundle: Dict[str, object]):
    grp = st.radio("Portfolio group", V328_GROUPS, horizontal=True, key="exec_dashboard_group",
                   help="On/Off UNISON from the MLC Central Mapping universe. IISL is a separate feed (pending).")
    return grp, _v328_scope_exec_inputs(bundle, grp, _v328_group_map(bundle))


# v355 (PROTOTYPE): render the executive card with NATIVE Streamlit widgets instead of
# a custom-HTML component. The run-log showed "15 render executive summary HTML" ~3s at
# cold load - the cost is Streamlit MOUNTING the HTML component, which st.html didn't
# fix (v352). This prototype renders the SAME numbers via st.columns + st.dataframe (no
# HTML component), so it can be A/B'd against the HTML card by a sidebar toggle. Default
# OFF - zero change to current behaviour until you switch it on. The number computation
# is UNCHANGED (identical inputs -> identical values); only the final render differs.
_EXEC_CARD_NATIVE: Dict[str, bool] = {"on": False}


def set_exec_card_native(on: bool) -> None:
    _EXEC_CARD_NATIVE["on"] = bool(on)


def _render_exec_card_native(total_count, within_count, out_count, out_pct, no_arc_count,
                             cold_count, hot_count, hot_pct,
                             auto_explained_fx_count, nil_actual_return_count,
                             current_account_dominated_count, unexplained_count,
                             driver_views) -> None:
    """v355 native-widget executive card. Same data as the HTML card, rendered with
    st.container/columns/dataframe (no custom-HTML component mount)."""
    try:
        with st.container(border=True):
            left, right = st.columns([0.9, 1.6])
            with left:
                st.markdown("**PORTFOLIO NUMBERS**")
                m1, m2, m3 = st.columns(3)
                m1.metric("Total", f"{int(total_count):,}")
                m2.metric("Within", f"{int(within_count):,}")
                m3.metric("Outside", f"{int(out_count):,}", delta=str(out_pct), delta_color="off")
                m4, m5, m6 = st.columns(3)
                m4.metric("No Error Risk", f"{int(no_arc_count):,}")
                m5.metric("Cold", f"{int(cold_count):,}", help=COLD_PORTFOLIO_TOOLTIP)
                m6.metric("Hot", f"{int(hot_count):,}", delta=str(hot_pct), delta_color="off", help=HOT_PORTFOLIO_TOOLTIP)
                st.caption(
                    f"Checks: Within {int(within_count):,} + Outside {int(out_count):,} = Total {int(total_count):,}. "
                    f"No Error Risk {int(no_arc_count):,} + Cold {int(cold_count):,} + Hot {int(hot_count):,} = Outside {int(out_count):,}. "
                    f"Auto FX {int(auto_explained_fx_count):,} + Nil actual return {int(nil_actual_return_count):,} + "
                    f"Current Account dominated {int(current_account_dominated_count):,} + Unexplained {int(unexplained_count):,} = Hot {int(hot_count):,}."
                )
            with right:
                st.markdown("**DRIVER MOVEMENT**")
                rows, totals = _driver_stage_matrix_rows_data(driver_views or {})
                if rows:
                    tdf = pd.DataFrame(rows)
                    total_row = {"Driver": "Total"}
                    total_row.update({k: int(v) for k, v in totals.items()})
                    tdf = pd.concat([tdf, pd.DataFrame([total_row])], ignore_index=True)
                    st.dataframe(tdf, hide_index=True, width="stretch")
                else:
                    st.info("No driver movement data")
    except Exception as exc:
        # never let the prototype break the page - fall back to a plain note
        try:
            st.warning(f"Native exec card render failed: {type(exc).__name__}: {exc}")
        except Exception:
            pass


def _render_executive_flow_bar(run_date_value: object, total_count: int, within_count: int, out_count: int, hot_count: int, auto_explained_fx_count: int, nil_actual_return_count: int, current_account_dominated_count: int, unexplained_count: int, unexplained_driver_df: Optional[pd.DataFrame] = None, driver_views: Optional[Dict[str, pd.DataFrame]] = None):
    """Two-section executive summary with aligned OUT split."""
    driver_views = driver_views or {}
    no_arc_count = _sum_driver_counts(driver_views.get("no_arc"))
    cold_count = _sum_driver_counts(driver_views.get("cold"))
    hot_pct = _pct_of_total(hot_count, total_count)
    out_pct = _pct_of_total(out_count, total_count)
    css = """
    <style>
      .es-shell, .es-shell *{font-family:inherit;}
      .es-shell{border:1px solid #60A5FA;border-radius:16px;background:linear-gradient(135deg,#DBEAFE 0%,#EFF6FF 100%);box-shadow:0 10px 24px rgba(37,99,235,0.15);margin:0.42rem 0 0.60rem 0;overflow:hidden;}
      .es-grid{display:grid;grid-template-columns:0.72fr 1.53fr;gap:0.56rem;padding:0.62rem;}
      .es-panel{border:1px solid #BFDBFE;background:rgba(255,255,255,0.97);border-radius:14px;overflow:hidden;}
      .es-title{padding:0.42rem 0.58rem;background:#DBEAFE;border-bottom:1px solid #BFDBFE;color:#0F172A;font-size:0.76rem;font-weight:950;letter-spacing:0.035em;text-transform:uppercase;}
      .es-flow{padding:0.48rem 0.56rem;display:flex;flex-direction:column;gap:0.30rem;}
      .es-row{display:grid;grid-template-columns:1fr auto auto;align-items:center;gap:0.34rem;border:1px solid #E2E8F0;background:#F8FAFC;border-radius:999px;padding:0.22rem 0.42rem;min-height:29px;}
      .es-row.noarc{border-color:#CBD5E1;background:#F8FAFC;}
      .es-row.cold{border-color:#BAE6FD;background:#F0F9FF;}
      .es-row.hot{border-color:#FCA5A5;background:#FFF1F2;}
      .es-label{font-size:0.76rem;font-weight:900;color:#0F172A;line-height:1.05;white-space:normal;}
      .es-count{font-size:0.82rem;font-weight:950;font-variant-numeric:tabular-nums;color:#0F172A;}
      .es-pct{font-size:0.64rem;font-weight:950;color:#1D4ED8;background:#DBEAFE;border:1px solid #93C5FD;border-radius:999px;padding:0.04rem 0.26rem;white-space:nowrap;}
      .es-check{margin:0.18rem 0.08rem 0;color:#64748B;font-size:0.65rem;font-weight:800;line-height:1.16;}
      .es-table{width:100%;border-collapse:separate;border-spacing:0;font-size:0.71rem;}
      .es-table th{background:#EFF6FF;color:#334155;border-bottom:1px solid #BFDBFE;padding:0.36rem 0.34rem;text-align:center;font-weight:950;line-height:1.08;white-space:normal;}
      .es-table th:first-child{text-align:left;width:34%;}
      .es-table td{border-bottom:1px solid #E2E8F0;padding:0.31rem 0.34rem;text-align:center;vertical-align:middle;}
      .es-table tr:last-child td{border-bottom:0;}
      .es-driver{text-align:left!important;font-weight:900;color:#0F172A;line-height:1.08;}
      .es-pill{display:inline-flex;align-items:center;justify-content:center;min-width:1.95rem;border-radius:999px;padding:0.08rem 0.32rem;font-weight:950;font-variant-numeric:tabular-nums;background:#F8FAFC;border:1px solid #CBD5E1;color:#0F172A;}
      .es-hot{background:#FFF7ED;border-color:#FDBA74;}.es-fx{background:#ECFDF5;border-color:#86EFAC;}.es-nil{background:#FEF9C3;border-color:#FACC15;}.es-current-account{background:#F5F3FF;border-color:#C4B5FD;}.es-unexplained{background:#FEE2E2;border-color:#FCA5A5;}
      .es-empty{padding:0.55rem;text-align:center;color:#64748B;font-weight:800;}
      .es-total td{border-top:2px solid #BFDBFE;background:#F8FAFC;font-weight:800;}
      .es-total .es-driver{text-transform:uppercase;letter-spacing:0.035em;}
      @media (max-width: 980px){.es-grid{grid-template-columns:1fr}.es-table{font-size:0.69rem}}
    </style>
    """
    left = (
        "<div class='es-panel'><div class='es-title'>Portfolio numbers</div><div class='es-flow'>"
        f"<div class='es-row'><span class='es-label'>Total portfolios</span><span class='es-count'>{int(total_count):,}</span><span></span></div>"
        f"<div class='es-row'><span class='es-label'>Within tolerance</span><span class='es-count'>{int(within_count):,}</span><span></span></div>"
        f"<div class='es-row'><span class='es-label'>Outside tolerance</span><span class='es-count'>{int(out_count):,}</span><span class='es-pct'>{out_pct}</span></div>"
        f"<div class='es-row noarc'><span class='es-label'>No Error Risk</span><span class='es-count'>{int(no_arc_count):,}</span><span></span></div>"
        f"<div class='es-row cold' title='{_html_safe(COLD_PORTFOLIO_TOOLTIP)}'><span class='es-label' title='{_html_safe(COLD_PORTFOLIO_TOOLTIP)}'>Cold portfolios</span><span class='es-count'>{int(cold_count):,}</span><span></span></div>"
        f"<div class='es-row hot' title='{_html_safe(HOT_PORTFOLIO_TOOLTIP)}'><span class='es-label' title='{_html_safe(HOT_PORTFOLIO_TOOLTIP)}'>Hot portfolios</span><span class='es-count'>{int(hot_count):,}</span><span class='es-pct'>{hot_pct}</span></div>"
        f"<div class='es-check'>Checks: Within {int(within_count):,} + Outside {int(out_count):,} = Total {int(total_count):,}. No Error Risk {int(no_arc_count):,} + Cold {int(cold_count):,} + Hot {int(hot_count):,} = Outside {int(out_count):,}. Auto FX {int(auto_explained_fx_count):,} + Nil actual return {int(nil_actual_return_count):,} + Current Account dominated {int(current_account_dominated_count):,} + Unexplained {int(unexplained_count):,} = Hot {int(hot_count):,}.</div>"
        "</div></div>"
    )
    right = (
        "<div class='es-panel'><div class='es-title'>Driver movement</div><table class='es-table'>"
        "<thead><tr><th>Driver</th><th>Hot<br>portfolios</th><th>Auto explained<br>by FX</th><th>Nil actual<br>return</th><th>Current Account<br>dominated</th><th>Unexplained</th></tr></thead>"
        f"<tbody>{_driver_stage_matrix_rows_html(driver_views)}</tbody></table></div>"
    )
    # v355: render via NATIVE widgets when the prototype toggle is on, else the HTML
    # card (default). Numbers above are identical either way - only the render differs.
    if _EXEC_CARD_NATIVE.get("on"):
        _render_exec_card_native(
            total_count, within_count, out_count, out_pct, no_arc_count,
            cold_count, hot_count, hot_pct,
            auto_explained_fx_count, nil_actual_return_count,
            current_account_dominated_count, unexplained_count, driver_views,
        )
        return
    html = css + "<div class='es-shell'><div class='es-grid'>" + left + right + "</div></div>"
    _render_inline_html(html, height=360)


def _tier1_driver_card_html(context: str, df: pd.DataFrame, accent: str) -> str:
    return f"<span>{_html_safe(context)}</span>"


def _render_tier1_driver_trace(bundle: Dict[str, object], auto_fx_summary_df: pd.DataFrame) -> None:
    return

def _inject_app_chrome_css() -> None:
    """Reduce app chrome without disabling the Streamlit sidebar toggle.

    v297 root-cause fix:
    - Previous CSS made the whole Streamlit header/toolbar non-interactive using
      pointer-events:none. That can make the visible collapsed-sidebar icon fail
      hit testing.
    - Keep the Streamlit header interactive, and only hide/neutralise the specific
      Deploy/menu/status chrome that caused the original overlay issue.
    """
    st.markdown("""
<style>

/* v304.6 dashboard polish: cleaner executive shell, controls, cards, table chips */
:root{
  --pcd-navy:#0f172a;
  --pcd-blue:#2563eb;
  --pcd-sky:#dbeafe;
  --pcd-sky-2:#eff6ff;
  --pcd-border:#bfdbfe;
  --pcd-soft:#f8fafc;
  --pcd-green:#16a34a;
  --pcd-amber:#f59e0b;
  --pcd-red:#ef4444;
  --pcd-purple:#7c3aed;
}

/* Tighten top spacing without interfering with Streamlit toolbar click targets. */
.block-container{
  padding-top:1.35rem !important;
  max-width:96vw !important;
}

/* Main title */
h1, .pcd-title{
  letter-spacing:-0.045em !important;
  color:var(--pcd-navy) !important;
  font-weight:950 !important;
}

/* Date navigation buttons as flatter executive controls */
div[data-testid="stButton"] > button{
  border-radius:14px !important;
  border:1px solid #dbe3ef !important;
  background:linear-gradient(180deg,#ffffff 0%,#f8fafc 100%) !important;
  box-shadow:0 4px 14px rgba(15,23,42,.055) !important;
  font-weight:850 !important;
  color:#1e293b !important;
}
div[data-testid="stButton"] > button:hover{
  border-color:#93c5fd !important;
  box-shadow:0 8px 22px rgba(37,99,235,.14) !important;
  transform:translateY(-1px);
}

/* Radio selector: turn long row into compact segmented pills. */
div[role="radiogroup"]{
  gap:.42rem !important;
  flex-wrap:wrap !important;
  padding:.35rem .45rem !important;
  border:1px solid #e2e8f0 !important;
  border-radius:18px !important;
  background:linear-gradient(180deg,#ffffff 0%,#f8fafc 100%) !important;
  box-shadow:0 8px 26px rgba(15,23,42,.045) !important;
}
div[role="radiogroup"] label{
  margin:0 !important;
  padding:.48rem .72rem !important;
  border:1px solid #e2e8f0 !important;
  border-radius:999px !important;
  background:#ffffff !important;
  transition:all .16s ease !important;
}
div[role="radiogroup"] label:hover{
  border-color:#93c5fd !important;
  background:#eff6ff !important;
}
div[role="radiogroup"] label:has(input:checked){
  background:linear-gradient(135deg,#2563eb 0%,#60a5fa 100%) !important;
  border-color:#2563eb !important;
  color:#ffffff !important;
  box-shadow:0 8px 18px rgba(37,99,235,.22) !important;
}
div[role="radiogroup"] label:has(input:checked) p,
div[role="radiogroup"] label:has(input:checked) span{
  color:#ffffff !important;
  font-weight:900 !important;
}

/* Expander dashboard shell */
div[data-testid="stExpander"]{
  border:1px solid #d7e3f7 !important;
  border-radius:18px !important;
  overflow:hidden !important;
  box-shadow:0 12px 34px rgba(15,23,42,.07) !important;
}
div[data-testid="stExpander"] details > summary{
  background:linear-gradient(135deg,#f8fbff 0%,#eef6ff 100%) !important;
  border-bottom:1px solid #e2e8f0 !important;
}

/* Executive summary container/card feel */
.es-shell{
  border-radius:22px !important;
  border:1px solid #93c5fd !important;
  background:linear-gradient(135deg,#eff6ff 0%,#ffffff 52%,#eaf5ff 100%) !important;
  box-shadow:0 22px 50px rgba(37,99,235,.14) !important;
  overflow:hidden !important;
}
.es-panel{
  border-radius:18px !important;
  background:rgba(255,255,255,.86) !important;
  backdrop-filter:blur(8px) !important;
  border:1px solid #cfe0f7 !important;
  box-shadow:0 10px 26px rgba(15,23,42,.055) !important;
}
.es-title{
  background:linear-gradient(135deg,#dbeafe 0%,#f8fbff 100%) !important;
  color:#0f172a !important;
  font-size:.80rem !important;
  letter-spacing:.07em !important;
}
.es-row{
  border-radius:14px !important;
  min-height:38px !important;
  padding:.36rem .62rem !important;
  background:#ffffff !important;
  border-color:#e5edf8 !important;
}
.es-row.hot{
  background:linear-gradient(135deg,#fff7ed 0%,#fff1f2 100%) !important;
  border-color:#fca5a5 !important;
}
.es-row.cold{
  background:linear-gradient(135deg,#f0f9ff 0%,#ffffff 100%) !important;
}
.es-count{font-size:.92rem !important;}
.es-pct{background:#e0ecff !important; color:#1d4ed8 !important;}
.es-check{font-size:.70rem !important;color:#475569 !important;}

/* Driver movement table polish */
.es-table{
  border-spacing:0 !important;
  background:#ffffff !important;
  overflow:hidden !important;
}
.es-table th{
  background:linear-gradient(180deg,#eff6ff 0%,#eaf2ff 100%) !important;
  color:#334155 !important;
  text-transform:none !important;
  font-size:.72rem !important;
  border-bottom:1px solid #bfdbfe !important;
}
.es-table td{
  padding:.42rem .44rem !important;
  border-bottom:1px solid #e8eef7 !important;
}
.es-table tr:hover td{
  background:#f8fbff !important;
}
.es-pill{
  min-width:2.25rem !important;
  border-radius:999px !important;
  font-size:.74rem !important;
  padding:.12rem .42rem !important;
  box-shadow:inset 0 -1px 0 rgba(15,23,42,.06) !important;
}
.es-hot{background:#fff7ed !important;border-color:#fdba74 !important;color:#9a3412 !important;}
.es-fx{background:#ecfdf5 !important;border-color:#86efac !important;color:#166534 !important;}
.es-current-account{background:#f5f3ff !important;border-color:#c4b5fd !important;color:#5b21b6 !important;}
.es-unexplained{background:#fee2e2 !important;border-color:#fca5a5 !important;color:#991b1b !important;}
.es-total td{
  background:#f8fafc !important;
  border-top:2px solid #bfdbfe !important;
  font-weight:950 !important;
}

/* Loading timing strip: make it look intentional, not like a raw table. */
.pcd-loading-strip, .pcd-stage-strip{
  border-radius:18px !important;
  background:linear-gradient(135deg,#eaf2ff 0%,#f8fbff 100%) !important;
  border:1px solid #93c5fd !important;
  box-shadow:0 10px 24px rgba(37,99,235,.10) !important;
}

/* Streamlit toolbar note: keep pointer events intact so sidebar/date buttons remain clickable. */
header[data-testid="stHeader"]{
  background:transparent !important;
}

</style>
""", unsafe_allow_html=True)
    st.markdown(
        """
        <style>
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        [data-testid="stDecoration"] {display: none;}
        [data-testid="stStatusWidget"] {visibility: hidden; pointer-events: none !important;}

        /* v297 root-cause correction: do not make the whole header non-interactive.
           The sidebar open/close control is rendered in/near Streamlit chrome, so
           pointer-events:none on header/stHeader can make the icon visible but not clickable. */
        header,
        [data-testid="stHeader"] {
            visibility: visible !important;
            display: flex !important;
            opacity: 1 !important;
            pointer-events: auto !important;
            background: transparent !important;
            box-shadow: none !important;
            z-index: 4 !important;
        }

        /* Hide or neutralise only deploy/toolbar chrome, rather than the full header. */
        [data-testid="stDeployButton"],
        [data-testid="stToolbarActions"],
        [data-testid="stActionButton"],
        button[title="Deploy"],
        a[title="Deploy"],
        [aria-label="Deploy"] {
            display: none !important;
            visibility: hidden !important;
            width: 0 !important;
            min-width: 0 !important;
            opacity: 0 !important;
            pointer-events: none !important;
        }

        [data-testid="stToolbar"] {
            background: transparent !important;
            box-shadow: none !important;
        }

        /* Sidebar and its collapsed control must remain ordinary clickable chrome. */
        [data-testid="stSidebar"],
        section[data-testid="stSidebar"],
        [data-testid="collapsedControl"],
        [data-testid="stSidebarCollapsedControl"],
        button[aria-label="Open sidebar"],
        button[aria-label="Close sidebar"],
        button[title="Open sidebar"],
        button[title="Close sidebar"] {
            visibility: visible !important;
            opacity: 1 !important;
            pointer-events: auto !important;
            position: relative !important;
            z-index: 10000 !important;
        }

        .block-container {
            padding-top: 0.35rem;
            padding-bottom: 1.0rem;
            position: relative !important;
            z-index: 1 !important;
        }
        /* v304.1: do not lift every Streamlit column/button above the sidebar toggle.
           Only the dashboard date-nav wrapper receives the click-safety z-index. */
        .pcd-date-nav-click-layer {
            position: relative !important;
            z-index: 12 !important;
            pointer-events: auto !important;
        }
        .pcd-date-nav-click-layer ~ div,
        .pcd-date-nav-click-layer + div {
            position: relative !important;
            z-index: 12 !important;
            pointer-events: auto !important;
        }
        /* Sidebar collapsed/expanded controls must win hit testing over app content. */
        [data-testid="collapsedControl"],
        [data-testid="stSidebarCollapsedControl"],
        button[aria-label="Open sidebar"],
        button[aria-label="Close sidebar"],
        button[title="Open sidebar"],
        button[title="Close sidebar"] {
            position: relative !important;
            z-index: 10000 !important;
            pointer-events: auto !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )




DASHBOARD_SECTION_OPTIONS = [
    ("portfolio_count", "Portfolio Numbers"),
    ("portfolio_drillthrough", "Portfolio Drill-through"),
    ("auto_explained", "Auto Explained"),
    ("unexplained", "Unexplained"),
]
DASHBOARD_DEFAULT_SECTION = "portfolio_count"

def _dashboard_section_label_to_key(label_or_key: object) -> str:
    raw = str(label_or_key or "").strip()
    if raw in {"portfolio_count", "Portfolio Count", "Portfolio Numbers"}:
        return "portfolio_count"
    if raw in {"out_portfolios", "OUT Portfolios"}:
        return "portfolio_count"
    if raw in {
        "auto_fx", "Auto explained by FX", "Auto Explained by FX",
        "nil_actual_return", "Nil actual return",
        "current_account_dominated", "Current Account dominated",
    }:
        return "auto_explained"
    key_set = {k for k, _ in DASHBOARD_SECTION_OPTIONS}
    if raw in key_set:
        return raw
    lookup = {label: key for key, label in DASHBOARD_SECTION_OPTIONS}
    return lookup.get(raw, DASHBOARD_DEFAULT_SECTION)

def _dashboard_section_key_to_label(key_or_label: object) -> str:
    key = _dashboard_section_label_to_key(key_or_label)
    return {k: label for k, label in DASHBOARD_SECTION_OPTIONS}.get(key, "Portfolio Numbers")

def _get_dashboard_selected_section() -> str:
    key = _dashboard_section_label_to_key(st.session_state.get("dashboard_selected_section", DASHBOARD_DEFAULT_SECTION))
    st.session_state["dashboard_selected_section"] = key
    return key

def _set_dashboard_selected_section(value: object) -> str:
    key = _dashboard_section_label_to_key(value)
    st.session_state["dashboard_selected_section"] = key
    return key

def _normalise_dashboard_section_variable(value: object) -> str:
    return _set_dashboard_selected_section(value)

def _render_dashboard_date_header(container, selected_date: object, selected_index: int, available_dates: List[date]) -> Tuple[bool, bool]:
    """Render the stable top title/date navigation row once per script run.

    v280 keeps visual output unchanged, but isolates the static header/date controls
    from the loading progress refresh path so progress updates only touch the
    dashboard progress panel underneath.
    """
    with container:
        st.markdown("<div class='pcd-date-nav-click-layer'></div>", unsafe_allow_html=True)
        title_col, nav_prev, nav_mid, nav_next = st.columns([2.2, 1.0, 1.25, 1.0])
        title_col.markdown(
            "<div style='font-size:2.15rem;line-height:1.05;font-weight:850;color:#1F2937;padding-top:0.05rem;'>Super Unit Pricing Engine (sUPe)</div>",
            unsafe_allow_html=True,
        )
        prev_clicked = nav_prev.button(
            "◀ Previous date",
            disabled=(selected_index == 0),
            width="stretch",
            key=f"portfolio_dashboard_prev_date_v304_{selected_index}",
        )
        next_clicked = nav_next.button(
            "Next date ▶",
            disabled=(selected_index >= len(available_dates) - 1),
            width="stretch",
            key=f"portfolio_dashboard_next_date_v304_{selected_index}",
        )
        nav_mid.markdown(
            f"<div style='text-align:center; padding-top:0.15rem;'><span style='display:inline-block; padding:0.45rem 0.9rem; border-radius:999px; background:#F8FAFC; border:1px solid #CBD5E1; color:#0F172A; font-weight:700;'>Selected date: {_date_string_yyyy_mm_dd(selected_date)}</span></div>",
            unsafe_allow_html=True,
        )
    return prev_clicked, next_clicked

def render_out_portfolio_control_dashboard(root_folder: str):
    # v306.7.4 canonical dashboard section init
    _get_dashboard_selected_section()
    loading_stages = [
        "Scan BNP date folders", "Load BNP day files", "Portfolio calcs",
        "Load FX & Error Risk files", "Build executive summary", "Render dashboard tabs",
    ]
    # v280: Reserve a stable title/date navigation container before the dashboard shell.
    # Loading-stage updates are confined to the progress panel below, so the top
    # date controls are not re-rendered by progress refreshes.
    header_container = st.container()
    dashboard_shell = st.expander("Dashboard", expanded=True)
    with dashboard_shell:
        progress_panel = st.empty()
    load_started_at = time.perf_counter()
    stage_state = {stage: {"status": "Pending", "elapsed": None} for stage in loading_stages}
    active_stage = {"name": None, "started_at": None}
    fx_subtimings = []
    render_tab_timing_rows: List[Dict[str, object]] = []
    dashboard_wallclock_timing_rows: List[Dict[str, object]] = []
    # v306.4.4: hidden on cache-hit section changes; shown immediately when a real load/rebuild starts.
    progress_should_render = {"enabled": False}
    progress_timer_started_at = {"value": None}

    def _record_wallclock_timing(phase: str, started_at: float, rows: object = "", detail: str = "", status: str = "Done") -> None:
        try:
            elapsed = round(float(time.perf_counter() - started_at), 4)
        except Exception:
            elapsed = 0.0
        dashboard_wallclock_timing_rows.append({"Phase": str(phase or ""), "Status": str(status or "Done"), "ElapsedSeconds": elapsed, "Rows": rows, "Detail": str(detail or "")})

    def _stage_timing_df() -> pd.DataFrame:
        return pd.DataFrame([
            {
                "Stage": str(stage),
                "Status": str(info.get("status", "")),
                "ElapsedSeconds": float(info.get("elapsed") or 0.0),
            }
            for stage, info in stage_state.items()
        ])

    def _record_render_tab_timing(tab_name: str, started_at: float, rows: object = "", detail: str = "") -> None:
        render_tab_timing_rows.append({
            "Tab": str(tab_name),
            "ElapsedSeconds": round(float(time.perf_counter() - started_at), 4),
            "Rows": rows,
            "Detail": str(detail or ""),
        })

    def _render_progress() -> None:
        if not bool(progress_should_render.get("enabled", False)):
            return
        timer_start = progress_timer_started_at.get("value") or load_started_at
        _render_loading_progress_cards(progress_panel, stage_state, time.perf_counter() - float(timer_start), fx_subtimings=fx_subtimings)

    def _start_loading_progress(stage: str) -> None:
        """Enable progress display and delegate all phase transitions to _mark_stage."""
        progress_should_render["enabled"] = True
        if progress_timer_started_at.get("value") is None:
            progress_timer_started_at["value"] = time.perf_counter()
        _mark_stage(stage)

    def _mark_stage(stage: str) -> None:
        if not bool(progress_should_render.get("enabled", False)):
            return
        if stage in {"Load ARC.xlb", "Load FX.xlsx"}:
            stage = "Load FX & Error Risk files"
        now = time.perf_counter()
        previous = active_stage.get("name")
        if previous == stage and previous in stage_state and stage_state[previous]["status"] == "Running":
            _render_progress()
            return
        if previous and previous in stage_state and stage_state[previous]["status"] == "Running":
            stage_state[previous]["status"] = "Done"
            stage_state[previous]["elapsed"] = now - float(active_stage.get("started_at") or now)
        if stage in stage_state:
            stage_state[stage]["status"] = "Running"
            active_stage["name"] = stage
            active_stage["started_at"] = now
        _render_progress()

    def _complete_active_stage() -> None:
        if not bool(progress_should_render.get("enabled", False)):
            return
        now = time.perf_counter()
        previous = active_stage.get("name")
        if previous and previous in stage_state and stage_state[previous]["status"] == "Running":
            stage_state[previous]["status"] = "Done"
            stage_state[previous]["elapsed"] = now - float(active_stage.get("started_at") or now)
        active_stage["name"] = None
        active_stage["started_at"] = None
        # Defensive cleanup: no completed render should leave a stale Running phase.
        for _stage_name, _info in stage_state.items():
            if str(_info.get("status", "")).lower() == "running":
                _info["status"] = "Done"
                if _info.get("elapsed") is None:
                    _info["elapsed"] = 0.0
        _render_progress()

    def _mark_fx_subtiming(label: str, elapsed_seconds: float, status: str = "Done") -> None:
        if not bool(progress_should_render.get("enabled", False)):
            return
        fx_subtimings.append({
            "Sub-step": str(label),
            "Status": str(status or "Done"),
            "Elapsed": f"{float(elapsed_seconds):,.1f}s",
        })
        _render_progress()

    _render_progress()
    st.sidebar.header("Portfolio dashboard filters")
    refresh_date_folder_scan = st.sidebar.button(
        "Refresh date folder scan",
        help="Re-scan the BNP root date folders. Normal section navigation reuses the in-session date-folder list.",
    )
    _phase_started = time.perf_counter()
    date_folder_cache_key = "_bnp_dashboard_date_folders_cache_v306_4"
    cached_date_folders = st.session_state.get(date_folder_cache_key, {}) if hasattr(st, "session_state") else {}
    if isinstance(cached_date_folders, dict) and cached_date_folders.get("root_folder") == str(root_folder) and not bool(refresh_date_folder_scan):
        folders = cached_date_folders.get("folders", [])
        try:
            st.session_state["_bnp_manifest_status"] = {"Status": "Loaded from session date-folder cache", "FolderCount": int(len(folders)) if folders else 0, "Root": str(root_folder)}
        except Exception:
            pass
        _record_wallclock_timing("01 Scan BNP date folders", _phase_started, rows=int(len(folders)) if folders else 0, detail=f"session cache hit; root={root_folder}", status="Session cache hit")
    else:
        _start_loading_progress("Scan BNP date folders")
        folders = scan_folders(root_folder, force_refresh=bool(refresh_date_folder_scan))
        try:
            st.session_state[date_folder_cache_key] = {"root_folder": str(root_folder), "folders": folders}
        except Exception:
            pass
        _record_wallclock_timing("01 Scan BNP date folders", _phase_started, rows=int(len(folders)) if folders else 0, detail=str(root_folder), status="Refreshed" if bool(refresh_date_folder_scan) else "Scanned")
    if not folders:
        _complete_active_stage()
        st.error(f"No valid day folders found under: {root_folder}")
        return

    _phase_started = time.perf_counter()
    date_map = {d: p for d, p in folders}
    available_dates = sorted(date_map.keys())
    state_key = "portfolio_dashboard_selected_date"

    if state_key not in st.session_state or st.session_state[state_key] not in available_dates:
        st.session_state[state_key] = available_dates[-1]

    selected_date = st.session_state[state_key]
    selected_index = available_dates.index(selected_date)
    prev_clicked, next_clicked = _render_dashboard_date_header(
        header_container,
        selected_date,
        selected_index,
        available_dates,
    )

    if prev_clicked and selected_index > 0:
        st.session_state[state_key] = available_dates[selected_index - 1]
        st.rerun()
    if next_clicked and selected_index < len(available_dates) - 1:
        st.session_state[state_key] = available_dates[selected_index + 1]
        st.rerun()

    selected_date = st.session_state[state_key]

    sidebar_selected_date = st.sidebar.selectbox(
        "Run date",
        available_dates,
        index=available_dates.index(selected_date),
    )
    if sidebar_selected_date != selected_date:
        st.session_state[state_key] = sidebar_selected_date
        st.rerun()

    # v317: config-only (Static Data 'thresholds'); sidebar widgets removed.
    tiny_upper = _v317_cfg_threshold("default_exclude_amount", DEFAULT_EXCLUDE_AMOUNT)
    fx_line_match_tolerance_dollar = _v317_cfg_threshold("fx_line_match_tolerance_dollar", 100.0)
    current_account_dominance_threshold_pct = _v317_cfg_threshold("current_account_dominance_threshold_pct", DEFAULT_CURRENT_ACCOUNT_DOMINANCE_THRESHOLD_PCT)
    refresh_current_date_cache = st.sidebar.button(
        "Refresh current date cache",
        help="Force rebuild of the persistent BNP source cache for the selected date. It also enables/rebuilds the process_day persistent cache for this run; normal runs bypass that process_day cache.",
    )

    selected_date = st.session_state[state_key]
    folder = date_map[selected_date]
    _record_wallclock_timing("02 Date controls and sidebar inputs", _phase_started, rows=int(len(available_dates)), detail=f"selected_date={selected_date}; folder={folder}")

    _phase_started = time.perf_counter()
    dashboard_bundle_cache_key = "_bnp_dashboard_prepared_bundle_cache_v306_4"
    # v329: fold a SOURCE-FILE SIGNATURE into the bundle cache key. Previously the
    # key was (folder, date, settings, versions) with NO file signature, so a date
    # whose folder GAINED a file after the first load (e.g. a late-arriving
    # DAssetReturn fileset) still hit the session cache and served the STALE bundle -
    # the new file was never read and downstream numbers (e.g. Advisor-UUT income)
    # never recalculated. folder_fingerprint(folder) is an md5 of each file's
    # name + nanosecond mtime + size (a single directory listing, already used
    # elsewhere), so adding/updating/removing ANY file changes the hash and forces a
    # rebuild. Guarded: on any scan error it returns "" and the key degrades to the
    # prior behaviour (never worse). The "Refresh current date cache" button remains
    # as a manual override.
    try:
        _bundle_source_fp_v329 = folder_fingerprint(folder)
    except Exception:
        _bundle_source_fp_v329 = ""
    bundle_cache_lookup_key = (
        str(folder), str(selected_date), round(float(tiny_upper or 0.0), 6),
        round(float(fx_line_match_tolerance_dollar or 0.0), 2),
        round(float(current_account_dominance_threshold_pct or 0.0), 2),
        str(CACHE_VERSION), str(APP_PYTHON_VERSION),
        str(_bundle_source_fp_v329),
    )
    cached_bundle_payload = st.session_state.get(dashboard_bundle_cache_key, {}) if hasattr(st, "session_state") else {}
    bundle_cache_hit = isinstance(cached_bundle_payload, dict) and cached_bundle_payload.get("key") == bundle_cache_lookup_key and isinstance(cached_bundle_payload.get("bundle"), dict) and not bool(refresh_current_date_cache)
    if bundle_cache_hit:
        bundle = cached_bundle_payload.get("bundle")
        if isinstance(bundle, dict):
            bundle["dashboard_bundle_cache_status_df"] = pd.DataFrame([{"Status": "Session cache hit", "Key": str(bundle_cache_lookup_key)}])
        _record_wallclock_timing("03 Prepare dashboard bundle", _phase_started, rows=int(len(bundle.get("portfolio_df", pd.DataFrame()))) if isinstance(bundle, dict) and isinstance(bundle.get("portfolio_df", pd.DataFrame()), pd.DataFrame) else "", detail="session bundle cache hit", status="Session cache hit")
    else:
        _start_loading_progress("Load BNP day files")
        bundle = _prepare_out_dashboard_bundle(
            folder, tiny_upper, progress_callback=_mark_stage, fx_timing_callback=_mark_fx_subtiming,
            force_source_refresh=bool(refresh_current_date_cache), force_process_refresh=bool(refresh_current_date_cache),
            fx_line_match_tolerance_dollar=float(fx_line_match_tolerance_dollar),
            current_account_dominance_threshold_pct=float(current_account_dominance_threshold_pct),
        )
        if isinstance(bundle, dict):
            bundle["dashboard_bundle_cache_status_df"] = pd.DataFrame([{"Status": "Rebuilt", "Key": str(bundle_cache_lookup_key), "RefreshCurrentDateCache": bool(refresh_current_date_cache)}])
            try:
                st.session_state[dashboard_bundle_cache_key] = {"key": bundle_cache_lookup_key, "bundle": bundle}
            except Exception:
                pass
        _record_wallclock_timing("03 Prepare dashboard bundle", _phase_started, rows=int(len(bundle.get("portfolio_df", pd.DataFrame()))) if isinstance(bundle, dict) and isinstance(bundle.get("portfolio_df", pd.DataFrame()), pd.DataFrame) else "", detail=str(folder), status="Rebuilt")
    if isinstance(bundle, dict):
        bundle["dashboard_wallclock_timing_df"] = pd.DataFrame(dashboard_wallclock_timing_rows)
        bundle["loading_stage_timing_df"] = _stage_timing_df()
        bundle["load_portfolio_arc_fx_timing_df"] = pd.DataFrame(fx_subtimings)
        bundle["file_manifest_status_df"] = _manifest_status_df()
        bundle["file_manifest_status_df"] = _manifest_status_df()
        bundle["selected_date"] = selected_date
        bundle["selected_date_label"] = _date_string_yyyy_mm_dd(selected_date)
        # v306.14.5: apply final Basis Impact classification before card/table data is bound.
        # v349 (instrument-only): deep-time this render-side classification - it runs
        # AFTER prepare returns but BEFORE the executive summary build (interaction not
        # yet bumped), i.e. inside the ~31s cold-load gap, and reclassifies all DAR
        # rows. Naming its cost helps split the gap between this and the FDV resolver.
        # v354 (re-applied on v357): MEMOISE this render-side classification per date.
        # It was re-running on EVERY Streamlit rerun (every click) even on a bundle
        # cache HIT - a full copy + groupby + row-match (~0.2s) with no idempotency
        # guard, so ~24 of ~25 runs per session were pure repeat work adding lag to
        # every interaction. It is deterministic for a given date (portfolio_df /
        # error_df don't change between clicks), so run it ONCE per date and skip on
        # repeat clicks via a date-keyed flag, mirroring the proven v344
        # _bpimpact_classified pattern in _render_overview_tab. The stamped bundle is
        # stored to session_state, so subsequent reruns (cache hit) carry the flag and
        # skip. Verified: N clicks on one date = 1 classify; date switch re-runs once;
        # returning to a prior date does NOT re-run.
        try:
            _bi_date_key = str(bundle.get("selected_date_label", "")) if isinstance(bundle, dict) else ""
        except Exception:
            _bi_date_key = ""
        _bi_already = isinstance(bundle, dict) and bundle.get("_basis_impact_classified_v354") == _bi_date_key and _bi_date_key != ""
        try:
            if _bi_already:
                with _deep_timer({}, "Post-prepare (gap)", "basis-impact classification (cached)", cache_hit=True):
                    pass
            elif callable(globals().get("_apply_basis_impact_error_risk_classification_v306_14_5")):
                with _deep_timer({}, "Post-prepare (gap)", "basis-impact error-risk classification (render-side)"):
                    bundle = _apply_basis_impact_error_risk_classification_v306_14_5(bundle)
                if isinstance(bundle, dict) and _bi_date_key:
                    bundle["_basis_impact_classified_v354"] = _bi_date_key
                try:
                    st.session_state[dashboard_bundle_cache_key] = {"key": bundle_cache_lookup_key, "bundle": bundle}
                except Exception:
                    pass
        except Exception:
            pass
    portfolio_df = bundle["portfolio_df"]
    out = bundle["out"]
    # v343 (Part C): begin a new interaction for the deep-timing run-log. This NO
    # LONGER clears the log - the log now accumulates in st.session_state across
    # clicks so a full click-through builds ONE exportable CSV. Clearing is
    # user-driven via the "Clear timing log" button in the diagnostics panel.
    _deep_timing_begin_interaction(bundle)
    if portfolio_df.empty:
        _complete_active_stage()
        st.warning("No portfolio detail is available for the selected day.")
        return

    executive_summary_cache_key = "_bnp_dashboard_executive_summary_cache_v306_4_1"
    executive_summary_cache_lookup_key = (
        str(bundle_cache_lookup_key) if "bundle_cache_lookup_key" in locals() else str(folder),
        str(selected_date), str(APP_PYTHON_VERSION), "executive_summary_v1",
    )
    cached_executive_payload = st.session_state.get(executive_summary_cache_key, {}) if hasattr(st, "session_state") else {}
    executive_summary_cache_hit = isinstance(cached_executive_payload, dict) and cached_executive_payload.get("key") == executive_summary_cache_lookup_key and isinstance(cached_executive_payload.get("payload"), dict) and not bool(refresh_current_date_cache)
    _exec_summary_total_started = time.perf_counter()
    # v334: ONE shared placeholder for the executive group render, created BEFORE the
    # cache-hit / fresh branch split. Both branches render into this single position,
    # so switching branch (e.g. On UNISON <-> IISL) REPLACES the card cleanly instead
    # of ghosting the previous branch's render below.
    with dashboard_shell:
        _exec_group_ph = st.empty()
    if executive_summary_cache_hit:
        payload = cached_executive_payload.get("payload", {})
        total_count = payload.get("total_count", int(len(portfolio_df)) if isinstance(portfolio_df, pd.DataFrame) else 0)
        within_count = payload.get("within_count", 0)
        out_count = payload.get("out_count", 0)
        hot_count = payload.get("hot_count", 0)
        auto_explained_fx_count = payload.get("auto_explained_fx_count", 0)
        nil_actual_return_count = payload.get("nil_actual_return_count", 0)
        current_account_dominated_count = payload.get("current_account_dominated_count", 0)
        unexplained_count = payload.get("unexplained_count", 0)
        unexplained_driver_df = payload.get("unexplained_driver_df", pd.DataFrame())
        executive_driver_views = payload.get("executive_driver_views", {})
        auto_fx_summary_df = payload.get("auto_fx_summary_df", pd.DataFrame())
        try:
            _afx_write_diag(bundle, auto_fx_summary_df, stage="executive summary cache hit before render")
        except Exception:
            pass
        if not isinstance(executive_driver_views, dict):
            executive_driver_views = {}
        with dashboard_shell:
            try:
                _card_hotcold = portfolio_df.get("Hot / Cold", pd.Series(dtype="object")).astype(str).str.strip() if isinstance(portfolio_df, pd.DataFrame) and "Hot / Cold" in portfolio_df.columns else pd.Series(dtype="object")
                executive_driver_views["_portfolio_counts"] = {
                    "no_error_risk": int(_card_hotcold.isin(["No Error Risk row", "No BP Impact row", "No ARC match"]).sum()) if not _card_hotcold.empty else 0,
                    "cold": int(_card_hotcold.eq("Cold").sum()) if not _card_hotcold.empty else 0,
                    "hot": int(_card_hotcold.eq("Hot").sum()) if not _card_hotcold.empty else int(hot_count),
                }
            except Exception:
                pass
            # v333: group radio + executive render.
            # FIX (two issues): (1) the flow bar is rendered into a dedicated
            # st.empty() placeholder so a group toggle REPLACES the content cleanly
            # instead of leaving the previous dashboard ghosting below; (2) the group
            # radio is created ONCE up front (outside the flow-bar try) so a partial
            # failure can't leave a half-drawn radio, and the flow bar renders exactly
            # ONCE (no double-render from the old except fallback).
            # v334: render the group radio + executive card into the SINGLE hoisted
            # placeholder (_exec_group_ph). One position for both branches = clean
            # replace on every toggle, no ghosting, and paints on first load.
            with _exec_group_ph.container():
                try:
                    _v328_grp, _v328_sc = _v328_render_group_radio_and_scope(bundle)
                except Exception:
                    _v328_grp, _v328_sc = (V328_GROUPS[0] if "V328_GROUPS" in globals() else "On UNISON", None)
                try:
                    if isinstance(_v328_sc, dict) and _v328_sc.get("mapping_total") is not None:
                        _mt = int(_v328_sc.get("mapping_total") or 0)
                        st.info(f"Total portfolios ({_mt:,}) sourced from the Central Mapping file (TEMPORARY) - "
                                f"{_v328_grp} is a separate feed not yet wired into BNP, so the checks "
                                f"(Within / Outside / Hot / Cold) are pending.")
                    elif isinstance(_v328_sc, dict) and _v328_sc.get("is_placeholder"):
                        st.info("Pending feed - structure shown so the dashboard reads as one holistic 3-group solution.")
                    if isinstance(_v328_sc, dict):
                        _render_executive_flow_bar(selected_date, _v328_sc["total"], _v328_sc["within"], _v328_sc["out"], _v328_sc["hot"], _v328_sc["fx"], _v328_sc["nil"], _v328_sc["ca"], _v328_sc["unexpl"], unexplained_driver_df, driver_views=_v328_sc["driver_views"])
                    else:
                        _render_executive_flow_bar(selected_date, total_count, within_count, out_count, hot_count, auto_explained_fx_count, nil_actual_return_count, current_account_dominated_count, unexplained_count, unexplained_driver_df, driver_views=executive_driver_views)
                except Exception:
                    _render_executive_flow_bar(selected_date, total_count, within_count, out_count, hot_count, auto_explained_fx_count, nil_actual_return_count, current_account_dominated_count, unexplained_count, unexplained_driver_df, driver_views=executive_driver_views)
            _render_executive_trend_snapshot_debug(bundle)
        executive_summary_elapsed = round(float(time.perf_counter() - _exec_summary_total_started), 4)
        executive_summary_timing_rows = [
            {"Step": "Executive summary session cache hit", "ElapsedSeconds": executive_summary_elapsed, "Rows": int(len(portfolio_df)) if isinstance(portfolio_df, pd.DataFrame) else "", "Detail": "rendered from cached executive summary payload"},
            {"Step": "TOTAL Build executive summary", "ElapsedSeconds": executive_summary_elapsed, "Rows": "", "Detail": "session cache hit"},
        ]
        if isinstance(bundle, dict):
            bundle["executive_summary_timing_df"] = pd.DataFrame(executive_summary_timing_rows)
            # v306.9.0: keep selected-date trend snapshot frames available on executive summary cache hits.
            if isinstance(payload.get("executive_trend_summary_snapshot_df"), pd.DataFrame):
                bundle["executive_trend_summary_snapshot_df"] = payload.get("executive_trend_summary_snapshot_df")
            if isinstance(payload.get("executive_trend_driver_snapshot_df"), pd.DataFrame):
                bundle["executive_trend_driver_snapshot_df"] = payload.get("executive_trend_driver_snapshot_df")
            if isinstance(payload.get("executive_trend_diagnostic_snapshot_df"), pd.DataFrame):
                bundle["executive_trend_diagnostic_snapshot_df"] = payload.get("executive_trend_diagnostic_snapshot_df")
            if "executive_trend_summary_snapshot_df" not in bundle:
                _attach_executive_trend_snapshot_to_bundle(bundle, selected_date, folder, str(folder_fp if 'folder_fp' in locals() else ''), auto_fx_summary_df, executive_driver_views)
            bundle["executive_summary_cache_status_df"] = pd.DataFrame([{"Status": "Session cache hit", "Key": str(executive_summary_cache_lookup_key)}])
        if "Build executive summary" in stage_state:
            stage_state["Build executive summary"]["status"] = "Session cache hit"
            stage_state["Build executive summary"]["elapsed"] = executive_summary_elapsed
        _render_progress()
        _record_wallclock_timing("04 Build executive summary", _exec_summary_total_started, rows=int(len(portfolio_df)) if isinstance(portfolio_df, pd.DataFrame) else "", detail="executive summary session cache hit", status="Session cache hit")
        if isinstance(bundle, dict):
            bundle["dashboard_wallclock_timing_df"] = pd.DataFrame(dashboard_wallclock_timing_rows)
            bundle["loading_stage_timing_df"] = _stage_timing_df()
            bundle["load_portfolio_arc_fx_timing_df"] = pd.DataFrame(fx_subtimings)
            bundle["file_manifest_status_df"] = _manifest_status_df()
    else:
        _start_loading_progress("Build executive summary")
        executive_summary_timing_rows: List[Dict[str, object]] = []
        _exec_summary_total_started = time.perf_counter()
        _exec_step_started = _exec_summary_total_started

        def _exec_mark(label: str, rows: object = "", detail: str = "") -> None:
            nonlocal _exec_step_started
            now = time.perf_counter()
            try:
                elapsed = float(now - _exec_step_started)
            except Exception:
                elapsed = 0.0
            executive_summary_timing_rows.append({
                "Step": str(label),
                "ElapsedSeconds": round(elapsed, 4),
                "Rows": rows,
                "Detail": str(detail or ""),
            })
            # v348 (instrument-only): mirror each executive-summary build step into the
            # deep-timing run-log too. The ~39s cold-load gap in the v347 log sits
            # between the end of prepare and the warm-up checks - the executive summary
            # build (cache-miss branch: hot resolution sets, Tier 1 driver views, trend
            # snapshot) runs in exactly that window, so surfacing these steps pins down
            # whether the culprit is here rather than in prepare. No behaviour change.
            try:
                _store = _deep_timing_store(None)
                _store.append({
                    "Interaction": _deep_timing_current_interaction(),
                    "Sequence": len(_store) + 1,
                    "Phase": "Executive summary build",
                    "Function": str(label),
                    "Status": "Done",
                    "ElapsedSeconds": round(float(elapsed), 4),
                    "Rows": rows,
                    "CacheHit": "",
                    "Detail": str(detail or ""),
                    "StartedAt": round(float(_exec_step_started), 4),
                })
            except Exception:
                pass
            _exec_step_started = now

        total_count = int(len(portfolio_df))
        within_count = int(portfolio_df["Within Tolerance"].sum()) if "Within Tolerance" in portfolio_df.columns else 0
        out_count = int((~portfolio_df["Within Tolerance"]).sum()) if "Within Tolerance" in portfolio_df.columns else 0
        exchange_rate_bundle = bundle.get("exchange_rates", {}) if isinstance(bundle, dict) else {}
        auto_fx_summary_df = exchange_rate_bundle.get("portfolio_fx_summary_df", pd.DataFrame()) if isinstance(exchange_rate_bundle, dict) else pd.DataFrame()
        try:
            _afx_write_diag(bundle, auto_fx_summary_df, stage="before _hot_resolution_sets")
        except Exception:
            pass
        hot_df, _auto_fx_exec_df_for_counts, _nil_actual_return_exec_df_for_counts, _current_account_exec_df_for_counts, unexplained_exec_df_for_counts = _hot_resolution_sets(bundle, auto_fx_summary_df)
        try:
            _afx_write_diag(bundle, auto_fx_summary_df, stage=f"after _hot_resolution_sets; auto_fx_rows={len(_auto_fx_exec_df_for_counts) if isinstance(_auto_fx_exec_df_for_counts, pd.DataFrame) else 0}")
        except Exception:
            pass
        hot_count = int(len(hot_df))
        auto_explained_fx_count = int(len(_auto_fx_exec_df_for_counts))
        nil_actual_return_count = int(len(_nil_actual_return_exec_df_for_counts))
        current_account_dominated_count = int(len(_current_account_exec_df_for_counts))
        unexplained_count = int(len(unexplained_exec_df_for_counts))
        _exec_mark(
            "01 counts and auto-explained totals",
            int(len(portfolio_df)),
            f"total={total_count:,}; within={within_count:,}; out={out_count:,}; hot={hot_count:,}; auto_fx={auto_explained_fx_count:,}; nil_actual_return={nil_actual_return_count:,}; current_account={current_account_dominated_count:,}; unexplained={unexplained_count:,}",
        )

        dat_source_for_exec = bundle.get("dat_index") or bundle.get("dat") if isinstance(bundle, dict) else pd.DataFrame()
        dar_source_for_exec = bundle.get("dar_index") or bundle.get("dar") if isinstance(bundle, dict) else pd.DataFrame()
        portfolio_df_for_exec = bundle.get("portfolio_df", pd.DataFrame()) if isinstance(bundle, dict) else pd.DataFrame()
        _exec_mark(
            "02 resolve executive data sources",
            int(len(portfolio_df_for_exec)) if isinstance(portfolio_df_for_exec, pd.DataFrame) else "",
            f"dat_source={'index' if isinstance(dat_source_for_exec, dict) else 'frame'}; dar_source={'index' if isinstance(dar_source_for_exec, dict) else 'frame'}",
        )

        _hot_exec_df, _auto_fx_exec_df, nil_actual_return_exec_df, _current_account_exec_df, unexplained_exec_df = _hot_resolution_sets(bundle, auto_fx_summary_df)
        _exec_mark(
            "03 resolve HOT / auto / unexplained sets",
            int(len(_hot_exec_df)) if isinstance(_hot_exec_df, pd.DataFrame) else "",
            f"hot={len(_hot_exec_df):,}; auto_fx={len(_auto_fx_exec_df):,}; nil_actual_return={len(nil_actual_return_exec_df):,}; current_account={len(_current_account_exec_df):,}; unexplained={len(unexplained_exec_df):,}",
        )

        no_arc_exec_df = portfolio_df_for_exec[portfolio_df_for_exec.get("Hot / Cold", pd.Series(dtype="object")).astype(str).str.strip().isin(["No ARC match", "No BP Impact row", "No Error Risk row"])].copy() if isinstance(portfolio_df_for_exec, pd.DataFrame) and "Hot / Cold" in portfolio_df_for_exec.columns else pd.DataFrame()
        cold_exec_df = portfolio_df_for_exec[portfolio_df_for_exec.get("Hot / Cold", pd.Series(dtype="object")).astype(str).str.strip().eq("Cold")].copy() if isinstance(portfolio_df_for_exec, pd.DataFrame) and "Hot / Cold" in portfolio_df_for_exec.columns else pd.DataFrame()
        out_exec_df = pd.concat([no_arc_exec_df, cold_exec_df, _hot_exec_df], ignore_index=True) if not no_arc_exec_df.empty or not cold_exec_df.empty or not _hot_exec_df.empty else pd.DataFrame()
        _exec_mark(
            "04 build OUT / No Error Risk / Cold subsets",
            int(len(out_exec_df)) if isinstance(out_exec_df, pd.DataFrame) else "",
            f"out_exec={len(out_exec_df):,}; no_error_risk={len(no_arc_exec_df):,}; cold={len(cold_exec_df):,}; hot={len(_hot_exec_df):,}",
        )

        # v306.5.8: use the shared Tier 1 assignment table prepared during bundle build.
        # This prevents the executive Driver Movement table from drifting away from the
        # section-level Nil actual return / Unexplained driver tables by rebuilding a
        # separate executive assignment table. Rebuild only if the shared table is absent.
        tier1_assignments_df = bundle.get("tier1_assignments_df", pd.DataFrame()) if isinstance(bundle, dict) else pd.DataFrame()
        tier1_assignment_portfolio_timing_df = bundle.get("tier1_assignment_diag_df", pd.DataFrame()) if isinstance(bundle, dict) else pd.DataFrame()
        _assignment_cache_hit = isinstance(tier1_assignments_df, pd.DataFrame) and not tier1_assignments_df.empty
        exec_assignment_population_df = _hot_exec_df.copy() if isinstance(_hot_exec_df, pd.DataFrame) else pd.DataFrame()
        if tier1_assignments_df is None or not isinstance(tier1_assignments_df, pd.DataFrame) or tier1_assignments_df.empty:
            try:
                tier1_assignments_df, tier1_assignment_portfolio_timing_df = _build_tier1_driver_assignments_vectorized(exec_assignment_population_df, dat_source_for_exec, dar_source_for_exec)
            except Exception as exc:
                tier1_assignments_df = pd.DataFrame(columns=["Portfolio code", "Largest Tier 1 driver"])
                tier1_assignment_portfolio_timing_df = pd.DataFrame([{"Status": "Error", "Error": f"{type(exc).__name__}: {exc}"}])
            if isinstance(bundle, dict):
                bundle["tier1_assignments_df"] = tier1_assignments_df
                bundle["tier1_assignment_diag_df"] = tier1_assignment_portfolio_timing_df
                bundle["executive_tier1_assignment_population_count"] = int(len(exec_assignment_population_df))
        _slowest_detail = ""
        if isinstance(tier1_assignment_portfolio_timing_df, pd.DataFrame) and not tier1_assignment_portfolio_timing_df.empty and "ElapsedSeconds" in tier1_assignment_portfolio_timing_df.columns:
            try:
                slowest = tier1_assignment_portfolio_timing_df.sort_values("ElapsedSeconds", ascending=False).head(3)
                _slowest_detail = "; slowest=" + " | ".join((slowest.get("Portfolio code", pd.Series(dtype="object")).astype(str) + ":" + slowest["ElapsedSeconds"].astype(float).map(lambda v: f"{v:,.2f}s")).tolist())
            except Exception:
                _slowest_detail = ""
        _exec_mark(
            "05 build/reuse Tier 1 assignments",
            int(len(tier1_assignments_df)) if isinstance(tier1_assignments_df, pd.DataFrame) else "",
            f"cache_hit={_assignment_cache_hit}; assignment_input_rows={len(exec_assignment_population_df) if isinstance(exec_assignment_population_df, pd.DataFrame) else ''}; out_exec_rows={len(out_exec_df) if isinstance(out_exec_df, pd.DataFrame) else ''}; assignment_scope=OUT only{_slowest_detail}",
        )

        # v292: revert the v291 keyed-groupby path because observed runtime regressed.
        # Keep the existing assignment/reuse path while measuring each executive driver view individually.
        unexplained_driver_df = _tier1_count_frame_from_assignments(unexplained_exec_df, tier1_assignments_df)
        _exec_mark("06 driver view - unexplained", int(len(unexplained_driver_df)) if isinstance(unexplained_driver_df, pd.DataFrame) else "", f"subset_rows={len(unexplained_exec_df):,}")
        executive_driver_views = {}
        executive_driver_views["out"] = _tier1_count_frame_from_assignments(out_exec_df, tier1_assignments_df)
        _exec_mark("07 driver view - out", int(len(executive_driver_views["out"])) if isinstance(executive_driver_views.get("out"), pd.DataFrame) else "", f"subset_rows={len(out_exec_df):,}")
        executive_driver_views["no_arc"] = _tier1_count_frame_from_assignments(no_arc_exec_df, tier1_assignments_df)
        _exec_mark("08 driver view - no_arc", int(len(executive_driver_views["no_arc"])) if isinstance(executive_driver_views.get("no_arc"), pd.DataFrame) else "", f"subset_rows={len(no_arc_exec_df):,}")
        executive_driver_views["cold"] = _tier1_count_frame_from_assignments(cold_exec_df, tier1_assignments_df)
        _exec_mark("09 driver view - cold", int(len(executive_driver_views["cold"])) if isinstance(executive_driver_views.get("cold"), pd.DataFrame) else "", f"subset_rows={len(cold_exec_df):,}")
        executive_driver_views["hot"] = _tier1_count_frame_from_assignments(_hot_exec_df, tier1_assignments_df)
        _exec_mark("10 driver view - hot", int(len(executive_driver_views["hot"])) if isinstance(executive_driver_views.get("hot"), pd.DataFrame) else "", f"subset_rows={len(_hot_exec_df):,}")
        executive_driver_views["auto_fx"] = _tier1_count_frame_from_assignments(_auto_fx_exec_df, tier1_assignments_df)
        _exec_mark("11 driver view - auto_fx", int(len(executive_driver_views["auto_fx"])) if isinstance(executive_driver_views.get("auto_fx"), pd.DataFrame) else "", f"subset_rows={len(_auto_fx_exec_df):,}")
        executive_driver_views["nil_actual_return"] = _tier1_count_frame_from_assignments(nil_actual_return_exec_df, tier1_assignments_df)
        _exec_mark("12 driver view - nil_actual_return", int(len(executive_driver_views["nil_actual_return"])) if isinstance(executive_driver_views.get("nil_actual_return"), pd.DataFrame) else "", f"subset_rows={len(nil_actual_return_exec_df):,}")
        executive_driver_views["current_account"] = _tier1_count_frame_from_assignments(_current_account_exec_df, tier1_assignments_df)
        _exec_mark("13 driver view - current_account", int(len(executive_driver_views["current_account"])) if isinstance(executive_driver_views.get("current_account"), pd.DataFrame) else "", f"subset_rows={len(_current_account_exec_df):,}")
        executive_driver_views["unexplained"] = unexplained_driver_df

        # v306.9.0: create selected-date executive trend snapshots from the same
        # counts/driver views that feed the executive dashboard render.
        try:
            _attach_executive_trend_snapshot_to_bundle(bundle, selected_date, folder, str(folder_fp if 'folder_fp' in locals() else ''), auto_fx_summary_df, executive_driver_views)
            _exec_mark("14 build executive trend snapshot", int(len(bundle.get("executive_trend_driver_snapshot_df", pd.DataFrame()))) if isinstance(bundle.get("executive_trend_driver_snapshot_df", pd.DataFrame()), pd.DataFrame) else "", "summary + long-form driver movement snapshot")
        except Exception as exc:
            if isinstance(bundle, dict):
                bundle["executive_trend_diagnostic_snapshot_df"] = pd.DataFrame([{"RunDate": _date_string_yyyy_mm_dd(selected_date), "Check": "Build executive trend snapshot", "Result": False, "Detail": f"{type(exc).__name__}: {exc}"}])
            _exec_mark("14 build executive trend snapshot", "", f"Error: {type(exc).__name__}: {exc}")

        with dashboard_shell:
            try:
                executive_driver_views["_portfolio_counts"] = {
                    "no_error_risk": int(len(no_arc_exec_df)) if isinstance(no_arc_exec_df, pd.DataFrame) else 0,
                    "cold": int(len(cold_exec_df)) if isinstance(cold_exec_df, pd.DataFrame) else 0,
                    "hot": int(len(_hot_exec_df)) if isinstance(_hot_exec_df, pd.DataFrame) else int(hot_count),
                }
            except Exception:
                pass
            # v333: group radio + executive render.
            # FIX (two issues): (1) the flow bar is rendered into a dedicated
            # st.empty() placeholder so a group toggle REPLACES the content cleanly
            # instead of leaving the previous dashboard ghosting below; (2) the group
            # radio is created ONCE up front (outside the flow-bar try) so a partial
            # failure can't leave a half-drawn radio, and the flow bar renders exactly
            # ONCE (no double-render from the old except fallback).
            # v334: render the group radio + executive card into the SINGLE hoisted
            # placeholder (_exec_group_ph). One position for both branches = clean
            # replace on every toggle, no ghosting, and paints on first load.
            with _exec_group_ph.container():
                try:
                    _v328_grp, _v328_sc = _v328_render_group_radio_and_scope(bundle)
                except Exception:
                    _v328_grp, _v328_sc = (V328_GROUPS[0] if "V328_GROUPS" in globals() else "On UNISON", None)
                try:
                    if isinstance(_v328_sc, dict) and _v328_sc.get("mapping_total") is not None:
                        _mt = int(_v328_sc.get("mapping_total") or 0)
                        st.info(f"Total portfolios ({_mt:,}) sourced from the Central Mapping file (TEMPORARY) - "
                                f"{_v328_grp} is a separate feed not yet wired into BNP, so the checks "
                                f"(Within / Outside / Hot / Cold) are pending.")
                    elif isinstance(_v328_sc, dict) and _v328_sc.get("is_placeholder"):
                        st.info("Pending feed - structure shown so the dashboard reads as one holistic 3-group solution.")
                    if isinstance(_v328_sc, dict):
                        _render_executive_flow_bar(selected_date, _v328_sc["total"], _v328_sc["within"], _v328_sc["out"], _v328_sc["hot"], _v328_sc["fx"], _v328_sc["nil"], _v328_sc["ca"], _v328_sc["unexpl"], unexplained_driver_df, driver_views=_v328_sc["driver_views"])
                    else:
                        _render_executive_flow_bar(selected_date, total_count, within_count, out_count, hot_count, auto_explained_fx_count, nil_actual_return_count, current_account_dominated_count, unexplained_count, unexplained_driver_df, driver_views=executive_driver_views)
                except Exception:
                    _render_executive_flow_bar(selected_date, total_count, within_count, out_count, hot_count, auto_explained_fx_count, nil_actual_return_count, current_account_dominated_count, unexplained_count, unexplained_driver_df, driver_views=executive_driver_views)
            _render_executive_trend_snapshot_debug(bundle)
        _exec_mark("15 render executive summary HTML", "", "_render_executive_flow_bar")

        try:
            total_exec_elapsed = float(time.perf_counter() - _exec_summary_total_started)
        except Exception:
            total_exec_elapsed = 0.0
        executive_summary_timing_rows.append({
            "Step": "TOTAL Build executive summary",
            "ElapsedSeconds": round(total_exec_elapsed, 4),
            "Rows": "",
            "Detail": "sum of measured executive summary steps",
        })
        if isinstance(bundle, dict):
            bundle["executive_summary_timing_df"] = pd.DataFrame(executive_summary_timing_rows)
        _record_wallclock_timing("04 Build executive summary", _exec_summary_total_started, rows=int(len(portfolio_df)) if isinstance(portfolio_df, pd.DataFrame) else "", detail=f"selected_date={selected_date}")

        if isinstance(bundle, dict):
            bundle["dashboard_wallclock_timing_df"] = pd.DataFrame(dashboard_wallclock_timing_rows)
            bundle["loading_stage_timing_df"] = _stage_timing_df()
            bundle["load_portfolio_arc_fx_timing_df"] = pd.DataFrame(fx_subtimings)
            bundle["file_manifest_status_df"] = _manifest_status_df()
        if isinstance(bundle, dict):
            try:
                executive_summary_cache_payload = {
                    "total_count": total_count,
                    "within_count": within_count,
                    "out_count": out_count,
                    "hot_count": hot_count,
                    "auto_explained_fx_count": auto_explained_fx_count,
                    "nil_actual_return_count": nil_actual_return_count,
                    "current_account_dominated_count": current_account_dominated_count,
                    "unexplained_count": unexplained_count,
                    "unexplained_driver_df": unexplained_driver_df,
                    "executive_driver_views": executive_driver_views,
                    "auto_fx_summary_df": auto_fx_summary_df,
                    "executive_summary_timing_df": bundle.get("executive_summary_timing_df", pd.DataFrame()),
                    "executive_trend_summary_snapshot_df": bundle.get("executive_trend_summary_snapshot_df", pd.DataFrame()),
                    "executive_trend_driver_snapshot_df": bundle.get("executive_trend_driver_snapshot_df", pd.DataFrame()),
                    "executive_trend_diagnostic_snapshot_df": bundle.get("executive_trend_diagnostic_snapshot_df", pd.DataFrame()),
                }
                st.session_state[executive_summary_cache_key] = {"key": executive_summary_cache_lookup_key, "payload": executive_summary_cache_payload}
                bundle["executive_summary_cache_status_df"] = pd.DataFrame([{"Status": "Rebuilt", "Key": str(executive_summary_cache_lookup_key)}])
            except Exception:
                bundle["executive_summary_cache_status_df"] = pd.DataFrame([{"Status": "Cache store skipped", "Key": str(executive_summary_cache_lookup_key)}])
    _mark_stage("Render dashboard tabs")
    # v362: new top-level layout - "Input Sources" moved before "Portfolio
    # Numbers" (renamed from the former "Data Sources" sub-section); new
    # "Control checks" tab hosts the 13 ARC/GAV-style controls previously
    # nested inside Portfolio Numbers; "Portfolio Drill-through" renamed to
    # "Single Portfolio Drill-through"; "Auto Explained" / "Unexplained"
    # renamed to "Daily Movements - Auto explained" / "Daily Movements -
    # Unexplained". All renames are DISPLAY/dispatch-key changes only - no
    # underlying control logic changed.
    dashboard_sections = [
        "Input Sources",
        "Portfolio Numbers",
        "Control checks",
        "Single Portfolio Drill-through",
        "Daily Movements - Auto explained",
        "Daily Movements - Unexplained",
    ]
    selected_date_key = _date_string_yyyy_mm_dd(selected_date)
    dashboard_section_key = f"portfolio_dashboard_active_section_{selected_date_key}"
    legacy_dashboard_value = st.session_state.get(dashboard_section_key, "Daily Movements - Unexplained")
    if legacy_dashboard_value in {"OUT Portfolios", "Portfolio Count"}:
        st.session_state[dashboard_section_key] = "Portfolio Numbers"
    elif legacy_dashboard_value in {"Auto explained by FX", "Auto Explained by FX", "Nil actual return", "Current Account dominated", "Auto Explained"}:
        st.session_state[dashboard_section_key] = "Daily Movements - Auto explained"
    elif legacy_dashboard_value == "Unexplained":
        st.session_state[dashboard_section_key] = "Daily Movements - Unexplained"
    elif legacy_dashboard_value == "Portfolio Drill-through":
        st.session_state[dashboard_section_key] = "Single Portfolio Drill-through"
    elif legacy_dashboard_value not in dashboard_sections:
        st.session_state[dashboard_section_key] = "Daily Movements - Unexplained"

    radio_kwargs = {
        "label": "Dashboard section",
        "options": dashboard_sections,
        "horizontal": True,
        "key": dashboard_section_key,
        "label_visibility": "collapsed",
    }
    if dashboard_section_key not in st.session_state:
        radio_kwargs["index"] = dashboard_sections.index("Daily Movements - Unexplained")
    # v325: warm-up - populate every check's bundle dataframes ONCE after the
    # dashboard loads, so the Control summary (and all check sub-sections) show data
    # immediately without needing each panel clicked first. Uses a no-op st stub so
    # the existing render functions build+stash to the bundle without drawing.
    class _V325NullSt:
        def __getattr__(self, name):
            return self._call
        def _call(self, *a, **k):
            return self
        def columns(self, spec, *a, **k):
            n = spec if isinstance(spec, int) else (len(spec) if hasattr(spec, "__len__") else 2)
            return [_V325NullSt() for _ in range(max(1, int(n)))]
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    def _v325_warm_checks(bundle):
        if not isinstance(bundle, dict) or bundle.get("_v325_warmed"):
            return
        _ns = _V325NullSt()
        # v344 (Part 1 - cold-load instrumentation): time EACH warm-up check. This is
        # a prime suspect for the ~114s cold "Render dashboard tabs" because it runs
        # every check renderer once at load - INCLUDING the two UUT builds that cost
        # ~24s each on click. Per-check rows now appear in the deep-timing run-log.
        for fn_name in ("_render_universe_section_v308", "_render_gav_section_v309",
                        "_render_return_check_section_v310",
                        # v330: build the base Advisor-UUT frame (advisor_uut_df) BEFORE the
                        # corrected panel, which reads it. Without this the corrected panel is blank.
                        "_render_uut_section_v311", "_render_uut_v311_1",
                        "_render_ancillary_section_v312", "_render_price_integrity_v313"):
            fn = globals().get(fn_name)
            if callable(fn):
                # reset UUT internal timers around the UUT warm-up builds so the
                # cold-load FDV T / T-1 / join breakdown is captured too.
                _is_uut = fn_name in ("_render_uut_section_v311", "_render_uut_v311_1")
                if _is_uut:
                    try:
                        if callable(globals().get("_uut_reset_timings_v344")):
                            _uut_reset_timings_v344()
                    except Exception:
                        pass
                try:
                    with _deep_timer(bundle, "Warm-up (cold load)", fn_name):
                        fn(_ns, bundle)
                except Exception:
                    pass
                if _is_uut:
                    _drain_uut_internal_timings_v344()
        bundle["_v325_warmed"] = True

    try:
        _v325_warm_checks(bundle)
    except Exception:
        pass

    # v341: the section radio is created FIRST and OUTSIDE the guard below so it
    # always paints. The per-section render is then FENCED: previously this whole
    # if/elif chain ran unguarded, so an exception on the On UNISON path (the only
    # group with a non-empty scoped frame) aborted the page and left the exec card
    # with no radio/sub-sections. A section failure now surfaces st.error() and the
    # radio + other sections stay usable.
    selected_section = st.radio(**radio_kwargs)
    _reset_section_timing(bundle, selected_section)
    _tab_started = time.perf_counter()
    try:
        # v342 (Option B): wrap each tab render in a deep timer so the exact
        # contributor to the "Render dashboard tabs" wallclock is captured per run.
        if selected_section == "Input Sources":
            with _deep_timer(bundle, "Render tab", "Input Sources"):
                _render_input_sources_tab(bundle, "Count")
            _record_render_tab_timing("Input Sources", _tab_started)
            _record_section_timing(bundle, "Input Sources", "Section total", _tab_started)
        elif selected_section == "Portfolio Numbers":
            with _deep_timer(bundle, "Render tab", "Portfolio Numbers", rows=int(len(portfolio_df)) if isinstance(portfolio_df, pd.DataFrame) else ""):
                _render_overview_tab(bundle, "Count")
            _record_render_tab_timing("Portfolio Numbers", _tab_started, int(len(portfolio_df)) if isinstance(portfolio_df, pd.DataFrame) else "")
            _record_section_timing(bundle, "Portfolio Numbers", "Section total", _tab_started, rows=int(len(portfolio_df)) if isinstance(portfolio_df, pd.DataFrame) else "")
        elif selected_section == "Control checks":
            with _deep_timer(bundle, "Render tab", "Control checks"):
                _render_control_checks_tab(bundle)
            _record_render_tab_timing("Control checks", _tab_started)
            _record_section_timing(bundle, "Control checks", "Section total", _tab_started)
        elif selected_section == "Single Portfolio Drill-through":
            with _deep_timer(bundle, "Render tab", "Single Portfolio Drill-through"):
                _render_portfolio_drillthrough_tab(bundle)
            _record_render_tab_timing("Single Portfolio Drill-through", _tab_started)
            _record_section_timing(bundle, "Single Portfolio Drill-through", "Section total", _tab_started)
        elif selected_section == "Daily Movements - Auto explained":
            with _deep_timer(bundle, "Render tab", "Daily Movements - Auto explained"):
                _render_auto_explained_tab(bundle, auto_fx_summary_df)
            _record_render_tab_timing("Daily Movements - Auto explained", _tab_started)
            _record_section_timing(bundle, "Daily Movements - Auto explained", "Section total", _tab_started)
        elif selected_section == "Daily Movements - Unexplained":
            with _deep_timer(bundle, "Render tab", "Daily Movements - Unexplained"):
                _render_unexplained_tab(bundle, auto_fx_summary_df)
            _record_render_tab_timing("Daily Movements - Unexplained", _tab_started)
            _record_section_timing(bundle, "Daily Movements - Unexplained", "Section total", _tab_started)
    except Exception as _section_exc:
        try:
            st.error(f"'{selected_section}' section could not render: {type(_section_exc).__name__}: {_section_exc}")
            if bool(globals().get("SHOW_DEBUG", False)):
                import traceback as _tb
                st.caption(_tb.format_exc())
        except Exception:
            pass

    _record_wallclock_timing("05 Selected section render", _tab_started, detail=str(selected_section))
    if isinstance(bundle, dict):
        bundle["render_tab_timing_df"] = pd.DataFrame(render_tab_timing_rows)
        bundle["active_render_section"] = selected_section
        bundle["dashboard_wallclock_timing_df"] = pd.DataFrame(dashboard_wallclock_timing_rows)
    _complete_active_stage()
    _record_wallclock_timing("99 TOTAL dashboard rerun to selected section displayed", load_started_at, rows=int(len(portfolio_df)) if isinstance(portfolio_df, pd.DataFrame) else "", detail=str(selected_section))
    if isinstance(bundle, dict):
        bundle["dashboard_wallclock_timing_df"] = pd.DataFrame(dashboard_wallclock_timing_rows)
        bundle["loading_stage_timing_df"] = _stage_timing_df()
        bundle["load_portfolio_arc_fx_timing_df"] = pd.DataFrame(fx_subtimings)
        bundle["render_tab_timing_df"] = pd.DataFrame(render_tab_timing_rows)

    # [removed] "Performance timing diagnostics - full user wait" section.
    # v342 Phase 3: the standalone "Diagnostics / support" expander was removed and
    # its retained tables (File load metadata, Run diagnostics, Processing
    # exceptions, and the three cache-status frames) were folded into the SINGLE
    # consolidated "Diagnostic support - source load checks" panel under Portfolio
    # Numbers. Regular type debug, ARC mapping preview and all exchange-rate blocks
    # were dropped by request.


# ========================================================
# APP SHELL
# ========================================================

# ========================================================
# BOOTSTRAP / ENTRY POINT
# ========================================================


# ========================================================
# TREND CHART LAYOUT PATCH v306.13.6.9
# ========================================================

def _trend_common_candidate_security_chart_long_df(common_candidate_df: pd.DataFrame) -> pd.DataFrame:
    """Security-only long-form chart data for common validation securities."""
    cols = ["RunDate", "DateLabel", "Asset Type", "Value", "_DateSort"]
    if common_candidate_df is None or not isinstance(common_candidate_df, pd.DataFrame) or common_candidate_df.empty:
        return pd.DataFrame(columns=cols)
    required = {"RunDate", "Asset Type", "Number of Securities"}
    if not required.issubset(set(common_candidate_df.columns)):
        return pd.DataFrame(columns=cols)
    work = common_candidate_df.copy()
    work["RunDate"] = pd.to_datetime(work["RunDate"], errors="coerce")
    work = work.dropna(subset=["RunDate"])
    if work.empty:
        return pd.DataFrame(columns=cols)
    work["Number of Securities"] = pd.to_numeric(work["Number of Securities"], errors="coerce").fillna(0)
    work["Asset Type"] = work["Asset Type"].astype(str).str.strip().replace("", "Unknown asset type")
    work["DateLabel"] = work["RunDate"].dt.strftime("%d/%m/%y")
    work["_DateSort"] = work["RunDate"].dt.strftime("%Y%m%d")
    out = (
        work.groupby(["RunDate", "DateLabel", "_DateSort", "Asset Type"], dropna=False)["Number of Securities"]
        .sum()
        .reset_index()
        .rename(columns={"Number of Securities": "Value"})
    )
    return out[cols].copy()


# v365: removed the SECOND of three (dead) definitions of
# _render_common_candidate_trend_chart. Only the LAST definition further down
# this file (kept) is actually bound and invoked at render time. See
# CHANGELOG.md v365.

def _trend_common_candidate_portfolio_coverage_chart_df(summary_df: pd.DataFrame, common_candidate_df: pd.DataFrame) -> pd.DataFrame:
    """Build stacked coverage data: common-validation-covered portfolios plus other unexplained causes.

    The common-candidate trend cache is currently stored by Asset Type, so the coverage value is the
    summed Asset Type portfolio coverage capped at the total unexplained count for that date. This keeps
    the stacked column balanced to total Unexplained portfolios even if a portfolio appears in more than
    one Asset Type bucket.
    """
    cols = ["RunDate", "DateLabel", "Coverage bucket", "Value", "_DateSort"]
    if summary_df is None or not isinstance(summary_df, pd.DataFrame) or summary_df.empty:
        return pd.DataFrame(columns=cols)
    if "RunDate" not in summary_df.columns or "Unexplained" not in summary_df.columns:
        return pd.DataFrame(columns=cols)
    base = summary_df[["RunDate", "Unexplained"]].copy()
    base["RunDate"] = pd.to_datetime(base["RunDate"], errors="coerce")
    base = base.dropna(subset=["RunDate"])
    if base.empty:
        return pd.DataFrame(columns=cols)
    base["Unexplained"] = pd.to_numeric(base["Unexplained"], errors="coerce").fillna(0).clip(lower=0)
    base = base.groupby("RunDate", as_index=False)["Unexplained"].max()

    if common_candidate_df is not None and isinstance(common_candidate_df, pd.DataFrame) and not common_candidate_df.empty and {"RunDate", "Number of Portfolios covered"}.issubset(set(common_candidate_df.columns)):
        covered = common_candidate_df[["RunDate", "Number of Portfolios covered"]].copy()
        covered["RunDate"] = pd.to_datetime(covered["RunDate"], errors="coerce")
        covered = covered.dropna(subset=["RunDate"])
        covered["Number of Portfolios covered"] = pd.to_numeric(covered["Number of Portfolios covered"], errors="coerce").fillna(0).clip(lower=0)
        covered = covered.groupby("RunDate", as_index=False)["Number of Portfolios covered"].sum()
    else:
        covered = pd.DataFrame(columns=["RunDate", "Number of Portfolios covered"])

    merged = base.merge(covered, on="RunDate", how="left")
    merged["Number of Portfolios covered"] = pd.to_numeric(merged["Number of Portfolios covered"], errors="coerce").fillna(0).clip(lower=0)
    merged["Common validation portfolios covered"] = merged[["Unexplained", "Number of Portfolios covered"]].min(axis=1)
    merged["Other causes"] = (merged["Unexplained"] - merged["Common validation portfolios covered"]).clip(lower=0)
    merged["DateLabel"] = merged["RunDate"].dt.strftime("%d/%m/%y")
    merged["_DateSort"] = merged["RunDate"].dt.strftime("%Y%m%d")
    out = merged.melt(
        id_vars=["RunDate", "DateLabel", "_DateSort"],
        value_vars=["Common validation portfolios covered", "Other causes"],
        var_name="Coverage bucket",
        value_name="Value",
    )
    out["Value"] = pd.to_numeric(out["Value"], errors="coerce").fillna(0)
    return out[cols].copy()


def _render_common_candidate_portfolio_coverage_chart(summary_df: pd.DataFrame, common_candidate_df: pd.DataFrame) -> None:
    chart_df = _trend_common_candidate_portfolio_coverage_chart_df(summary_df, common_candidate_df)
    if chart_df.empty:
        st.info("No common validation portfolio coverage trend data is available for the selected date range/settings.")
        return
    st.caption("Stacked to total Unexplained portfolios. Common validation coverage is shown at the bottom; Other causes is the balancing figure.")
    _render_stacked_column_chart(
        chart_df,
        x_field="DateLabel",
        colour_field="Coverage bucket",
        y_field="Value",
        y_title="Unexplained portfolio count",
        tooltip_fields=["DateLabel", "Coverage bucket", "Value"],
        category_order=["Common validation portfolios covered", "Other causes"],
        colour_map={
            "Common validation portfolios covered": "#2CA02C",
            "Other causes": "#B8B8B8",
        },
    )


def _render_trend_history_charts(summary_df: pd.DataFrame, driver_df: pd.DataFrame, common_candidates_df: Optional[pd.DataFrame] = None) -> None:
    """Render Trend History charts in requested order.

    Order: Portfolio Numbers, Hot waterfall, Common validation coverage, Common validation securities, Driver movement.
    """
    if summary_df is None or not isinstance(summary_df, pd.DataFrame) or summary_df.empty:
        st.info("No executive trend summary rows are available for the selected date range/settings. Build or refresh trend history first.")
        return
    st.markdown("### Trend charts")
    st.caption("Charts are stacked columns by reporting date. X-axis labels use dd/mm/yy. Segment labels show counts. Colours are fixed across Trend tabs for easier review.")
    tabs = st.tabs(["Portfolio Numbers", "Hot waterfall", "Common validation coverage", "Common validation securities", "Driver movement"])

    with tabs[0]:
        chart_df = _trend_portfolio_numbers_chart_df(summary_df)
        _render_stacked_column_chart(
            chart_df,
            x_field="DateLabel",
            colour_field="Metric",
            y_field="Value",
            y_title="Portfolio count",
            tooltip_fields=["DateLabel", "Metric", "Value"],
            category_order=TREND_PORTFOLIO_NUMBER_ORDER,
            colour_map=TREND_PORTFOLIO_NUMBER_COLOURS,
        )

    with tabs[1]:
        hot_cols = ["Auto explained by FX", "Nil actual return", "Current Account dominated", "Unexplained"]
        hot_df = _trend_chart_long_df(summary_df, hot_cols)
        _render_stacked_column_chart(
            hot_df,
            x_field="DateLabel",
            colour_field="Metric",
            y_field="Value",
            y_title="Portfolio count",
            tooltip_fields=["DateLabel", "Metric", "Value"],
            category_order=hot_cols,
            colour_map=TREND_HOT_WATERFALL_COLOURS,
        )

    with tabs[2]:
        _render_common_candidate_portfolio_coverage_chart(summary_df, common_candidates_df if isinstance(common_candidates_df, pd.DataFrame) else pd.DataFrame())

    with tabs[3]:
        _render_common_candidate_trend_chart(common_candidates_df if isinstance(common_candidates_df, pd.DataFrame) else pd.DataFrame())

    with tabs[4]:
        driver_chart_df = _trend_driver_chart_long_df(driver_df, "Unexplained", top_n=8)
        if driver_chart_df.empty:
            st.info("No Driver movement trend data is available for the selected date range/settings.")
        else:
            top_drivers = driver_chart_df["Driver"].astype(str).dropna().unique().tolist()
            palette = list(globals().get("TREND_DEFAULT_COLOUR_RANGE", [])) or ["#1F77B4", "#FF7F0E", "#2CA02C", "#D62728", "#9467BD"]
            colour_map = {driver: palette[i % len(palette)] for i, driver in enumerate(top_drivers)}
            _render_stacked_column_chart(
                driver_chart_df,
                x_field="DateLabel",
                colour_field="Driver",
                y_field="Portfolio count",
                y_title="Portfolio count",
                tooltip_fields=["DateLabel", "Driver", "Portfolio count"],
                category_order=top_drivers,
                colour_map=colour_map,
            )



# ========================================================
# TREND HISTORY PERFORMANCE PATCH v306.13.7.0
# Patch 1: Trend source profile skips TransactionListing
# Patch 2: Memoise folder_fingerprint during Trend build
# ========================================================

TREND_HISTORY_PERFORMANCE_PATCH_VERSION = "v306.13.7.0_trend_source_profile_and_fingerprint_cache"
_TREND_HISTORY_FAST_SOURCE_PROFILE_ACTIVE = False
_TREND_HISTORY_FINGERPRINT_CACHE = {}


def _trend_perf_add_timing(phase, started_at, status="Done", rows="", detail="", folder=""):
    try:
        if callable(globals().get("_trend_timing_diag_add")):
            _trend_timing_diag_add(
                phase,
                started_at,
                status=status,
                rows=rows,
                detail=detail,
                folder=folder,
                scope="Trend History performance patch",
                source=TREND_HISTORY_PERFORMANCE_PATCH_VERSION,
            )
    except Exception:
        pass


if callable(globals().get("folder_fingerprint")) and not getattr(globals().get("folder_fingerprint"), "_trend_perf_fingerprint_cached", False):
    _trend_perf_original_folder_fingerprint = folder_fingerprint

    def folder_fingerprint(folder):
        folder_key = str(folder or "")
        if bool(globals().get("_TREND_HISTORY_FAST_SOURCE_PROFILE_ACTIVE", False)) and folder_key in _TREND_HISTORY_FINGERPRINT_CACHE:
            started = time.perf_counter()
            out = _TREND_HISTORY_FINGERPRINT_CACHE.get(folder_key, "")
            _trend_perf_add_timing(
                "source.folder_fingerprint.memoized_hit",
                started,
                status="Cached",
                detail="Returned memoised folder fingerprint for this Trend History build.",
                folder=folder_key,
            )
            return out
        started = time.perf_counter()
        out = _trend_perf_original_folder_fingerprint(folder)
        if bool(globals().get("_TREND_HISTORY_FAST_SOURCE_PROFILE_ACTIVE", False)):
            _TREND_HISTORY_FINGERPRINT_CACHE[folder_key] = out
            _trend_perf_add_timing(
                "source.folder_fingerprint.memoized_store",
                started,
                status="Stored",
                detail="Computed once and stored for reuse within this Trend History build.",
                folder=folder_key,
            )
        return out

    folder_fingerprint._trend_perf_fingerprint_cached = True
    folder_fingerprint._trend_perf_original = _trend_perf_original_folder_fingerprint


if callable(globals().get("load_day_files_v184_readcsv_cached")) and not getattr(globals().get("load_day_files_v184_readcsv_cached"), "_trend_perf_profile_wrapped", False):
    _trend_perf_original_load_day_files_v184_readcsv_cached = load_day_files_v184_readcsv_cached

    def load_day_files_v184_readcsv_cached(folder, folder_fp, cache_version):
        if not bool(globals().get("_TREND_HISTORY_FAST_SOURCE_PROFILE_ACTIVE", False)):
            return _trend_perf_original_load_day_files_v184_readcsv_cached(folder, folder_fp, cache_version)
        started_total = time.perf_counter()
        ingestion_v162.configure_ingestion(
            header_contracts=HEADER_CONTRACTS,
            excluded_filename_tokens=EXCLUDED_FILENAME_TOKENS,
            required_file_keywords=REQUIRED_FILE_KEYWORDS,
            optional_file_keywords=[k for k in OPTIONAL_FILE_KEYWORDS if str(k).strip().lower() != "transactionlisting"],
        )
        file_map = {}
        file_meta_rows = []
        timing_rows = []
        alias_map = {"DDetailedReturn": "dd", "DAssetTypeReturn": "dat", "DAssetReturn": "dar", "BenchmarkStatic": "bmk"}
        keywords = list(REQUIRED_FILE_KEYWORDS) + [k for k in OPTIONAL_FILE_KEYWORDS if str(k).strip().lower() != "transactionlisting"]
        for keyword in keywords:
            keyword_started = time.perf_counter()
            df, meta, keyword_timing_rows = _bnp_source_file_aggregated_v184(keyword, folder)
            if isinstance(keyword_timing_rows, list):
                timing_rows.extend(keyword_timing_rows)
            if isinstance(df, pd.DataFrame):
                prime_started = time.perf_counter()
                df = _prime_dataframe_col_index(df)
                timing_rows.append({"Sub-step": f"BNP v184 trend source profile: {keyword} prime dataframe columns", "Status": "Done", "ElapsedSeconds": float(time.perf_counter() - prime_started)})
            alias = alias_map.get(str(keyword))
            if alias:
                file_map[alias] = df
            if isinstance(meta, dict):
                file_meta_rows.append(meta)
            timing_rows.append({"Sub-step": f"BNP v184 trend source profile: {keyword} total", "Status": "Done" if isinstance(df, pd.DataFrame) else "Missing", "ElapsedSeconds": float(time.perf_counter() - keyword_started)})
        timing_rows.append({"Sub-step": "BNP v184 trend source profile: TransactionListing skipped", "Status": "Skipped", "ElapsedSeconds": 0.0})
        timing_rows.append({"Sub-step": "BNP v184 trend source profile: total source load/prime excluding TransactionListing", "Status": "Done", "ElapsedSeconds": float(time.perf_counter() - started_total)})
        return {"dd": file_map.get("dd"), "dat": file_map.get("dat"), "dar": file_map.get("dar"), "txn": pd.DataFrame(), "bmk": file_map.get("bmk"), "file_meta_df": pd.DataFrame(file_meta_rows), "bnp_load_timing_df": pd.DataFrame(timing_rows), "trend_source_profile": TREND_HISTORY_PERFORMANCE_PATCH_VERSION}

    load_day_files_v184_readcsv_cached._trend_perf_profile_wrapped = True
    load_day_files_v184_readcsv_cached._trend_perf_original = _trend_perf_original_load_day_files_v184_readcsv_cached


if callable(globals().get("_load_bnp_source_persistent_cached")) and not getattr(globals().get("_load_bnp_source_persistent_cached"), "_trend_perf_profile_wrapped", False):
    _trend_perf_original_load_bnp_source_persistent_cached = _load_bnp_source_persistent_cached

    def _load_bnp_source_persistent_cached(folder, folder_fp, cache_version, force_refresh=False):
        if bool(globals().get("_TREND_HISTORY_FAST_SOURCE_PROFILE_ACTIVE", False)):
            profile_cache_version = f"{cache_version}|trend_no_transactionlisting|{TREND_HISTORY_PERFORMANCE_PATCH_VERSION}"
            loaded, status = _trend_perf_original_load_bnp_source_persistent_cached(folder, folder_fp, profile_cache_version, force_refresh=force_refresh)
            try:
                if isinstance(loaded, dict):
                    loaded["trend_source_profile"] = TREND_HISTORY_PERFORMANCE_PATCH_VERSION
                    if "txn" not in loaded or loaded.get("txn") is None:
                        loaded["txn"] = pd.DataFrame()
                if isinstance(status, dict):
                    status["TrendSourceProfile"] = TREND_HISTORY_PERFORMANCE_PATCH_VERSION
                    status["TransactionListing"] = "Skipped for Trend History"
            except Exception:
                pass
            return loaded, status
        return _trend_perf_original_load_bnp_source_persistent_cached(folder, folder_fp, cache_version, force_refresh=force_refresh)

    _load_bnp_source_persistent_cached._trend_perf_profile_wrapped = True
    _load_bnp_source_persistent_cached._trend_perf_original = _trend_perf_original_load_bnp_source_persistent_cached


if callable(globals().get("_build_or_refresh_executive_trend_history")) and not getattr(globals().get("_build_or_refresh_executive_trend_history"), "_trend_perf_profile_wrapped", False):
    _trend_perf_original_build_or_refresh_executive_trend_history = _build_or_refresh_executive_trend_history

    def _build_or_refresh_executive_trend_history(*args, **kwargs):
        global _TREND_HISTORY_FAST_SOURCE_PROFILE_ACTIVE, _TREND_HISTORY_FINGERPRINT_CACHE
        previous_active = bool(globals().get("_TREND_HISTORY_FAST_SOURCE_PROFILE_ACTIVE", False))
        previous_cache = dict(globals().get("_TREND_HISTORY_FINGERPRINT_CACHE", {}))
        _TREND_HISTORY_FAST_SOURCE_PROFILE_ACTIVE = True
        _TREND_HISTORY_FINGERPRINT_CACHE = {}
        started = time.perf_counter()
        try:
            _trend_perf_add_timing("trend.performance_profile.enabled", started, status="Enabled", detail="TransactionListing skipped for Trend History; folder fingerprints memoised per folder.")
            result = _trend_perf_original_build_or_refresh_executive_trend_history(*args, **kwargs)
            try:
                if isinstance(result, dict):
                    result["trend_performance_profile_df"] = pd.DataFrame([{"PatchVersion": TREND_HISTORY_PERFORMANCE_PATCH_VERSION, "TransactionListing": "Skipped for Trend History source loads", "FingerprintMemoisedFolders": int(len(_TREND_HISTORY_FINGERPRINT_CACHE)), "ElapsedSeconds": round(float(time.perf_counter() - started), 4)}])
            except Exception:
                pass
            _trend_perf_add_timing("trend.performance_profile.completed", started, status="Done", rows=int(len(_TREND_HISTORY_FINGERPRINT_CACHE)), detail="Trend History performance profile completed.")
            return result
        finally:
            _TREND_HISTORY_FAST_SOURCE_PROFILE_ACTIVE = previous_active
            _TREND_HISTORY_FINGERPRINT_CACHE = previous_cache

    _build_or_refresh_executive_trend_history._trend_perf_profile_wrapped = True
    _build_or_refresh_executive_trend_history._trend_perf_original = _trend_perf_original_build_or_refresh_executive_trend_history



# ========================================================
# TREND CHART CORRECTION PATCH v306.13.7.1
# - Exact common-validation portfolio coverage
# - Security chart labels centred and shown for every positive Asset Type segment
# ========================================================

TREND_CHART_CORRECTION_PATCH_VERSION = "v306.13.7.1_common_validation_coverage_and_labels"


def _trend_common_candidate_unique_portfolios_from_common_df(common_df: pd.DataFrame) -> set:
    """Return unique impacted portfolio codes from security-level common candidates."""
    portfolios = set()
    if common_df is None or not isinstance(common_df, pd.DataFrame) or common_df.empty:
        return portfolios
    for col in ["Portfolio list", "Portfolios impacted"]:
        if col in common_df.columns:
            for val in common_df[col].dropna().astype(str).tolist():
                txt = str(val).strip()
                if not txt:
                    continue
                # Portfolio list is usually delimited text. Keep this intentionally permissive.
                parts = re.split(r"[,;|\n\r\t]+", txt)
                for part in parts:
                    code = str(part).strip()
                    if not code:
                        continue
                    # Ignore pure count-like values from Portfolios impacted when no list is present.
                    if col == "Portfolios impacted" and re.fullmatch(r"[-+]?\d+(\.0+)?", code):
                        continue
                    portfolios.add(code)
            if portfolios:
                return portfolios
    return portfolios


def _trend_common_candidate_snapshot_df(run_date_value: object, folder: str, folder_fp: str, bundle: Dict[str, object], auto_fx_summary_df: Optional[pd.DataFrame], *, settings_hash: str, tiny_upper: float, fx_line_match_tolerance_dollar: float, current_account_dominance_threshold_pct: float, processed_at: str = "") -> pd.DataFrame:
    """Build common validation Asset Type trend rows with exact date-level portfolio coverage.

    v306.13.7.1 change:
    - Asset Type rows still retain Number of Securities and Number of Portfolios covered.
    - Adds date-level exact coverage columns derived from security-level Portfolio list before Asset Type aggregation:
        Common validation portfolios covered
        Total unexplained portfolios
        Other causes
    These repeated date-level columns allow the coverage chart to split total unexplained correctly instead of summing Asset Type portfolio counts.
    """
    run_date_str = _trend_normalised_date_string(run_date_value)
    processed_at = processed_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        hot_df, auto_fx_df, nil_df, current_df, unexplained_df = _hot_resolution_sets(bundle, auto_fx_summary_df if isinstance(auto_fx_summary_df, pd.DataFrame) else pd.DataFrame())
        total_unexplained = int(len(unexplained_df)) if isinstance(unexplained_df, pd.DataFrame) else 0
        if unexplained_df is None or not isinstance(unexplained_df, pd.DataFrame) or unexplained_df.empty:
            return _empty_trend_common_candidate_df()
        dar_source = bundle.get("dar_index") or bundle.get("dar")
        if dar_source is None or not isinstance(dar_source, pd.DataFrame) or dar_source.empty:
            return _empty_trend_common_candidate_df()
        _summary_df, candidate_df, _diagnostic_df = build_unexplained_minimum_validation_sets(unexplained_df, dar_source)
        if candidate_df is None or not isinstance(candidate_df, pd.DataFrame) or candidate_df.empty:
            return _empty_trend_common_candidate_df()
        common_df = build_unexplained_common_validation_candidates(candidate_df)
        if common_df is None or not isinstance(common_df, pd.DataFrame) or common_df.empty:
            return _empty_trend_common_candidate_df()
        exact_portfolios = _trend_common_candidate_unique_portfolios_from_common_df(common_df)
        exact_covered = int(len(exact_portfolios)) if exact_portfolios else 0
        exact_covered = max(0, min(exact_covered, total_unexplained))
        other_causes = max(0, int(total_unexplained) - int(exact_covered))
        asset_type_df = _common_validation_candidates_by_asset_type_df(common_df)
        if asset_type_df is None or not isinstance(asset_type_df, pd.DataFrame) or asset_type_df.empty:
            return _empty_trend_common_candidate_df()
        asset_type_df = asset_type_df.copy()
        asset_type_df.insert(0, "RunDate", run_date_str)
        asset_type_df["Common validation portfolios covered"] = exact_covered
        asset_type_df["Total unexplained portfolios"] = total_unexplained
        asset_type_df["Other causes"] = other_causes
        asset_type_df["SourceFolder"] = str(folder or "")
        asset_type_df["FolderFingerprint"] = str(folder_fp or "")
        asset_type_df["CacheVersion"] = CACHE_VERSION
        asset_type_df["AppPythonVersion"] = APP_PYTHON_VERSION
        asset_type_df["SettingsHash"] = settings_hash
        asset_type_df["MV Tiny Upper Bound"] = tiny_upper
        asset_type_df["FX Line Match Tolerance Dollar"] = fx_line_match_tolerance_dollar
        asset_type_df["Current Account Dominance Threshold Pct"] = current_account_dominance_threshold_pct
        asset_type_df["ProcessedAt"] = processed_at
        return asset_type_df.reset_index(drop=True)
    except Exception:
        return _empty_trend_common_candidate_df()


def _trend_common_candidate_portfolio_coverage_chart_df(summary_df: pd.DataFrame, common_candidate_df: pd.DataFrame) -> pd.DataFrame:
    """Build stacked coverage data using exact date-level coverage if available.

    v306.13.7.1 fixes the previous behaviour where summed Asset Type portfolio coverage was capped to Unexplained,
    causing the common-validation segment to equal total Unexplained. The preferred source is now the exact date-level
    'Common validation portfolios covered' column produced by the snapshot.
    """
    cols = ["RunDate", "DateLabel", "Coverage bucket", "Value", "_DateSort"]
    if summary_df is None or not isinstance(summary_df, pd.DataFrame) or summary_df.empty:
        return pd.DataFrame(columns=cols)
    if "RunDate" not in summary_df.columns or "Unexplained" not in summary_df.columns:
        return pd.DataFrame(columns=cols)
    base = summary_df[["RunDate", "Unexplained"]].copy()
    base["RunDate"] = pd.to_datetime(base["RunDate"], errors="coerce")
    base = base.dropna(subset=["RunDate"])
    if base.empty:
        return pd.DataFrame(columns=cols)
    base["Unexplained"] = pd.to_numeric(base["Unexplained"], errors="coerce").fillna(0).clip(lower=0)
    base = base.groupby("RunDate", as_index=False)["Unexplained"].max()

    covered = pd.DataFrame(columns=["RunDate", "Common validation portfolios covered"])
    if common_candidate_df is not None and isinstance(common_candidate_df, pd.DataFrame) and not common_candidate_df.empty:
        work = common_candidate_df.copy()
        if "RunDate" in work.columns:
            work["RunDate"] = pd.to_datetime(work["RunDate"], errors="coerce")
            work = work.dropna(subset=["RunDate"])
            if "Common validation portfolios covered" in work.columns:
                work["Common validation portfolios covered"] = pd.to_numeric(work["Common validation portfolios covered"], errors="coerce").fillna(0).clip(lower=0)
                covered = work.groupby("RunDate", as_index=False)["Common validation portfolios covered"].max()
            elif "Number of Portfolios covered" in work.columns:
                # Fallback only for old cache rows. Use max, not sum, to avoid forcing coverage to total unexplained.
                work["Common validation portfolios covered"] = pd.to_numeric(work["Number of Portfolios covered"], errors="coerce").fillna(0).clip(lower=0)
                covered = work.groupby("RunDate", as_index=False)["Common validation portfolios covered"].max()

    merged = base.merge(covered, on="RunDate", how="left")
    merged["Common validation portfolios covered"] = pd.to_numeric(merged.get("Common validation portfolios covered", 0), errors="coerce").fillna(0).clip(lower=0)
    merged["Common validation portfolios covered"] = merged[["Unexplained", "Common validation portfolios covered"]].min(axis=1)
    merged["Other causes"] = (merged["Unexplained"] - merged["Common validation portfolios covered"]).clip(lower=0)
    merged["DateLabel"] = merged["RunDate"].dt.strftime("%d/%m/%y")
    merged["_DateSort"] = merged["RunDate"].dt.strftime("%Y%m%d")
    out = merged.melt(
        id_vars=["RunDate", "DateLabel", "_DateSort"],
        value_vars=["Common validation portfolios covered", "Other causes"],
        var_name="Coverage bucket",
        value_name="Value",
    )
    out["Value"] = pd.to_numeric(out["Value"], errors="coerce").fillna(0)
    return out[cols].copy()


def _render_common_candidate_trend_chart(common_candidate_df: pd.DataFrame) -> None:
    """Render common validation securities with centred labels on every positive Asset Type segment."""
    chart_df = _trend_common_candidate_security_chart_long_df(common_candidate_df)
    if chart_df.empty:
        st.info("No common validation security Asset Type trend data is available for the selected date range/settings.")
        return
    try:
        import altair as alt
        work = chart_df.copy()
        work["Value"] = pd.to_numeric(work["Value"], errors="coerce").fillna(0)
        date_order = work[["DateLabel", "_DateSort"]].drop_duplicates().sort_values("_DateSort")["DateLabel"].astype(str).tolist()
        asset_types = sorted(work["Asset Type"].astype(str).dropna().unique().tolist())
        palette = list(globals().get("TREND_DEFAULT_COLOUR_RANGE", [])) or ["#1F77B4", "#FF7F0E", "#2CA02C", "#D62728", "#9467BD", "#8C564B", "#E377C2"]
        colour_scale = alt.Scale(domain=asset_types, range=[palette[i % len(palette)] for i in range(len(asset_types))])
        base = alt.Chart(work).encode(
            x=alt.X("DateLabel:N", title="Run date", sort=date_order, axis=alt.Axis(labelAngle=0)),
            order=alt.Order("Asset Type:N", sort="ascending"),
        )
        bars = base.mark_bar().encode(
            y=alt.Y("Value:Q", title="Number of securities", stack="zero"),
            color=alt.Color("Asset Type:N", title="Asset Type", scale=colour_scale),
            tooltip=[
                alt.Tooltip("DateLabel:N", title="Run date"),
                alt.Tooltip("Asset Type:N", title="Asset Type"),
                alt.Tooltip("Value:Q", title="Number of securities", format=",.0f"),
            ],
        ).properties(height=400)
        labels = base.transform_filter("datum.Value > 0").mark_text(
            color="black",
            fontWeight="bold",
            fontSize=12,
            baseline="middle",
            align="center",
            dy=0,
            clip=False,
        ).encode(
            y=alt.Y("Value:Q", stack="center"),
            detail="Asset Type:N",
            text=alt.Text("Value:Q", format=",.0f"),
        )
        st.altair_chart(bars + labels, width="stretch")
    except Exception as exc:
        st.warning(f"Common validation securities chart render failed ({type(exc).__name__}: {exc}). Showing data table instead.")
        show_df(common_candidate_df, hide_index=True)



# v365: removed diagnostic-only patch 'DAssetReturn TREND DEPENDENCY + LOW-LEVEL
# TIMING TRACE v306.13.7.2' (self-labelled diagnostic-only). It wrapped
# _bnp_source_file_aggregated_v184, build_unexplained_minimum_validation_sets,
# build_unexplained_common_validation_candidates and
# _build_or_refresh_executive_trend_history purely to build
# dar_trend_dependency_trace_df / dar_parse_low_level_timing_df, which were
# stored on the result dict but never read anywhere else in the app (confirmed
# via full-file search) and never written to disk (CSV write already stubbed).
# Removing the wrapper block restores each function to its real, unwrapped
# definition - no behaviour change. See CHANGELOG.md v365.
# ========================================================
# DAssetReturn TREND SLIM PROJECTION + HEADER PROBE PATCH v306.13.7.3_7.4
# 7.3: Trend-only safe post-load DAssetReturn column projection
# 7.4: Improved low-level DAssetReturn probe that locates the real BNP header row
# ========================================================

DAR_TREND_SLIM_PATCH_VERSION = "v306.13.7.3_7.4_dar_safe_slim_projection_and_header_probe"
_DAR_TREND_SLIM_PROJECTION_ROWS = []

# Safe retained list for Trend History. This includes the 18 common-validation candidates plus
# additional columns used by concentration/current-account/holding-preview style Trend bundle steps.
TREND_DAR_SAFE_SLIM_COLUMNS = [
    "Effective_date",
    "Trust/Sector",
    "Portfolio",
    "External portfolio reference",
    "Asset Type",
    "Asset Type description",
    "Asset Code",
    "Asset Name",
    "CCY",
    "Holding Quantity Prev_Day",
    "Holding Quantity Curr_Day",
    "Asset Price Prev_Day",
    "Asset Price Curr_Day",
    "FDV Valuation Prev_Day",
    "FDV Valuation Curr_Day",
    "Cashflow",
    "Income",
    "Transactions",
    "All Transactions",
    "Variance",
    "Change in Unrealised Profit",
    "Asset Weight",
    "Benchmark Weight",
    "Weight Deviation",
    "Actual Return",
    "Price Return",
    "Tolerance",
    "Return Deviation",
    "Tol Deviation",
    "Price Deviation",
    "Trust Contribution",
    "Asset to Portfolio Contributions",
    "Benchmark Contribution",
    "Excess Contribution",
    "FX Return",
    "FX Return Deviation",
    "Comments",
]

# Columns that prove the common-validation path has what it needs.
TREND_DAR_COMMON_VALIDATION_COLUMNS = [
    "Effective_date",
    "Portfolio",
    "External portfolio reference",
    "Asset Type",
    "Asset Type description",
    "Asset Code",
    "Asset Name",
    "CCY",
    "Asset Price Prev_Day",
    "Asset Price Curr_Day",
    "Actual Return",
    "Price Return",
    "Asset to Portfolio Contributions",
    "Benchmark Contribution",
    "Excess Contribution",
    "FX Return",
    "FX Return Deviation",
    "Comments",
]


def _dar73_now():
    try:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""


def _dar73_cache_dir():
    try:
        return str(CACHE_DIR)
    except Exception:
        return "trend_cache"


def _dar73_mem_mb(df):
    try:
        if isinstance(df, pd.DataFrame):
            return round(float(df.memory_usage(deep=True).sum()) / (1024 ** 2), 4)
    except Exception:
        pass
    return 0.0


def _dar73_active():
    # The v306.13.7.0 source profile sets this during Trend History builds.
    return bool(globals().get("_TREND_HISTORY_FAST_SOURCE_PROFILE_ACTIVE", False))


def _dar73_low_timing(stage, status="Done", elapsed=0.0, rows="", bytes_read="", files="", detail="", source_folder=""):
    # Prefer the v306.13.7.2 timing sink if present so all parser diagnostics land in one file.
    try:
        if callable(globals().get("_dar_low_timing_add")):
            _dar_low_timing_add(stage, status=status, elapsed=elapsed, rows=rows, bytes_read=bytes_read, files=files, detail=detail, source_folder=source_folder)
            return
    except Exception:
        pass
    try:
        if "_DAR_TREND_LOW_LEVEL_TIMING_ROWS" in globals():
            _DAR_TREND_LOW_LEVEL_TIMING_ROWS.append({
                "Stage": str(stage or ""),
                "Status": str(status or ""),
                "ElapsedSeconds": round(float(elapsed or 0), 4),
                "Rows": rows,
                "Bytes": bytes_read,
                "Files": files,
                "SourceFolder": str(source_folder or ""),
                "Detail": str(detail or ""),
                "RecordedAt": _dar73_now(),
                "PatchVersion": DAR_TREND_SLIM_PATCH_VERSION,
            })
    except Exception:
        pass


def _dar73_add_projection_row(stage, status="Done", source_folder="", before_rows="", before_cols="", before_mb="", after_rows="", after_cols="", after_mb="", retained_cols="", missing_cols="", detail=""):
    try:
        _DAR_TREND_SLIM_PROJECTION_ROWS.append({
            "Stage": str(stage or ""),
            "Status": str(status or ""),
            "SourceFolder": str(source_folder or ""),
            "BeforeRows": before_rows,
            "BeforeColumns": before_cols,
            "BeforeMemoryMB": before_mb,
            "AfterRows": after_rows,
            "AfterColumns": after_cols,
            "AfterMemoryMB": after_mb,
            "RetainedColumns": " | ".join(map(str, retained_cols)) if isinstance(retained_cols, (list, tuple)) else str(retained_cols or ""),
            "MissingColumns": " | ".join(map(str, missing_cols)) if isinstance(missing_cols, (list, tuple)) else str(missing_cols or ""),
            "Detail": str(detail or ""),
            "RecordedAt": _dar73_now(),
            "PatchVersion": DAR_TREND_SLIM_PATCH_VERSION,
        })
    except Exception:
        pass


def _dar73_write_projection_file(result=None):
    try:
        import os as _os
        _os.makedirs(_dar73_cache_dir(), exist_ok=True)
        slim_df = pd.DataFrame(_DAR_TREND_SLIM_PROJECTION_ROWS)
        slim_path = _os.path.join(_dar73_cache_dir(), "dar_trend_slim_projection_last_run.csv")
        pass  # [removed] diagnostic CSV write
        if isinstance(result, dict):
            result["dar_trend_slim_projection_df"] = slim_df
    except Exception:
        pass


def _dar73_resolve_columns(df, requested_cols):
    try:
        actual = list(df.columns)
        by_norm = {str(c).strip().casefold(): c for c in actual}
        resolved = []
        missing = []
        for col in requested_cols:
            key = str(col).strip().casefold()
            if key in by_norm:
                resolved.append(by_norm[key])
            else:
                missing.append(col)
        # Preserve source column order, not requested order, to minimise downstream surprises.
        resolved_set = set(resolved)
        ordered = [c for c in actual if c in resolved_set]
        return ordered, missing
    except Exception:
        return [], list(requested_cols)


def _dar73_project_dar_for_trend(df, folder=""):
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return df
    if not _dar73_active():
        return df
    started = time.perf_counter()
    before_rows = int(len(df))
    before_cols = int(len(df.columns))
    before_mb = _dar73_mem_mb(df)
    retained, missing = _dar73_resolve_columns(df, TREND_DAR_SAFE_SLIM_COLUMNS)
    common_retained, common_missing = _dar73_resolve_columns(df, TREND_DAR_COMMON_VALIDATION_COLUMNS)
    if not retained:
        _dar73_add_projection_row(
            "DAssetReturn safe slim projection",
            "Skipped",
            source_folder=folder,
            before_rows=before_rows,
            before_cols=before_cols,
            before_mb=before_mb,
            after_rows=before_rows,
            after_cols=before_cols,
            after_mb=before_mb,
            retained_cols=[],
            missing_cols=missing,
            detail="No retained columns resolved; returned original dataframe.",
        )
        return df
    out = df.loc[:, retained].copy()
    after_mb = _dar73_mem_mb(out)
    _dar73_add_projection_row(
        "DAssetReturn safe slim projection",
        "Done",
        source_folder=folder,
        before_rows=before_rows,
        before_cols=before_cols,
        before_mb=before_mb,
        after_rows=int(len(out)),
        after_cols=int(len(out.columns)),
        after_mb=after_mb,
        retained_cols=retained,
        missing_cols=missing,
        detail=f"common_validation_columns_present={len(common_retained)}; common_validation_missing={common_missing}; elapsed={round(time.perf_counter() - started, 4)}s",
    )
    _dar73_low_timing(
        "DAssetReturn safe slim projection",
        "Done",
        elapsed=time.perf_counter() - started,
        rows=int(len(out)),
        detail=f"before={before_rows}x{before_cols} {before_mb}MB; after={len(out)}x{len(out.columns)} {after_mb}MB; missing={missing}",
        source_folder=folder,
    )
    return out


def _dar73_matching_files(folder):
    files = []
    started = time.perf_counter()
    try:
        import os as _os
        for name in _os.listdir(folder):
            lower = str(name).lower()
            if "dassetreturn" in lower and not any(str(tok).lower() in lower for tok in globals().get("EXCLUDED_FILENAME_TOKENS", [])):
                full = _os.path.join(folder, name)
                if _os.path.isfile(full):
                    files.append(full)
        _dar73_low_timing("DAssetReturn improved file discovery", "Done", elapsed=time.perf_counter() - started, files=len(files), source_folder=folder)
    except Exception as exc:
        _dar73_low_timing("DAssetReturn improved file discovery", "Error", elapsed=time.perf_counter() - started, files=0, detail=f"{type(exc).__name__}: {exc}", source_folder=folder)
    return files


def _dar73_find_real_header(csv_path, max_scan_rows=80):
    """Find the real BNP DAssetReturn header row instead of the first physical CSV row.

    BNP source files can have leading metadata rows. The previous probe read physical row 1, which
    often had only 3 columns; this scan selects the row with the strongest required-column match.
    """
    import csv as _csv
    required_norm = {str(c).strip().casefold() for c in TREND_DAR_COMMON_VALIDATION_COLUMNS}
    best = {"row_index": None, "header": [], "score": -1, "matched": []}
    with open(csv_path, "r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        reader = _csv.reader(handle)
        for i, row in enumerate(reader):
            if i >= max_scan_rows:
                break
            norm_row = [str(x).strip().casefold() for x in row]
            matched = [x for x in norm_row if x in required_norm]
            score = len(matched)
            # Strong shortcut: the real header should include Portfolio + Asset Code + contribution.
            has_core = (
                "portfolio" in norm_row
                and "asset code" in norm_row
                and "asset to portfolio contributions" in norm_row
            )
            if score > best["score"] or (score == best["score"] and has_core):
                best = {"row_index": i, "header": row, "score": score, "matched": matched}
            if has_core and score >= 6:
                break
    return best


def _dar_file_probe(folder):
    """Improved v306.13.7.4 low-level probe aligned to real BNP header detection.

    This intentionally shadows the v306.13.7.2 probe. The existing v306.13.7.2 wrapper calls the
    global _dar_file_probe name, so applying this patch upgrades the probe without adding another
    full parsing pass.
    """
    try:
        import os as _os
        import csv as _csv
        files = _dar73_matching_files(folder)
        stat_started = time.perf_counter()
        total_bytes = 0
        for fp in files:
            try:
                total_bytes += int(_os.path.getsize(fp))
            except Exception:
                pass
        _dar73_low_timing("DAssetReturn improved file stat", "Done", elapsed=time.perf_counter() - stat_started, bytes_read=total_bytes, files=len(files), source_folder=folder)
        for fp in files:
            name = _os.path.basename(fp)
            header_started = time.perf_counter()
            try:
                info = _dar73_find_real_header(fp)
                header = info.get("header", []) or []
                row_index = info.get("row_index")
                score = info.get("score")
                header_norm = {str(c).strip().casefold(): idx for idx, c in enumerate(header)}
                required_indexes = []
                missing = []
                for col in TREND_DAR_SAFE_SLIM_COLUMNS:
                    key = str(col).strip().casefold()
                    if key in header_norm:
                        required_indexes.append(header_norm[key])
                    else:
                        missing.append(col)
                _dar73_low_timing(
                    "DAssetReturn improved real header scan",
                    "Done" if row_index is not None and score >= 3 else "WeakMatch",
                    elapsed=time.perf_counter() - header_started,
                    rows=(row_index if row_index is not None else ""),
                    files=1,
                    detail=f"file={name}; real_header_row={row_index}; header_cols={len(header)}; matched_common_cols={score}; selected_indexes={len(required_indexes)}; missing_safe_cols={missing}",
                    source_folder=folder,
                )
            except Exception as exc:
                _dar73_low_timing("DAssetReturn improved real header scan", "Error", elapsed=time.perf_counter() - header_started, files=1, detail=f"file={name}; {type(exc).__name__}: {exc}", source_folder=folder)
                continue

            sample_started = time.perf_counter()
            sample_rows = 0
            selected_fields = 0
            all_fields = 0
            sample_limit = 2000
            try:
                if row_index is None:
                    raise RuntimeError("real header row was not resolved")
                with open(fp, "r", encoding="utf-8-sig", errors="replace", newline="") as handle:
                    reader = _csv.reader(handle)
                    for i, row in enumerate(reader):
                        if i <= row_index:
                            continue
                        sample_rows += 1
                        all_fields += min(len(row), 41)
                        selected_fields += sum(1 for idx in required_indexes if idx < len(row))
                        if sample_rows >= sample_limit:
                            break
                _dar73_low_timing(
                    "DAssetReturn improved csv.reader selected-column sample",
                    "Done",
                    elapsed=time.perf_counter() - sample_started,
                    rows=sample_rows,
                    files=1,
                    detail=f"file={name}; selected_fields={selected_fields}; all_fields_first_41={all_fields}; selected_indexes={len(required_indexes)}; sample_limit={sample_limit}",
                    source_folder=folder,
                )
            except Exception as exc:
                _dar73_low_timing("DAssetReturn improved csv.reader selected-column sample", "Error", elapsed=time.perf_counter() - sample_started, rows=sample_rows, files=1, detail=f"file={name}; {type(exc).__name__}: {exc}", source_folder=folder)
    except Exception as exc:
        _dar73_low_timing("DAssetReturn improved low-level probe", "Error", elapsed=0, detail=f"{type(exc).__name__}: {exc}", source_folder=folder)


# Wrap DAssetReturn aggregation so Trend source profile receives the safe slim dataframe.
if callable(globals().get("_bnp_source_file_aggregated_v184")) and not getattr(globals().get("_bnp_source_file_aggregated_v184"), "_dar73_slim_wrapped", False):
    _dar73_original_bnp_source_file_aggregated_v184 = _bnp_source_file_aggregated_v184

    def _bnp_source_file_aggregated_v184(keyword, folder):
        is_dar = str(keyword).strip().lower() == "dassetreturn"
        # If v306.13.7.2 is not installed, run the improved probe here. If it is installed,
        # its existing wrapper will call the now-shadowed improved _dar_file_probe.
        if is_dar and _dar73_active() and not getattr(_dar73_original_bnp_source_file_aggregated_v184, "_dar_trace_wrapped", False):
            _dar_file_probe(folder)
        df, meta, timing_rows = _dar73_original_bnp_source_file_aggregated_v184(keyword, folder)
        if is_dar and _dar73_active() and isinstance(df, pd.DataFrame):
            df = _dar73_project_dar_for_trend(df, folder=folder)
        return df, meta, timing_rows

    _bnp_source_file_aggregated_v184._dar73_slim_wrapped = True
    _bnp_source_file_aggregated_v184._dar73_original = _dar73_original_bnp_source_file_aggregated_v184


# Build wrapper writes slim projection diagnostics after Trend build.
if callable(globals().get("_build_or_refresh_executive_trend_history")) and not getattr(globals().get("_build_or_refresh_executive_trend_history"), "_dar73_slim_wrapped", False):
    _dar73_original_build_or_refresh_executive_trend_history = _build_or_refresh_executive_trend_history

    def _build_or_refresh_executive_trend_history(*args, **kwargs):
        global _DAR_TREND_SLIM_PROJECTION_ROWS
        _DAR_TREND_SLIM_PROJECTION_ROWS = []
        try:
            result = _dar73_original_build_or_refresh_executive_trend_history(*args, **kwargs)
            _dar73_write_projection_file(result if isinstance(result, dict) else None)
            return result
        except Exception:
            _dar73_write_projection_file(None)
            raise

    _build_or_refresh_executive_trend_history._dar73_slim_wrapped = True
    _build_or_refresh_executive_trend_history._dar73_original = _dar73_original_build_or_refresh_executive_trend_history



# ========================================================
# DAssetReturn PARSER-LEVEL SELECTED-COLUMN READER PATCH v306.13.7.5
# Moves Trend DAssetReturn slimming into the CSV parser path and disables low-level probe overhead by default.
# ========================================================

DAR_SELECTED_PARSER_PATCH_VERSION = "v306.13.7.5_dar_selected_column_parser"
_DAR_SELECTED_PARSER_ROWS = []

# Toggle for the bounded diagnostic probe introduced in v306.13.7.2/7.4.
# Keep false for clean benchmarking. Set True manually if header/sample probing is needed again.
ENABLE_DAR_LOW_LEVEL_PROBE = False

if "TREND_DAR_SAFE_SLIM_COLUMNS" not in globals():
    TREND_DAR_SAFE_SLIM_COLUMNS = [
        "Effective_date",
        "Trust/Sector",
        "Portfolio",
        "External portfolio reference",
        "Asset Type",
        "Asset Type description",
        "Asset Code",
        "Asset Name",
        "CCY",
        "Holding Quantity Prev_Day",
        "Holding Quantity Curr_Day",
        "Asset Price Prev_Day",
        "Asset Price Curr_Day",
        "FDV Valuation Prev_Day",
        "FDV Valuation Curr_Day",
        "Cashflow",
        "Income",
        "Transactions",
        "All Transactions",
        "Variance",
        "Change in Unrealised Profit",
        "Asset Weight",
        "Benchmark Weight",
        "Weight Deviation",
        "Actual Return",
        "Price Return",
        "Tolerance",
        "Return Deviation",
        "Tol Deviation",
        "Price Deviation",
        "Trust Contribution",
        "Asset to Portfolio Contributions",
        "Benchmark Contribution",
        "Excess Contribution",
        "FX Return",
        "FX Return Deviation",
        "Comments",
    ]

if "TREND_DAR_COMMON_VALIDATION_COLUMNS" not in globals():
    TREND_DAR_COMMON_VALIDATION_COLUMNS = [
        "Effective_date",
        "Portfolio",
        "External portfolio reference",
        "Asset Type",
        "Asset Type description",
        "Asset Code",
        "Asset Name",
        "CCY",
        "Asset Price Prev_Day",
        "Asset Price Curr_Day",
        "Actual Return",
        "Price Return",
        "Asset to Portfolio Contributions",
        "Benchmark Contribution",
        "Excess Contribution",
        "FX Return",
        "FX Return Deviation",
        "Comments",
    ]


def _dar75_now():
    try:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return ""


def _dar75_cache_dir():
    try:
        return str(CACHE_DIR)
    except Exception:
        return "trend_cache"


def _dar75_active():
    return bool(globals().get("_TREND_HISTORY_FAST_SOURCE_PROFILE_ACTIVE", False))


def _dar75_mem_mb(df):
    try:
        if isinstance(df, pd.DataFrame):
            return round(float(df.memory_usage(deep=True).sum()) / (1024 ** 2), 4)
    except Exception:
        pass
    return 0.0


def _dar75_add_row(stage, status="Done", elapsed=0.0, rows="", columns="", files="", bytes_read="", source_folder="", detail=""):
    try:
        _DAR_SELECTED_PARSER_ROWS.append({
            "Stage": str(stage or ""),
            "Status": str(status or ""),
            "ElapsedSeconds": round(float(elapsed or 0), 4),
            "Rows": rows,
            "Columns": columns,
            "Files": files,
            "Bytes": bytes_read,
            "SourceFolder": str(source_folder or ""),
            "Detail": str(detail or ""),
            "RecordedAt": _dar75_now(),
            "PatchVersion": DAR_SELECTED_PARSER_PATCH_VERSION,
        })
    except Exception:
        pass


def _dar75_low_timing(stage, status="Done", elapsed=0.0, rows="", files="", bytes_read="", detail="", source_folder=""):
    # Write into v306.13.7.2 timing sink if present, so selected-parser timings appear with the rest.
    try:
        if callable(globals().get("_dar_low_timing_add")):
            _dar_low_timing_add(stage, status=status, elapsed=elapsed, rows=rows, files=files, bytes_read=bytes_read, detail=detail, source_folder=source_folder)
    except Exception:
        pass


def _dar75_write_file(result=None):
    try:
        import os as _os
        _os.makedirs(_dar75_cache_dir(), exist_ok=True)
        df = pd.DataFrame(_DAR_SELECTED_PARSER_ROWS)
        out = _os.path.join(_dar75_cache_dir(), "dar_selected_column_parser_last_run.csv")
        pass  # [removed] diagnostic CSV write
        if isinstance(result, dict):
            result["dar_selected_column_parser_df"] = df
    except Exception:
        pass


def _dar75_matching_files(folder):
    import os as _os
    files = []
    started = time.perf_counter()
    total_entries = 0
    try:
        for name in _os.listdir(folder):
            total_entries += 1
            lower = str(name).lower()
            if "dassetreturn" not in lower:
                continue
            excluded = False
            for tok in globals().get("EXCLUDED_FILENAME_TOKENS", []):
                if str(tok).lower() in lower:
                    excluded = True
                    break
            if excluded:
                continue
            full = _os.path.join(folder, name)
            if _os.path.isfile(full):
                files.append(full)
        _dar75_add_row("DAssetReturn selected parser discovery", "Done", time.perf_counter() - started, files=len(files), source_folder=folder, detail=f"folder_entries={total_entries}")
        _dar75_low_timing("DAssetReturn selected parser discovery", "Done", time.perf_counter() - started, files=len(files), source_folder=folder, detail=f"folder_entries={total_entries}")
    except Exception as exc:
        _dar75_add_row("DAssetReturn selected parser discovery", "Error", time.perf_counter() - started, files=len(files), source_folder=folder, detail=f"{type(exc).__name__}: {exc}")
        raise
    return files


def _dar75_find_header(csv_path, max_scan_rows=100):
    import csv as _csv
    required_norm = {str(c).strip().casefold() for c in TREND_DAR_COMMON_VALIDATION_COLUMNS}
    best = {"row_index": None, "header": [], "score": -1}
    with open(csv_path, "r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        reader = _csv.reader(handle)
        for i, row in enumerate(reader):
            if i >= max_scan_rows:
                break
            norm_row = [str(x).strip().casefold() for x in row]
            score = sum(1 for x in norm_row if x in required_norm)
            has_core = (
                "portfolio" in norm_row
                and "asset code" in norm_row
                and "asset to portfolio contributions" in norm_row
            )
            if score > best["score"] or (score == best["score"] and has_core):
                best = {"row_index": i, "header": row, "score": score}
            if has_core and score >= 6:
                break
    return best


def _dar75_resolve_selected_indexes(header):
    # Case-insensitive lookup, preserve source column order.
    index_by_norm = {str(c).strip().casefold(): i for i, c in enumerate(header)}
    selected_pairs = []
    missing = []
    for col in TREND_DAR_SAFE_SLIM_COLUMNS:
        key = str(col).strip().casefold()
        if key in index_by_norm:
            selected_pairs.append((index_by_norm[key], header[index_by_norm[key]]))
        else:
            missing.append(col)
    selected_pairs = sorted(selected_pairs, key=lambda x: x[0])
    indexes = [x[0] for x in selected_pairs]
    columns = [str(x[1]).strip() for x in selected_pairs]
    return indexes, columns, missing


def _dar75_parse_one_file(path, folder=""):
    import os as _os
    import csv as _csv
    started = time.perf_counter()
    file_name = _os.path.basename(path)
    file_bytes = 0
    try:
        file_bytes = int(_os.path.getsize(path))
    except Exception:
        pass
    header_info = _dar75_find_header(path)
    header = header_info.get("header", []) or []
    header_row = header_info.get("row_index")
    score = header_info.get("score")
    if header_row is None or score is None or score < 3:
        raise RuntimeError(f"Could not resolve DAssetReturn header for {file_name}; score={score}; row={header_row}")
    indexes, columns, missing = _dar75_resolve_selected_indexes(header)
    if not indexes:
        raise RuntimeError(f"No selected DAssetReturn columns resolved for {file_name}")

    rows = []
    malformed = 0
    parse_started = time.perf_counter()
    with open(path, "r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        reader = _csv.reader(handle)
        for i, row in enumerate(reader):
            if i <= header_row:
                continue
            if not row or all(str(x).strip() == "" for x in row):
                continue
            out_row = []
            for idx in indexes:
                if idx < len(row):
                    out_row.append(row[idx])
                else:
                    out_row.append("")
                    malformed += 1
            rows.append(out_row)
    parse_elapsed = time.perf_counter() - parse_started
    df = pd.DataFrame(rows, columns=columns)
    elapsed = time.perf_counter() - started
    detail = f"file={file_name}; real_header_row={header_row}; header_cols={len(header)}; matched_common_cols={score}; selected_cols={len(columns)}; missing_safe_cols={missing}; malformed_cells={malformed}; parse_loop_elapsed={round(parse_elapsed,4)}s"
    _dar75_add_row("DAssetReturn selected parser file", "Done", elapsed, rows=len(df), columns=len(df.columns), files=1, bytes_read=file_bytes, source_folder=folder, detail=detail)
    _dar75_low_timing("DAssetReturn selected parser file", "Done", elapsed, rows=len(df), files=1, bytes_read=file_bytes, source_folder=folder, detail=detail)
    return df, {"file": file_name, "rows": len(df), "columns": len(df.columns), "bytes": file_bytes, "header_row": header_row, "missing_safe_cols": missing}


def _dar75_selected_column_parser(folder):
    import os as _os
    started = time.perf_counter()
    files = _dar75_matching_files(folder)
    frames = []
    meta_files = []
    total_bytes = 0
    for path in files:
        df_file, meta = _dar75_parse_one_file(path, folder=folder)
        frames.append(df_file)
        meta_files.append(meta)
        try:
            total_bytes += int(meta.get("bytes", 0))
        except Exception:
            pass
    if frames:
        df = pd.concat(frames, ignore_index=True, sort=False)
    else:
        df = pd.DataFrame(columns=list(TREND_DAR_SAFE_SLIM_COLUMNS))
    # Match previous cleanup behaviour as far as possible without changing values.
    try:
        df.columns = [str(c).strip() for c in df.columns]
    except Exception:
        pass
    elapsed = time.perf_counter() - started
    mem = _dar75_mem_mb(df)
    missing_common = [c for c in TREND_DAR_COMMON_VALIDATION_COLUMNS if str(c).strip().casefold() not in {str(x).strip().casefold() for x in df.columns}]
    detail = f"files={len(files)}; shape={df.shape}; memory_mb={mem}; missing_common_cols={missing_common}; mode=selected-column csv.reader"
    _dar75_add_row("DAssetReturn selected parser aggregate", "Done", elapsed, rows=len(df), columns=len(df.columns), files=len(files), bytes_read=total_bytes, source_folder=folder, detail=detail)
    _dar75_low_timing("DAssetReturn selected parser aggregate", "Done", elapsed, rows=len(df), files=len(files), bytes_read=total_bytes, source_folder=folder, detail=detail)
    meta = {
        "keyword": "DAssetReturn",
        "mode": "selected-column csv.reader",
        "files": meta_files,
        "rows": int(len(df)),
        "columns": int(len(df.columns)),
        "bytes": int(total_bytes),
        "memory_mb": mem,
        "patch_version": DAR_SELECTED_PARSER_PATCH_VERSION,
    }
    timing_rows = [
        {
            "Phase": f"BNP v184 trend source profile: DAssetReturn selected-column parser aggregate - {len(files)}/{len(files)} files; {len(df):,} rows; {len(df.columns)} cols; {total_bytes:,} bytes",
            "ElapsedSeconds": round(elapsed, 4),
            "Rows": int(len(df)),
            "Detail": detail,
        },
        {
            "Phase": "BNP v184 trend source profile: DAssetReturn selected-column parser memory",
            "ElapsedSeconds": 0.0,
            "Rows": int(len(df)),
            "Detail": f"memory_mb={mem}; columns={list(df.columns)}",
        },
    ]
    return df, meta, timing_rows


# Disable lower-level probe overhead by default. The selected-column parser already scans the real header.
def _dar_file_probe(folder):
    if bool(globals().get("ENABLE_DAR_LOW_LEVEL_PROBE", False)):
        # If an older probe was stored, use it; otherwise no-op.
        prior = globals().get("_dar75_previous_dar_file_probe")
        if callable(prior):
            return prior(folder)
    try:
        _dar75_low_timing("DAssetReturn low-level probe", "Skipped", 0.0, detail="ENABLE_DAR_LOW_LEVEL_PROBE is False; skipped for clean benchmark", source_folder=folder)
    except Exception:
        pass
    return None


# Wrap the BNP source aggregator. If v306.13.7.3 already wrapped it, unwrap to the base original for non-target/fallback.
if callable(globals().get("_bnp_source_file_aggregated_v184")) and not getattr(globals().get("_bnp_source_file_aggregated_v184"), "_dar75_selected_parser_wrapped", False):
    _dar75_current_bnp_source_file_aggregated_v184 = _bnp_source_file_aggregated_v184
    _dar75_base_bnp_source_file_aggregated_v184 = getattr(_dar75_current_bnp_source_file_aggregated_v184, "_dar73_original", _dar75_current_bnp_source_file_aggregated_v184)

    def _bnp_source_file_aggregated_v184(keyword, folder):
        is_dar = str(keyword).strip().lower() == "dassetreturn"
        if is_dar and _dar75_active():
            try:
                return _dar75_selected_column_parser(folder)
            except Exception as exc:
                _dar75_add_row("DAssetReturn selected parser fallback", "Error", 0.0, source_folder=folder, detail=f"{type(exc).__name__}: {exc}; falling back to previous parser")
                _dar75_low_timing("DAssetReturn selected parser fallback", "Error", 0.0, detail=f"{type(exc).__name__}: {exc}; falling back to previous parser", source_folder=folder)
                return _dar75_current_bnp_source_file_aggregated_v184(keyword, folder)
        return _dar75_base_bnp_source_file_aggregated_v184(keyword, folder)

    _bnp_source_file_aggregated_v184._dar75_selected_parser_wrapped = True
    _bnp_source_file_aggregated_v184._dar75_previous = _dar75_current_bnp_source_file_aggregated_v184
    _bnp_source_file_aggregated_v184._dar75_base = _dar75_base_bnp_source_file_aggregated_v184


# Build wrapper writes selected-parser diagnostics after Trend build.
if callable(globals().get("_build_or_refresh_executive_trend_history")) and not getattr(globals().get("_build_or_refresh_executive_trend_history"), "_dar75_selected_parser_wrapped", False):
    _dar75_original_build_or_refresh_executive_trend_history = _build_or_refresh_executive_trend_history

    def _build_or_refresh_executive_trend_history(*args, **kwargs):
        global _DAR_SELECTED_PARSER_ROWS
        _DAR_SELECTED_PARSER_ROWS = []
        try:
            result = _dar75_original_build_or_refresh_executive_trend_history(*args, **kwargs)
            _dar75_write_file(result if isinstance(result, dict) else None)
            return result
        except Exception:
            _dar75_write_file(None)
            raise

    _build_or_refresh_executive_trend_history._dar75_selected_parser_wrapped = True
    _build_or_refresh_executive_trend_history._dar75_original = _dar75_original_build_or_refresh_executive_trend_history



# v365: removed diagnostic-only patch 'DAssetReturn SELECTED PARSER TIMING
# LABEL + COLUMN USAGE TRACE PATCH v306.13.7.5.1'. It wrapped
# _dar75_selected_column_parser and _build_or_refresh_executive_trend_history
# purely to build dar_retained_column_usage_trace_df, stored on the result
# dict but never read elsewhere (confirmed via full-file search) and never
# written to disk (CSV write already stubbed). Removing the wrapper block
# restores each function to its real, unwrapped definition - no behaviour
# change. See CHANGELOG.md v365.
# v365: removed diagnostic-only patch 'TREND PERFORMANCE PROFILE + FX
# EXTERNALS DIAGNOSTICS PATCH v306.13.7.6'. It wrapped
# _dar75_selected_column_parser, _prepare_exchange_rate_source and
# _build_or_refresh_executive_trend_history purely to build
# dar_profile_ab_comparison_df / fx_workbook_discovery_diagnostics_df, stored
# on the result dict but never read elsewhere (confirmed via full-file
# search) and never written to disk (CSV write already stubbed). Removing
# the wrapper block restores each function to its real, unwrapped
# definition - no behaviour change; FX business logic was explicitly
# untouched by this patch per its own header comment. See CHANGELOG.md v365.
# v365: removed diagnostic-only patch 'v306.13.7.6b COMPLETE PATCH: app
# diagnostics + timing label fix'. Same wrap targets as v306.13.7.6
# (_dar75_selected_column_parser, _prepare_exchange_rate_source,
# _build_or_refresh_executive_trend_history); its CSV writes
# (dar_profile_ab_comparison_last_run.csv, dar_profile_ab_timing_last_run.csv,
# fx_workbook_discovery_diagnostics_last_run.csv) were already stubbed to
# no-ops. Removing the wrapper block restores each function to its real,
# unwrapped definition - no behaviour change. See CHANGELOG.md v365.

# ========================================================
# v306.13.13 STATIC DATA BUNDLE SAFETY FIX
# ========================================================
# Guarantees Static Data globals exist before Tableau and BP Impact Tool wrappers
# reference them. Fixes diagnostics error:
# NameError: name 'STATIC_DATA_BUNDLE' is not defined.

def _ensure_static_data_bundle_v306_13_13() -> Dict[str, object]:
    global STATIC_DATA_BUNDLE, STATIC_DATA_EXCEPTION_DF, STATIC_DATA_VALIDATION_DF, STATIC_DATA_META_DF, STATIC_DATA_GLOBAL_OVERRIDE_DF

    if "STATIC_DATA_BUNDLE" not in globals() or not isinstance(globals().get("STATIC_DATA_BUNDLE"), dict):
        STATIC_DATA_BUNDLE = {"tables": {}}
    if "STATIC_DATA_EXCEPTION_DF" not in globals() or not isinstance(globals().get("STATIC_DATA_EXCEPTION_DF"), pd.DataFrame):
        STATIC_DATA_EXCEPTION_DF = pd.DataFrame()
    if "STATIC_DATA_VALIDATION_DF" not in globals() or not isinstance(globals().get("STATIC_DATA_VALIDATION_DF"), pd.DataFrame):
        STATIC_DATA_VALIDATION_DF = pd.DataFrame()
    if "STATIC_DATA_META_DF" not in globals() or not isinstance(globals().get("STATIC_DATA_META_DF"), pd.DataFrame):
        STATIC_DATA_META_DF = pd.DataFrame()
    if "STATIC_DATA_GLOBAL_OVERRIDE_DF" not in globals() or not isinstance(globals().get("STATIC_DATA_GLOBAL_OVERRIDE_DF"), pd.DataFrame):
        STATIC_DATA_GLOBAL_OVERRIDE_DF = pd.DataFrame()

    # If the bundle is empty but the static-data helper is available, load now.
    try:
        tables = STATIC_DATA_BUNDLE.get("tables", {}) if isinstance(STATIC_DATA_BUNDLE, dict) else {}
        if (not tables) and callable(globals().get("_load_static_data_v306_13_8")):
            loaded = _load_static_data_v306_13_8(app_file_path=__file__)
            if isinstance(loaded, dict):
                STATIC_DATA_BUNDLE = loaded
                STATIC_DATA_EXCEPTION_DF = loaded.get("static_exception_df", pd.DataFrame())
                STATIC_DATA_VALIDATION_DF = loaded.get("static_validation_df", pd.DataFrame())
                STATIC_DATA_META_DF = loaded.get("static_meta_df", pd.DataFrame())
    except Exception as exc:
        STATIC_DATA_EXCEPTION_DF = pd.concat([
            STATIC_DATA_EXCEPTION_DF if isinstance(STATIC_DATA_EXCEPTION_DF, pd.DataFrame) else pd.DataFrame(),
            pd.DataFrame([{"Severity": "Error", "Check": "StaticDataBundleSafetyLoad", "Detail": f"{type(exc).__name__}: {exc}"}]),
        ], ignore_index=True, sort=False)

    return STATIC_DATA_BUNDLE if isinstance(STATIC_DATA_BUNDLE, dict) else {"tables": {}}


# Initialise once immediately so downstream wrappers and diagnostics can rely on it.
try:
    _ensure_static_data_bundle_v306_13_13()
except Exception:
    pass

# v306.13.8 TABLEAU / UNISON BO SOURCE WRAPPER
# ========================================================
# Adds the three Tableau CSVs to the dashboard bundle without changing the
# existing calculation path yet. This is the first ARC replacement input layer.
if callable(globals().get("_prepare_out_dashboard_bundle")) and not getattr(globals().get("_prepare_out_dashboard_bundle"), "_static_tableau_v306_13_8_wrapped", False):
    _prepare_out_dashboard_bundle_v306_13_8_original = _prepare_out_dashboard_bundle

    def _prepare_out_dashboard_bundle(*args, **kwargs) -> Dict[str, object]:
        bundle = _prepare_out_dashboard_bundle_v306_13_8_original(*args, **kwargs)
        try:
            folder = args[0] if args else kwargs.get("folder", "")
            run_date_value = parse_date_from_path(str(folder or ""))
            if run_date_value is None and isinstance(bundle, dict):
                run_date_value = bundle.get("run_date", bundle.get("RunDate", ""))
            if _prepare_tableau_sources_v306_13_8 is None:
                tableau_bundle = {
                    "tableau_exception_df": pd.DataFrame([{"Severity": "Warning", "Check": "TableauHelperImport", "Detail": "bnp_helpers_tableau.py not available."}]),
                    "tableau_file_meta_df": pd.DataFrame(),
                    "tableau_diagnostic_df": pd.DataFrame(),
                    "tableau_timing_df": pd.DataFrame(),
                }
            else:
                tableau_bundle = _prepare_tableau_sources_v306_13_8(run_date_value, static_bundle=_ensure_static_data_bundle_v306_13_13())
            if isinstance(bundle, dict):
                bundle["static_data"] = STATIC_DATA_BUNDLE
                bundle["static_data_meta_df"] = STATIC_DATA_META_DF
                bundle["static_data_validation_df"] = STATIC_DATA_VALIDATION_DF
                bundle["static_data_exception_df"] = STATIC_DATA_EXCEPTION_DF
                bundle["static_data_global_override_df"] = STATIC_DATA_GLOBAL_OVERRIDE_DF
                bundle["tableau"] = tableau_bundle
                for key in [
                    "tableau_folder",
                    "acc_balance_df",
                    "tableau_price_sf_df",
                    "tableau_price_trust_df",
                    "tableau_file_meta_df",
                    "tableau_diagnostic_df",
                    "tableau_exception_df",
                    "tableau_timing_df",
                ]:
                    bundle[key] = tableau_bundle.get(key, pd.DataFrame() if key.endswith("_df") else "")
                # Append Tableau timing into existing full-run timing when available.
                try:
                    if isinstance(bundle.get("tableau_timing_df"), pd.DataFrame) and not bundle["tableau_timing_df"].empty:
                        existing = bundle.get("prepare_timing_df", pd.DataFrame())
                        if isinstance(existing, pd.DataFrame):
                            bundle["prepare_timing_df"] = pd.concat([existing, bundle["tableau_timing_df"]], ignore_index=True, sort=False)
                except Exception:
                    pass
        except Exception as exc:
            try:
                if isinstance(bundle, dict):
                    bundle["tableau_exception_df"] = pd.DataFrame([{"Severity": "Error", "Check": "TableauBundleAttach", "Detail": f"{type(exc).__name__}: {exc}"}])
            except Exception:
                pass
        return bundle

    _prepare_out_dashboard_bundle._static_tableau_v306_13_8_wrapped = True


# v367: removed the 'v306.13.9 BP IMPACT TOOL ERROR RISK SOURCE WRAPPER'.
# Confirmed dead: it wrapped the (already-dead) original
# _prepare_arc_error_risk, and its own wrapped version was itself
# immediately shadowed by the unconditional top-level 'def' at
# v306.13.15 further down the file (kept, then itself superseded by
# v306.13.16 - the live version). Neither this wrap's closure nor its
# '_original' capture is referenced anywhere else. See CHANGELOG.md v367.




# ========================================================
# v306.13.11 PORTFOLIO NUMBERS SOURCE LOAD DIAGNOSTICS
# ========================================================
# Renders Static Data, Tableau / Unison BO, and BP Impact Tool Error Risk load
# checks inside Portfolio Numbers -> Diagnostic support, avoiding a separate
# sidebar diagnostics location.

def _pn_source_diag_safe_df_v306_13_11(value) -> pd.DataFrame:
    try:
        return value.copy() if isinstance(value, pd.DataFrame) else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def _pn_source_diag_status_v306_13_11(meta_df: pd.DataFrame, exception_df: pd.DataFrame, expected_loaded: int = 0) -> str:
    try:
        if isinstance(exception_df, pd.DataFrame) and not exception_df.empty:
            sev = exception_df.get("Severity", pd.Series(dtype="object")).astype(str).str.lower()
            if sev.str.contains("error", na=False).any():
                return "Error"
            if sev.str.contains("warning", na=False).any():
                return "Warning"
        if isinstance(meta_df, pd.DataFrame) and not meta_df.empty:
            if "Loaded" in meta_df.columns:
                loaded = meta_df["Loaded"].fillna(False).astype(bool)
                if expected_loaded and int(loaded.sum()) < int(expected_loaded):
                    return "Partial"
                if len(loaded) and bool(loaded.all()):
                    return "Loaded"
                return "Partial"
            return "Available"
        return "Not available"
    except Exception:
        return "Unknown"


# v342 Phase 1: _pn_source_load_summary_df_v306_13_11 (the v11-only summary builder)
# was removed with its renderer. The retained panel uses the v14 summary, which
# reuses the _12 summary and adds ARC-aware Error Risk rows.


# v342 Phase 1: _render_portfolio_numbers_source_load_diagnostics_v306_13_11 was one
# of three near-identical source-load diagnostic renderers. It (and the _12 variant)
# were removed - the single consolidated renderer is now
# _render_source_load_checks_under_portfolio_numbers_v306_13_14.


def main():
    global SHOW_DEBUG
    st.set_page_config(layout="wide", initial_sidebar_state="collapsed")
    _inject_app_chrome_css()
    # v331: DETERMINISTIC first-load landing. The v328 sub-section default relied on
    # the radio's index-0 fallback, but a session that already carried a valid older
    # value (e.g. the pre-v328 "Data Sources" default) never got reset - so the app
    # did not reliably land on Portfolio Numbers -> Reconciliation export. This primes
    # BOTH the top-level section and the sub-section ONCE per session (sentinel-guarded),
    # BEFORE any widget with those keys is created, so the landing is guaranteed while
    # later user navigation is preserved. Pairs with the v328 eager warm-up, which has
    # already populated every check frame at prepare time so the export is complete here.
    if not st.session_state.get("_v331_landing_done"):
        st.session_state["dashboard_selected_section"] = "portfolio_count"   # Portfolio Numbers
        st.session_state["portfolio_count_sub_section"] = "Reconciliation export"
        st.session_state["_v331_landing_done"] = True
    SHOW_DEBUG = st.sidebar.checkbox("Show debug / diagnostics", value=False)
    # v351: removed the "Fast Excel engine (calamine)" and "Copy-local FDV reads"
    # sidebar toggles and all their wiring. Calamine gave no measurable gain (the real
    # cost is the FDV CSV, which it can't touch) and carried dtype-inference risk;
    # copy-local made the first FDV read WORSE (64s) on this bandwidth-capped share; the
    # FDV Parquet layer is replaced by a pickle cache. The FX/Error-Risk Excel in-process
    # cache is retained (mem only). The FDV pickle cache is pointed at the SAME
    # .bnp_manifest_cache folder the BNP source pickle uses, so reopens of a date read
    # the local pickle (~0.05s) instead of re-reading G:/ - the same mechanism that
    # already makes the BNP reports fast on reopen.
    # v351.1 FIX: point the FDV + Excel pickle caches at the SAME directory the BNP
    # source pickle actually uses - _manifest_cache_dir() (= Path(__file__).parent /
    # .bnp_manifest_cache), NOT os.getcwd(). Under `streamlit run` the working directory
    # is often not the app folder (and may be non-writable), so the v351 os.getcwd()
    # base wrote the FDV pickle to the wrong place - which is why reopens never hit it
    # and FDV re-read ~22s every time. Using the proven manifest dir makes the FDV/Excel
    # pickles co-locate with the BNP pickle that already works on reopen.
    try:
        _bnp_cache_dir_v351_1 = str(_manifest_cache_dir())
    except Exception:
        _bnp_cache_dir_v351_1 = os.path.join(os.getcwd(), ".bnp_manifest_cache")
    try:
        from bnp_helpers_columns import set_excel_cache_dir as _set_xl_cache_dir_v346
        _xl_cache_dir_v351 = os.environ.get("BNP_EXCEL_CACHE_DIR", "").strip() or _bnp_cache_dir_v351_1
        _set_xl_cache_dir_v346(_xl_cache_dir_v351)
    except Exception:
        pass
    try:
        from bnp_helpers_fdv_enrichment import set_fdv_pickle_dir as _set_fdv_pkl_v351
        _fdv_pkl_dir_v351 = os.environ.get("BNP_FDV_CACHE_DIR", "").strip() or _bnp_cache_dir_v351_1
        _set_fdv_pkl_v351(_fdv_pkl_dir_v351)
    except Exception:
        pass
    # v355 PROTOTYPE: A/B the executive card render. Off = current HTML card; on =
    # native Streamlit widgets (no HTML-component mount). Toggle it and compare the
    # run-log's "15 render executive summary HTML" row to see if the native path is
    # faster. Default off = zero change to current behaviour.
    try:
        _exec_native_v355 = st.sidebar.checkbox(
            "Exec card: native widgets (prototype)", value=False,
            help="Render the executive summary card with native Streamlit widgets instead of the "
                 "custom-HTML component. Measure the '15 render executive summary HTML' timing with "
                 "it on vs off - native avoids the HTML-component mount cost. Visual style differs.",
        )
        set_exec_card_native(bool(_exec_native_v355))
    except Exception:
        pass
    dashboard_mode = st.sidebar.radio(
        "Dashboard mode",
        ["Daily Dashboard", "Trend History"],
        index=0,
        key="dashboard_mode_v306_11_0",
    )
    _render_asset_type_code_map_sidebar()
    if dashboard_mode == "Trend History":
        _render_trend_history_dashboard(ROOT_FOLDER)
    else:
        render_out_portfolio_control_dashboard(ROOT_FOLDER)




# v306.13.7.8 activate folder_fingerprint wrapper after function definitions
try:
    _v306_13_7_8_wrap_folder_fingerprint()
except Exception:
    pass



# ========================================================
# v306.13.7.8a diagnostics hotfix
# - Overrides the v306.13.7.7 rollup functions used by the existing to_csv wrapper
# - Keeps v306.13.7.8 fingerprint cache logic unchanged
# - Produces additive rollups with ElapsedRole / AdditiveElapsedSeconds
# - Handles cached non-force DAR slim projection as Skipped rather than EmptyDataError
# ========================================================
try:
    import os as _v306_13_7_8a_os
    from pathlib import Path as _v306_13_7_8a_Path
    import pandas as _v306_13_7_8a_pd

    _V306_13_7_8A_VERSION = "v306.13.7.8a_rollup_override_and_slim_projection_hotfix"

    def _v306_13_7_8a_base_to_csv(df, path, index=False):
        base_writer = globals().get("_v306_13_7_7_ORIGINAL_TO_CSV", None)
        if base_writer is None:
            base_writer = globals().get("_v306_13_7_8_BASE_TO_CSV", None)
        if base_writer is None:
            base_writer = _v306_13_7_8a_pd.DataFrame.to_csv
        return base_writer(df, path, index=index)

    def _v306_13_7_8a_phase_group(scope, phase, detail=""):
        text = (str(scope or "") + " " + str(phase or "") + " " + str(detail or "")).lower()
        if "source.folder_fingerprint" in text or "folder fingerprint" in text:
            return "01 folder fingerprint"
        if "cache.per_date_hit_check" in text:
            return "14 trend cache read/write/filter"
        if "dassetreturn selected" in text or "dassetreturn source" in text:
            return "02 DAssetReturn parse/load"
        if "dassetreturn total" in text:
            return "02 DAssetReturn parse/load"
        if "ddetailedreturn" in text:
            return "03 DDetailedReturn parse/load"
        if "dassettypereturn" in text:
            return "04 DAssetTypeReturn parse/load"
        if "benchmarkstatic" in text:
            return "05 BenchmarkStatic parse/load"
        if "persistent source dataframe cache" in text or "bnp load:" in text:
            return "06 persistent source cache"
        if "arc " in text or "arc_" in text or "prepare arc" in text:
            return "07 ARC load"
        if "fx find" in text or "fx workbook" in text or "fx diagnostics" in text or "fx load" in text or "fx validation" in text:
            return "08 FX load/validation"
        if "process_day" in text or "process day" in text:
            return "09 process_day core"
        if "portfolio calc" in text or "transaction map" in text:
            return "10 portfolio calc / transaction map"
        if "build executive summary" in text or "snapshot.executive" in text or "executive_summary" in text:
            return "11 executive summary / snapshot"
        if "minimum validation" in text:
            return "12 minimum validation"
        if "common candidate" in text or "common_validation" in text:
            return "13 common validation candidates"
        if "cache.read" in text or "cache.write" in text or "cache.dedupe" in text or "cache.filter" in text:
            return "14 trend cache read/write/filter"
        if "bundle.prepare_out_dashboard_bundle" in text:
            return "15 bundle.prepare_out_dashboard_bundle"
        if "trend_history.total" in text or "total_build" in text:
            return "99 trend history total"
        return "98 other / unclassified"

    def _v306_13_7_8a_elapsed_role(scope, phase, detail=""):
        text = (str(scope or "") + " " + str(phase or "") + " " + str(detail or "")).lower()
        if "trend_history.total" in text or "total_build" in text:
            return "ParentTotal"
        if "bundle.prepare_out_dashboard_bundle" in text:
            return "ParentTotal"
        if "total source load/prime" in text:
            return "ParentTotal"
        if "memoized_store" in text:
            return "Mirror"
        if "selected-column parser memory" in text:
            return "DiagnosticZero"
        if "dassetreturn total" in text:
            return "ParentTotal"
        if "ddetailedreturn total" in text or "dassettypereturn total" in text or "benchmarkstatic total" in text:
            return "ParentTotal"
        if "process_day: total" in text or "portfolio calc: total" in text:
            return "ParentTotal"
        return "Child"

    def _v306_13_7_7_build_slim_projection(timing_csv_path):
        base_dir = _v306_13_7_8a_Path(timing_csv_path).parent
        out_path = base_dir / "dar_trend_slim_projection_last_run.csv"
        ab_path = base_dir / "dar_profile_ab_comparison_last_run.csv"
        try:
            if not ab_path.exists() or ab_path.stat().st_size == 0:
                out = _v306_13_7_8a_pd.DataFrame([{
                    "Status": "Skipped",
                    "Detail": "DAR profile A/B comparison was not produced on this cached non-force run.",
                    "PatchVersion": _V306_13_7_8A_VERSION,
                }])
                _v306_13_7_8a_base_to_csv(out, out_path, index=False)
                return
            try:
                ab = _v306_13_7_8a_pd.read_csv(ab_path)
            except Exception as exc:
                out = _v306_13_7_8a_pd.DataFrame([{
                    "Status": "Skipped",
                    "Detail": f"DAR profile A/B comparison could not be read on this cached/non-force run: {type(exc).__name__}: {exc}",
                    "PatchVersion": _V306_13_7_8A_VERSION,
                }])
                _v306_13_7_8a_base_to_csv(out, out_path, index=False)
                return
            if ab.empty:
                out = _v306_13_7_8a_pd.DataFrame([{
                    "Status": "Skipped",
                    "Detail": "DAR profile A/B comparison file was empty on this cached non-force run.",
                    "PatchVersion": _V306_13_7_8A_VERSION,
                }])
                _v306_13_7_8a_base_to_csv(out, out_path, index=False)
                return
            rows = []
            for _, row in ab.iterrows():
                base_cols = _v306_13_7_8a_pd.to_numeric(_v306_13_7_8a_pd.Series([row.get("BaseColumns", 0)]), errors="coerce").fillna(0).iloc[0]
                profile_cols = _v306_13_7_8a_pd.to_numeric(_v306_13_7_8a_pd.Series([row.get("ProfileColumns", 0)]), errors="coerce").fillna(0).iloc[0]
                base_mb = _v306_13_7_8a_pd.to_numeric(_v306_13_7_8a_pd.Series([row.get("BaseMemoryMB", 0)]), errors="coerce").fillna(0).iloc[0]
                profile_mb = _v306_13_7_8a_pd.to_numeric(_v306_13_7_8a_pd.Series([row.get("ProfileMemoryMB", 0)]), errors="coerce").fillna(0).iloc[0]
                profile = str(row.get("Profile", ""))
                rows.append({
                    "SourceFolder": row.get("SourceFolder", ""),
                    "Profile": profile,
                    "Rows": row.get("ProfileRows", row.get("BaseRows", "")),
                    "BaseColumns": int(base_cols),
                    "ProfileColumns": int(profile_cols),
                    "ColumnReduction": int(base_cols - profile_cols),
                    "BaseMemoryMB": round(float(base_mb), 4),
                    "ProfileMemoryMB": round(float(profile_mb), 4),
                    "MemoryReductionMB": round(float(base_mb - profile_mb), 4),
                    "MemoryReductionPct": round(((float(base_mb) - float(profile_mb)) / float(base_mb) * 100.0), 2) if float(base_mb) else 0.0,
                    "MissingColumns": row.get("MissingColumns", ""),
                    "ProfileStatus": row.get("Status", ""),
                    "SuggestedUse": (
                        "Common validation / price validation path" if "18" in profile or "common_validation" in profile else
                        "Concentration / holdings candidate path" if "25" in profile or "concentration" in profile else
                        "Movement / tolerance extended path" if "29" in profile or "movement" in profile else
                        "Current full safe profile"
                    ),
                    "PatchVersion": _V306_13_7_8A_VERSION,
                })
            _v306_13_7_8a_base_to_csv(_v306_13_7_8a_pd.DataFrame(rows), out_path, index=False)
        except Exception as exc:
            out = _v306_13_7_8a_pd.DataFrame([{
                "Status": "Skipped",
                "Detail": f"DAR slim projection not rebuilt: {type(exc).__name__}: {exc}",
                "PatchVersion": _V306_13_7_8A_VERSION,
            }])
            try:
                _v306_13_7_8a_base_to_csv(out, out_path, index=False)
            except Exception:
                pass

    def _v306_13_7_7_build_trend_timing_rollups(timing_csv_path):
        try:
            path = _v306_13_7_8a_Path(timing_csv_path)
            if not path.exists():
                return
            df = _v306_13_7_8a_pd.read_csv(path)
            if df.empty or "ElapsedSeconds" not in df.columns:
                return
            df = df.copy()
            for required in ["RunDate", "Scope", "Phase", "Status", "Detail", "TimingSource", "SourceFolder", "PatchVersion"]:
                if required not in df.columns:
                    df[required] = ""
            df["ElapsedSecondsNum"] = _v306_13_7_8a_pd.to_numeric(df["ElapsedSeconds"], errors="coerce").fillna(0.0)
            df["RowsNum"] = _v306_13_7_8a_pd.to_numeric(df.get("Rows", 0), errors="coerce").fillna(0.0)
            df["RunDateRollup"] = df["RunDate"].fillna("").astype(str).replace({"nan": ""})
            df.loc[df["RunDateRollup"].str.strip() == "", "RunDateRollup"] = "ALL / build-level"
            df["PhaseGroup"] = df.apply(lambda r: _v306_13_7_8a_phase_group(r.get("Scope"), r.get("Phase"), r.get("Detail")), axis=1)
            df["ElapsedRole"] = df.apply(lambda r: _v306_13_7_8a_elapsed_role(r.get("Scope"), r.get("Phase"), r.get("Detail")), axis=1)
            df["IsAdditive"] = df["ElapsedRole"].eq("Child")
            df["AdditiveElapsedSeconds"] = df["ElapsedSecondsNum"].where(df["IsAdditive"], 0.0)

            per_run = (
                df.groupby(["RunDateRollup", "PhaseGroup"], dropna=False)
                .agg(
                    Events=("Phase", "size"),
                    AdditiveEvents=("IsAdditive", "sum"),
                    TotalElapsedSeconds=("ElapsedSecondsNum", "sum"),
                    AdditiveElapsedSeconds=("AdditiveElapsedSeconds", "sum"),
                    MaxElapsedSeconds=("ElapsedSecondsNum", "max"),
                    TotalRows=("RowsNum", "sum"),
                    Roles=("ElapsedRole", lambda s: " | ".join(sorted({str(x) for x in s}))),
                    ExamplePhase=("Phase", lambda s: " | ".join([str(x) for x in s.dropna().astype(str).head(5).tolist()])),
                    ExampleStatus=("Status", lambda s: " | ".join([str(x) for x in s.dropna().astype(str).head(5).tolist()])),
                )
                .reset_index()
            )
            for col in ["TotalElapsedSeconds", "AdditiveElapsedSeconds", "MaxElapsedSeconds"]:
                per_run[col] = per_run[col].round(4)
            per_run["PatchVersion"] = _V306_13_7_8A_VERSION
            per_run = per_run.sort_values(["RunDateRollup", "PhaseGroup"])
            _v306_13_7_8a_base_to_csv(per_run, path.parent / "trend_timing_rollup_last_run.csv", index=False)

            summary = (
                df.groupby(["PhaseGroup"], dropna=False)
                .agg(
                    Events=("Phase", "size"),
                    AdditiveEvents=("IsAdditive", "sum"),
                    TotalElapsedSeconds=("ElapsedSecondsNum", "sum"),
                    AdditiveElapsedSeconds=("AdditiveElapsedSeconds", "sum"),
                    MaxElapsedSeconds=("ElapsedSecondsNum", "max"),
                    TotalRows=("RowsNum", "sum"),
                    Roles=("ElapsedRole", lambda s: " | ".join(sorted({str(x) for x in s}))),
                    RunDates=("RunDateRollup", lambda s: " | ".join(sorted({str(x) for x in s if str(x).strip()}))),
                    ExamplePhase=("Phase", lambda s: " | ".join([str(x) for x in s.dropna().astype(str).head(8).tolist()])),
                )
                .reset_index()
            )
            for col in ["TotalElapsedSeconds", "AdditiveElapsedSeconds", "MaxElapsedSeconds"]:
                summary[col] = summary[col].round(4)
            additive_total = float(summary["AdditiveElapsedSeconds"].sum())
            summary["PctOfAdditiveElapsed"] = summary["AdditiveElapsedSeconds"].apply(lambda x: round((float(x) / additive_total * 100.0), 2) if additive_total else 0.0)
            summary["PatchVersion"] = _V306_13_7_8A_VERSION
            summary = summary.sort_values(["AdditiveElapsedSeconds", "TotalElapsedSeconds"], ascending=False)
            _v306_13_7_8a_base_to_csv(summary, path.parent / "trend_timing_rollup_summary_last_run.csv", index=False)

            detail = (
                df.groupby(["RunDateRollup", "PhaseGroup", "ElapsedRole", "Scope", "TimingSource"], dropna=False)
                .agg(
                    Events=("Phase", "size"),
                    AdditiveEvents=("IsAdditive", "sum"),
                    TotalElapsedSeconds=("ElapsedSecondsNum", "sum"),
                    AdditiveElapsedSeconds=("AdditiveElapsedSeconds", "sum"),
                    MaxElapsedSeconds=("ElapsedSecondsNum", "max"),
                    ExamplePhase=("Phase", lambda s: " | ".join([str(x) for x in s.dropna().astype(str).head(5).tolist()])),
                )
                .reset_index()
            )
            for col in ["TotalElapsedSeconds", "AdditiveElapsedSeconds", "MaxElapsedSeconds"]:
                detail[col] = detail[col].round(4)
            detail["PatchVersion"] = _V306_13_7_8A_VERSION
            detail = detail.sort_values(["RunDateRollup", "PhaseGroup", "ElapsedRole", "AdditiveElapsedSeconds"], ascending=[True, True, True, False])
            _v306_13_7_8a_base_to_csv(detail, path.parent / "trend_timing_rollup_detail_last_run.csv", index=False)

            _v306_13_7_7_build_slim_projection(path)
        except Exception as exc:
            try:
                err = _v306_13_7_8a_pd.DataFrame([{
                    "Status": "Error",
                    "Detail": f"{type(exc).__name__}: {exc}",
                    "PatchVersion": _V306_13_7_8A_VERSION,
                }])
                _v306_13_7_8a_base_to_csv(err, _v306_13_7_8a_Path(timing_csv_path).parent / "trend_timing_rollup_summary_last_run.csv", index=False)
            except Exception:
                pass
except Exception:
    pass


# ========================================================
# v306.13.12 PORTFOLIO NUMBERS SOURCE LOAD DIAGNOSTICS FIX
# ========================================================
# Late-binding wrapper applied after all function definitions. This fixes cases
# where the v306.13.11 diagnostic renderer was inserted but not reliably hooked
# into the Portfolio Numbers / overview render flow.

def _source_diag_df_v306_13_12(value) -> pd.DataFrame:
    try:
        return value.copy() if isinstance(value, pd.DataFrame) else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def _source_diag_status_v306_13_12(meta_df: pd.DataFrame, exception_df: pd.DataFrame, expected_loaded: int = 0) -> str:
    try:
        if isinstance(exception_df, pd.DataFrame) and not exception_df.empty:
            sev = exception_df.get("Severity", pd.Series(dtype="object")).astype(str).str.lower()
            if sev.str.contains("error", na=False).any():
                return "Error"
            if sev.str.contains("warning", na=False).any():
                return "Warning"
        if isinstance(meta_df, pd.DataFrame) and not meta_df.empty:
            if "Loaded" in meta_df.columns:
                loaded = meta_df["Loaded"].fillna(False).astype(bool)
                if expected_loaded and int(loaded.sum()) < int(expected_loaded):
                    return "Partial"
                if len(loaded) and bool(loaded.all()):
                    return "Loaded"
                return "Partial"
            return "Available"
        return "Not available"
    except Exception:
        return "Unknown"


def _source_diag_loaded_file_count_v306_13_12(df: pd.DataFrame) -> int:
    try:
        if isinstance(df, pd.DataFrame) and not df.empty and "Loaded" in df.columns:
            return int(df["Loaded"].fillna(False).astype(bool).sum())
    except Exception:
        pass
    return 0


def _source_diag_row_count_v306_13_12(df: pd.DataFrame) -> int:
    try:
        if isinstance(df, pd.DataFrame) and not df.empty and "Rows" in df.columns:
            return int(pd.to_numeric(df["Rows"], errors="coerce").fillna(0).sum())
    except Exception:
        pass
    return 0


def _source_diag_summary_v306_13_12(bundle: Dict[str, object]) -> pd.DataFrame:
    if not isinstance(bundle, dict):
        bundle = {}
    static_meta_df = _source_diag_df_v306_13_12(bundle.get("static_data_meta_df", globals().get("STATIC_DATA_META_DF", pd.DataFrame())))
    static_exception_df = _source_diag_df_v306_13_12(bundle.get("static_data_exception_df", globals().get("STATIC_DATA_EXCEPTION_DF", pd.DataFrame())))
    tableau_meta_df = _source_diag_df_v306_13_12(bundle.get("tableau_file_meta_df", pd.DataFrame()))
    tableau_exception_df = _source_diag_df_v306_13_12(bundle.get("tableau_exception_df", pd.DataFrame()))
    error_risk_meta_df = _source_diag_df_v306_13_12(bundle.get("error_risk_meta_df", pd.DataFrame()))
    error_risk_exception_df = _source_diag_df_v306_13_12(bundle.get("error_risk_exception_df", pd.DataFrame()))

    static_file = ""
    try:
        static_bundle = bundle.get("static_data", _ensure_static_data_bundle_v306_13_13())
        if isinstance(static_bundle, dict):
            static_file = str(static_bundle.get("static_file", ""))
    except Exception:
        static_file = ""

    return pd.DataFrame([
        {
            "Source area": "Static Data workbook",
            "Status": _source_diag_status_v306_13_12(static_meta_df, static_exception_df),
            "Loaded files / rows": int(len(static_meta_df)) if isinstance(static_meta_df, pd.DataFrame) else 0,
            "Source detail": static_file,
        },
        {
            "Source area": "BP Impact Tool Error Risk Report",
            "Status": _source_diag_status_v306_13_12(error_risk_meta_df, error_risk_exception_df, expected_loaded=1),
            "Loaded files / rows": _source_diag_row_count_v306_13_12(error_risk_meta_df),
            "Source detail": str(bundle.get("error_risk_source", "BP Impact Tool.xlsb / Error Risk Report")),
        },
        {
            "Source area": "Tableau / Unison BO CSVs",
            "Status": _source_diag_status_v306_13_12(tableau_meta_df, tableau_exception_df, expected_loaded=3),
            "Loaded files / rows": _source_diag_loaded_file_count_v306_13_12(tableau_meta_df),
            "Source detail": str(bundle.get("tableau_folder", "")),
        },
    ])


# v342 Phase 1: _render_source_load_checks_under_portfolio_numbers_v306_13_12 was
# removed (duplicate renderer). Its summary builder _source_diag_summary_v306_13_12
# is KEPT because the retained v14 summary reuses it.




# ========================================================
# v306.13.14 ERROR RISK DIAGNOSTIC NESTED ARC FIX
# ========================================================
# Aligns Portfolio Numbers source-load diagnostics with ARC mapping preview by
# reading Error Risk diagnostics from top-level keys or nested bundle['arc'].

def _erdiag_df_v306_13_14(value) -> pd.DataFrame:
    try:
        return value.copy() if isinstance(value, pd.DataFrame) else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def _erdiag_arc_bundle_v306_13_14(bundle: Dict[str, object]) -> Dict[str, object]:
    if not isinstance(bundle, dict):
        return {}
    arc = bundle.get("arc", {})
    return arc if isinstance(arc, dict) else {}


def _erdiag_get_df_v306_13_14(bundle: Dict[str, object], key: str) -> pd.DataFrame:
    if not isinstance(bundle, dict):
        return pd.DataFrame()
    top = _erdiag_df_v306_13_14(bundle.get(key, pd.DataFrame()))
    if not top.empty:
        return top
    arc = _erdiag_arc_bundle_v306_13_14(bundle)
    nested = _erdiag_df_v306_13_14(arc.get(key, pd.DataFrame()))
    return nested


def _erdiag_error_risk_status_v306_13_14(bundle: Dict[str, object]) -> str:
    arc = _erdiag_arc_bundle_v306_13_14(bundle)
    explicit = str(bundle.get("error_risk_source", "") if isinstance(bundle, dict) else "").strip()
    arc_status = str(arc.get("status", "")).strip()
    # If ARC mapping preview says OK with BP Impact Tool, source-load summary should not say Not available.
    if "error risk loaded from bp impact" in arc_status.lower():
        return "Loaded"
    meta = _erdiag_get_df_v306_13_14(bundle, "error_risk_meta_df")
    exc = _erdiag_get_df_v306_13_14(bundle, "error_risk_exception_df")
    try:
        if isinstance(exc, pd.DataFrame) and not exc.empty:
            sev = exc.get("Severity", pd.Series(dtype="object")).astype(str).str.lower()
            if sev.str.contains("error", na=False).any():
                return "Error"
            if sev.str.contains("warning", na=False).any():
                return "Warning"
        if isinstance(meta, pd.DataFrame) and not meta.empty:
            if "Loaded" in meta.columns:
                loaded = meta["Loaded"].fillna(False).astype(bool)
                return "Loaded" if bool(loaded.any()) else "Partial"
            return "Available"
    except Exception:
        return "Unknown"
    if explicit:
        return "Available"
    return "Not available"


def _erdiag_error_risk_rows_v306_13_14(bundle: Dict[str, object]) -> int:
    meta = _erdiag_get_df_v306_13_14(bundle, "error_risk_meta_df")
    try:
        if isinstance(meta, pd.DataFrame) and not meta.empty and "Rows" in meta.columns:
            return int(pd.to_numeric(meta["Rows"], errors="coerce").fillna(0).sum())
    except Exception:
        pass
    arc = _erdiag_arc_bundle_v306_13_14(bundle)
    err = _erdiag_df_v306_13_14(arc.get("error_df", pd.DataFrame()))
    return int(len(err)) if isinstance(err, pd.DataFrame) and not err.empty else 0


def _erdiag_error_risk_detail_v306_13_14(bundle: Dict[str, object]) -> str:
    arc = _erdiag_arc_bundle_v306_13_14(bundle)
    candidates = [
        bundle.get("error_risk_source", "") if isinstance(bundle, dict) else "",
        arc.get("error_risk_source", ""),
        arc.get("arc_file", ""),
        bundle.get("arc_file", "") if isinstance(bundle, dict) else "",
    ]
    for c in candidates:
        if str(c or "").strip():
            c = str(c).strip()
            if "BP Impact Tool" in c and "Error Risk Report" not in c:
                return c + " / Error Risk Report"
            return c
    return "BP Impact Tool.xlsb / Error Risk Report"


def _erdiag_source_summary_v306_13_14(bundle: Dict[str, object]) -> pd.DataFrame:
    # Reuse existing summary where available, but overwrite the Error Risk row using nested ARC-aware logic.
    try:
        base = _source_diag_summary_v306_13_12(bundle) if callable(globals().get("_source_diag_summary_v306_13_12")) else pd.DataFrame()
    except Exception:
        base = pd.DataFrame()
    if base is None or not isinstance(base, pd.DataFrame) or base.empty:
        base = pd.DataFrame(columns=["Source area", "Status", "Loaded files / rows", "Source detail"])
    base = base.copy()
    er_row = {
        "Source area": "BP Impact Tool Error Risk Report",
        "Status": _erdiag_error_risk_status_v306_13_14(bundle),
        "Loaded files / rows": _erdiag_error_risk_rows_v306_13_14(bundle),
        "Source detail": _erdiag_error_risk_detail_v306_13_14(bundle),
    }
    if "Source area" in base.columns and base["Source area"].astype(str).eq("BP Impact Tool Error Risk Report").any():
        mask = base["Source area"].astype(str).eq("BP Impact Tool Error Risk Report")
        for k, v in er_row.items():
            base.loc[mask, k] = v
    else:
        base = pd.concat([base, pd.DataFrame([er_row])], ignore_index=True, sort=False)
    return base


def _erdiag_cached_source_summary_v342(bundle: Dict[str, object]) -> pd.DataFrame:
    """v342 Phase 4: compute the source-load summary ONCE per selected date and cache
    it on the bundle, so re-opening the diagnostics panel (or any Portfolio Numbers
    re-render) reuses the frame instead of rebuilding it every time."""
    if not isinstance(bundle, dict):
        try:
            return _erdiag_source_summary_v306_13_14(bundle)
        except Exception:
            return pd.DataFrame()
    date_key = str(bundle.get("selected_date_label", ""))
    cache = bundle.get("_source_load_summary_cache_v342")
    if isinstance(cache, dict) and cache.get("key") == date_key and isinstance(cache.get("df"), pd.DataFrame):
        return cache["df"]
    try:
        df = _erdiag_source_summary_v306_13_14(bundle)
    except Exception:
        df = pd.DataFrame()
    bundle["_source_load_summary_cache_v342"] = {"key": date_key, "df": df}
    return df


def _render_source_load_checks_under_portfolio_numbers_v306_13_14(bundle: Dict[str, object]) -> None:
    # v342 Phases 1-4 + Option B: this is now the SINGLE consolidated diagnostics
    # panel. It (1) shows the source-load summary once, (2) renders every detail
    # table FLAT (headed sections, no nested expanders - display all at once), (3)
    # folds in the retained "Diagnostics / support" tables (File load metadata, Run
    # diagnostics, Processing exceptions, and the three cache-status frames) while
    # dropping Regular type debug, ARC mapping preview and ALL exchange-rate blocks,
    # and (4) surfaces the deep-timing run-log with a CSV export.
    if not bool(globals().get("SHOW_DEBUG", False)):
        return
    if not isinstance(bundle, dict):
        return

    def _emit_flat(label: str, raw_df: object, key_suffix: str) -> None:
        """Render one titled section (no inner expander) with a per-table CSV button."""
        df = _erdiag_df_v306_13_14(raw_df)
        if df is None or not isinstance(df, pd.DataFrame) or df.empty:
            return
        st.markdown(f"##### {label}")
        show_df(df, hide_index=True)
        try:
            st.download_button(
                f"Download {label} CSV",
                data=df.to_csv(index=False).encode("utf-8"),
                file_name=label.lower().replace(" ", "_").replace("/", "_") + ".csv",
                mime="text/csv",
                key="download_source_diag_v342_" + key_suffix,
            )
        except Exception:
            pass

    out = bundle.get("out", {}) if isinstance(bundle.get("out"), dict) else {}

    with st.expander("Diagnostic support - source load checks", expanded=False):
        st.caption("Confirms whether Static Data, BP Impact Tool Error Risk Report, and Tableau / Unison BO CSVs loaded for the selected date. Consolidated diagnostics - all sections shown at once.")
        # (1) source-load summary (Phase 4: cached per date)
        show_df(_erdiag_cached_source_summary_v342(bundle), hide_index=True)

        # (2) source-load detail tables - FLAT (Phase 2)
        st.markdown("### Source load detail")
        source_detail_tables = [
            ("Tableau file metadata", bundle.get("tableau_file_meta_df", pd.DataFrame()), "tableau_file_meta"),
            ("Tableau folder diagnostics", bundle.get("tableau_diagnostic_df", pd.DataFrame()), "tableau_folder_diag"),
            ("Tableau exceptions", bundle.get("tableau_exception_df", pd.DataFrame()), "tableau_exceptions"),
            ("BP Impact Tool Error Risk metadata", _erdiag_get_df_v306_13_14(bundle, "error_risk_meta_df"), "er_meta"),
            ("BP Impact Tool Error Risk diagnostics", _erdiag_get_df_v306_13_14(bundle, "error_risk_diagnostic_df"), "er_diag"),
            ("BP Impact Tool Error Risk exceptions", _erdiag_get_df_v306_13_14(bundle, "error_risk_exception_df"), "er_exceptions"),
            ("Static Data validation", bundle.get("static_data_validation_df", globals().get("STATIC_DATA_VALIDATION_DF", pd.DataFrame())), "static_validation"),
            ("Static Data path/global overrides", bundle.get("static_data_global_override_df", globals().get("STATIC_DATA_GLOBAL_OVERRIDE_DF", pd.DataFrame())), "static_overrides"),
            ("Static Data exceptions", bundle.get("static_data_exception_df", globals().get("STATIC_DATA_EXCEPTION_DF", pd.DataFrame())), "static_exceptions"),
        ]
        for label, raw_df, key_suffix in source_detail_tables:
            _emit_flat(label, raw_df, key_suffix)

        # (3) retained "Diagnostics / support" tables - folded in FLAT (Phase 3).
        # Removed by request: Regular type debug, ARC mapping preview, and all
        # exchange-rate resolver/extraction/probe/sheet-test/preview blocks.
        st.markdown("### Run diagnostics & cache status")
        support_tables = [
            ("File load metadata", out.get("file_meta_df", pd.DataFrame()), "file_load_meta"),
            ("Run diagnostics", out.get("diagnostic_df", pd.DataFrame()), "run_diagnostics"),
            ("Processing exceptions", out.get("exception_df", pd.DataFrame()), "processing_exceptions"),
            ("Date-folder cache status", bundle.get("file_manifest_status_df", pd.DataFrame()), "date_folder_cache"),
            ("BNP source cache status", bundle.get("bnp_source_cache_status_df", pd.DataFrame()), "bnp_source_cache"),
            ("process_day cache status", bundle.get("process_day_cache_status_df", pd.DataFrame()), "process_day_cache"),
        ]
        for label, raw_df, key_suffix in support_tables:
            _emit_flat(label, raw_df, key_suffix)

        # v345: shared FDV frame cache stats - shows how many network reads were saved
        # by the single-source-of-truth loader (each FDV file read once per process).
        try:
            from bnp_helpers_fdv_enrichment import fdv_cache_stats as _fdv_cache_stats_v345
            _st = _fdv_cache_stats_v345()
            if isinstance(_st, dict):
                st.caption(
                    f"Shared FDV frame (v345): {int(_st.get('files', 0))} file(s) cached; "
                    f"{int(_st.get('reads', 0))} network read(s), {int(_st.get('hits', 0))} cache hit(s). "
                    f"Each FDV file is read from G:/ once per process and reused by UUT, "
                    f"price-integrity and enrichment."
                )
        except Exception:
            pass
        # v351: FDV pickle-persist stats. pickle_hits climbing while network_reads stay
        # flat proves reopens are served from the local pickle (~0.05s) instead of
        # re-reading the ~59 MB over G:/ (~23s first read) - the same mechanism the BNP
        # source reports use.
        try:
            from bnp_helpers_fdv_enrichment import fdv_persist_stats as _fdv_persist_stats_v351
            _ps = _fdv_persist_stats_v351()
            if isinstance(_ps, dict):
                st.caption(
                    f"FDV pickle-persist (v351): {int(_ps.get('pickle_hits', 0))} pickle hit(s) "
                    f"(reopens served locally ~0.05s), {int(_ps.get('pickle_writes', 0))} pickle write(s), "
                    f"{int(_ps.get('network_reads', 0))} first network read(s) of a new file version. "
                    f"Stored in the same .bnp_manifest_cache folder as the BNP source pickle."
                )
        except Exception:
            pass
        # v346: FX / Error Risk cached Excel reader stats. If this caption is ABSENT,
        # bnp_helpers_columns.py (v346) is not deployed and the caching is inactive.
        try:
            from bnp_helpers_columns import excel_cache_stats as _excel_cache_stats_v346
            _xs = _excel_cache_stats_v346()
            if isinstance(_xs, dict):
                st.caption(
                    f"Cached Excel reader (v351, FX + Error Risk): {int(_xs.get('parses', 0))} network parse(s), "
                    f"{int(_xs.get('mem_hits', 0))} in-process hit(s), {int(_xs.get('pickle_hits', 0))} pickle hit(s), "
                    f"{int(_xs.get('pickle_writes', 0))} pickle write(s). Each (workbook version, sheet) is parsed "
                    f"from G:/ once and reused from cache / local pickle (calamine removed)."
                )
        except Exception:
            pass

        # (4) Option B deep-timing run-log + CSV export.
        st.markdown("### Detailed timing run-log (Option B)")
        # v343 (Part C): the run-log now ACCUMULATES across clicks in session_state.
        # Click through every sub-section once, then download ONE CSV covering the
        # whole pass. Use "Clear timing log" to start a fresh profiling run.
        run_log_df = _deep_timing_run_log_df(bundle)
        _clear_col, _info_col = st.columns([1, 3])
        with _clear_col:
            if st.button("Clear timing log", key="clear_deep_timing_run_log_v343"):
                _reset_deep_timing(bundle)
                try:
                    st.rerun()
                except Exception:
                    try:
                        st.experimental_rerun()
                    except Exception:
                        pass
        if isinstance(run_log_df, pd.DataFrame) and not run_log_df.empty:
            try:
                _total = float(pd.to_numeric(run_log_df["ElapsedSeconds"], errors="coerce").fillna(0).sum())
                _steps = int(len(run_log_df))
                _interactions = int(pd.to_numeric(run_log_df.get("Interaction", pd.Series(dtype="float")), errors="coerce").fillna(0).max() or 0)
                _slowest = run_log_df.sort_values("ElapsedSeconds", ascending=False).head(1)
                _slow_txt = ""
                if not _slowest.empty:
                    _slow_txt = f" Slowest step: {_slowest['Function'].iloc[0]} ({float(_slowest['ElapsedSeconds'].iloc[0]):,.2f}s)."
                with _info_col:
                    st.caption(f"Accumulated across {_interactions} interaction(s): {_steps} step(s) totalling {_total:,.2f}s.{_slow_txt} Times are per instrumented block, not the full wallclock. Use 'Clear timing log' to start fresh.")
            except Exception:
                pass
            show_df(run_log_df, hide_index=True)
            try:
                _fname = "timing_run_log_" + re.sub(r"[^0-9]+", "", str(bundle.get("selected_date_label", ""))) + ".csv"
                st.download_button(
                    "Download detailed timing run-log CSV",
                    data=run_log_df.to_csv(index=False).encode("utf-8"),
                    file_name=_fname if _fname != "timing_run_log_.csv" else "timing_run_log.csv",
                    mime="text/csv",
                    key="download_deep_timing_run_log_v342",
                )
            except Exception:
                pass
        else:
            with _info_col:
                st.caption("No timing steps captured yet. Click through the Portfolio Numbers sub-sections (and other tabs) to populate the accumulating run-log, then download the CSV.")




# v367: removed the 'v306.13.15 REMOVE ARC WORKBOOK MAPPING / UNISON
# USAGE' block - its _prepare_arc_error_risk redefinition ('No-ARC-
# workbook replacement') was confirmed dead, shadowed by the final
# v306.13.16 'Non-ARC replacement' definition immediately below (kept,
# unchanged). Its three private helpers
# (_empty_removed_arc_mapping_df_v306_13_15,
# _empty_removed_arc_portfolio_df_v306_13_15,
# _removed_arc_sheet_meta_v306_13_15) were used only by this dead
# definition and are removed with it; confirmed via full-file search no
# other caller exists. The associated attribute-tag assignment
# ('_arc_mapping_unison_removed_v306_13_15 = True') was also inert (never
# read via getattr anywhere) and removed with it. See CHANGELOG.md v367.




# ========================================================
# v306.13.16 NON-ARC BP IMPACT COVERAGE REPLACEMENT
# ========================================================
# Proper non-ARC replacement for the old ARC workbook coverage role.
# The app no longer reads ARC workbook Mapping or Unison vs BNP return check.
# Instead, BP Impact Tool.xlsb / Error Risk Report is used to supply the
# portfolio coverage/error-risk dataframe expected by legacy dashboard paths.

def _bpimpact_find_col_v306_13_16(df: pd.DataFrame, candidates: list) -> Optional[str]:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return None
    try:
        if callable(globals().get("find_col")):
            found = find_col(df, candidates)
            if found:
                return found
    except Exception:
        pass
    norm = {str(c).strip().lower().replace(" ", "").replace("_", ""): c for c in df.columns}
    for cand in candidates:
        key = str(cand).strip().lower().replace(" ", "").replace("_", "")
        if key in norm:
            return norm[key]
    return None


def _bpimpact_ratio_series_v306_13_16(df: pd.DataFrame, ratio_col: Optional[str]) -> pd.Series:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty or not ratio_col or ratio_col not in df.columns:
        return pd.Series(dtype="float64")
    raw = pd.to_numeric(df[ratio_col], errors="coerce")
    non_null = raw.dropna()
    divisor = 1.0
    try:
        if not non_null.empty:
            med = float(non_null.abs().median())
            # Workbook-style 300 = 3.00% -> 0.03. Existing helper also uses this rule.
            if med > 10:
                divisor = 10000.0
            # Some sources may hold 3 for 3%; convert to 0.03.
            elif med > 1:
                divisor = 100.0
    except Exception:
        divisor = 1.0
    return raw / divisor


def _build_bpimpact_arc_portfolio_df_v306_13_16(error_df: pd.DataFrame) -> pd.DataFrame:
    """Build a legacy-compatible portfolio coverage frame from BP Impact Tool."""
    if error_df is None or not isinstance(error_df, pd.DataFrame) or error_df.empty:
        return pd.DataFrame(columns=[
            "Portfolio", "Portfolio code", "ARC Error Risk Ratio",
            "Error Risk Source", "ARC Workbook Used",
        ])
    out = error_df.copy()
    # v352 FIX: the BP Impact Tool "Error Risk Report" sheet is keyed by "Advisor"
    # (with "Parent" as the group), not any of the previously-listed column names - so
    # the portfolio key never bound, every row was dropped as "no portfolio key", the
    # coverage frame came back empty, and the app logged "portfolio coverage columns
    # were not resolved". Adding "Advisor"/"Parent" (confirmed: Advisor maps to
    # portfolio) binds the key so coverage populates and the warning clears.
    port_col = _bpimpact_find_col_v306_13_16(out, [
        "Portfolio", "Portfolio code", "PortfolioCode", "Hiport Code", "HiPort Code",
        "Advisor Code", "Advisor", "Parent",
    ])
    if port_col and port_col in out.columns:
        if "Portfolio" not in out.columns:
            out["Portfolio"] = out[port_col].astype(str).str.strip()
        if "Portfolio code" not in out.columns:
            out["Portfolio code"] = out[port_col].astype(str).str.strip()
    else:
        out["Portfolio"] = ""
        out["Portfolio code"] = ""

    ratio_col = _bpimpact_find_col_v306_13_16(out, [
        "ARC Error Risk Ratio", "Error Risk Ratio", "ErrorRiskRatio", "Risk Ratio", "ERR",
    ])
    if "ARC Error Risk Ratio" not in out.columns:
        out["ARC Error Risk Ratio"] = _bpimpact_ratio_series_v306_13_16(out, ratio_col)
    else:
        # Normalise in place only if the existing values look workbook-style.
        out["ARC Error Risk Ratio"] = _bpimpact_ratio_series_v306_13_16(out, "ARC Error Risk Ratio")

    if "Error Risk Ratio" not in out.columns and ratio_col and ratio_col in out.columns:
        out["Error Risk Ratio"] = out[ratio_col]
    if "Error Risk Source" not in out.columns:
        out["Error Risk Source"] = "BP Impact Tool.xlsb / Error Risk Report"
    out["ARC Workbook Used"] = False
    out["ARC Sheet Replacement"] = "BP Impact Tool Error Risk Report"

    # Drop rows without a portfolio key so they do not create false coverage.
    try:
        out = out[out["Portfolio"].astype(str).str.strip().ne("")].copy()
    except Exception:
        pass
    return out.reset_index(drop=True)


def _prepare_arc_error_risk(run_date: object, timing_callback=None) -> Dict[str, object]:
    """Non-ARC replacement for the legacy ARC bundle.

    This does not read ARC workbook Mapping or Unison vs BNP return check.
    It uses BP Impact Tool Error Risk Report to create the portfolio coverage
    dataframe that the existing dashboard logic expects.
    """
    started = time.perf_counter()

    def _emit(label: str, start: float, status: str = "Done") -> None:
        if timing_callback is None:
            return
        try:
            timing_callback(label, time.perf_counter() - start, status)
        except Exception:
            pass

    result = {
        "arc_file": "",
        "arc_location": "Removed - ARC workbook not used",
        "mapping_df": pd.DataFrame([
            {"Source": "ARC Mapping", "Status": "Removed", "Detail": "ARC workbook Mapping sheet is not used from v306.13.16."}
        ]),
        "error_df": pd.DataFrame(),
        "arc_portfolio_df": pd.DataFrame(),
        "status": "ARC workbook removed - awaiting BP Impact Tool Error Risk Report",
        "diagnostics": {
            "arc_workbook_used": False,
            "mapping_sheet_used": False,
            "unison_vs_bnp_return_check_sheet_used": False,
            "coverage_source": "BP Impact Tool.xlsb / Error Risk Report",
            "patch_version": "v306.13.16",
        },
        "sheet_meta": [
            {"sheet_name": "Mapping", "ok": False, "rows": 0, "cols": 0, "engine_used": "not read", "error": "Removed - ARC workbook sheet not used."},
            {"sheet_name": "Unison vs BNP return check", "ok": False, "rows": 0, "cols": 0, "engine_used": "not read", "error": "Removed - ARC workbook sheet not used."},
        ],
        "arc_match_df": pd.DataFrame(columns=["Location", "File", "Path", "Modified", "Selected"]),
        "arc_removed_df": pd.DataFrame([
            {"Removed ARC sheet": "Mapping", "Replacement / status": "Not used by v306.13.16"},
            {"Removed ARC sheet": "Unison vs BNP return check", "Replacement / status": "Portfolio coverage sourced from BP Impact Tool Error Risk Report"},
            {"Removed ARC sheet": "Error Risk Ratio", "Replacement / status": "BP Impact Tool.xlsb / Error Risk Report"},
        ]),
    }

    load_started = time.perf_counter()
    try:
        if not callable(globals().get("_prepare_error_risk_source_v306_13_9")):
            result["status"] = "Error - BP Impact Tool Error Risk helper unavailable"
            result["error_risk_exception_df"] = pd.DataFrame([
                {"Severity": "Error", "Check": "ErrorRiskHelperImport", "Detail": "_prepare_error_risk_source_v306_13_9 is not available."}
            ])
            return result

        if callable(globals().get("_ensure_static_data_bundle_v306_13_13")):
            static_bundle = _ensure_static_data_bundle_v306_13_13()
        else:
            static_bundle = globals().get("STATIC_DATA_BUNDLE", {"tables": {}})

        er = _prepare_error_risk_source_v306_13_9(static_bundle, run_date=run_date, timing_callback=timing_callback)
        if not isinstance(er, dict):
            result["status"] = "Error - BP Impact Tool Error Risk helper returned no bundle"
            return result

        error_df = er.get("error_df", pd.DataFrame())
        result["error_df"] = error_df if isinstance(error_df, pd.DataFrame) else pd.DataFrame()
        result["arc_portfolio_df"] = _build_bpimpact_arc_portfolio_df_v306_13_16(result["error_df"])
        result["error_risk_meta_df"] = er.get("error_risk_meta_df", pd.DataFrame())
        result["error_risk_diagnostic_df"] = er.get("error_risk_diagnostic_df", pd.DataFrame())
        result["error_risk_exception_df"] = er.get("error_risk_exception_df", pd.DataFrame())
        result["error_risk_timing_df"] = er.get("error_risk_timing_df", pd.DataFrame())
        result["error_risk_source"] = "BP Impact Tool.xlsb / Error Risk Report"
        result["arc_file"] = er.get("source_file", "") or "BP Impact Tool.xlsb"
        result["arc_sheet"] = er.get("source_sheet", "Error Risk Report")
        result["coverage_source"] = "BP Impact Tool Error Risk Report"
        result["diagnostics"]["bp_impact_rows"] = int(len(result["error_df"]))
        result["diagnostics"]["synthetic_arc_portfolio_rows"] = int(len(result["arc_portfolio_df"]))

        if isinstance(result["arc_portfolio_df"], pd.DataFrame) and not result["arc_portfolio_df"].empty:
            result["status"] = "OK - ARC workbook removed; portfolio coverage loaded from BP Impact Tool"
        elif isinstance(result["error_df"], pd.DataFrame) and not result["error_df"].empty:
            result["status"] = "Warning - BP Impact Tool loaded but portfolio coverage columns were not resolved"
        else:
            result["status"] = "Warning - ARC workbook removed; BP Impact Tool Error Risk empty or unavailable"
    except Exception as exc:
        result["status"] = "Error - ARC workbook removed; BP Impact Tool coverage load failed"
        result["error_risk_exception_df"] = pd.DataFrame([
            {"Severity": "Error", "Check": "BPImpactCoverageLoad", "Detail": f"{type(exc).__name__}: {exc}"}
        ])
    finally:
        _emit("arc.non_arc_bp_impact_coverage", load_started, result.get("status", "Done"))
        _emit("arc.non_arc_total", started, "Done")

    return result


try:
    _prepare_arc_error_risk._non_arc_bp_impact_coverage_v306_13_16 = True
except Exception:
    pass


# ========================================================
# v306.13.17 NON-ARC BP IMPACT POST-BUNDLE CLASSIFICATION - REMOVED (v364)
# ========================================================
# Dead code removed. This classifier's body never ran: its name was
# reassigned to _apply_basis_impact_error_risk_classification_v306_14_5
# by the alias-recreation block below before any caller could invoke it
# (Python resolves function-body global names at call time). See
# CHANGELOG.md v307/v306.13.9 for why the ARC-workbook-based classifier
# was superseded, and v306.14.5 below for the classifier actually used.
# The '_apply_non_arc_bpimpact_classification_v306_13_17' name is still
# created (as an alias to v306_14_5) further down, since a few older
# wrapper closures still call it by that name.


# Wrap bundle preparation for new/rebuilt bundles.
try:
    if callable(globals().get("_prepare_out_dashboard_bundle")) and not getattr(globals().get("_prepare_out_dashboard_bundle"), "_na17_bpimpact_classification_wrapped", False):
        _prepare_out_dashboard_bundle_v306_13_17_original = _prepare_out_dashboard_bundle

        def _prepare_out_dashboard_bundle(*args, **kwargs):
            bundle = _prepare_out_dashboard_bundle_v306_13_17_original(*args, **kwargs)
            return _apply_non_arc_bpimpact_classification_v306_13_17(bundle)

        _prepare_out_dashboard_bundle._na17_bpimpact_classification_wrapped = True
except Exception:
    pass




# Also wrap the executive flow if it is called from a cached bundle path.
try:
    if callable(globals().get("_hot_resolution_sets")) and not getattr(globals().get("_hot_resolution_sets"), "_na17_bpimpact_classification_wrapped", False):
        _hot_resolution_sets_v306_13_17_original = _hot_resolution_sets

        def _hot_resolution_sets(bundle: Dict[str, object], auto_fx_summary_df: pd.DataFrame):
            bundle = _apply_non_arc_bpimpact_classification_v306_13_17(bundle)
            return _hot_resolution_sets_v306_13_17_original(bundle, auto_fx_summary_df)

        _hot_resolution_sets._na17_bpimpact_classification_wrapped = True
except Exception:
    pass


# ========================================================
# v306.13.18 NON-ARC BP IMPACT ADVISOR / EXTERNAL REF MATCH FIX - REMOVED (v364)
# ========================================================
# Dead code removed (superseded by v306.13.19's Advisor-matching logic,
# itself superseded by v306.14.5). See note on v306.13.17 above and
# CHANGELOG.md for history. Alias recreated further down for compatibility
# with older wrapper closures that still call this name.


# Wrap bundle preparation for new/rebuilt bundles.
try:
    if callable(globals().get("_prepare_out_dashboard_bundle")) and not getattr(globals().get("_prepare_out_dashboard_bundle"), "_na18_bpimpact_external_ref_wrapped", False):
        _prepare_out_dashboard_bundle_v306_13_18_original = _prepare_out_dashboard_bundle
        def _prepare_out_dashboard_bundle(*args, **kwargs):
            bundle = _prepare_out_dashboard_bundle_v306_13_18_original(*args, **kwargs)
            return _apply_non_arc_bpimpact_classification_v306_13_18(bundle)
        _prepare_out_dashboard_bundle._na18_bpimpact_external_ref_wrapped = True
except Exception:
    pass




# Also wrap hot-resolution path for cached bundles used outside Portfolio Numbers.
try:
    if callable(globals().get("_hot_resolution_sets")) and not getattr(globals().get("_hot_resolution_sets"), "_na18_bpimpact_external_ref_wrapped", False):
        _hot_resolution_sets_v306_13_18_original = _hot_resolution_sets
        def _hot_resolution_sets(bundle: Dict[str, object], auto_fx_summary_df: pd.DataFrame):
            bundle = _apply_non_arc_bpimpact_classification_v306_13_18(bundle)
            return _hot_resolution_sets_v306_13_18_original(bundle, auto_fx_summary_df)
        _hot_resolution_sets._na18_bpimpact_external_ref_wrapped = True
except Exception:
    pass


# ========================================================
# v306.13.19 BP IMPACT ADVISOR FROM PORTFOLIO NAME FALLBACK - REMOVED (v364)
# ========================================================
# Dead code removed (superseded by v306.14.5). See note on v306.13.17
# above and CHANGELOG.md for history. Alias recreated further down for
# compatibility with older wrapper closures that still call this name.


# Wrap bundle preparation.
try:
    if callable(globals().get("_prepare_out_dashboard_bundle")) and not getattr(globals().get("_prepare_out_dashboard_bundle"), "_na19_bpimpact_name_token_wrapped", False):
        _prepare_out_dashboard_bundle_v306_13_19_original = _prepare_out_dashboard_bundle
        def _prepare_out_dashboard_bundle(*args, **kwargs):
            bundle = _prepare_out_dashboard_bundle_v306_13_19_original(*args, **kwargs)
            return _apply_non_arc_bpimpact_classification_v306_13_19(bundle)
        _prepare_out_dashboard_bundle._na19_bpimpact_name_token_wrapped = True
except Exception:
    pass




# Wrap hot-resolution sets used by executive flow/auto explained.
try:
    if callable(globals().get("_hot_resolution_sets")) and not getattr(globals().get("_hot_resolution_sets"), "_na19_bpimpact_name_token_wrapped", False):
        _hot_resolution_sets_v306_13_19_original = _hot_resolution_sets
        def _hot_resolution_sets(bundle: Dict[str, object], auto_fx_summary_df: pd.DataFrame):
            bundle = _apply_non_arc_bpimpact_classification_v306_13_19(bundle)
            return _hot_resolution_sets_v306_13_19_original(bundle, auto_fx_summary_df)
        _hot_resolution_sets._na19_bpimpact_name_token_wrapped = True
except Exception:
    pass


# ========================================================
# v306.13.20 BP IMPACT MATCH DIAGNOSTICS
# ========================================================
# Diagnostic-only patch. Adds CSV artefacts and, if Streamlit is available in the
# render path, an expander showing source columns, sample keys and match counts.

_BPIMPACT_DIAG_CSV = "bpimpact_match_diagnostics_last_run.csv"
_BPIMPACT_DIAG_SAMPLE_CSV = "bpimpact_match_diagnostics_sample_last_run.csv"
_BPIMPACT_DIAG_SOURCE_SAMPLE_CSV = "bpimpact_error_risk_source_sample_last_run.csv"


def _bpdiag_find_col(df: pd.DataFrame, candidates: list) -> Optional[str]:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return None
    try:
        if callable(globals().get("find_col")):
            found = find_col(df, candidates)
            if found:
                return found
    except Exception:
        pass
    norm = {str(c).strip().lower().replace(" ", "").replace("_", ""): c for c in df.columns}
    for cand in candidates:
        key = str(cand).strip().lower().replace(" ", "").replace("_", "")
        if key in norm:
            return norm[key]
    for cand in candidates:
        parts = [p for p in re.split(r"[\s_]+", str(cand).strip().lower()) if p]
        for c in df.columns:
            low = str(c).strip().lower()
            if parts and all(p in low for p in parts):
                return c
    return None


def _bpdiag_key_series(s: pd.Series) -> pd.Series:
    try:
        return normalise_join_key_series(s.astype(str).str.strip())
    except Exception:
        return s.astype(str).str.strip().str.upper().str.replace(r"[^A-Z0-9]", "", regex=True)


def _bpdiag_extract_first_token(value: object) -> str:
    text = str(value or "").strip().upper()
    if not text or text.lower() in {"nan", "none", "nat"}:
        return ""
    token = re.split(r"\s+", text, maxsplit=1)[0].strip()
    return re.sub(r"[^A-Z0-9]", "", token)


def _bpdiag_source_candidates(bundle: Dict[str, object]) -> list:
    rows = []
    if not isinstance(bundle, dict):
        return rows
    direct_names = ["error_df", "error_risk_df", "arc_portfolio_df", "bp_impact_portfolio_df"]
    for name in direct_names:
        obj = bundle.get(name, None)
        if isinstance(obj, pd.DataFrame):
            rows.append(("bundle." + name, obj))
    arc = bundle.get("arc", {})
    if isinstance(arc, dict):
        for name in direct_names + ["mapping_df"]:
            obj = arc.get(name, None)
            if isinstance(obj, pd.DataFrame):
                rows.append(("bundle.arc." + name, obj))
    return rows


def _bpdiag_pick_bpimpact_source(bundle: Dict[str, object]) -> Tuple[str, pd.DataFrame]:
    candidates = _bpdiag_source_candidates(bundle)
    best_name = ""
    best_df = pd.DataFrame()
    best_score = -1
    for name, df in candidates:
        if not isinstance(df, pd.DataFrame) or df.empty:
            score = 0
        else:
            cols = [str(c).lower() for c in df.columns]
            score = 0
            if any("advisor" in c for c in cols): score += 10
            if any("error" in c and "risk" in c for c in cols): score += 10
            if any("ratio" in c for c in cols): score += 3
            score += min(len(df), 1000) / 100000.0
        if score > best_score:
            best_score = score
            best_name = name
            best_df = df
    return best_name, best_df.copy() if isinstance(best_df, pd.DataFrame) else pd.DataFrame()


def _bpdiag_out_mask(df: pd.DataFrame) -> pd.Series:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return pd.Series(dtype="bool")
    if "Within Tolerance" in df.columns:
        try:
            return ~df["Within Tolerance"].fillna(False).astype(bool)
        except Exception:
            pass
    for col in ["Status", "Tolerance Status", "OUT - Control Break Flag", "Transaction-aware Outside Tolerance"]:
        if col in df.columns:
            s = df[col]
            if str(s.dtype).lower() == "bool":
                return s.fillna(False).astype(bool)
            text = s.astype(str).str.strip().str.upper()
            if col in ["Status", "Tolerance Status"]:
                return text.str.contains("OUT|OUTSIDE|FAIL|BREACH", regex=True, na=False)
            return text.isin(["TRUE", "YES", "1", "OUT", "OUTSIDE"])
    return pd.Series([False] * len(df), index=df.index)


def _bpdiag_build(bundle: Dict[str, object]) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    rows = []
    sample = pd.DataFrame()
    src_sample = pd.DataFrame()
    if not isinstance(bundle, dict):
        return pd.DataFrame([{"Check": "bundle", "Result": "Not dict", "Detail": str(type(bundle))}]), sample, src_sample

    portfolio_df = bundle.get("portfolio_df", pd.DataFrame())
    rows.append({"Check": "bundle keys", "Result": "OK", "Detail": ", ".join(sorted([str(k) for k in bundle.keys()]))})
    if not isinstance(portfolio_df, pd.DataFrame) or portfolio_df.empty:
        rows.append({"Check": "portfolio_df", "Result": "Empty/Missing", "Detail": str(type(portfolio_df))})
        return pd.DataFrame(rows), sample, src_sample

    rows.append({"Check": "portfolio_df shape", "Result": "OK", "Detail": f"rows={len(portfolio_df):,}; cols={len(portfolio_df.columns):,}"})
    rows.append({"Check": "portfolio_df columns", "Result": "OK", "Detail": " | ".join(map(str, portfolio_df.columns.tolist()))})

    port_col = _bpdiag_find_col(portfolio_df, ["Portfolio code", "Portfolio", "PortfolioCode", "portfolio", "portfolio code"])
    name_col = _bpdiag_find_col(portfolio_df, ["Portfolio Name", "PortfolioName", "Name"])
    ext_col = _bpdiag_find_col(portfolio_df, ["External portfolio reference", "ExternalPortfolioReference", "External reference", "Advisor", "Advisor code"])
    hot_col = _bpdiag_find_col(portfolio_df, ["Hot / Cold", "Hot Cold", "HotCold"])
    rows.append({"Check": "portfolio key columns", "Result": "OK", "Detail": f"portfolio_col={port_col or ''}; name_col={name_col or ''}; external_ref_col={ext_col or ''}; hot_col={hot_col or ''}"})

    out_mask = _bpdiag_out_mask(portfolio_df)
    rows.append({"Check": "OUT mask", "Result": "OK", "Detail": f"OUT rows={int(out_mask.sum()):,}; total rows={len(portfolio_df):,}"})
    if hot_col:
        counts = portfolio_df.loc[out_mask, hot_col].astype(str).fillna("").value_counts(dropna=False).to_dict()
        rows.append({"Check": "current OUT Hot/Cold counts", "Result": "OK", "Detail": str(counts)})

    source_name, src = _bpdiag_pick_bpimpact_source(bundle)
    for cand_name, cand_df in _bpdiag_source_candidates(bundle):
        rows.append({"Check": "source candidate", "Result": "Present" if isinstance(cand_df, pd.DataFrame) and not cand_df.empty else "Empty", "Detail": f"{cand_name}; rows={0 if not isinstance(cand_df, pd.DataFrame) else len(cand_df):,}; cols={0 if not isinstance(cand_df, pd.DataFrame) else len(cand_df.columns):,}; columns={' | '.join(map(str, cand_df.columns.tolist())) if isinstance(cand_df, pd.DataFrame) else ''}"})

    if not isinstance(src, pd.DataFrame) or src.empty:
        rows.append({"Check": "selected BP Impact source", "Result": "Empty", "Detail": f"selected={source_name}"})
        return pd.DataFrame(rows), sample, src_sample

    advisor_col = _bpdiag_find_col(src, ["Advisor", "Advisor code", "Advisor Code", "External portfolio reference", "ExternalPortfolioReference"])
    ratio_col = _bpdiag_find_col(src, ["ARC Error Risk Ratio", "Error Risk Ratio", "ErrorRiskRatio", "Risk Ratio", "ERR", "Error Risk"])
    rows.append({"Check": "selected BP Impact source", "Result": "OK", "Detail": f"selected={source_name}; rows={len(src):,}; cols={len(src.columns):,}; advisor_col={advisor_col or ''}; ratio_col={ratio_col or ''}"})

    if advisor_col and advisor_col in src.columns:
        src_keys = set(_bpdiag_key_series(src[advisor_col]).astype(str).tolist())
    else:
        src_keys = set()
    rows.append({"Check": "BP Impact key count", "Result": "OK" if src_keys else "Empty", "Detail": f"unique keys={len(src_keys):,}"})

    tmp = portfolio_df.copy()
    tmp["_bpdiag_portfolio_key"] = _bpdiag_key_series(tmp[port_col]) if port_col else ""
    tmp["_bpdiag_name_token"] = tmp[name_col].map(_bpdiag_extract_first_token) if name_col else ""
    tmp["_bpdiag_name_token_key"] = _bpdiag_key_series(tmp["_bpdiag_name_token"])
    tmp["_bpdiag_external_ref"] = tmp[ext_col].astype(str).str.strip() if ext_col and ext_col in tmp.columns else ""
    tmp["_bpdiag_external_ref_key"] = _bpdiag_key_series(tmp["_bpdiag_external_ref"])
    tmp["_bpdiag_match_external_ref"] = tmp["_bpdiag_external_ref_key"].map(lambda k: str(k) in src_keys)
    tmp["_bpdiag_match_name_token"] = tmp["_bpdiag_name_token_key"].map(lambda k: str(k) in src_keys)
    tmp["_bpdiag_match_portfolio_code"] = tmp["_bpdiag_portfolio_key"].map(lambda k: str(k) in src_keys)
    tmp["_bpdiag_any_match"] = tmp["_bpdiag_match_external_ref"] | tmp["_bpdiag_match_name_token"] | tmp["_bpdiag_match_portfolio_code"]

    rows.append({"Check": "match counts on OUT rows", "Result": "OK", "Detail": f"external_ref={int((out_mask & tmp['_bpdiag_match_external_ref']).sum()):,}; name_token={int((out_mask & ~tmp['_bpdiag_match_external_ref'] & tmp['_bpdiag_match_name_token']).sum()):,}; portfolio_code={int((out_mask & ~tmp['_bpdiag_match_external_ref'] & ~tmp['_bpdiag_match_name_token'] & tmp['_bpdiag_match_portfolio_code']).sum()):,}; any={int((out_mask & tmp['_bpdiag_any_match']).sum()):,}; no_match={int((out_mask & ~tmp['_bpdiag_any_match']).sum()):,}"})

    preferred_cols = []
    for c in [port_col, name_col, ext_col, hot_col, "ARC Error Risk Ratio", "BP Impact Error Risk Ratio", "BP Impact matched?", "BP Impact match basis", "BP Impact match key"]:
        if c and c in tmp.columns and c not in preferred_cols:
            preferred_cols.append(c)
    debug_cols = ["_bpdiag_external_ref", "_bpdiag_name_token", "_bpdiag_external_ref_key", "_bpdiag_name_token_key", "_bpdiag_portfolio_key", "_bpdiag_match_external_ref", "_bpdiag_match_name_token", "_bpdiag_match_portfolio_code", "_bpdiag_any_match"]
    sample = tmp.loc[out_mask, preferred_cols + debug_cols].head(100).copy()
    src_sample_cols = [c for c in [advisor_col, ratio_col] if c and c in src.columns]
    if not src_sample_cols:
        src_sample_cols = src.columns.tolist()[:10]
    src_sample = src[src_sample_cols].head(100).copy()
    return pd.DataFrame(rows), sample, src_sample


def _bpdiag_write_files(bundle: Dict[str, object], label: str = "") -> None:
    try:
        diag, sample, src_sample = _bpdiag_build(bundle)
        if not diag.empty:
            diag.insert(0, "Stage", label)
            pass  # [removed] diagnostic CSV write
        if isinstance(sample, pd.DataFrame) and not sample.empty:
            pass  # [removed] diagnostic CSV write
        if isinstance(src_sample, pd.DataFrame) and not src_sample.empty:
            pass  # [removed] diagnostic CSV write
    except Exception as e:
        try:
            pass  # [removed] diagnostic CSV write
        except Exception:
            pass


def _bpdiag_render_expander(bundle: Dict[str, object], label: str = "Portfolio Numbers") -> None:
    # [removed] "Diagnostic support - BP Impact Advisor matching" timing/diagnostic panel.
    # ARC audit panels (Universe, GAV, UUT, Ancillary, Price integrity) retained below.
    # v368: Parity Matrix removed at user request (bnp_helpers_parity.py deleted).
    if "st" not in globals() or st is None:
        return

    # v323: the ARC check panels are now rendered as sub-sections of Portfolio
    # Numbers (see _render_overview_tab), not as expanders here.

# Wrap bundle preparation so diagnostics are written even if UI hook is not the right one.
try:
    if callable(globals().get("_prepare_out_dashboard_bundle")) and not getattr(globals().get("_prepare_out_dashboard_bundle"), "_bpdiag_v306_13_20_wrapped", False):
        _prepare_out_dashboard_bundle_bpdiag_original = _prepare_out_dashboard_bundle
        def _prepare_out_dashboard_bundle(*args, **kwargs):
            bundle = _prepare_out_dashboard_bundle_bpdiag_original(*args, **kwargs)
            _bpdiag_write_files(bundle, label="_prepare_out_dashboard_bundle")
            return bundle
        _prepare_out_dashboard_bundle._bpdiag_v306_13_20_wrapped = True
except Exception:
    pass


# Wrap likely Portfolio Numbers/overview render functions. These are diagnostic-only.
for _bpdiag_func_name in [
    "_render_overview_tab",
    "_render_portfolio_numbers",
    "_render_portfolio_numbers_section",
    "_render_portfolio_count_tab",
    "_render_portfolio_count_section",
]:
    try:
        _func = globals().get(_bpdiag_func_name)
        if callable(_func) and not getattr(_func, "_bpdiag_v306_13_20_wrapped", False):
            def _make_bpdiag_wrapper(fn, fn_name):
                def _wrapped(*args, **kwargs):
                    bundle = None
                    if args and isinstance(args[0], dict):
                        bundle = args[0]
                    elif "bundle" in kwargs and isinstance(kwargs.get("bundle"), dict):
                        bundle = kwargs.get("bundle")
                    if isinstance(bundle, dict):
                        _bpdiag_render_expander(bundle, label=fn_name + " before render")
                    result = fn(*args, **kwargs)
                    if isinstance(bundle, dict):
                        _bpdiag_write_files(bundle, label=fn_name + " after render")
                    return result
                _wrapped._bpdiag_v306_13_20_wrapped = True
                return _wrapped
            globals()[_bpdiag_func_name] = _make_bpdiag_wrapper(_func, _bpdiag_func_name)
    except Exception:
        pass


# ========================================================
# v306.13.21 FORCE BP IMPACT HOT/COLD FROM DIAGNOSED MATCH FIELDS - REMOVED (v364)
# ========================================================
# Dead code removed (superseded by v306.14.5). See note on v306.13.17
# above and CHANGELOG.md for history. Alias recreated further down for
# compatibility with older wrapper closures that still call this name.


# Re-wrap all likely paths. This intentionally runs after older v306.13.18/19 wrappers.
try:
    if callable(globals().get("_prepare_out_dashboard_bundle")) and not getattr(globals().get("_prepare_out_dashboard_bundle"), "_na21_force_bpimpact_hotcold_wrapped", False):
        _prepare_out_dashboard_bundle_v306_13_21_original = _prepare_out_dashboard_bundle
        def _prepare_out_dashboard_bundle(*args, **kwargs):
            bundle = _prepare_out_dashboard_bundle_v306_13_21_original(*args, **kwargs)
            return _apply_bpimpact_hotcold_force_v306_13_21(bundle)
        _prepare_out_dashboard_bundle._na21_force_bpimpact_hotcold_wrapped = True
except Exception:
    pass


for _na21_func_name in [
    "_render_overview_tab",
    "_render_portfolio_numbers",
    "_render_portfolio_numbers_section",
    "_render_portfolio_count_tab",
    "_render_portfolio_count_section",
    "_hot_resolution_sets",
]:
    try:
        _func = globals().get(_na21_func_name)
        if callable(_func) and not getattr(_func, "_na21_force_bpimpact_hotcold_wrapped", False):
            def _make_na21_wrapper(fn, fn_name):
                def _wrapped(*args, **kwargs):
                    new_args = list(args)
                    if new_args and isinstance(new_args[0], dict):
                        new_args[0] = _apply_bpimpact_hotcold_force_v306_13_21(new_args[0])
                    elif "bundle" in kwargs and isinstance(kwargs.get("bundle"), dict):
                        kwargs["bundle"] = _apply_bpimpact_hotcold_force_v306_13_21(kwargs["bundle"])
                    return fn(*new_args, **kwargs)
                _wrapped._na21_force_bpimpact_hotcold_wrapped = True
                return _wrapped
            globals()[_na21_func_name] = _make_na21_wrapper(_func, _na21_func_name)
    except Exception:
        pass


# ========================================================

# ========================================================
# v310.1 HOT/COLD REALIGNMENT TO THE UNISON DEVIATION
# ========================================================
# After the dashboard bundle is prepared (tableau prices attached, BNP-basis
# Hot/Cold classified), attach the Unison-basis "Volatility over Tolerance" and
# re-run the authoritative classifier so severity (Hot vs Cold) uses the SAME
# Unison-vs-benchmark deviation as OUT. The invariant (No source + Cold + Hot =
# OUT) and the OUT population are unchanged - only the Hot/Cold split may shift.
# Fully guarded; a failure leaves Hot/Cold on the prior BNP-internal basis.
def _v310_1_realign_hotcold_unison(bundle):
    try:
        if not isinstance(bundle, dict):
            return bundle
        if not callable(globals().get("_attach_unison_vot_v310_1")):
            return bundle
        bundle = _attach_unison_vot_v310_1(bundle)
        if callable(globals().get("_apply_basis_impact_error_risk_classification_v306_14_5")):
            bundle = _apply_basis_impact_error_risk_classification_v306_14_5(bundle)
        if callable(globals().get("_record_hotcold_reclass_v310_1")):
            bundle = _record_hotcold_reclass_v310_1(bundle)
    except Exception:
        pass
    return bundle

try:
    if callable(globals().get("_prepare_out_dashboard_bundle")) and not getattr(globals().get("_prepare_out_dashboard_bundle"), "_v310_1_realign_wrapped", False):
        _prepare_out_dashboard_bundle_v310_0_original = _prepare_out_dashboard_bundle
        def _prepare_out_dashboard_bundle(*args, **kwargs):
            bundle = _prepare_out_dashboard_bundle_v310_0_original(*args, **kwargs)
            return _v310_1_realign_hotcold_unison(bundle)
        _prepare_out_dashboard_bundle._v310_1_realign_wrapped = True
except Exception:
    pass



# ========================================================
# v311 DETAILED VALUATION FDV (T / T-1) PATH RESOLUTION
# ========================================================
# The UUT look-through needs both the current-day (T) and previous-day (T-1)
# DetailedValuationFDV files. Resolve their paths from the BNP file metadata and
# stash on the bundle so bnp_helpers_uut can read them. Fully guarded.
def _v311_resolve_fdv_paths(bundle):
    # v311b FIX: the UUT look-through needs BOTH the current-day (T) and the
    # previous-day (T-1) DetailedValuationFDV files. The T-1 file lives in a
    # DIFFERENT date folder (...\YYYY\MM Mmm\DD Mmm\), which the earlier resolver
    # never scanned - so only T was ever supplied and t1_date came back blank.
    # This resolver now: (a) collects today's FDV files, (b) parses the current
    # folder date, (c) scans sibling day-folders (this month + the year folder for
    # month/year boundaries) for the most recent PRIOR date that has FDV files,
    # and (d) stashes the full multi-day list in bundle['fdv_files'] so
    # bnp_helpers_uut groups by the filename date token. Fully guarded.
    try:
        if not isinstance(bundle, dict):
            return bundle
        import glob, os as _os

        def _fdv_in(folder_path):
            if folder_path and _os.path.isdir(folder_path):
                return glob.glob(_os.path.join(folder_path, "*DetailedValuationFDV*.csv"))
            return []

        files = []
        # (a) today's files: from file_meta_df and the current day folder.
        meta = bundle.get("file_meta_df")
        if isinstance(meta, pd.DataFrame) and not meta.empty:
            for col in meta.columns:
                for v in meta[col].astype(str).tolist():
                    if "DetailedValuationFDV" in v and v.lower().endswith(".csv") and _os.path.exists(v):
                        files.append(v)
        folder = str(bundle.get("folder") or "")
        files += _fdv_in(folder)

        # (b)+(c) previous-day folder: find the most recent PRIOR date folder that
        # has FDV files. v351.1 SCAN FOLD-IN: the "Scan BNP date folders" stage already
        # walked the whole YYYY/MM Mmm/DD Mmm tree and cached every date folder in
        # st.session_state["_bnp_date_folder_cache_df"]. Reuse that cached list to pick
        # the prior date(s) instead of re-walking the year folder over G:/ with
        # os.scandir. Falls back to the original scandir walk only if the cached list is
        # unavailable, so behaviour is unchanged. (Still deep-timed so the run-log shows
        # the cheaper reused path.)
        prev_files = []
        try:
            with _deep_timer({}, "Post-prepare (gap)", "FDV T-1 folder resolve (reuse cached date-folder scan)"):
                cur_date = parse_date_from_path(folder) if folder else None
                if cur_date is not None:
                    day_folders = []
                    # (b1) reuse the already-scanned date-folder list from the manifest
                    _reused = False
                    try:
                        _fdf = st.session_state.get("_bnp_date_folder_cache_df") if hasattr(st, "session_state") else None
                        if isinstance(_fdf, pd.DataFrame) and not _fdf.empty and {"RunDate", "Folder"}.issubset(_fdf.columns):
                            for _rd, _fld in zip(_fdf["RunDate"].tolist(), _fdf["Folder"].astype(str).tolist()):
                                try:
                                    _dt = pd.to_datetime(_rd).date()
                                except Exception:
                                    _dt = parse_date_from_path(_fld)
                                if _dt is not None and _dt < cur_date and _fld:
                                    day_folders.append((_dt, _fld))
                            _reused = True
                    except Exception:
                        _reused = False
                    # (b2) fallback: original sibling scandir walk only if no cached list
                    if not _reused or not day_folders:
                        year_folder = _os.path.dirname(_os.path.dirname(folder))  # ...\YYYY\
                        if year_folder and _os.path.isdir(year_folder):
                            for mdir in [p.path for p in _os.scandir(year_folder) if p.is_dir()]:
                                for ddir in [p.path for p in _os.scandir(mdir) if p.is_dir()]:
                                    dt = parse_date_from_path(ddir)
                                    if dt is not None and dt < cur_date:
                                        day_folders.append((dt, ddir))
                    # nearest prior date first; take the first that actually has FDV files
                    for dt, ddir in sorted(day_folders, key=lambda x: x[0], reverse=True):
                        got = _fdv_in(ddir)
                        if got:
                            prev_files = got
                            bundle["fdv_t1_folder"] = ddir
                            bundle["fdv_t1_date"] = str(dt)
                            break
        except Exception:
            prev_files = []
        files += prev_files

        # de-dup, preserve order
        seen = set(); uniq = []
        for c in files:
            rc = c
            if rc and rc not in seen and _os.path.exists(rc):
                seen.add(rc); uniq.append(rc)

        if uniq:
            # Full multi-day list -> bnp_helpers_uut groups by date token.
            bundle["fdv_files"] = uniq
            # v343 (Part B): build the FDV enrichment lookup NOW (load-time), through
            # the same bundle-prep pass as the other BNP reports, so it's vectorised
            # and cached once instead of lazily on the first render click.
            # v349 (instrument-only): deep-time this first full read of all FDV files
            # (also inside the ~31s post-prepare gap) so the run-log separates it from
            # the scandir walk above. No behaviour change.
            try:
                with _deep_timer({}, "Post-prepare (gap)", "FDV enrichment lookup build (first FDV read)"):
                    if callable(globals().get("_v320_build_fdv_lookup_at_load")):
                        _v320_build_fdv_lookup_at_load(bundle)
            except Exception:
                pass
        # v313: also collect the DStalePrice report files from the current folder.
        try:
            sp = []
            if folder and _os.path.isdir(folder):
                sp += glob.glob(_os.path.join(folder, "*DStalePrice*.csv"))
            if isinstance(meta, pd.DataFrame) and not meta.empty:
                for _c in meta.columns:
                    for _v in meta[_c].astype(str).tolist():
                        if "DStalePrice" in _v and _v.lower().endswith(".csv") and _os.path.exists(_v):
                            sp.append(_v)
            sp = [p for p in dict.fromkeys(sp) if _os.path.exists(p)]
            if sp:
                bundle["stale_price_files"] = sp
        except Exception:
            pass
    except Exception:
        pass
    return bundle

try:
    if callable(globals().get("_prepare_out_dashboard_bundle")) and not getattr(globals().get("_prepare_out_dashboard_bundle"), "_v311_fdv_wrapped", False):
        _prepare_out_dashboard_bundle_v310_1_original = _prepare_out_dashboard_bundle
        def _prepare_out_dashboard_bundle(*args, **kwargs):
            bundle = _prepare_out_dashboard_bundle_v310_1_original(*args, **kwargs)
            # v349 (instrument-only): time the ENTIRE post-prepare FDV-path resolver
            # (scandir walk + FDV lookup build + DStalePrice glob) as one row, so the
            # run-log shows its total contribution to the ~31s cold-load gap alongside
            # the two sub-part rows. No behaviour change.
            try:
                with _deep_timer({}, "Post-prepare (gap)", "_v311_resolve_fdv_paths TOTAL"):
                    return _v311_resolve_fdv_paths(bundle)
            except Exception:
                return _v311_resolve_fdv_paths(bundle)
        _prepare_out_dashboard_bundle._v311_fdv_wrapped = True
except Exception:
    pass



# ========================================================
# v322 BENCHMARK NAMES (BM Mapping -> Static Data)
# ========================================================
# Attach 'Benchmark Name' to portfolio_df from Static Data 'bm_mapping' and stash
# the 'Check BM Mapping' data-quality frame. Display/reference-data only; never
# alters a calculation. Fully guarded.
try:
    from bnp_helpers_static_data import attach_benchmark_name as _bm_attach_v322, build_bm_quality_flags as _bm_flags_v322
except Exception:
    _bm_attach_v322 = None
    _bm_flags_v322 = None

def _v322_enrich_bm(bundle):
    try:
        if not isinstance(bundle, dict) or not callable(globals().get("_bm_attach_v322")):
            return bundle
        pf = bundle.get("portfolio_df")
        if not isinstance(pf, pd.DataFrame) or pf.empty:
            return bundle
        pf2 = _bm_attach_v322(pf, bundle.get("static_data"))
        bundle["portfolio_df"] = pf2
        if callable(globals().get("_bm_flags_v322")):
            bundle["bm_mapping_check_df"] = _bm_flags_v322(pf2)
    except Exception:
        pass
    return bundle

try:
    if callable(globals().get("_prepare_out_dashboard_bundle")) and not getattr(globals().get("_prepare_out_dashboard_bundle"), "_bm_v322_wrapped", False):
        _prepare_out_dashboard_bundle_pre_bm_v322 = _prepare_out_dashboard_bundle
        def _prepare_out_dashboard_bundle(*args, **kwargs):
            bundle = _prepare_out_dashboard_bundle_pre_bm_v322(*args, **kwargs)
            return _v322_enrich_bm(bundle)
        _prepare_out_dashboard_bundle._bm_v322_wrapped = True
except Exception:
    pass


# ========================================================
# v327 - GUARANTEE Unison NAV AT PREP TIME (NAV=0 gate always fires)
# ========================================================
# The v326 (B/C-2) workbook-scoped OUT reads Unison NAV from bundle['gav_check_df']
# to apply the workbook AD=IF(NAV<>0,...) gate. That frame was only populated when
# the GAV sub-section rendered, so the NAV=0 gate was inactive if a user opened
# Advisor Return before GAV. This computes the GAV Check ONCE at bundle prep and
# stashes gav_check_df / gav_check_summary on the bundle, so the NAV gate ALWAYS
# has data regardless of section render order. It reuses the SAME validated GAV
# builder (Acc Balance acct 9018) and the SAME acc-balance resolver the render path
# uses - no new NAV source, workbook-exact. Idempotent (skips if already present)
# and fully guarded: on any problem the bundle is returned unchanged, and the
# render-time class-only scope still applies as the fail-safe.
try:
    from bnp_helpers_gav import (
        build_gav_check as _build_gav_check_v327,
        enrich_portfolio_class_from_mapping as _enrich_gav_class_v358_1,
        resolve_acc_balance_source as _resolve_acc_balance_source_v327,
        _resolve_tolerance as _resolve_gav_tolerance_v327,
    )
except Exception:
    _build_gav_check_v327 = None
    _enrich_gav_class_v358_1 = None
    _resolve_acc_balance_source_v327 = None
    _resolve_gav_tolerance_v327 = None


def _ensure_gav_on_bundle_v327(bundle):
    try:
        if not isinstance(bundle, dict) or not callable(globals().get("_build_gav_check_v327")):
            return bundle
        # already built (e.g. GAV section rendered first, or a prior prep pass) -> keep it
        existing = bundle.get("gav_check_df")
        if isinstance(existing, pd.DataFrame) and not existing.empty:
            return bundle
        if bundle.get("_gav_ensured_v327"):
            return bundle
        pf = bundle.get("portfolio_df")
        if not isinstance(pf, pd.DataFrame) or pf.empty:
            return bundle
        acc = _resolve_acc_balance_source_v327(bundle) if callable(globals().get("_resolve_acc_balance_source_v327")) else None
        if acc is None:
            # no Acc Balance source this run -> leave NAV absent; render-time class-only
            # scope still applies. Mark ensured so we don't retry every prep pass.
            bundle["_gav_ensured_v327"] = True
            bundle["gav_ensured_diag_v327"] = {"status": "acc balance unavailable", "rows": 0}
            return bundle
        static_bundle = bundle.get("static_data")
        tol = _resolve_gav_tolerance_v327(static_bundle) if callable(globals().get("_resolve_gav_tolerance_v327")) else 0.01
        dar = bundle.get("dar", pd.DataFrame())
        if callable(globals().get("_enrich_gav_class_v358_1")):
            pf = _enrich_gav_class_v358_1(pf, bundle)
        res = _build_gav_check_v327(pf, acc, dar, tolerance_pct=tol)
        gav_df = getattr(res, "gav_df", None)
        if isinstance(gav_df, pd.DataFrame) and not gav_df.empty:
            bundle["gav_check_df"] = gav_df
            bundle["gav_full_df"] = getattr(res, "full_df", pd.DataFrame())
            bundle["gav_treasury_excluded_df"] = getattr(res, "treasury_excluded_df", pd.DataFrame())
            bundle["gav_check_summary"] = getattr(res, "summary", {})
            bundle["gav_ensured_diag_v327"] = {"status": "OK", "rows": int(len(gav_df))}
        else:
            bundle["gav_ensured_diag_v327"] = {"status": getattr(res, "status", "no rows"), "rows": 0}
        bundle["_gav_ensured_v327"] = True
    except Exception:
        pass
    return bundle


try:
    if callable(globals().get("_prepare_out_dashboard_bundle")) and not getattr(globals().get("_prepare_out_dashboard_bundle"), "_gav_ensure_v327_wrapped", False):
        _prepare_out_dashboard_bundle_pre_gav_v327 = _prepare_out_dashboard_bundle
        def _prepare_out_dashboard_bundle(*args, **kwargs):
            bundle = _prepare_out_dashboard_bundle_pre_gav_v327(*args, **kwargs)
            return _ensure_gav_on_bundle_v327(bundle)
        _prepare_out_dashboard_bundle._gav_ensure_v327_wrapped = True
except Exception:
    pass


# ========================================================
# v326 (A2) - EXCLUDED-FROM-BNP-REPORTS POPULATION FILTER
# ========================================================
# The BNP DDetailedReturn feed carries a few codes the ARC workbook intentionally
# excludes/does not hold (statutory-fund overlay cash pools M2STT2 / M2STT4, and
# the app-side M7MLCH). This drops them from portfolio_df ONCE, at bundle prep,
# BEFORE the Basis-Impact / Hot-Cold classifiers (defined below) run - so every
# downstream check, count and the executive card reconcile to the workbook
# population. The exclusion list is CONFIG-DRIVEN from Static Data
# 'excluded_from_bnp_reports' (Active='Y'); nothing is hard-coded here. It also
# nets the excluded codes out of the v308 universe reconciliation so they no
# longer resurface as 'unmapped in BNP', and stashes an evidence frame + diag.
# Fully guarded: on any problem the bundle is returned unchanged.
try:
    from bnp_helpers_static_data import load_excluded_bnp_report_codes as _load_excluded_codes_v326
except Exception:
    _load_excluded_codes_v326 = None


def _v326_norm_code(v) -> str:
    return "".join(ch for ch in str(v or "").upper().strip() if ch.isalnum())


def _apply_excluded_bnp_codes_v326(bundle):
    try:
        if not isinstance(bundle, dict) or not callable(globals().get("_load_excluded_codes_v326")):
            return bundle
        # idempotent per bundle (the wrapper stack can call prepare more than once)
        if bundle.get("_excluded_bnp_codes_applied_v326"):
            return bundle
        info = _load_excluded_codes_v326(bundle.get("static_data"))
        codes_norm = set(info.get("codes_norm") or set())
        if not codes_norm:
            bundle["_excluded_bnp_codes_applied_v326"] = True
            bundle["excluded_bnp_reports_diag"] = {"status": info.get("status", "no codes"), "removed": 0}
            return bundle

        pf = bundle.get("portfolio_df")
        removed_df = pd.DataFrame()
        if isinstance(pf, pd.DataFrame) and not pf.empty and "Portfolio code" in pf.columns:
            key = pf["Portfolio code"].map(_v326_norm_code)
            drop_mask = key.isin(codes_norm)
            removed_df = pf[drop_mask].copy()
            if bool(drop_mask.any()):
                bundle["portfolio_df"] = pf[~drop_mask].copy()

        # Net the excluded codes out of the v308 universe reconciliation so they
        # do not resurface as 'unmapped in BNP'.
        def _scrub_unmapped(frame):
            if isinstance(frame, pd.DataFrame) and not frame.empty:
                for col in ("Portfolio code", "Portfolio", "Hiport Code"):
                    if col in frame.columns:
                        k = frame[col].map(_v326_norm_code)
                        return frame[~k.isin(codes_norm)].copy()
            return frame

        if isinstance(bundle.get("universe_unmapped_in_bnp_df"), pd.DataFrame):
            bundle["universe_unmapped_in_bnp_df"] = _scrub_unmapped(bundle["universe_unmapped_in_bnp_df"])
        recon = bundle.get("_universe_reconciliation_v308")
        if recon is not None and hasattr(recon, "unmapped_in_bnp_df"):
            try:
                recon.unmapped_in_bnp_df = _scrub_unmapped(recon.unmapped_in_bnp_df)
            except Exception:
                pass

        bundle["excluded_bnp_reports_applied_df"] = removed_df
        bundle["excluded_bnp_reports_evidence_df"] = info.get("evidence_df", pd.DataFrame())
        bundle["excluded_bnp_reports_diag"] = {
            "status": info.get("status", "OK"),
            "codes": list(info.get("codes") or []),
            "removed": int(len(removed_df)),
            "requested": int(len(codes_norm)),
        }
        bundle["_excluded_bnp_codes_applied_v326"] = True
    except Exception:
        pass
    return bundle


try:
    if callable(globals().get("_prepare_out_dashboard_bundle")) and not getattr(globals().get("_prepare_out_dashboard_bundle"), "_excluded_v326_wrapped", False):
        _prepare_out_dashboard_bundle_pre_excluded_v326 = _prepare_out_dashboard_bundle
        def _prepare_out_dashboard_bundle(*args, **kwargs):
            bundle = _prepare_out_dashboard_bundle_pre_excluded_v326(*args, **kwargs)
            return _apply_excluded_bnp_codes_v326(bundle)
        _prepare_out_dashboard_bundle._excluded_v326_wrapped = True
except Exception:
    pass


# ========================================================
# v306.14.0 BASIS IMPACT ERROR RISK CUTOVER - REMOVED (v364)
# ========================================================
# Dead code removed (superseded within the same rebuild by v306.14.5,
# a handful of lines below - itself unaffected by this removal). See
# note on v306.13.17 above and CHANGELOG.md for history. Alias recreated
# further down for compatibility with older wrapper closures that still
# call this name.


try:
    if callable(globals().get("_prepare_out_dashboard_bundle")) and not getattr(globals().get("_prepare_out_dashboard_bundle"), "_er14_basis_impact_wrapped", False):
        _prepare_out_dashboard_bundle_v306_14_0_original = _prepare_out_dashboard_bundle
        def _prepare_out_dashboard_bundle(*args, **kwargs):
            bundle = _prepare_out_dashboard_bundle_v306_14_0_original(*args, **kwargs)
            return _apply_basis_impact_error_risk_classification_v306_14_0(bundle)
        _prepare_out_dashboard_bundle._er14_basis_impact_wrapped = True
except Exception:
    pass

for _er14_func_name in [
    "_render_overview_tab",
    "_render_portfolio_numbers",
    "_render_portfolio_numbers_section",
    "_render_portfolio_count_tab",
    "_render_portfolio_count_section",
    "_hot_resolution_sets",
]:
    try:
        _func = globals().get(_er14_func_name)
        if callable(_func) and not getattr(_func, "_er14_basis_impact_wrapped", False):
            def _make_er14_wrapper(fn, fn_name):
                def _wrapped(*args, **kwargs):
                    new_args = list(args)
                    if new_args and isinstance(new_args[0], dict):
                        new_args[0] = _apply_basis_impact_error_risk_classification_v306_14_0(new_args[0])
                    elif "bundle" in kwargs and isinstance(kwargs.get("bundle"), dict):
                        kwargs["bundle"] = _apply_basis_impact_error_risk_classification_v306_14_0(kwargs["bundle"])
                    return fn(*new_args, **kwargs)
                _wrapped._er14_basis_impact_wrapped = True
                return _wrapped
            globals()[_er14_func_name] = _make_er14_wrapper(_func, _er14_func_name)
    except Exception:
        pass


# ========================================================
# BASIS IMPACT ERROR RISK RUNTIME DIAGNOSTIC
# Paste before: if __name__ == "__main__": main()
# Exports:
#   error_risk_classification_diagnostics_last_run.csv
#   error_risk_classification_sample_last_run.csv
# Purpose:
#   Proves whether Basis/BP Impact classification survives legacy wrappers/render.
# ========================================================

ERROR_RISK_CLASSIFICATION_DIAG_CSV = "error_risk_classification_diagnostics_last_run.csv"
ERROR_RISK_CLASSIFICATION_SAMPLE_CSV = "error_risk_classification_sample_last_run.csv"
NO_ERROR_RISK_LABELS_DIAG = {"No Error Risk row", "No BP Impact row", "No ARC match"}


def _er_runtime_bool_series(s, index):
    try:
        return s.fillna(False).astype(bool)
    except Exception:
        try:
            return s.astype(str).str.strip().str.upper().isin(["TRUE", "YES", "1"])
        except Exception:
            return pd.Series([False] * len(index), index=index)


def _er_runtime_num_series(s, index):
    try:
        if s is None:
            return pd.Series([float("nan")] * len(index), index=index)
        if pd.api.types.is_numeric_dtype(s):
            return pd.to_numeric(s, errors="coerce")
        txt = (
            s.astype(str)
            .str.replace("%", "", regex=False)
            .str.replace(",", "", regex=False)
            .str.replace("$", "", regex=False)
            .str.replace("(", "-", regex=False)
            .str.replace(")", "", regex=False)
            .str.strip()
        )
        return pd.to_numeric(txt, errors="coerce")
    except Exception:
        return pd.Series([float("nan")] * len(index), index=index)


def _er_runtime_out_mask(df):
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return pd.Series(dtype="bool")
    if "Within Tolerance" in df.columns:
        try:
            return ~df["Within Tolerance"].fillna(False).astype(bool)
        except Exception:
            pass
    if "Status Normalised" in df.columns:
        return df["Status Normalised"].astype(str).str.strip().str.upper().eq("OUT")
    if "Status" in df.columns:
        return df["Status"].astype(str).str.strip().str.upper().str.contains("OUT|OUTSIDE|FAIL|BREACH", regex=True, na=False)
    return pd.Series([False] * len(df), index=df.index)


def _er_runtime_write_diag(bundle, stage=""):
    try:
        if not isinstance(bundle, dict):
            return
        df = bundle.get("portfolio_df", pd.DataFrame())
        if df is None or not isinstance(df, pd.DataFrame) or df.empty:
            return
        out_mask = _er_runtime_out_mask(df)
        hotcold = df.get("Hot / Cold", pd.Series([""] * len(df), index=df.index)).astype(str).str.strip()
        er_matched = _er_runtime_bool_series(df.get("Error Risk matched?", pd.Series([False] * len(df), index=df.index)), df.index)
        bp_matched = _er_runtime_bool_series(df.get("BP Impact matched?", pd.Series([False] * len(df), index=df.index)), df.index)
        er_risk = _er_runtime_num_series(df.get("Error Risk Ratio Decimal", pd.Series(dtype="float64")), df.index)
        bp_risk = _er_runtime_num_series(df.get("BP Impact Error Risk Ratio", pd.Series(dtype="float64")), df.index)
        arc_risk = _er_runtime_num_series(df.get("ARC Error Risk Ratio", pd.Series(dtype="float64")), df.index)
        break_abs = _er_runtime_num_series(df.get("Volatility over Tolerance Num", pd.Series(dtype="float64")), df.index).abs()
        ext_ref = df.get("External portfolio reference", pd.Series([""] * len(df), index=df.index)).astype(str).str.strip()
        basis = df.get("Error Risk match basis", pd.Series([""] * len(df), index=df.index)).astype(str).str.strip()
        bp_basis = df.get("BP Impact match basis", pd.Series([""] * len(df), index=df.index)).astype(str).str.strip()

        diag = pd.DataFrame([
            {"Stage": stage, "Check": "OUT Hot/Cold counts", "Result": "OK", "Detail": str(hotcold[out_mask].value_counts(dropna=False).to_dict())},
            {"Stage": stage, "Check": "Error Risk field survival", "Result": "OK", "Detail": f"OUT={int(out_mask.sum()):,}; ErrorRiskMatched={int((out_mask & er_matched).sum()):,}; BPImpactMatched={int((out_mask & bp_matched).sum()):,}; ErrorRiskRatioPopulated={int((out_mask & er_risk.notna()).sum()):,}; BPImpactRatioPopulated={int((out_mask & bp_risk.notna()).sum()):,}; ARCRiskPopulated={int((out_mask & arc_risk.notna()).sum()):,}; BreakPopulated={int((out_mask & break_abs.notna()).sum()):,}"},
            {"Stage": stage, "Check": "basis indicators", "Result": "OK", "Detail": f"ExternalRefPopulated={int((out_mask & ext_ref.ne('')).sum()):,}; ErrorRiskBasisPopulated={int((out_mask & basis.ne('')).sum()):,}; BPImpactBasisPopulated={int((out_mask & bp_basis.ne('')).sum()):,}"},
        ])
        try:
            existing = bundle.get("error_risk_classification_diag_df", pd.DataFrame())
            if isinstance(existing, pd.DataFrame) and not existing.empty:
                tmp = existing.copy()
                if "Stage" not in tmp.columns:
                    tmp.insert(0, "Stage", stage + " / existing error_risk_classification_diag_df")
                diag = pd.concat([diag, tmp], ignore_index=True)
        except Exception:
            pass
        pass  # [removed] diagnostic CSV write

        cols = [c for c in [
            "Portfolio code", "Portfolio Name", "External portfolio reference", "Hot / Cold",
            "Error Risk matched?", "Error Risk match basis", "Error Risk match key", "Error Risk Ratio Decimal",
            "BP Impact matched?", "BP Impact match basis", "BP Impact match key", "BP Impact Error Risk Ratio",
            "ARC Error Risk Ratio", "ARC Error Risk Ratio Decimal", "Volatility over Tolerance Num", "Error Risk Source", "Non-ARC coverage source",
        ] if c in df.columns]
        if cols:
            pass  # [removed] diagnostic CSV write
    except Exception as exc:
        try:
            pass  # [removed] diagnostic CSV write
        except Exception:
            pass





# ========================================================
# v306.14.2 EXECUTIVE CARD COUNT FIX
# ========================================================
# Root cause: Basis/BP Impact classification is now correct in portfolio_df,
# but the executive card derives No Error Risk / Cold counts from driver count
# frames. Those frames can be empty when Tier 1 assignments are only built for
# Hot / review populations, so the card shows zeros even when portfolio_df has
# Cold / No Error Risk rows.
#
# Paste this BEFORE: if __name__ == "__main__": main()


def _er142_subset_portfolio_count(df: pd.DataFrame) -> int:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return 0
    try:
        key_col = find_col(df, ["Portfolio code", "Portfolio", "PortfolioCode", "portfolio", "portfolio code"])
        if key_col and key_col in df.columns:
            return int(df[key_col].astype(str).str.strip().replace("", pd.NA).dropna().nunique())
    except Exception:
        pass
    return int(len(df))


# Make driver count frames count the subset even when no Tier 1 assignment exists.
# This is important for No Error Risk and Cold, which are not part of the Hot
# movement diagnosis population but still need to reconcile to Outside tolerance.
try:
    if callable(globals().get("_tier1_count_frame_from_assignments")) and not getattr(globals().get("_tier1_count_frame_from_assignments"), "_er142_count_fallback_wrapped", False):
        _tier1_count_frame_from_assignments_er142_original = _tier1_count_frame_from_assignments

        def _tier1_count_frame_from_assignments(subset_df: pd.DataFrame, assignments_df: pd.DataFrame) -> pd.DataFrame:
            result = _tier1_count_frame_from_assignments_er142_original(subset_df, assignments_df)
            if result is not None and isinstance(result, pd.DataFrame) and not result.empty:
                return result
            count = _er142_subset_portfolio_count(subset_df)
            if count <= 0:
                return result if isinstance(result, pd.DataFrame) else pd.DataFrame(columns=["Largest Tier 1 driver", "Portfolio count"])
            return pd.DataFrame([{"Largest Tier 1 driver": "Unassigned", "Portfolio count": int(count)}])

        _tier1_count_frame_from_assignments._er142_count_fallback_wrapped = True
except Exception:
    pass


# Also harden the executive card itself. If direct portfolio counts are supplied
# in driver_views['_portfolio_counts'], use those instead of assignment-derived
# frames for No Error Risk, Cold and Hot.
try:
    if callable(globals().get("_render_executive_flow_bar")) and not getattr(globals().get("_render_executive_flow_bar"), "_er142_direct_counts_wrapped", False):
        _render_executive_flow_bar_er142_original = _render_executive_flow_bar

        def _render_executive_flow_bar(run_date_value: object, total_count: int, within_count: int, out_count: int, hot_count: int, auto_explained_fx_count: int, nil_actual_return_count: int, current_account_dominated_count: int, unexplained_count: int, unexplained_driver_df: Optional[pd.DataFrame] = None, driver_views: Optional[Dict[str, pd.DataFrame]] = None):
            driver_views = driver_views or {}
            counts = driver_views.get("_portfolio_counts", {}) if isinstance(driver_views, dict) else {}
            if isinstance(counts, dict):
                try:
                    if "no_error_risk" in counts:
                        driver_views["no_arc"] = pd.DataFrame([{"Largest Tier 1 driver": "No Error Risk", "Portfolio count": int(counts.get("no_error_risk", 0))}])
                    if "cold" in counts:
                        driver_views["cold"] = pd.DataFrame([{"Largest Tier 1 driver": "Cold", "Portfolio count": int(counts.get("cold", 0))}])
                    if "hot" in counts:
                        hot_count = int(counts.get("hot", hot_count))
                except Exception:
                    pass
            return _render_executive_flow_bar_er142_original(run_date_value, total_count, within_count, out_count, hot_count, auto_explained_fx_count, nil_actual_return_count, current_account_dominated_count, unexplained_count, unexplained_driver_df, driver_views=driver_views)

        _render_executive_flow_bar._er142_direct_counts_wrapped = True
except Exception:
    pass


# ========================================================
# v306.14.5 BASIS IMPACT MATCH + SCALED ERROR RISK FINAL
# ========================================================
# Final canonical classifier:
# - Source: Basis/BP Impact Error Risk dataframe, normally bundle['arc']['error_df'].
# - Primary join: portfolio_df['External portfolio reference'] -> source['Advisor'].
# - Risk scaling: source value 1.0 means 1.00%, so store as 0.01 for app comparisons/display.
# - OUT + matched + abs(Volatility over Tolerance Num) >= scaled risk => Hot.
# - OUT + matched + below threshold => Cold.
# - OUT + no matched source row => No Error Risk row.

NO_ERROR_RISK_LABEL = "No Error Risk row"
NO_ERROR_RISK_LABELS = {"No Error Risk row", "No BP Impact row", "No ARC match"}
ERROR_RISK_SOURCE_LABEL = "Basis Impact spreadsheet"
BASIS_IMPACT_FINAL_DIAG_CSV = "basis_impact_final_classification_diagnostics_last_run.csv"
BASIS_IMPACT_FINAL_SAMPLE_CSV = "basis_impact_final_classification_sample_last_run.csv"


def _bi145_find_col(df: pd.DataFrame, candidates: list) -> Optional[str]:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return None
    try:
        if callable(globals().get("find_col")):
            found = find_col(df, candidates)
            if found:
                return found
    except Exception:
        pass
    norm = {str(c).strip().lower().replace(" ", "").replace("_", "").replace("/", ""): c for c in df.columns}
    for cand in candidates:
        key = str(cand).strip().lower().replace(" ", "").replace("_", "").replace("/", "")
        if key in norm:
            return norm[key]
    for cand in candidates:
        parts = [p for p in re.split(r"[\s_/]+", str(cand).strip().lower()) if p]
        for c in df.columns:
            low = str(c).strip().lower()
            if parts and all(p in low for p in parts):
                return c
    return None


def _bi145_key_series(s: pd.Series) -> pd.Series:
    try:
        return normalise_join_key_series(s.astype(str).str.strip())
    except Exception:
        return s.astype(str).str.strip().str.upper().str.replace(r"[^A-Z0-9]", "", regex=True)


def _bi145_num_series(s: pd.Series, index=None) -> pd.Series:
    if s is None:
        return pd.Series([float("nan")] * len(index), index=index) if index is not None else pd.Series(dtype="float64")
    try:
        if pd.api.types.is_numeric_dtype(s):
            return pd.to_numeric(s, errors="coerce")
        txt = (
            s.astype(str)
            .str.replace("%", "", regex=False)
            .str.replace(",", "", regex=False)
            .str.replace("$", "", regex=False)
            .str.replace("(", "-", regex=False)
            .str.replace(")", "", regex=False)
            .str.strip()
        )
        return pd.to_numeric(txt, errors="coerce")
    except Exception:
        return pd.Series([float("nan")] * len(index), index=index) if index is not None else pd.Series(dtype="float64")


def _bi145_extract_first_token(value: object) -> str:
    text = str(value or "").strip()
    return re.split(r"\s+", text)[0].strip() if text else ""


def _bi145_out_mask(df: pd.DataFrame) -> pd.Series:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return pd.Series(dtype="bool")
    if "Within Tolerance" in df.columns:
        try:
            return ~df["Within Tolerance"].fillna(False).astype(bool)
        except Exception:
            pass
    if "Status Normalised" in df.columns:
        return df["Status Normalised"].astype(str).str.strip().str.upper().eq("OUT")
    if "Status" in df.columns:
        return df["Status"].astype(str).str.strip().str.upper().str.contains("OUT|OUTSIDE|FAIL|BREACH", regex=True, na=False)
    return pd.Series([False] * len(df), index=df.index)


def _bi145_break_abs(df: pd.DataFrame) -> pd.Series:
    for col in [
        "Unison Volatility over Tolerance Num",  # v310.1: Unison-basis severity (preferred)
        "Volatility over Tolerance Num",
        "Transaction-aware Control Break",
        "Source Calculated over/under",
        "Calculated Actual v Benchmark Diff Num",
        "Actual vs Benchmark Num",
        "Over/Under Num",
        "Calculated over/under",
        "Actual vs Benchmark",
        "Over/Under",
    ]:
        if col in df.columns:
            return _bi145_num_series(df[col], df.index).abs()
    return pd.Series([float("nan")] * len(df), index=df.index)


def _bi145_get_error_df(bundle: Dict[str, object]) -> pd.DataFrame:
    if not isinstance(bundle, dict):
        return pd.DataFrame()
    candidates = [
        bundle.get("basis_impact_error_risk_df", pd.DataFrame()),
        bundle.get("bpimpact_error_risk_df", pd.DataFrame()),
        bundle.get("error_risk_df", pd.DataFrame()),
        bundle.get("error_df", pd.DataFrame()),
    ]
    arc = bundle.get("arc", {})
    if isinstance(arc, dict):
        candidates.extend([
            arc.get("error_df", pd.DataFrame()),
            arc.get("bp_impact_portfolio_df", pd.DataFrame()),
            arc.get("arc_portfolio_df", pd.DataFrame()),
        ])
    best = pd.DataFrame()
    best_score = -1
    for c in candidates:
        if not isinstance(c, pd.DataFrame) or c.empty:
            continue
        cols = [str(x).lower() for x in c.columns]
        score = 0
        if any("advisor" in x for x in cols):
            score += 10
        if any("error" in x and "risk" in x for x in cols):
            score += 10
        if any("ratio" in x for x in cols):
            score += 5
        score += min(len(c), 1000) / 100000.0
        if score > best_score:
            best_score = score
            best = c.copy()
    return best


def _apply_basis_impact_error_risk_classification_v306_14_5(bundle: Dict[str, object]) -> Dict[str, object]:
    if not isinstance(bundle, dict):
        return bundle
    df = bundle.get("portfolio_df", pd.DataFrame())
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return bundle

    out = df.copy()
    out_mask = _bi145_out_mask(out)
    err = _bi145_get_error_df(bundle)

    if err is None or not isinstance(err, pd.DataFrame) or err.empty:
        if "Hot / Cold" in out.columns:
            out.loc[out_mask & out["Hot / Cold"].astype(str).str.strip().isin(NO_ERROR_RISK_LABELS), "Hot / Cold"] = NO_ERROR_RISK_LABEL
        bundle["portfolio_df"] = out
        bundle["error_risk_classification_diag_df"] = pd.DataFrame([{"Check": "Basis Impact final classification", "Result": "No source dataframe", "Detail": f"OUT={int(out_mask.sum()):,}; no error risk dataframe available"}])
        return bundle

    advisor_col = _bi145_find_col(err, [
        "Advisor", "Advisor code", "Advisor Code",
        "External portfolio reference", "External Portfolio Reference", "ExternalPortfolioReference",
        "Portfolio external reference", "Portfolio External Reference",
    ])
    ratio_col = _bi145_find_col(err, [
        "Error Risk Ratio", "ARC Error Risk Ratio", "BP Impact Error Risk Ratio",
        "Risk Ratio", "ERR", "Error Risk", "ARC Error Risk Ratio Pct",
    ])
    if not advisor_col or advisor_col not in err.columns:
        bundle["error_risk_classification_diag_df"] = pd.DataFrame([{"Check": "Basis Impact source key", "Result": "Missing", "Detail": "Could not resolve Advisor column in error risk source."}])
        return bundle

    work = err.copy()
    work["_bi145_key"] = _bi145_key_series(work[advisor_col])
    raw_ratio = _bi145_num_series(work[ratio_col], work.index).abs() if ratio_col and ratio_col in work.columns else pd.Series([float("nan")] * len(work), index=work.index)
    # Critical scaling: Basis/BP Impact values are percentage points. 1.0 means 1.00% => 0.01.
    work["_bi145_risk_decimal"] = raw_ratio / 100.0
    work = work[work["_bi145_key"].astype(str).str.strip().ne("")].copy()
    risk_map = (
        work.groupby("_bi145_key", dropna=False)["_bi145_risk_decimal"]
        .apply(lambda s: float(pd.to_numeric(s, errors="coerce").abs().max()) if pd.to_numeric(s, errors="coerce").notna().any() else float("nan"))
        .to_dict()
    ) if not work.empty else {}

    port_col = _bi145_find_col(out, ["Portfolio code", "Portfolio", "PortfolioCode", "portfolio", "portfolio code"])
    name_col = _bi145_find_col(out, ["Portfolio Name", "PortfolioName", "Name"])
    ext_col = _bi145_find_col(out, ["External portfolio reference", "External Portfolio Reference", "ExternalPortfolioReference", "External portfolio ref", "External reference", "Advisor", "Advisor code"])

    ext_key = _bi145_key_series(out[ext_col]) if ext_col and ext_col in out.columns else pd.Series([""] * len(out), index=out.index, dtype="object")
    name_key = _bi145_key_series(out[name_col].map(_bi145_extract_first_token)) if name_col and name_col in out.columns else pd.Series([""] * len(out), index=out.index, dtype="object")
    port_key = _bi145_key_series(out[port_col]) if port_col and port_col in out.columns else pd.Series([""] * len(out), index=out.index, dtype="object")

    ext_match = ext_key.map(lambda k: str(k) in risk_map)
    name_match = name_key.map(lambda k: str(k) in risk_map)
    port_match = port_key.map(lambda k: str(k) in risk_map)
    matched = ext_match | name_match | port_match
    match_key = ext_key.where(ext_match, name_key.where(name_match, port_key.where(port_match, "")))
    risk = match_key.map(lambda k: risk_map.get(str(k), float("nan")))
    break_abs = _bi145_break_abs(out)

    no_source = out_mask & ~matched
    classifiable = out_mask & matched
    hot = classifiable & (risk.isna() | break_abs.ge(risk.abs()))
    cold = classifiable & ~hot

    if "Hot / Cold" not in out.columns:
        out["Hot / Cold"] = ""
    out.loc[out_mask & out["Hot / Cold"].astype(str).str.strip().isin(NO_ERROR_RISK_LABELS), "Hot / Cold"] = NO_ERROR_RISK_LABEL
    out.loc[no_source, "Hot / Cold"] = NO_ERROR_RISK_LABEL
    out.loc[cold, "Hot / Cold"] = "Cold"
    out.loc[hot, "Hot / Cold"] = "Hot"

    out["Error Risk matched?"] = matched.where(out_mask, False)
    out["Error Risk match basis"] = ""
    out.loc[out_mask & ext_match, "Error Risk match basis"] = "External portfolio reference -> Advisor"
    out.loc[out_mask & ~ext_match & name_match, "Error Risk match basis"] = "Portfolio Name first token -> Advisor"
    out.loc[out_mask & ~ext_match & ~name_match & port_match, "Error Risk match basis"] = "Portfolio code fallback"
    out["Error Risk match key"] = match_key.where(out_mask & matched, "")
    out["Error Risk Ratio Decimal"] = risk
    out["Error Risk Source"] = ERROR_RISK_SOURCE_LABEL

    # Compatibility aliases for older display/export code.
    out["BP Impact matched?"] = out["Error Risk matched?"]
    out["BP Impact match basis"] = out["Error Risk match basis"]
    out["BP Impact match key"] = out["Error Risk match key"]
    out["BP Impact Error Risk Ratio"] = out["Error Risk Ratio Decimal"]
    out["ARC Error Risk Ratio"] = out["Error Risk Ratio Decimal"]
    out["ARC Error Risk Ratio Decimal"] = out["Error Risk Ratio Decimal"]
    out["ARC Workbook Used"] = False
    out["Non-ARC coverage source"] = ERROR_RISK_SOURCE_LABEL

    bundle["portfolio_df"] = out

    # v307: assert & surface the invariant No source + Cold + Hot == OUT.
    # Read-only (never raises) so a mismatch is surfaced, not crash the render.
    try:
        if callable(globals().get("_compute_hotcold_invariant_v307")):
            _inv_v307 = _compute_hotcold_invariant_v307(out, hotcold_col="Hot / Cold")
        else:
            _hc_v307 = out["Hot / Cold"].astype(str).str.strip()
            _no_v307 = int(out_mask.sum())
            _ns_v307 = int((out_mask & _hc_v307.isin(NO_ERROR_RISK_LABELS)).sum())
            _cd_v307 = int((out_mask & _hc_v307.eq("Cold")).sum())
            _ht_v307 = int((out_mask & _hc_v307.eq("Hot")).sum())
            _tt_v307 = _ns_v307 + _cd_v307 + _ht_v307
            _inv_v307 = {"invariant_ok": bool(_tt_v307 == _no_v307),
                "detail": (f"No source ({_ns_v307}) + Cold ({_cd_v307}) + Hot ({_ht_v307}) "
                           f"= {_tt_v307}; OUT = {_no_v307}; {'OK' if _tt_v307 == _no_v307 else 'MISMATCH'}"),
                "out_count": _no_v307, "no_source": _ns_v307, "cold": _cd_v307, "hot": _ht_v307}
        bundle["error_risk_invariant"] = _inv_v307
        bundle["error_risk_invariant_df"] = pd.DataFrame([{
            "Check": "v307 Hot/Cold invariant (No source + Cold + Hot == OUT)",
            "Result": "OK" if _inv_v307.get("invariant_ok") else "MISMATCH",
            "Detail": _inv_v307.get("detail", "")}])
    except Exception:
        pass

    diag = pd.DataFrame([{
        "Check": "Basis Impact final classification",
        "Result": "Applied",
        "Detail": (
            f"OUT={int(out_mask.sum()):,}; matched={int((out_mask & matched).sum()):,}; "
            f"external_ref_matches={int((out_mask & ext_match).sum()):,}; "
            f"name_token_matches={int((out_mask & ~ext_match & name_match).sum()):,}; "
            f"portfolio_code_matches={int((out_mask & ~ext_match & ~name_match & port_match).sum()):,}; "
            f"no_error_risk={int(no_source.sum()):,}; cold={int(cold.sum()):,}; hot={int(hot.sum()):,}; "
            f"source_rows={len(err):,}; source_key_col={advisor_col}; ratio_col={ratio_col or ''}; "
            f"risk_min={float(pd.Series(risk)[out_mask & pd.Series(risk).notna()].min()) if (out_mask & pd.Series(risk).notna()).any() else ''}; "
            f"risk_max={float(pd.Series(risk)[out_mask & pd.Series(risk).notna()].max()) if (out_mask & pd.Series(risk).notna()).any() else ''}; "
            f"break_max={float(break_abs[out_mask & break_abs.notna()].max()) if (out_mask & break_abs.notna()).any() else ''}"
        )
    }])
    bundle["error_risk_classification_diag_df"] = diag
    bundle["non_arc_bpimpact_classification_diag_df"] = diag
    bundle["bpimpact_forced_hotcold_diag_df"] = diag
    try:
        pass  # [removed] diagnostic CSV write
        sample_cols = [c for c in ["Portfolio code", "Portfolio Name", "External portfolio reference", "Hot / Cold", "Error Risk matched?", "Error Risk match basis", "Error Risk match key", "Error Risk Ratio Decimal", "BP Impact Error Risk Ratio", "ARC Error Risk Ratio Decimal", "Volatility over Tolerance Num", "Error Risk Source"] if c in out.columns]
        pass  # [removed] diagnostic CSV write
    except Exception:
        pass
    try:
        arc = bundle.get("arc", {})
        if isinstance(arc, dict):
            arc["status"] = "OK - Basis Impact spreadsheet used for Error Risk Hot/Cold classification v306.14.5"
            arc["error_risk_classification_diag_df"] = diag
            arc["non_arc_bpimpact_classification_diag_df"] = diag
            bundle["arc"] = arc
    except Exception:
        pass
    return bundle


# Override all legacy BP Impact/ARC replacement classifiers so any older wrapper stack
# resolves to the final canonical classifier at call time.
_apply_basis_impact_error_risk_classification_v306_14_0 = _apply_basis_impact_error_risk_classification_v306_14_5
try:
    _apply_non_arc_bpimpact_classification_v306_13_17 = _apply_basis_impact_error_risk_classification_v306_14_5
except Exception:
    pass
try:
    _apply_non_arc_bpimpact_classification_v306_13_18 = _apply_basis_impact_error_risk_classification_v306_14_5
except Exception:
    pass
try:
    _apply_non_arc_bpimpact_classification_v306_13_19 = _apply_basis_impact_error_risk_classification_v306_14_5
except Exception:
    pass
try:
    _apply_bpimpact_hotcold_force_v306_13_21 = _apply_basis_impact_error_risk_classification_v306_14_5
except Exception:
    pass

# Apply immediately before key render/count paths in case the bundle came from session cache.
for _bi145_func_name in ["_render_overview_tab", "_render_portfolio_numbers", "_render_portfolio_numbers_section", "_render_portfolio_count_tab", "_render_portfolio_count_section", "_hot_resolution_sets"]:
    try:
        _func = globals().get(_bi145_func_name)
        if callable(_func) and not getattr(_func, "_bi145_final_wrapped", False):
            def _make_bi145_wrapper(fn, fn_name):
                def _wrapped(*args, **kwargs):
                    new_args = list(args)
                    if new_args and isinstance(new_args[0], dict):
                        new_args[0] = _apply_basis_impact_error_risk_classification_v306_14_5(new_args[0])
                    elif "bundle" in kwargs and isinstance(kwargs.get("bundle"), dict):
                        kwargs["bundle"] = _apply_basis_impact_error_risk_classification_v306_14_5(kwargs["bundle"])
                    return fn(*new_args, **kwargs)
                _wrapped._bi145_final_wrapped = True
                return _wrapped
            globals()[_bi145_func_name] = _make_bi145_wrapper(_func, _bi145_func_name)
    except Exception:
        pass


# ========================================================
# v306.14.6 AUTO FX CANDIDATE DIAGNOSTICS
# ========================================================
# Diagnostic-only instrumentation. It does not change Auto FX classification.
# It exports the exact state feeding _hot_resolution_sets / _portfolio_subset_from_fx_yes.
AUTO_FX_DIAG_CSV = "auto_fx_candidate_diagnostics_last_run.csv"
AUTO_FX_SAMPLE_CSV = "auto_fx_hot_overlap_sample_last_run.csv"
AUTO_FX_APP_SUBSET_SAMPLE_CSV = "auto_fx_app_subset_sample_last_run.csv"


def _afx_diag_find_col(df: pd.DataFrame, candidates: list) -> Optional[str]:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return None
    try:
        if callable(globals().get("find_col")):
            found = find_col(df, candidates)
            if found:
                return found
    except Exception:
        pass
    norm = {str(c).strip().lower().replace(" ", "").replace("_", "").replace("/", ""): c for c in df.columns}
    for cand in candidates:
        key = str(cand).strip().lower().replace(" ", "").replace("_", "").replace("/", "")
        if key in norm:
            return norm[key]
    for cand in candidates:
        parts = [p for p in re.split(r"[\s_/]+", str(cand).strip().lower()) if p]
        for c in df.columns:
            low = str(c).strip().lower()
            if parts and all(p in low for p in parts):
                return c
    return None


def _afx_diag_key_series(s: pd.Series) -> pd.Series:
    try:
        return normalise_join_key_series(s.astype(str).str.strip())
    except Exception:
        return s.astype(str).str.strip().str.upper().str.replace(r"[^A-Z0-9]", "", regex=True)


def _afx_diag_bool_like(s: pd.Series) -> pd.Series:
    if s is None:
        return pd.Series(dtype="bool")
    text = s.astype(str).str.strip().str.upper()
    return text.isin(["YES", "Y", "TRUE", "1", "CANDIDATE", "AUTO EXPLAINED", "AUTO-EXPLAINED", "PASS"])


def _afx_write_diag(bundle: Dict[str, object], auto_fx_summary_df: Optional[pd.DataFrame] = None, stage: str = "") -> None:
    try:
        rows = []
        if not isinstance(bundle, dict):
            pass  # [removed] diagnostic CSV write
            return

        portfolio_df = bundle.get("portfolio_df", pd.DataFrame())
        if not isinstance(portfolio_df, pd.DataFrame) or portfolio_df.empty:
            pass  # [removed] diagnostic CSV write
            return

        if auto_fx_summary_df is None or not isinstance(auto_fx_summary_df, pd.DataFrame):
            ex0 = bundle.get("exchange_rates", {})
            auto_fx_summary_df = ex0.get("portfolio_fx_summary_df", pd.DataFrame()) if isinstance(ex0, dict) else pd.DataFrame()

        hc = portfolio_df.get("Hot / Cold", pd.Series([""] * len(portfolio_df), index=portfolio_df.index)).astype(str).str.strip()
        hot_df = portfolio_df[hc.eq("Hot")].copy()
        rows.append({"Stage": stage, "Check": "portfolio Hot / Cold counts", "Result": "OK", "Detail": str(hc.value_counts(dropna=False).to_dict())})
        rows.append({"Stage": stage, "Check": "Hot population", "Result": "OK", "Detail": f"hot_rows={len(hot_df):,}; portfolio_rows={len(portfolio_df):,}"})

        ex = bundle.get("exchange_rates", {}) if isinstance(bundle, dict) else {}
        if isinstance(ex, dict):
            rows.append({"Stage": stage, "Check": "exchange_rates status", "Result": str(ex.get("status", "")), "Detail": f"source_file={ex.get('source_file','')}; sheet_used={ex.get('sheet_used','')}; header_row={ex.get('header_row','')}; index_sector_col={ex.get('index_sector_col','')}"})
            for key in ["portfolio_fx_summary_df", "portfolio_fx_detail_df", "portfolio_fx_control_df", "diagnostic_df", "exception_df", "exchange_rate_diagnostic_df", "exchange_rate_exception_df", "resolver_diagnostic_df"]:
                val = ex.get(key, pd.DataFrame())
                rows.append({"Stage": stage, "Check": f"exchange_rates.{key}", "Result": "Present" if isinstance(val, pd.DataFrame) and not val.empty else "Empty", "Detail": f"rows={len(val) if isinstance(val, pd.DataFrame) else 0}; cols={' | '.join(map(str, val.columns.tolist())) if isinstance(val, pd.DataFrame) else ''}"})

        if not isinstance(auto_fx_summary_df, pd.DataFrame) or auto_fx_summary_df.empty:
            rows.append({"Stage": stage, "Check": "auto_fx_summary_df", "Result": "Empty", "Detail": "No portfolio FX summary rows available where Auto FX is expected."})
            pass  # [removed] diagnostic CSV write
            return

        rows.append({"Stage": stage, "Check": "auto_fx_summary_df", "Result": "Present", "Detail": f"rows={len(auto_fx_summary_df):,}; cols={' | '.join(map(str, auto_fx_summary_df.columns.tolist()))}"})

        # What does the app itself select as Auto FX?
        try:
            app_subset = _portfolio_subset_from_fx_yes(portfolio_df, auto_fx_summary_df) if callable(globals().get("_portfolio_subset_from_fx_yes")) else pd.DataFrame()
            rows.append({"Stage": stage, "Check": "_portfolio_subset_from_fx_yes output", "Result": "OK", "Detail": f"rows={len(app_subset) if isinstance(app_subset, pd.DataFrame) else 0:,}; cols={' | '.join(map(str, app_subset.columns.tolist())) if isinstance(app_subset, pd.DataFrame) else ''}"})
            if isinstance(app_subset, pd.DataFrame) and not app_subset.empty:
                pass  # [removed] diagnostic CSV write
        except Exception as exc:
            rows.append({"Stage": stage, "Check": "_portfolio_subset_from_fx_yes output", "Result": "Error", "Detail": f"{type(exc).__name__}: {exc}"})

        pcol = _afx_diag_find_col(auto_fx_summary_df, ["Portfolio code", "Portfolio", "PortfolioCode", "portfolio code"])
        hot_key_col = _afx_diag_find_col(hot_df, ["Portfolio code", "Portfolio", "PortfolioCode", "portfolio code"])
        flag_cols = [c for c in auto_fx_summary_df.columns if any(tok in str(c).lower() for tok in ["candidate", "auto", "explained", "fx", "pass", "yes", "match", "status"])]
        rows.append({"Stage": stage, "Check": "FX summary key/flag columns", "Result": "OK", "Detail": f"portfolio_col={pcol or ''}; hot_key_col={hot_key_col or ''}; flag_cols={' | '.join(map(str, flag_cols))}"})

        for c in flag_cols[:20]:
            try:
                rows.append({"Stage": stage, "Check": f"value counts: {c}", "Result": "OK", "Detail": str(auto_fx_summary_df[c].astype(str).str.strip().value_counts(dropna=False).head(30).to_dict())})
            except Exception as exc:
                rows.append({"Stage": stage, "Check": f"value counts: {c}", "Result": "Error", "Detail": f"{type(exc).__name__}: {exc}"})

        if pcol and hot_key_col:
            hot_keys = set(_afx_diag_key_series(hot_df[hot_key_col]).astype(str))
            fx = auto_fx_summary_df.copy()
            fx["_afx_key"] = _afx_diag_key_series(fx[pcol])
            overlap = fx[fx["_afx_key"].isin(hot_keys)].copy()
            rows.append({"Stage": stage, "Check": "Hot vs FX summary overlap", "Result": "OK", "Detail": f"hot_keys={len(hot_keys):,}; fx_summary_keys={fx['_afx_key'].nunique():,}; overlap_rows={len(overlap):,}; overlap_keys={overlap['_afx_key'].nunique() if not overlap.empty else 0:,}"})
            cand = pd.Series([False] * len(overlap), index=overlap.index)
            for c in flag_cols:
                try:
                    cand = cand | _afx_diag_bool_like(overlap[c]).reindex(overlap.index, fill_value=False)
                except Exception:
                    pass
            rows.append({"Stage": stage, "Check": "Hot overlap bool-like candidate count", "Result": "OK", "Detail": f"candidate_rows={int(cand.sum()):,}; non_candidate_rows={int((~cand).sum()) if len(cand) else 0:,}"})
            keep_cols = [c for c in [pcol] + flag_cols + ["_afx_key"] if c in overlap.columns]
            if keep_cols:
                pass  # [removed] diagnostic CSV write

        pass  # [removed] diagnostic CSV write
    except Exception as exc:
        try:
            pass  # [removed] diagnostic CSV write
        except Exception:
            pass


# ========================================================
# v306.14.8 RESTORE AUTO FX DETAIL AFTER POST-HOT REBUILD
# ========================================================
# Rebuilds portfolio FX validation after final Basis Impact Hot/Cold labels are known,
# then refreshes the cached display artefacts used by the Auto explained by FX page.
AUTO_FX_REBUILD_DIAG_CSV = "auto_fx_rebuild_diagnostics_last_run.csv"
AUTO_FX_DETAIL_REFRESH_DIAG_CSV = "auto_fx_detail_refresh_diagnostics_last_run.csv"


def _afx148_df(value) -> pd.DataFrame:
    return value if isinstance(value, pd.DataFrame) else pd.DataFrame()


def _afx148_hot_count(df: pd.DataFrame) -> int:
    if not isinstance(df, pd.DataFrame) or df.empty or "Hot / Cold" not in df.columns:
        return 0
    return int(df["Hot / Cold"].astype(str).str.strip().eq("Hot").sum())


def _afx148_refresh_auto_fx_display_artifacts(bundle: Dict[str, object], stage: str = "") -> Dict[str, object]:
    rows = []
    try:
        if not isinstance(bundle, dict):
            return bundle
        exchange_rate_bundle = bundle.get("exchange_rates", {})
        if not isinstance(exchange_rate_bundle, dict):
            return bundle
        summary_df = _afx148_df(exchange_rate_bundle.get("portfolio_fx_summary_df", pd.DataFrame()))
        rows.append({"Stage": stage, "Check": "FX summary rows before display refresh", "Result": "OK", "Detail": f"summary_rows={len(summary_df):,}"})
        if summary_df.empty:
            bundle["auto_fx_summary_display_df"] = pd.DataFrame()
            bundle["auto_fx_section_frames"] = {}
            pass  # [removed] diagnostic CSV write
            return bundle

        display_df = _prepare_auto_fx_summary_display(bundle, summary_df) if callable(globals().get("_prepare_auto_fx_summary_display")) else summary_df.copy()
        bundle["auto_fx_summary_display_df"] = display_df if isinstance(display_df, pd.DataFrame) else pd.DataFrame()
        section_frames = {}
        for key in ["A", "B", "C", "D", "E"]:
            try:
                section = _auto_fx_section_display_df(bundle["auto_fx_summary_display_df"], key) if callable(globals().get("_auto_fx_section_display_df")) else pd.DataFrame()
                if callable(globals().get("_format_numeric_df_for_display")):
                    section = _format_numeric_df_for_display(section)
                section_frames[key] = section
                rows.append({"Stage": stage, "Check": f"section {key} rows", "Result": "OK", "Detail": f"rows={len(section) if isinstance(section, pd.DataFrame) else 0:,}; cols={' | '.join(map(str, section.columns.tolist())) if isinstance(section, pd.DataFrame) else ''}"})
            except Exception as exc:
                section_frames[key] = pd.DataFrame()
                rows.append({"Stage": stage, "Check": f"section {key} build", "Result": "Error", "Detail": f"{type(exc).__name__}: {exc}"})
        bundle["auto_fx_section_frames"] = section_frames

        # Keep shared waterfall sets aligned with the refreshed FX summary.
        try:
            if callable(globals().get("_hot_resolution_sets")):
                hot_df, auto_fx_df, nil_df, ca_df, unexplained_df = _hot_resolution_sets(bundle, summary_df)
                bundle["hot_resolution_sets"] = {"hot": hot_df, "auto_fx": auto_fx_df, "nil_actual_return": nil_df, "current_account": ca_df, "unexplained": unexplained_df}
                assignments = _afx148_df(bundle.get("tier1_assignments_df", pd.DataFrame()))
                if callable(globals().get("_tier1_count_frame_from_assignments")):
                    bundle["tier1_driver_count_frames"] = {
                        "hot": _tier1_count_frame_from_assignments(hot_df, assignments),
                        "auto_fx": _tier1_count_frame_from_assignments(auto_fx_df, assignments),
                        "nil_actual_return": _tier1_count_frame_from_assignments(nil_df, assignments),
                        "current_account": _tier1_count_frame_from_assignments(ca_df, assignments),
                        "unexplained": _tier1_count_frame_from_assignments(unexplained_df, assignments),
                    }
                rows.append({"Stage": stage, "Check": "refreshed waterfall sets", "Result": "OK", "Detail": f"hot={len(hot_df):,}; auto_fx={len(auto_fx_df):,}; nil={len(nil_df):,}; current_account={len(ca_df):,}; unexplained={len(unexplained_df):,}"})
        except Exception as exc:
            rows.append({"Stage": stage, "Check": "refreshed waterfall sets", "Result": "Warning", "Detail": f"{type(exc).__name__}: {exc}"})

        pass  # [removed] diagnostic CSV write
        return bundle
    except Exception as exc:
        try:
            rows.append({"Stage": stage, "Check": "Auto FX display refresh", "Result": "Error", "Detail": f"{type(exc).__name__}: {exc}"})
            pass  # [removed] diagnostic CSV write
        except Exception:
            pass
        return bundle


def _afx148_rebuild_auto_fx_after_basis_impact(bundle: Dict[str, object], stage: str = "", force: bool = False) -> Dict[str, object]:
    rows = []
    try:
        if not isinstance(bundle, dict):
            return bundle
        try:
            if callable(globals().get("_apply_basis_impact_error_risk_classification_v306_14_5")):
                bundle = _apply_basis_impact_error_risk_classification_v306_14_5(bundle)
        except Exception as exc:
            rows.append({"Stage": stage, "Check": "Basis Impact classifier", "Result": "Warning", "Detail": f"{type(exc).__name__}: {exc}"})

        portfolio_df = _afx148_df(bundle.get("portfolio_df", pd.DataFrame()))
        exchange_rate_bundle = bundle.get("exchange_rates", {})
        if not isinstance(exchange_rate_bundle, dict):
            exchange_rate_bundle = {}
        current_summary = _afx148_df(exchange_rate_bundle.get("portfolio_fx_summary_df", pd.DataFrame()))
        rows.append({"Stage": stage, "Check": "before rebuild", "Result": "OK", "Detail": f"force={bool(force)}; hot_count={_afx148_hot_count(portfolio_df):,}; current_summary_rows={len(current_summary):,}"})

        dar_df = _afx148_df(bundle.get("dar", pd.DataFrame()))
        exchange_df = _afx148_df(exchange_rate_bundle.get("exchange_rate_df", pd.DataFrame()))
        if portfolio_df.empty or dar_df.empty or exchange_df.empty:
            rows.append({"Stage": stage, "Check": "rebuild inputs", "Result": "Missing", "Detail": f"portfolio_rows={len(portfolio_df):,}; dar_rows={len(dar_df):,}; exchange_rate_rows={len(exchange_df):,}"})
            pass  # [removed] diagnostic CSV write
            return _afx148_refresh_auto_fx_display_artifacts(bundle, stage=stage + " / missing rebuild inputs")

        # Rebuild when forced or when the current summary/detail is empty/stale.
        if force or current_summary.empty:
            try:
                fx_tol = float(bundle.get("fx_line_match_tolerance_dollar", 100.0))
            except Exception:
                fx_tol = 100.0
            try:
                summary_df, detail_df, control_df = fx_validation_v172.build_portfolio_fx_validation(
                    dar_df,
                    exchange_df,
                    portfolio_df=portfolio_df,
                    line_match_tolerance_dollar=fx_tol,
                )
                rows.append({"Stage": stage, "Check": "build_portfolio_fx_validation", "Result": "OK", "Detail": f"raw_summary_rows={len(summary_df) if isinstance(summary_df, pd.DataFrame) else 0:,}; raw_detail_rows={len(detail_df) if isinstance(detail_df, pd.DataFrame) else 0:,}; control_rows={len(control_df) if isinstance(control_df, pd.DataFrame) else 0:,}; fx_tolerance={fx_tol}"})
            except Exception as exc:
                rows.append({"Stage": stage, "Check": "build_portfolio_fx_validation", "Result": "Error", "Detail": f"{type(exc).__name__}: {exc}"})
                pass  # [removed] diagnostic CSV write
                return bundle

            try:
                tier1_context_bundle = {
                    "portfolio_df": portfolio_df,
                    "dat": _afx148_df(bundle.get("dat", pd.DataFrame())),
                    "dar": dar_df,
                    "dat_index": bundle.get("dat_index", {}),
                    "dar_index": bundle.get("dar_index", {}),
                    "tier1_assignments_df": _afx148_df(bundle.get("tier1_assignments_df", pd.DataFrame())),
                    "tier1_assignment_diag_df": _afx148_df(bundle.get("tier1_assignment_diag_df", pd.DataFrame())),
                }
                if callable(globals().get("_apply_tier1_driver_assignments_to_fx_summary")):
                    summary_df = _apply_tier1_driver_assignments_to_fx_summary(tier1_context_bundle, summary_df)
            except Exception as exc:
                rows.append({"Stage": stage, "Check": "apply Tier 1 to FX summary", "Result": "Warning", "Detail": f"{type(exc).__name__}: {exc}"})

            exchange_rate_bundle["portfolio_fx_summary_df"] = summary_df if isinstance(summary_df, pd.DataFrame) else pd.DataFrame()
            exchange_rate_bundle["portfolio_fx_detail_df"] = detail_df if isinstance(detail_df, pd.DataFrame) else pd.DataFrame()
            exchange_rate_bundle["portfolio_fx_control_df"] = control_df if isinstance(control_df, pd.DataFrame) else pd.DataFrame()

            before_filter_summary = len(_afx148_df(exchange_rate_bundle.get("portfolio_fx_summary_df", pd.DataFrame())))
            before_filter_detail = len(_afx148_df(exchange_rate_bundle.get("portfolio_fx_detail_df", pd.DataFrame())))
            try:
                if callable(globals().get("_filter_exchange_rate_bundle_to_hot_portfolios")):
                    exchange_rate_bundle = _filter_exchange_rate_bundle_to_hot_portfolios(exchange_rate_bundle, portfolio_df)
            except Exception as exc:
                rows.append({"Stage": stage, "Check": "HOT filter", "Result": "Warning", "Detail": f"{type(exc).__name__}: {exc}"})
            after_summary = len(_afx148_df(exchange_rate_bundle.get("portfolio_fx_summary_df", pd.DataFrame())))
            after_detail = len(_afx148_df(exchange_rate_bundle.get("portfolio_fx_detail_df", pd.DataFrame())))
            rows.append({"Stage": stage, "Check": "after HOT filter", "Result": "OK", "Detail": f"summary_before_filter={before_filter_summary:,}; summary_after_filter={after_summary:,}; detail_before_filter={before_filter_detail:,}; detail_after_filter={after_detail:,}"})

            control_df2 = _afx148_df(exchange_rate_bundle.get("portfolio_fx_control_df", pd.DataFrame()))
            add_control = pd.DataFrame([
                {"Measure": "Auto FX rebuild after Basis Impact", "Value": "Applied v306.14.8"},
                {"Measure": "Auto FX summary rows after HOT filter", "Value": int(after_summary)},
                {"Measure": "Auto FX detail rows after HOT filter", "Value": int(after_detail)},
            ])
            exchange_rate_bundle["portfolio_fx_control_df"] = pd.concat([control_df2, add_control], ignore_index=True, sort=False) if not control_df2.empty else add_control
            bundle["exchange_rates"] = exchange_rate_bundle
        else:
            rows.append({"Stage": stage, "Check": "rebuild skipped", "Result": "OK", "Detail": "Existing portfolio_fx_summary_df had rows; refreshed display artefacts only."})

        pass  # [removed] diagnostic CSV write
        return _afx148_refresh_auto_fx_display_artifacts(bundle, stage=stage + " / after rebuild")
    except Exception as exc:
        try:
            rows.append({"Stage": stage, "Check": "Auto FX rebuild", "Result": "Error", "Detail": f"{type(exc).__name__}: {exc}"})
            pass  # [removed] diagnostic CSV write
        except Exception:
            pass
        return bundle


# Wrap bundle prep and key render paths so FX detail artefacts survive the post-Hot rebuild.
try:
    if callable(globals().get("_prepare_out_dashboard_bundle")) and not getattr(globals().get("_prepare_out_dashboard_bundle"), "_afx148_wrapped", False):
        _prepare_out_dashboard_bundle_afx148_original = _prepare_out_dashboard_bundle
        def _prepare_out_dashboard_bundle(*args, **kwargs):
            bundle = _prepare_out_dashboard_bundle_afx148_original(*args, **kwargs)
            return _afx148_rebuild_auto_fx_after_basis_impact(bundle, stage="after _prepare_out_dashboard_bundle", force=True)
        _prepare_out_dashboard_bundle._afx148_wrapped = True
except Exception:
    pass

try:
    if callable(globals().get("_render_portfolio_fx_validation_tab")) and not getattr(globals().get("_render_portfolio_fx_validation_tab"), "_afx148_wrapped", False):
        _render_portfolio_fx_validation_tab_afx148_original = _render_portfolio_fx_validation_tab
        def _render_portfolio_fx_validation_tab(bundle: Dict[str, object]):
            try:
                bundle = _afx148_rebuild_auto_fx_after_basis_impact(bundle, stage="before Auto FX tab render", force=False)
            except Exception:
                pass
            return _render_portfolio_fx_validation_tab_afx148_original(bundle)
        _render_portfolio_fx_validation_tab._afx148_wrapped = True
except Exception:
    pass


# ========================================================
# v328 - EAGER WARM-UP: fire every Portfolio Numbers check at load finish
# ========================================================
# On load finish the app lands on Portfolio Numbers -> Reconciliation export. For
# that export (and every sub-section) to be complete/current WITHOUT the user
# clicking through each panel, this builds every check frame ONCE at bundle prep,
# reusing the export module's shared, idempotent, parallel `ensure_all_check_frames`
# (single source of truth - the export and the on-screen panels therefore show
# identical numbers). It is the OUTERMOST prepare wrapper (defined last), so it runs
# AFTER the full prepare chain (BM names v322, excluded codes v326, GAV v327,
# Basis-Impact Hot/Cold v306.14.x, Auto-FX rebuild v306.14.8) has populated
# portfolio_df - the checks then see the final, workbook-scoped population.
#
# Cost is paid ONCE per date (the prepared bundle is session-cached), and the
# independent checks run on threads (I/O-bound -> GIL released), so the added
# wall-time is ~the slowest single check, not the sum. Fully guarded and idempotent:
# a render that already built a frame is reused (no recompute), and any failure
# leaves the bundle exactly as prepared. The v327 GAV seed still runs first inside
# the shared routine (universe + GAV before the rest), so the return-check NAV=0
# gate always has data.
try:
    from bnp_helpers_reconciliation_export import ensure_all_check_frames as _ensure_all_check_frames_v328
except Exception:
    _ensure_all_check_frames_v328 = None


def _eager_warm_all_checks_v328(bundle):
    try:
        if not isinstance(bundle, dict) or not callable(globals().get("_ensure_all_check_frames_v328")):
            return bundle
        if bundle.get("_all_check_frames_ready"):
            return bundle
        pf = bundle.get("portfolio_df")
        if not isinstance(pf, pd.DataFrame) or pf.empty:
            return bundle
        with _deep_timer(bundle, "Post-prepare (gap)", "v328 eager warm-up (all checks)"):
            _ensure_all_check_frames_v328(bundle, parallel=True)
    except Exception:
        pass
    return bundle


try:
    if callable(globals().get("_prepare_out_dashboard_bundle")) and not getattr(globals().get("_prepare_out_dashboard_bundle"), "_eager_warm_v328_wrapped", False):
        _prepare_out_dashboard_bundle_pre_eager_v328 = _prepare_out_dashboard_bundle
        def _prepare_out_dashboard_bundle(*args, **kwargs):
            bundle = _prepare_out_dashboard_bundle_pre_eager_v328(*args, **kwargs)
            return _eager_warm_all_checks_v328(bundle)
        _prepare_out_dashboard_bundle._eager_warm_v328_wrapped = True
except Exception:
    pass


if __name__ == "__main__":
    main()


# ========================================================
# v306.13.8 STATIC DATA CONFIG BOOTSTRAP
# ========================================================
# Static Data.xlsx is expected to sit beside this Python file. It controls root
# paths, source report definitions, BNP keyword contracts, exclusions and
# business thresholds. Existing Python constants remain as fallbacks.
STATIC_DATA_BUNDLE = {"tables": {}}
STATIC_DATA_EXCEPTION_DF = pd.DataFrame()
STATIC_DATA_VALIDATION_DF = pd.DataFrame()
STATIC_DATA_META_DF = pd.DataFrame()
STATIC_DATA_GLOBAL_OVERRIDE_DF = pd.DataFrame()


def _apply_static_data_config_v306_13_8() -> None:
    global STATIC_DATA_BUNDLE, STATIC_DATA_EXCEPTION_DF, STATIC_DATA_VALIDATION_DF, STATIC_DATA_META_DF, STATIC_DATA_GLOBAL_OVERRIDE_DF
    global ROOT_FOLDER, ARC_ROOT_FOLDER, ARC_ARCHIVE_ROOT, EXCHANGE_RATES_ROOT_FOLDER, CACHE_DIR
    global REQUIRED_FILE_KEYWORDS, OPTIONAL_FILE_KEYWORDS, EXCLUDED_FILENAME_TOKENS, HEADER_CONTRACTS
    global DEFAULT_EXCLUDE_AMOUNT, DEFAULT_CURRENT_ACCOUNT_DOMINANCE_THRESHOLD_PCT, NIL_ACTUAL_RETURN_ZERO_TOLERANCE_PP
    if _load_static_data_v306_13_8 is None:
        STATIC_DATA_EXCEPTION_DF = pd.DataFrame([{"Severity": "Warning", "Check": "StaticDataImport", "Detail": "bnp_helpers_static_data.py not available; using Python defaults."}])
        return
    try:
        STATIC_DATA_BUNDLE = _load_static_data_v306_13_8(app_file_path=__file__)
        STATIC_DATA_EXCEPTION_DF = STATIC_DATA_BUNDLE.get("static_exception_df", pd.DataFrame())
        STATIC_DATA_VALIDATION_DF = STATIC_DATA_BUNDLE.get("static_validation_df", pd.DataFrame())
        STATIC_DATA_META_DF = STATIC_DATA_BUNDLE.get("static_meta_df", pd.DataFrame())
        rows = []

        def _set_path_global(global_name: str, config_key: str) -> None:
            old_val = globals().get(global_name, "")
            new_val = _static_get_config_value_v306_13_8(STATIC_DATA_BUNDLE, config_key, old_val) if _static_get_config_value_v306_13_8 else old_val
            if new_val is not None and str(new_val).strip() != "":
                globals()[global_name] = str(new_val)
            rows.append({"GlobalName": global_name, "ConfigKey": config_key, "OldValue": old_val, "NewValue": globals().get(global_name, ""), "Changed": str(old_val) != str(globals().get(global_name, ""))})

        _set_path_global("ROOT_FOLDER", "bnp_reports_root")
        _set_path_global("ARC_ROOT_FOLDER", "arc_root")
        _set_path_global("ARC_ARCHIVE_ROOT", "arc_archive_root")
        _set_path_global("EXCHANGE_RATES_ROOT_FOLDER", "exchange_rates_root")
        _set_path_global("CACHE_DIR", "cache_dir")
        _set_path_global("LOCAL_PRICE_VALIDATION_TEMPLATE_DEFAULT", "local_price_validation_template")
        # v363 FIX: Static Data now stores a BARE FILENAME for this key (the user
        # keeps the template alongside the .py files, not at a personal machine
        # path), but _set_path_global() above does a straight substitution with no
        # path-joining. An already-absolute configured value (e.g. a personal
        # override) is left untouched; a bare/relative filename is resolved
        # against this file's own folder - the same folder Static Data.xlsx is
        # loaded from - so it resolves correctly regardless of the Streamlit
        # process's working directory.
        try:
            _tpl_val = str(globals().get("LOCAL_PRICE_VALIDATION_TEMPLATE_DEFAULT", "") or "")
            if _tpl_val and not os.path.isabs(_tpl_val):
                globals()["LOCAL_PRICE_VALIDATION_TEMPLATE_DEFAULT"] = str(Path(__file__).resolve().parent / _tpl_val)
        except Exception:
            pass

        try:
            DEFAULT_EXCLUDE_AMOUNT = float(_static_get_threshold_value_v306_13_8(STATIC_DATA_BUNDLE, "default_exclude_amount", DEFAULT_EXCLUDE_AMOUNT))
        except Exception:
            pass
        try:
            DEFAULT_CURRENT_ACCOUNT_DOMINANCE_THRESHOLD_PCT = float(_static_get_threshold_value_v306_13_8(STATIC_DATA_BUNDLE, "current_account_dominance_threshold_pct", DEFAULT_CURRENT_ACCOUNT_DOMINANCE_THRESHOLD_PCT))
        except Exception:
            pass
        try:
            NIL_ACTUAL_RETURN_ZERO_TOLERANCE_PP = float(_static_get_threshold_value_v306_13_8(STATIC_DATA_BUNDLE, "nil_actual_return_zero_tolerance_pp", NIL_ACTUAL_RETURN_ZERO_TOLERANCE_PP))
        except Exception:
            pass

        if _static_build_ingestion_config_v306_13_8:
            cfg = _static_build_ingestion_config_v306_13_8(STATIC_DATA_BUNDLE, source_group="BNP")
            if cfg.get("required_file_keywords"):
                REQUIRED_FILE_KEYWORDS = list(cfg.get("required_file_keywords"))
            if cfg.get("optional_file_keywords"):
                OPTIONAL_FILE_KEYWORDS = list(cfg.get("optional_file_keywords"))
            if cfg.get("excluded_filename_tokens") is not None:
                EXCLUDED_FILENAME_TOKENS = list(cfg.get("excluded_filename_tokens"))
            if cfg.get("header_contracts"):
                HEADER_CONTRACTS = dict(cfg.get("header_contracts"))

        try:
            os.makedirs(CACHE_DIR, exist_ok=True)
        except Exception:
            pass
        STATIC_DATA_GLOBAL_OVERRIDE_DF = pd.DataFrame(rows)
    except Exception as exc:
        STATIC_DATA_EXCEPTION_DF = pd.DataFrame([{"Severity": "Error", "Check": "StaticDataBootstrap", "Detail": f"{type(exc).__name__}: {exc}"}])


_apply_static_data_config_v306_13_8()
