# -*- coding: utf-8 -*-
"""
bnp_helpers_fdv_enrichment.py  (v343 - vectorised, named-column FDV lookup/merge)

The DetailedValuationFDV reports carry 92 columns of holdings-level detail that the
unexplained sections (built from DAssetReturn) don't currently show. This module
attaches a curated, validation-focused subset to any dataframe that has an
'Asset Code' column, so that when the unexplained candidates / prompt packs are
loaded into Copilot there is far more context to validate a price/return anomaly.

v343 CHANGES (Part B - align FDV with the standard BNP report load path)
  * NAMED-COLUMN resolution replaces hard-coded positional indices (7, 13, 8...).
    Verified against all six live FDV files (3 portfolios x T / T-1): headers are
    identical and 92-wide, but named lookup means a future BNP column reorder can't
    silently break the mapping.
  * QUOTE-AWARE, VECTORISED parse via pandas.read_csv (the files are quoted and can
    carry embedded commas), replacing the row-by-row csv.reader dict build.
  * SINGLE df.merge enrich replaces the 15x per-column .map(lambda ...) loop.
  * FIRST-WINS preserved: the lookup is de-duplicated (keep first) BEFORE the merge,
    so enriched row counts are IDENTICAL to the legacy dict (which used setdefault).
    This matters because ~8% of SecurityCode keys repeat within a single file.

JOIN KEY (verified against the real FDV samples)
    DAssetReturn 'Asset Code'  ->  FDV 'SecurityCode'   (BNP's canonical security id,
    100% populated). SEDOL / ISIN are secondary fallbacks (only ~66% / ~83%
    populated). Matching is security-code first, then SEDOL, then ISIN.

CURATED COLUMNS (chosen after reviewing all 92 for validation value)
  Identity:      SecurityCode, SecurityLongName, ISIN, BloombergTicker
  Classification:AssetClassName, AssetSubClassName, GICSSectorName, CountryName
  Pricing:       LocalCurrency, LocalMarketPrice, LocalLastPrice, MarketPriceDate
  Detail:        CreditRating, MaturityDate, Portfolio%TotalMV
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple
import os
import pandas as pd

FDV_ENRICH_VERSION = "v344"
# v344: added GLGroupName to the shared source-column union so the price-integrity
# module's material-movement population rule (bnp_helpers_price_integrity v314) can
# read it from the single cached FDV frame instead of a separate network scan.

# Source FDV column NAME -> curated output column name. Verified against the live
# 92-column FDV header (all six files identical).
FDV_FIELD_NAMES: Dict[str, str] = {
    "SecurityCode":      "FDV Security Code",
    "SecurityLongName":  "FDV Security Long Name",
    "ISIN":              "FDV ISIN",
    "BloombergTicker":   "FDV Bloomberg Ticker",
    "AssetClassName":    "FDV Asset Class",
    "AssetSubClassName": "FDV Asset Sub Class",
    "GICSSectorName":    "FDV GICS Sector",
    "CountryName":       "FDV Country",
    "LocalCurrency":     "FDV Local Currency",
    "LocalMarketPrice":  "FDV Local Market Price",
    "LocalLastPrice":    "FDV Local Last Price",
    "MarketPriceDate":   "FDV Market Price Date",
    "CreditRating":      "FDV Credit Rating",
    "MaturityDate":      "FDV Maturity Date",
    "Portfolio%TotalMV": "FDV Portfolio % Total MV",
}
# Ordered curated output labels (stable column order for downstream display/CSV).
FDV_OUTPUT_COLUMNS: List[str] = list(FDV_FIELD_NAMES.values())

# Legacy positional index -> output label. Retained ONLY as a fallback for a file
# that somehow arrives without a usable header row; the named path is preferred.
FDV_FIELDS = {
    7:  "FDV Security Code",
    13: "FDV Security Long Name",
    8:  "FDV ISIN",
    12: "FDV Bloomberg Ticker",
    16: "FDV Asset Class",
    18: "FDV Asset Sub Class",
    65: "FDV GICS Sector",
    61: "FDV Country",
    19: "FDV Local Currency",
    24: "FDV Local Market Price",
    47: "FDV Local Last Price",
    82: "FDV Market Price Date",
    63: "FDV Credit Rating",
    20: "FDV Maturity Date",
    59: "FDV Portfolio % Total MV",
}

# Source key columns, in priority order (first match wins on enrich).
FDV_KEY_NAMES: List[str] = ["SecurityCode", "SEDOL", "ISIN"]
FDV_INTERNAL_KEY = "_fdvkey"

# ============================================================
# v345: SHARED FDV FRAME - single source of truth
# ------------------------------------------------------------
# The FDV files (~59 MB across 6 files, on a G:/ network share) were previously read
# 4-5 SEPARATE times per cold load - once each by: UUT base build (load_fdv_holdings),
# UUT scope (load_uut_scope_from_fdv), price-integrity stale + material movement
# (_load_fdv_prices x2), and the enrichment lookup. Over the network each row-by-row
# csv.reader pass cost ~11s/fileset, so the same bytes were re-read ~5x = the bulk of
# the ~114s cold load.
#
# v345 reads each physical FDV file from G:/ EXACTLY ONCE per process via a vectorised,
# quote-aware pandas.read_csv, caches the resulting DataFrame keyed by (resolved path,
# size, mtime), and every consumer now slices these cached frames instead of
# re-scanning the network. This is the single source of truth.
#
# The shared frame carries the UNION of every column any consumer needs (named), so
# UUT (price/MV/subclass), price-integrity (price/weight) and enrichment (curated 15)
# all derive their views from it.
# ============================================================

# Union of source column NAMES needed across ALL FDV consumers.
FDV_SHARED_SOURCE_COLUMNS: List[str] = list(dict.fromkeys(
    list(FDV_FIELD_NAMES.keys()) + FDV_KEY_NAMES + [
        "PortfolioCode", "ExternalPortfolioCode", "AssetSubClassName",
        "LocalMarketPrice", "MarketValue", "Portfolio%TotalMV",
        "GLGroupName",  # v344: material-movement population rule (price_integrity v314)
    ]
))

# Per-file cache: resolved_path -> {"sig": (size, mtime), "df": DataFrame}
_FDV_FILE_CACHE: Dict[str, Dict[str, Any]] = {}
# stats so the app can surface how many network reads were saved
_FDV_CACHE_STATS: Dict[str, int] = {"reads": 0, "hits": 0}

# ============================================================
# v351: FDV PICKLE-PERSIST (the BNP-report cache mechanism, applied to FDV)
# ------------------------------------------------------------
# The v349/v350 logs proved the ~23s cold-load cost is the FIRST read of the ~59 MB of
# FDV CSVs over G:/. Local parse is <1s, so the cost is pure network I/O - and it is
# UNAVOIDABLE on the first read of a NEW date. The other BNP reports pay the same ~22s
# cold, but feel fast because they ride a persistent PICKLE cache (keyed by folder
# fingerprint) that makes REOPENS ~1s. FDV was loaded OUTSIDE that cache, so it re-read
# G:/ every time. v350 tried a separate Parquet + copy-local layer; copy-local made the
# first read WORSE (64s) on this bandwidth-capped share, and the parquet layer did not
# reliably engage on reopen. v351 removes BOTH and instead persists the parsed FDV
# frame as a local PICKLE keyed by (resolved path, size, mtime) - the exact mechanism
# the BNP reports use - so a reopen (even after a restart) reads the pickle (~0.05s)
# instead of re-reading G:/. Parity-preserving: the pickled frame is byte-identical to
# the direct read.
# ============================================================
_FDV_PICKLE_DIR: Dict[str, str] = {"dir": ""}
_FDV_PERSIST_STATS: Dict[str, int] = {"pickle_hits": 0, "pickle_writes": 0, "network_reads": 0}


def set_fdv_pickle_dir(path: str) -> None:
    """Point the persisted (pickle) FDV cache at a local folder (the app sets this to
    the same .bnp_manifest_cache folder the BNP source pickle uses). Created if absent.
    If never set, pickle-persist is disabled and only the in-process cache applies."""
    try:
        p = str(path or "").strip()
        if p:
            os.makedirs(p, exist_ok=True)
            _FDV_PICKLE_DIR["dir"] = p
    except Exception:
        _FDV_PICKLE_DIR["dir"] = ""


def fdv_persist_stats() -> Dict[str, int]:
    """Pickle-persist counters so the app can report the reopen win: pickle_hits are
    reopens served locally; network_reads are genuine first reads of a new file."""
    return dict(_FDV_PERSIST_STATS)


def _fdv_pickle_path_for(resolved: str, sig: tuple) -> str:
    d = _FDV_PICKLE_DIR.get("dir") or ""
    if not d:
        return ""
    import hashlib as _hl
    key = _hl.md5(f"{resolved}|{sig[0]}|{sig[1]}".encode("utf-8", "replace")).hexdigest()
    return os.path.join(d, f"fdvcache_{key}.pkl")


def _fdv_first_existing(path: str) -> str:
    """Resolve an FDV path, trying a G:/ <-> \\\\hq.local\\Corp UNC variant (mirrors the
    resolver in bnp_helpers_uut) so a single canonical key is cached regardless of how
    the path was expressed."""
    p = str(path or "").strip()
    if not p:
        return ""
    bs = chr(92)
    cands = [p]
    if p.upper().startswith("G:" + bs):
        cands.append(bs + bs + "hq.local" + bs + "Corp" + bs + p[3:].lstrip(bs))
    for c in cands:
        try:
            if c and os.path.exists(c):
                return c
        except Exception:
            continue
    return p if os.path.exists(p) else ""


def _fdv_file_signature(resolved: str) -> tuple:
    try:
        stt = os.stat(resolved)
        return (int(stt.st_size), int(stt.st_mtime))
    except Exception:
        return (0, 0)


def _fdv_parse_csv(csv_path: str) -> pd.DataFrame:
    """Vectorised, quote-aware parse of one FDV CSV into the shared named-column frame.
    This is the SAME parse used since v345 - Parquet/copy-local only change WHERE the
    bytes come from, never the parsed result (parity preserved)."""
    wanted = set(FDV_SHARED_SOURCE_COLUMNS)
    df = pd.read_csv(
        csv_path,
        dtype=str,
        encoding="latin-1",
        usecols=lambda c: c in wanted,
        keep_default_na=False,
        na_filter=False,
        low_memory=False,
    )
    if df is None:
        df = pd.DataFrame(columns=FDV_SHARED_SOURCE_COLUMNS)
    for col in FDV_SHARED_SOURCE_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    # v350: return a CANONICAL column order so the network-parse path, the Parquet
    # write, and the Parquet-read path are byte-identical (parity). All consumers use
    # NAMED column access, so fixing the order changes nothing functionally.
    return df[FDV_SHARED_SOURCE_COLUMNS]


def _load_fdv_file_cached(path: str) -> pd.DataFrame:
    """Read ONE FDV file into the shared named-column frame, reading the network file
    AT MOST ONCE per (path,size,mtime). Order: in-process cache -> local PICKLE ->
    direct network parse; then persist to pickle. Empty frame on failure.

    v351: pickle-persist (the BNP-report cache mechanism) replaces the v350 Parquet +
    copy-local layer. A reopen of a date already loaded reads the local pickle (~0.05s)
    instead of re-reading the file over G:/."""
    resolved = _fdv_first_existing(path) or str(path or "")
    if not resolved or not os.path.exists(resolved):
        return pd.DataFrame(columns=FDV_SHARED_SOURCE_COLUMNS)
    sig = _fdv_file_signature(resolved)

    # 1) in-process cache
    hit = _FDV_FILE_CACHE.get(resolved)
    if isinstance(hit, dict) and hit.get("sig") == sig and isinstance(hit.get("df"), pd.DataFrame):
        _FDV_CACHE_STATS["hits"] = _FDV_CACHE_STATS.get("hits", 0) + 1
        return hit["df"]

    # 2) persisted PICKLE cache (reopen win, incl. after restart)
    pk = _fdv_pickle_path_for(resolved, sig)
    if pk and os.path.exists(pk):
        try:
            df = pd.read_pickle(pk)
            if isinstance(df, pd.DataFrame):
                for col in FDV_SHARED_SOURCE_COLUMNS:
                    if col not in df.columns:
                        df[col] = ""
                df = df[FDV_SHARED_SOURCE_COLUMNS]
                _FDV_FILE_CACHE[resolved] = {"sig": sig, "df": df}
                _FDV_PERSIST_STATS["pickle_hits"] = _FDV_PERSIST_STATS.get("pickle_hits", 0) + 1
                _FDV_CACHE_STATS["hits"] = _FDV_CACHE_STATS.get("hits", 0) + 1
                return df
        except Exception:
            pass  # corrupt/unavailable -> re-read source

    # 3) direct network parse - the expensive path (first read of this file version)
    try:
        df = _fdv_parse_csv(resolved)
    except Exception:
        df = pd.DataFrame(columns=FDV_SHARED_SOURCE_COLUMNS)
    _FDV_FILE_CACHE[resolved] = {"sig": sig, "df": df}
    _FDV_CACHE_STATS["reads"] = _FDV_CACHE_STATS.get("reads", 0) + 1
    _FDV_PERSIST_STATS["network_reads"] = _FDV_PERSIST_STATS.get("network_reads", 0) + 1

    # 4) persist to pickle for next time (best-effort; never fail the read)
    if pk and isinstance(df, pd.DataFrame) and not df.empty:
        try:
            df.to_pickle(pk)
            _FDV_PERSIST_STATS["pickle_writes"] = _FDV_PERSIST_STATS.get("pickle_writes", 0) + 1
        except Exception:
            pass
    return df


def load_fdv_frame(paths: Any) -> pd.DataFrame:
    """v345 single-source-of-truth loader. Given one or more FDV paths, return a single
    vectorised named-column DataFrame (union of all consumer columns), reading each
    physical file from the network AT MOST ONCE per process. All FDV consumers (UUT
    base, UUT scope, price-integrity, enrichment) call this instead of re-scanning."""
    plist = paths if isinstance(paths, (list, tuple)) else [paths]
    frames: List[pd.DataFrame] = []
    seen = set()
    for p in plist:
        resolved = _fdv_first_existing(p) or str(p or "")
        if not resolved or resolved in seen:
            continue
        seen.add(resolved)
        df = _load_fdv_file_cached(p)
        if isinstance(df, pd.DataFrame) and not df.empty:
            frames.append(df)
    if not frames:
        return pd.DataFrame(columns=FDV_SHARED_SOURCE_COLUMNS)
    return pd.concat(frames, ignore_index=True, sort=False)


def fdv_cache_stats() -> Dict[str, int]:
    """Return {'reads':N, 'hits':M, 'files':K} so the app can report network reads saved."""
    s = dict(_FDV_CACHE_STATS)
    s["files"] = len(_FDV_FILE_CACHE)
    return s


def clear_fdv_cache(drop_persisted: bool = False, **_legacy) -> None:
    """Drop the in-process per-file FDV cache (e.g. on a forced source refresh). If
    drop_persisted, also delete the on-disk PICKLE cache so a refresh truly re-reads
    G:/. (**_legacy accepts the old drop_parquet kwarg harmlessly.)"""
    if not drop_persisted and _legacy.get("drop_parquet"):
        drop_persisted = True
    try:
        _FDV_FILE_CACHE.clear()
        _FDV_CACHE_STATS.update({"reads": 0, "hits": 0})
        for k in _FDV_PERSIST_STATS:
            _FDV_PERSIST_STATS[k] = 0
    except Exception:
        pass
    if drop_persisted:
        d = _FDV_PICKLE_DIR.get("dir") or ""
        if d and os.path.isdir(d):
            try:
                for fn in os.listdir(d):
                    if fn.startswith("fdvcache_") and fn.endswith(".pkl"):
                        try:
                            os.remove(os.path.join(d, fn))
                        except Exception:
                            pass
            except Exception:
                pass


def _norm_series(s: pd.Series) -> pd.Series:
    """Vectorised normaliser: uppercase, keep alphanumerics only. Mirrors the legacy
    scalar _norm so keys join identically."""
    return (
        s.astype(str)
         .str.upper()
         .str.replace(r"[^0-9A-Z]", "", regex=True)
         .str.strip()
    )


def _norm(v) -> str:
    """Scalar normaliser retained for backward compatibility / self-test."""
    return "".join(ch for ch in str(v or "").upper().strip() if ch.isalnum())


def _read_one_fdv(path: str) -> Optional[pd.DataFrame]:
    """Quote-aware, vectorised read of a single FDV CSV, returning only the curated
    source columns plus the key columns (by NAME). Returns None on failure."""
    try:
        wanted = list(dict.fromkeys(list(FDV_FIELD_NAMES.keys()) + FDV_KEY_NAMES))
        # dtype=str keeps codes/prices exactly as issued (no float coercion of IDs);
        # engine="c" + quoting default handles the embedded-comma quoted fields.
        df = pd.read_csv(
            path,
            dtype=str,
            encoding="latin-1",
            usecols=lambda c: c in wanted,
            keep_default_na=False,
            na_filter=False,
            low_memory=False,
        )
        if df is None or df.empty:
            return None
        # ensure every expected source column exists (blank if the file omitted one)
        for col in wanted:
            if col not in df.columns:
                df[col] = ""
        return df
    except Exception:
        return None


def load_fdv_enrichment_lookup(fdv_paths: Any) -> pd.DataFrame:
    """Build a de-duplicated lookup FRAME from one or more FDV CSVs.

    Returns a DataFrame indexed by the normalised join key (``_fdvkey``) with the 15
    curated FDV output columns. The frame is keyed by SecurityCode, then SEDOL, then
    ISIN (all normalised), with FIRST occurrence winning - identical semantics to the
    legacy dict's setdefault, so enrich row counts are unchanged.

    Pass the current-day (T) files first so they win over T-1 on shared keys.
    """
    # v345: read via the shared single-source-of-truth frame so this enrichment build
    # reuses the SAME per-file cache as UUT and price-integrity (no extra network read).
    empty = pd.DataFrame(columns=[FDV_INTERNAL_KEY] + FDV_OUTPUT_COLUMNS).set_index(FDV_INTERNAL_KEY)
    raw = load_fdv_frame(fdv_paths)
    if not isinstance(raw, pd.DataFrame) or raw.empty:
        return empty

    # rename curated source columns -> output labels
    ren = raw.rename(columns=FDV_FIELD_NAMES)
    # keep a stable per-row order so "first wins" is deterministic across the three
    # key passes (row order = file order passed in = T before T-1).
    ren = ren.reset_index(drop=True)
    ren["_row_order"] = range(len(ren))

    key_frames: List[pd.DataFrame] = []
    for pri, key_col in enumerate(FDV_KEY_NAMES):
        if key_col not in raw.columns:
            continue
        k = _norm_series(raw[key_col])
        block = ren.copy()
        block[FDV_INTERNAL_KEY] = k.values
        block["_key_priority"] = pri  # SecurityCode=0, SEDOL=1, ISIN=2
        block = block[block[FDV_INTERNAL_KEY] != ""]
        key_frames.append(block)

    if not key_frames:
        return empty

    stacked = pd.concat(key_frames, ignore_index=True, sort=False)
    # FIRST WINS: prefer key priority (security > sedol > isin), then original row
    # order (T before T-1, first occurrence in file).
    stacked = stacked.sort_values(["_key_priority", "_row_order"], kind="stable")
    stacked = stacked.drop_duplicates(subset=[FDV_INTERNAL_KEY], keep="first")

    lookup = stacked.set_index(FDV_INTERNAL_KEY)[FDV_OUTPUT_COLUMNS].copy()
    return lookup


def _coerce_lookup_frame(fdv: Any) -> pd.DataFrame:
    """Accept a prebuilt lookup frame, a legacy dict, or path(s), and return a lookup
    DataFrame indexed by the normalised key. Keeps backward compatibility."""
    if isinstance(fdv, pd.DataFrame):
        if fdv.index.name == FDV_INTERNAL_KEY:
            return fdv
        # a frame handed in without our index - try to use it as-is if it has the key
        if FDV_INTERNAL_KEY in fdv.columns:
            return fdv.set_index(FDV_INTERNAL_KEY)
        return fdv
    if isinstance(fdv, dict):
        # legacy dict {key: {out_col: value}} -> frame
        if not fdv:
            return pd.DataFrame(columns=FDV_OUTPUT_COLUMNS)
        frame = pd.DataFrame.from_dict(fdv, orient="index")
        for col in FDV_OUTPUT_COLUMNS:
            if col not in frame.columns:
                frame[col] = ""
        frame = frame[FDV_OUTPUT_COLUMNS]
        frame.index.name = FDV_INTERNAL_KEY
        return frame
    # paths
    return load_fdv_enrichment_lookup(fdv)


def enrich_with_fdv(df: pd.DataFrame, fdv: Any,
                    *, code_col: str = "Asset Code") -> pd.DataFrame:
    """Attach the curated FDV columns to `df` via a SINGLE vectorised merge, joining
    df[code_col] -> FDV SecurityCode (SEDOL/ISIN fallback baked into the lookup).
    `fdv` may be a prebuilt lookup frame, a legacy dict, a list of FDV paths, or a
    single path. Rows with no FDV match get blanks. Display/enrichment only - existing
    columns are untouched and row count/order are preserved."""
    if not isinstance(df, pd.DataFrame) or df.empty or code_col not in df.columns:
        return df
    lookup = _coerce_lookup_frame(fdv)
    if not isinstance(lookup, pd.DataFrame) or lookup.empty:
        return df

    out = df.copy()
    join_key = _norm_series(out[code_col])
    # single merge on the normalised key; preserve df's original order via a temp col.
    out["_fdv_join"] = join_key.values
    merged = out.merge(
        lookup, left_on="_fdv_join", right_index=True, how="left", sort=False,
    )
    merged = merged.drop(columns=["_fdv_join"], errors="ignore")
    # fill unmatched with blanks and guarantee all curated columns exist in order.
    for col in FDV_OUTPUT_COLUMNS:
        if col not in merged.columns:
            merged[col] = ""
    merged[FDV_OUTPUT_COLUMNS] = merged[FDV_OUTPUT_COLUMNS].fillna("")
    # restore original index/order
    merged.index = out.index
    return merged


def enrichment_coverage(df: pd.DataFrame) -> Dict[str, Any]:
    """How many rows got an FDV match (any curated column populated)."""
    if not isinstance(df, pd.DataFrame) or df.empty or "FDV Security Code" not in df.columns:
        return {"rows": 0, "matched": 0, "pct": 0.0}
    matched = int((df["FDV Security Code"].astype(str).str.strip() != "").sum())
    n = len(df)
    return {"rows": n, "matched": matched, "pct": round(100.0 * matched / n, 1) if n else 0.0}


if __name__ == "__main__":
    import glob
    print(f"[{FDV_ENRICH_VERSION}] FDV enrichment self-test (vectorised named-column)")
    fdv = sorted(glob.glob("/mnt/user-data/uploads/*DetailedValuationFDV*.csv")) or \
          sorted(glob.glob("*DetailedValuationFDV*.csv"))
    if not fdv:
        print("  (no FDV files present)"); raise SystemExit
    t_files = [p for p in fdv if "-310726-" in p] or fdv
    lookup = load_fdv_enrichment_lookup(t_files)
    print(f"  FDV files (T): {len(t_files)} | lookup keys: {len(lookup):,} | columns: {len(FDV_OUTPUT_COLUMNS)}")
    # pull a few real security codes and prove the round-trip
    sample = _read_one_fdv(t_files[0])
    sample_codes = [c for c in sample["SecurityCode"].tolist() if str(c).strip()][:5]
    test = pd.DataFrame({"Asset Code": sample_codes})
    enr = enrich_with_fdv(test, lookup)
    cols = ["Asset Code", "FDV Security Long Name", "FDV Asset Sub Class", "FDV Bloomberg Ticker", "FDV Local Market Price", "FDV Market Price Date"]
    print(enr[[c for c in cols if c in enr.columns]].to_string(index=False))
    cov = enrichment_coverage(enr)
    print(f"  coverage: {cov['matched']}/{cov['rows']} = {cov['pct']}%")
    assert cov["matched"] == len(test), "all sample security codes should match"
    print("  OK - FDV detail attaches by Asset Code -> SecurityCode (single merge)")
