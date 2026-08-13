# -*- coding: utf-8 -*-
"""
bnp_helpers_uut.py  (v311 - UUT look-through / Advisor-UUT Check)
v311a FIX: group DetailedValuationFDV files by the DATE TOKEN in the filename so
that, with multiple filesets per day, the two most-recent files can no longer be
mistaken for T and T-1 (the bug that left every Previous Price blank -> Weighted
UUT Return 0 -> every portfolio falsely "Check").

CORE (per underlying holding), from the decoded workbook formulas:
    Price Return    = CurrentPrice(T) / PreviousPrice(T-1) - 1        (LocalMarketPrice)
    Weight          = holding MarketValue / portfolio total FDV
    Weighted Return = Price Return * Weight
    Weighted UUT Return = SUM over the portfolio's holdings
    Variance        = Unison Return - Weighted UUT Return  ->  Breach at tolerance

DATA CONTRACTS (validated to 7dp vs the workbook 'Book2.xlsx' anchor, 31/30 Jul):
    DetailedValuationFDV, comma CSV, single header:
        idx3 PortfolioCode  idx4 ExternalPortfolioCode  idx7 SecurityCode
        idx24 LocalMarketPrice  idx32 MarketValue
    Filename date token: '...FDV_<FILESET>-DDMMYY-...' (e.g. -310726- = 31 Jul).
    Price Return matches on (PortfolioCode, SecurityCode) across the two days,
    concatenating ALL filesets for each date.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import csv, os, re, glob, time
import pandas as pd

# v345: consume the shared single-source-of-truth FDV frame so UUT no longer
# re-scans the ~59 MB of FDV files over G:/ (they are read once per process and
# cached in bnp_helpers_fdv_enrichment). Guarded so the module still imports if the
# FDV helper is unavailable (readers fall back to their original per-file path).
try:
    from bnp_helpers_fdv_enrichment import load_fdv_frame as _shared_load_fdv_frame_v345
except Exception:
    _shared_load_fdv_frame_v345 = None


def _num_series_v345(s: pd.Series) -> pd.Series:
    """Vectorised equivalent of _num: strip commas/$/space, treat (x) as -x, coerce to
    float (unparseable -> NaN, which matches _num's None in a float column)."""
    txt = (s.astype(str)
             .str.replace(",", "", regex=False)
             .str.replace("$", "", regex=False)
             .str.strip())
    neg = txt.str.startswith("(") & txt.str.endswith(")")
    txt = txt.mask(neg, "-" + txt.str.slice(1, -1))
    return pd.to_numeric(txt, errors="coerce")

# ============================================================
# v344: self-contained internal timing sink for the Advisor-UUT build.
# The ~24s Advisor-UUT render is the app's biggest render hotspot. To pinpoint WHICH
# step dominates (FDV T load / FDV T-1 load / join+weight / weighted aggregate /
# Unison map / advisor merge), this module records per-step timings into a
# module-global list. The app resets it before rendering Advisor-UUT and drains it
# afterwards into the accumulating deep-timing run-log. Single-threaded Streamlit
# render makes a module-global safe, and it keeps this module free of any app import.
# ============================================================
_UUT_TIMINGS: List[Dict[str, Any]] = []


def uut_reset_timings() -> None:
    """Clear the internal UUT step timings (app calls this before an Advisor-UUT render)."""
    try:
        _UUT_TIMINGS.clear()
    except Exception:
        pass


def uut_get_timings() -> List[Dict[str, Any]]:
    """Return a copy of the recorded UUT step timings (app drains this after render)."""
    try:
        return list(_UUT_TIMINGS)
    except Exception:
        return []


class _uut_step:
    """Context manager recording one internal UUT step timing. Never raises into the
    wrapped body; on exception it still records the step (Status=Error) and re-raises."""

    def __init__(self, label: str, rows: object = ""):
        self.label = str(label or "")
        self.rows = rows
        self._t0 = 0.0

    def __enter__(self):
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            elapsed = round(float(time.perf_counter() - self._t0), 4)
        except Exception:
            elapsed = 0.0
        try:
            _UUT_TIMINGS.append({
                "label": self.label,
                "elapsed": elapsed,
                "rows": self.rows,
                "status": "Error" if exc_type is not None else "Done",
                "detail": (f"{exc_type.__name__}: {exc_val}" if exc_type is not None else ""),
            })
        except Exception:
            pass
        return False  # never suppress

UUT_VERSION = "v311a"

FDV_PORT_IDX = 3
FDV_EXTPORT_IDX = 4
FDV_SEC_IDX = 7
FDV_PRICE_IDX = 24      # LocalMarketPrice
FDV_MV_IDX = 32         # MarketValue
DEFAULT_UUT_TOLERANCE_PCT = 0.04

# v321 - SLEEVE INCOME. Per-holding income from the DetailedValuationFDV, so the
# Advisor-UUT income is measured on the UUT SLEEVE (MV-weighted underlying income),
# matching the workbook's Advisor-UUT Return Check Income column - rather than the
# whole-portfolio 'Income return %' (which runs ~lower because it is diluted by
# non-sleeve holdings). Candidate FDV columns (shared frame, matched by name):
#   - RATE columns are a per-holding income RETURN (decimal, same basis as Price
#     Return); sleeve income = SUM(income_rate * weight).
#   - AMOUNT columns are a per-holding income $ ; sleeve income = SUM(amount)/port_total.
# Names are matched case-insensitively; '%'/'pct' rate columns are scaled /100.
# If none are present, sleeve income is unavailable and the check falls back to the
# portfolio 'Income return %' (v320) - so this degrades safely with no behaviour change.
FDV_INCOME_RATE_COLS = ("IncomeReturn", "Income Return", "IncomeReturnLocal",
                        "IncomeReturnPct", "Income Return %", "IncomeYield")
FDV_INCOME_AMOUNT_COLS = ("Income", "IncomeLocal", "AccruedIncome", "IncomeAmount",
                          "Accrued Income", "IncomeMarketValue")
# Legacy positional CSV income index is unknown/unsafe to guess -> disabled (None).
FDV_INCOME_IDX: Optional[int] = None

_DATE_RE = re.compile(r"FDV_[A-Za-z0-9]+-(\d{6})-", re.IGNORECASE)

try:
    from bnp_helpers_columns import normalise_join_key_series as _norm_join
except Exception:
    def _norm_join(s: pd.Series) -> pd.Series:
        return s.astype(str).str.strip().str.upper().str.replace(r"\s+", "", regex=True)


def _num(x) -> Optional[float]:
    s = str(x).replace(",", "").replace("$", "").strip()
    if s in ("", "nan", "None"):
        return None
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        return float(s)
    except Exception:
        return None


def _norm_token(v: object) -> str:
    t = str(v or "").strip()
    first = t.split()[0] if t else ""
    return "".join(ch for ch in first.upper() if ch.isalnum())


def _first_existing(path: str) -> str:
    p = str(path or "").strip()
    if not p:
        return ""
    bs = chr(92); cands = [p]
    if p.upper().startswith("G:" + bs):
        cands.append(bs + bs + "hq.local" + bs + "Corp" + bs + p[3:].lstrip(bs))
    for c in cands:
        if c and os.path.exists(c):
            return c
    return p if os.path.exists(p) else ""


def _date_token(path: str) -> str:
    """Return the DDMMYY date token from an FDV filename, sortable as YYMMDD."""
    m = _DATE_RE.search(os.path.basename(str(path)))
    if not m:
        return ""
    ddmmyy = m.group(1)
    return ddmmyy[4:6] + ddmmyy[2:4] + ddmmyy[0:2]  # YYMMDD for correct ordering


def group_fdv_files_by_date(paths: List[str]) -> Tuple[List[str], List[str], Dict[str, Any]]:
    """Given a list of DetailedValuationFDV paths (any filesets, any days), return
    (T_files, T1_files, diag): ALL filesets for the latest date as T, ALL for the
    prior date as T-1. This is the v311a fix - never pair by modified-time."""
    existing = [p for p in (paths or []) if p and os.path.exists(_first_existing(p))]
    existing = [_first_existing(p) for p in existing]
    by_date: Dict[str, List[str]] = {}
    for p in existing:
        tok = _date_token(p)
        if tok:
            by_date.setdefault(tok, []).append(p)
    dates = sorted(by_date.keys(), reverse=True)  # newest first
    t_files = by_date.get(dates[0], []) if dates else []
    t1_files = by_date.get(dates[1], []) if len(dates) >= 2 else []
    diag = {"dates_found": dates, "t_date": dates[0] if dates else "",
            "t1_date": dates[1] if len(dates) >= 2 else "",
            "t_files": len(t_files), "t1_files": len(t1_files),
            "ungrouped": len(existing) - sum(len(v) for v in by_date.values())}
    return t_files, t1_files, diag


# ---------------------------------------------------------------------------
# FDV loader (accepts a single path OR a list of paths -> concatenated)
# ---------------------------------------------------------------------------
_LEGACY_HOLDINGS_COLS = ["PortfolioCode", "ExternalPortfolioCode", "SecurityCode", "Price", "MV"]


def _load_fdv_holdings_legacy(path_or_paths: Any) -> pd.DataFrame:
    """Original row-by-row reader, retained as a fallback when the shared frame helper
    is unavailable."""
    paths = path_or_paths if isinstance(path_or_paths, (list, tuple)) else [path_or_paths]
    recs = []
    for path in paths:
        resolved = _first_existing(path) or path
        if not resolved or not os.path.exists(resolved):
            continue
        for enc in ("latin-1", "utf-8-sig", "utf-8"):
            try:
                with open(resolved, encoding=enc, newline="") as f:
                    r = csv.reader(f)
                    next(r, None)
                    for row in r:
                        if len(row) <= FDV_MV_IDX:
                            continue
                        recs.append({
                            "PortfolioCode": str(row[FDV_PORT_IDX]).strip(),
                            "ExternalPortfolioCode": str(row[FDV_EXTPORT_IDX]).strip(),
                            "SecurityCode": str(row[FDV_SEC_IDX]).strip(),
                            "Price": _num(row[FDV_PRICE_IDX]),
                            "MV": _num(row[FDV_MV_IDX]),
                        })
                break
            except Exception:
                continue
    return pd.DataFrame(recs, columns=_LEGACY_HOLDINGS_COLS)


def load_fdv_holdings(path_or_paths: Any) -> pd.DataFrame:
    """v345: derive holdings from the SHARED FDV frame (single network read per file,
    vectorised) instead of a per-call row-by-row csv.reader scan. Output is identical:
    PortfolioCode, ExternalPortfolioCode, SecurityCode, Price (LocalMarketPrice),
    MV (MarketValue). Falls back to the legacy reader if the shared helper is absent."""
    if not callable(_shared_load_fdv_frame_v345):
        return _load_fdv_holdings_legacy(path_or_paths)
    frame = _shared_load_fdv_frame_v345(path_or_paths)
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return pd.DataFrame(columns=_LEGACY_HOLDINGS_COLS)
    out = pd.DataFrame({
        "PortfolioCode": frame.get("PortfolioCode", "").astype(str).str.strip(),
        "ExternalPortfolioCode": frame.get("ExternalPortfolioCode", "").astype(str).str.strip(),
        "SecurityCode": frame.get("SecurityCode", "").astype(str).str.strip(),
        "Price": _num_series_v345(frame.get("LocalMarketPrice", "")),
        "MV": _num_series_v345(frame.get("MarketValue", "")),
    })
    # v321: carry per-holding income when the FDV frame exposes it (rate or amount).
    inc_rate, inc_amount = _extract_fdv_income(frame)
    if inc_rate is not None:
        out["Income Rate"] = inc_rate.reindex(range(len(out))).values if len(inc_rate) == len(out) else inc_rate.values
    if inc_amount is not None:
        out["Income Amount"] = inc_amount.reindex(range(len(out))).values if len(inc_amount) == len(out) else inc_amount.values
    return out.reset_index(drop=True)


def _find_frame_col(frame: pd.DataFrame, candidates) -> Optional[str]:
    """Case-insensitive lookup of the first matching column name in `frame`."""
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return None
    lower = {str(c).strip().lower(): c for c in frame.columns}
    for cand in candidates:
        c = lower.get(str(cand).strip().lower())
        if c is not None:
            return c
    return None


def _extract_fdv_income(frame: pd.DataFrame):
    """Return (income_rate_series, income_amount_series) parsed to numeric from the
    shared FDV frame, or (None, None) when neither is present. A rate column named
    with '%'/'pct' is scaled to DECIMAL; other rate columns are assumed decimal."""
    rate = amount = None
    rc = _find_frame_col(frame, FDV_INCOME_RATE_COLS)
    if rc is not None:
        s = _num_series_v345(frame[rc])
        if str(rc).strip().lower().replace(" ", "").endswith(("%", "pct")) or "%" in str(rc):
            s = s / 100.0
        rate = s.reset_index(drop=True)
    ac = _find_frame_col(frame, FDV_INCOME_AMOUNT_COLS)
    if ac is not None:
        amount = _num_series_v345(frame[ac]).reset_index(drop=True)
    return rate, amount


def build_uut_return(fdv_t: Any, fdv_t1: Any) -> pd.DataFrame:
    # v344: split the two FDV holdings loads so the run-log shows each separately -
    # these row-by-row csv.reader loads are the prime suspects for the ~24s render.
    with _uut_step("load_fdv_holdings T") as _s:
        t = load_fdv_holdings(fdv_t)
        _s.rows = int(len(t)) if isinstance(t, pd.DataFrame) else ""
    with _uut_step("load_fdv_holdings T-1") as _s:
        t1 = load_fdv_holdings(fdv_t1)
        _s.rows = int(len(t1)) if isinstance(t1, pd.DataFrame) else ""
    if t.empty or t1.empty:
        return pd.DataFrame()
    with _uut_step("build_uut_return join+weight") as _s:
        prev = t1[["PortfolioCode", "SecurityCode", "Price"]].drop_duplicates(
            ["PortfolioCode", "SecurityCode"]).rename(columns={"Price": "Previous Price"})
        df = t.merge(prev, on=["PortfolioCode", "SecurityCode"], how="left")
        df = df.rename(columns={"Price": "Current Price", "MV": "Current MV"})
        df["Current MV"] = pd.to_numeric(df["Current MV"], errors="coerce")
        df["Current Price"] = pd.to_numeric(df["Current Price"], errors="coerce")
        df["Previous Price"] = pd.to_numeric(df["Previous Price"], errors="coerce")
        port_total = df.groupby("PortfolioCode")["Current MV"].transform("sum")
        df["Weight"] = df["Current MV"] / port_total.where(port_total != 0)
        good = df["Current Price"].notna() & df["Previous Price"].notna() & (df["Previous Price"] != 0) & df["Current MV"].notna()
        df["Price Return"] = pd.NA
        df.loc[good, "Price Return"] = df.loc[good, "Current Price"] / df.loc[good, "Previous Price"] - 1
        df["Weighted Return"] = pd.to_numeric(df["Price Return"], errors="coerce") * df["Weight"]
        # v321: per-holding weighted income on the SAME MV weight as the price
        # return, so the sleeve income aggregates onto the identical basis as the
        # Weighted UUT Return. A rate income is weighted directly; an amount income
        # is divided by the portfolio total (amount/total == (amount/MV)*weight).
        if "Income Rate" in df.columns:
            df["Weighted Income"] = pd.to_numeric(df["Income Rate"], errors="coerce") * df["Weight"]
        elif "Income Amount" in df.columns:
            df["Weighted Income"] = pd.to_numeric(df["Income Amount"], errors="coerce") / port_total.where(port_total != 0)
        _s.rows = int(len(df))
    return df


def aggregate_weighted_uut_return(uut_holdings: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(uut_holdings, pd.DataFrame) or uut_holdings.empty:
        return pd.DataFrame(columns=["PortfolioCode", "ExternalPortfolioCode", "Weighted UUT Return", "Holdings"])
    _agg = {"Weighted UUT Return": ("Weighted Return", "sum"),
            "Holdings": ("SecurityCode", "count")}
    # v321: aggregate the per-holding weighted income into the sleeve income
    # (SUM over the portfolio's underlying holdings), when income was available.
    if "Weighted Income" in uut_holdings.columns:
        _agg["Weighted UUT Income"] = ("Weighted Income", "sum")
    g = uut_holdings.groupby("PortfolioCode").agg(**_agg).reset_index()
    ext = uut_holdings.groupby("PortfolioCode")["ExternalPortfolioCode"].first().reset_index()
    g = g.merge(ext, on="PortfolioCode", how="left")
    g["_adv"] = g["ExternalPortfolioCode"].map(_norm_token)
    g["_hip"] = _norm_join(g["PortfolioCode"])
    return g


@dataclass
class UutResult:
    holdings_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    advisor_uut_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    summary: Dict[str, Any] = field(default_factory=dict)
    status: str = "OK"
    diag: Dict[str, Any] = field(default_factory=dict)


def _collect_fdv_paths(bundle: Dict[str, object]) -> List[str]:
    """Gather candidate FDV paths from the bundle (list, explicit keys, or folder)."""
    out: List[str] = []
    if not isinstance(bundle, dict):
        return out
    lst = bundle.get("fdv_files")
    if isinstance(lst, (list, tuple)):
        out += [str(p) for p in lst]
    for k in ("fdv_t_path", "fdv_t1_path"):
        v = bundle.get(k)
        if isinstance(v, str) and v:
            out.append(v)
    folder = str(bundle.get("folder") or "")
    if folder and os.path.isdir(folder):
        out += glob.glob(os.path.join(folder, "*DetailedValuationFDV*.csv"))
    # de-dup preserving order
    seen, res = set(), []
    for p in out:
        rp = _first_existing(p)
        if rp and rp not in seen:
            seen.add(rp); res.append(rp)
    return res


# ---------------------------------------------------------------------------
# v323 - DAssetReturn income, joined to the UUT LOOK-THROUGH holdings
# ---------------------------------------------------------------------------
# Provenance (traced from the workbook VBA + cell formulas, verified 287/294 to 6dp):
#   'Advisor-UUT Check'!U (Income $) = SUMIF('UUT Return'!B, hiport, 'UUT Return'!Z)
#   'Advisor-UUT Check'!N (Income)   = U / GAV
#   'UUT Return'!Z                   = -SUMIFS(DAssetReturn!P, DAssetReturn!C=port,
#                                              DAssetReturn!G=security)
# So income is: for each UUT-SLEEVE holding, NEGATE the DAssetReturn 'Income' matched
# on (Portfolio, Security/Asset Code); SUM over the portfolio's UUT holdings; / GAV.
# This is a genuine SLEEVE income (restricted to the look-through holdings) sourced
# from DAssetReturn (the FDV has no income column) - correcting v322 which used the
# WHOLE-portfolio income WITHOUT the negation (wrong sign, wrong scope).
DASSETRETURN_GLOB = "*DAssetReturn*.csv"
_DAR_PORT_NAMES = ("Portfolio",)
_DAR_ASSET_NAMES = ("Asset Code", "AssetCode", "Security Code", "SecurityCode")
_DAR_INCOME_NAMES = ("Income",)


def _collect_dassetreturn_paths(bundle: Dict[str, object]) -> List[str]:
    """Gather DAssetReturn CSV paths (list key, explicit key, or folder glob). The
    app concatenates ALL filesets at runtime, so every matching file is summed."""
    out: List[str] = []
    if not isinstance(bundle, dict):
        return out
    lst = bundle.get("dassetreturn_files") or bundle.get("dar_files")
    if isinstance(lst, (list, tuple)):
        out += [str(p) for p in lst]
    v = bundle.get("dassetreturn_path") or bundle.get("dar_path")
    if isinstance(v, str) and v:
        out.append(v)
    folder = str(bundle.get("folder") or "")
    if folder and os.path.isdir(folder):
        out += glob.glob(os.path.join(folder, DASSETRETURN_GLOB))
    seen, res = set(), []
    for p in out:
        rp = _first_existing(p)
        if rp and rp not in seen:
            seen.add(rp); res.append(rp)
    return res


def _dar_header_indices(rows_iter):
    """Locate the DAssetReturn header row (the file has a title band above it) and
    return (row_index, {port, asset, income}) matched by NAME. (None, {}) if absent."""
    def _match(cell, names):
        c = str(cell or "").strip().lower()
        return any(c == n.lower() for n in names)
    for ri, row in enumerate(rows_iter):
        if ri > 12:
            break
        port = asset = income = None
        for ci, cell in enumerate(row):
            if port is None and _match(cell, _DAR_PORT_NAMES):
                port = ci
            elif asset is None and _match(cell, _DAR_ASSET_NAMES):
                asset = ci
            elif income is None and _match(cell, _DAR_INCOME_NAMES):
                income = ci
        if port is not None and asset is not None and income is not None:
            return ri, {"port": port, "asset": asset, "income": income}
    return None, {}


def load_dassetreturn_income_by_holding(paths: Any) -> Dict[Tuple[str, str], float]:
    """Sum the DAssetReturn 'Income' per (Portfolio, Asset/Security code) across ALL
    supplied filesets. Returns {(norm_port, norm_sec): income$}. NOTE: the raw sign
    is returned here; the workbook NEGATES it when aggregating (see build_uut_income
    _by_code). Fully guarded; unreadable files skipped."""
    paths = paths if isinstance(paths, (list, tuple)) else [paths]
    acc: Dict[Tuple[str, str], float] = {}
    for path in paths:
        resolved = _first_existing(path) or path
        if not resolved or not os.path.exists(resolved):
            continue
        for enc in ("latin-1", "utf-8-sig", "utf-8"):
            try:
                with open(resolved, encoding=enc, newline="") as f:
                    reader = csv.reader(f)
                    hdr_row, idx = _dar_header_indices(reader)
                    if hdr_row is None:
                        break
                    pi, ai, ii = idx["port"], idx["asset"], idx["income"]
                    need = max(pi, ai, ii)
                    for row in reader:  # positioned after the header
                        if len(row) <= need:
                            continue
                        p = _norm_hip_code(row[pi])
                        s = str(row[ai] or "").strip().upper()
                        if not p or not s:
                            continue
                        val = _num(row[ii]) or 0.0
                        key = (p, s)
                        acc[key] = acc.get(key, 0.0) + val
                break
            except Exception:
                continue
    return acc


def _uut_holdings_from_bundle(bundle: Dict[str, object]) -> pd.DataFrame:
    """Return the UUT look-through holdings (PortfolioCode, SecurityCode) from the
    bundle if the core v311 render produced them; else an empty frame."""
    if isinstance(bundle, dict):
        h = bundle.get("uut_holdings_df")
        if isinstance(h, pd.DataFrame) and not h.empty:
            return h
    return pd.DataFrame()


def _gav_by_portfolio_from_bundle(bundle: Dict[str, object]) -> Dict[str, float]:
    """{norm_portfolio_code -> GAV} from the app's gav_check_df ('BNP GAV', with
    'Unison NAV' fallback). Empty when the GAV frame is not on the bundle."""
    out: Dict[str, float] = {}
    if not isinstance(bundle, dict):
        return out
    gav = bundle.get("gav_check_df")
    if not isinstance(gav, pd.DataFrame) or gav.empty:
        return out
    pcol = next((c for c in ("Portfolio code", "Portfolio", "PortfolioCode") if c in gav.columns), None)
    gcol = next((c for c in ("BNP GAV", "GAV", "Unison NAV") if c in gav.columns), None)
    if not pcol or not gcol:
        return out
    keys = gav[pcol].map(_norm_hip_code)
    vals = pd.to_numeric(gav[gcol], errors="coerce")
    for k, v in zip(keys.tolist(), vals.tolist()):
        if k and k not in out and pd.notna(v):
            out[k] = float(v)
    return out


DEFAULT_GAV_FLOOR_DOLLAR = 1000.0  # v325: below this GAV, income/GAV is unreliable


def build_uut_income_by_code(bundle: Dict[str, object], *,
                             sleeve_pairs: Optional[set] = None,
                             gav_floor_dollar: float = DEFAULT_GAV_FLOOR_DOLLAR) -> Dict[str, float]:
    """Return {portfolio_code -> Income (DECIMAL)} reproducing the workbook exactly:
        income$_port = SUM over the portfolio's UUT holdings of -DAssetReturn.Income(port, sec)
        Income       = income$_port / GAV
    Join is (PortfolioCode, SecurityCode) - i.e. restricted to the UUT look-through
    sleeve - matching 'UUT Return'!Z. GAV from the app's gav_check_df ('BNP GAV').
    Returns {} when DAssetReturn or holdings or GAV are unavailable, so apply_v311_1
    falls back to the DDetailedReturn 'Income return %' (v320).

    v325 SLEEVE RESTRICTION: `sleeve_pairs` is the set of (PortfolioCode, SecurityCode)
    for the true UUT-subclass securities (from resolve_uut_scope['pairs']). When
    supplied, ONLY those holdings are summed - so the income lands on the UUT SLEEVE
    (matching 'UUT Return'!Z), NOT the whole portfolio. Without it (None), behaviour
    is unchanged (whole uut_holdings_df) so the function degrades safely.

    v325 GAV FLOOR: a portfolio whose GAV is below `gav_floor_dollar` (default $1,000)
    is skipped (income left to the v320 fallback), so a near-zero / blank GAV can't
    manufacture a spurious breach (e.g. terminated M1TASx GAV 0.1, blank-GAV overlays)."""
    # v324 DIAGNOSTIC: this records, per portfolio, exactly how income was sourced
    # and computed, and stashes it on bundle['uut_income_diag_df'] +
    # bundle['uut_income_diag_summary'] so the corrected panel can surface it. It is
    # the single artefact that confirms "what's going on": whether DAssetReturn was
    # found, how many sleeve holdings matched, and CRUCIALLY the SLEEVE income$ vs
    # the WHOLE-PORTFOLIO income$ side-by-side (if they are equal, uut_holdings_df is
    # spanning the whole portfolio, not the UUT sleeve - the exact failure mode).
    def _stash_diag(status: str, rows=None, summary_extra=None):
        try:
            if isinstance(bundle, dict):
                bundle["uut_income_diag_df"] = pd.DataFrame(rows or [])
                s = {"status": status,
                     "dassetreturn_paths": len(paths) if 'paths' in dir() and paths else 0,
                     "holdings_rows": int(len(holdings)) if isinstance(holdings, pd.DataFrame) else 0,
                     "gav_portfolios": len(gav_map) if 'gav_map' in dir() and gav_map else 0,
                     "portfolios_with_income": int(sum(1 for r in (rows or []) if r.get("income_decimal") not in (None, 0.0))),
                     "portfolios_sleeve_eq_whole": int(sum(1 for r in (rows or []) if r.get("sleeve_eq_whole"))),
                     "portfolios_evaluated": int(len(rows or [])),
                     "dar_source": (summary_extra or {}).get("dar_source", "")}
                s.update(summary_extra or {})
                bundle["uut_income_diag_summary"] = s
        except Exception:
            pass

    paths = _collect_dassetreturn_paths(bundle)
    holdings = _uut_holdings_from_bundle(bundle)
    # v324: also try the parsed bundle['dar'] frame as a source (runtime carries the
    # frame, not paths). Prefer whichever yields the (port,sec) income map.
    dar = {}
    dar_source = ""
    if paths:
        dar = load_dassetreturn_income_by_holding(paths) or {}
        if dar:
            dar_source = f"CSV paths ({len(paths)} file(s))"
    if not dar and callable(globals().get("_dar_income_by_holding_from_df")):
        try:
            dar = _dar_income_by_holding_from_df(bundle.get("dar") if isinstance(bundle, dict) else None) or {}
            if dar:
                dar_source = "bundle['dar'] frame"
        except Exception:
            dar = {}
    if holdings is None or (isinstance(holdings, pd.DataFrame) and holdings.empty):
        _stash_diag("no uut_holdings_df", summary_extra={"dar_source": dar_source})
        return {}
    pcol = next((c for c in ("PortfolioCode", "Portfolio code", "Portfolio") if c in holdings.columns), None)
    scol = next((c for c in ("SecurityCode", "Security Code") if c in holdings.columns), None)
    if not pcol or not scol:
        _stash_diag("holdings missing port/sec column", summary_extra={"dar_source": dar_source})
        return {}
    if not dar:
        _stash_diag("no DAssetReturn income (paths and dar frame both empty)", summary_extra={"dar_source": dar_source})
        return {}
    gav_map = _gav_by_portfolio_from_bundle(bundle)
    if not gav_map:
        _stash_diag("no gav_check_df", summary_extra={"dar_source": dar_source})
        return {}

    # Whole-portfolio DAssetReturn income per portfolio (SUM over ALL that port's
    # keys) - the comparison baseline for the diagnostic.
    whole_by_port: Dict[str, float] = {}
    for (p, s), v in dar.items():
        whole_by_port[p] = whole_by_port.get(p, 0.0) + v

    # v325: normalise the sleeve pair set to the same (norm_port, upper_sec) keys
    # used for the join. When present, only these holdings feed the income sum.
    sleeve_norm = None
    if sleeve_pairs:
        sleeve_norm = {(_norm_hip_code(p), str(s).strip().upper()) for (p, s) in sleeve_pairs}

    # Per-holding negated income, summed to the SLEEVE, matched on (port, sec).
    income_dollar: Dict[str, float] = {}
    matched_ct: Dict[str, int] = {}
    holdings_ct: Dict[str, int] = {}
    sleeve_ct: Dict[str, int] = {}
    ports = holdings[pcol].map(_norm_hip_code)
    secs = holdings[scol].astype(str).str.strip().str.upper()
    for p, s in zip(ports.tolist(), secs.tolist()):
        if not p or not s:
            continue
        holdings_ct[p] = holdings_ct.get(p, 0) + 1
        # v325: sleeve restriction - skip holdings that are not UUT-subclass securities.
        if sleeve_norm is not None and (p, s) not in sleeve_norm:
            continue
        sleeve_ct[p] = sleeve_ct.get(p, 0) + 1
        v = dar.get((p, s))
        if v is None:
            continue
        matched_ct[p] = matched_ct.get(p, 0) + 1
        income_dollar[p] = income_dollar.get(p, 0.0) + (-v)  # NEGATE (workbook 'UUT Return'!Z)

    out: Dict[str, float] = {}
    diag_rows = []
    gav_floor_skipped = 0
    for code in sorted(set(list(income_dollar) + list(holdings_ct))):
        sleeve_inc = income_dollar.get(code, 0.0)
        whole_inc = -whole_by_port.get(code, 0.0)  # negate to match sleeve convention
        gav = gav_map.get(code)
        # v325 GAV FLOOR: skip portfolios with GAV below the floor (or missing) so a
        # near-zero denominator can't fabricate a breach; leave to the v320 fallback.
        below_floor = (gav is None) or (abs(gav) < float(gav_floor_dollar))
        inc_dec = None
        if not below_floor and gav and gav != 0.0:
            inc_dec = sleeve_inc / gav
            out[code] = inc_dec
        elif below_floor:
            gav_floor_skipped += 1
        diag_rows.append({
            "Portfolio code": code,
            "holdings_in_uut_df": int(holdings_ct.get(code, 0)),
            "sleeve_holdings": int(sleeve_ct.get(code, 0)) if sleeve_norm is not None else int(holdings_ct.get(code, 0)),
            "matched_to_DAssetReturn": int(matched_ct.get(code, 0)),
            "sleeve_income$": round(sleeve_inc, 2),
            "whole_portfolio_income$": round(whole_inc, 2),
            "sleeve_eq_whole": bool(abs(sleeve_inc - whole_inc) < 1.0),
            "GAV": gav,
            "below_gav_floor": bool(below_floor),
            "income_decimal": inc_dec,
        })
    _stash_diag("OK", rows=diag_rows, summary_extra={
        "dar_source": dar_source,
        "sleeve_restricted": bool(sleeve_norm is not None),
        "sleeve_pairs": int(len(sleeve_norm)) if sleeve_norm is not None else 0,
        "gav_floor_dollar": float(gav_floor_dollar),
        "gav_floor_skipped": int(gav_floor_skipped),
    })
    return out


def build_advisor_uut_check(portfolio_df: pd.DataFrame, bundle: Dict[str, object],
                            *, fdv_t: Any = None, fdv_t1: Any = None,
                            tolerance_pct: float = DEFAULT_UUT_TOLERANCE_PCT,
                            portfolio_code_col: str = "Portfolio code",
                            advisor_col: str = "External portfolio reference") -> UutResult:
    diag: Dict[str, Any] = {}
    if fdv_t is None or fdv_t1 is None:
        # v311a: group ALL FDV files by date token; T = latest date, T-1 = prior.
        t_files, t1_files, gdiag = group_fdv_files_by_date(_collect_fdv_paths(bundle))
        diag.update(gdiag)
        fdv_t = fdv_t or t_files
        fdv_t1 = fdv_t1 or t1_files
    if not fdv_t or not fdv_t1:
        return UutResult(status="No FDV T/T-1 (need current-day and previous-day DetailedValuationFDV files)", diag=diag)

    holdings = build_uut_return(fdv_t, fdv_t1)
    if holdings.empty:
        return UutResult(status="No FDV holdings parsed", diag=diag)
    matched = int(holdings["Previous Price"].notna().sum())
    diag["holdings"] = int(len(holdings)); diag["with_previous_price"] = matched
    if matched == 0:
        return UutResult(holdings, status="FDV T/T-1 did not join (0 previous prices) - check date grouping", diag=diag)

    with _uut_step("aggregate_weighted_uut_return") as _s:
        wuut = aggregate_weighted_uut_return(holdings)
        _s.rows = int(len(wuut)) if isinstance(wuut, pd.DataFrame) else ""

    with _uut_step("advisor merge (portfolio_df)") as _s:
        df = portfolio_df.copy() if isinstance(portfolio_df, pd.DataFrame) else pd.DataFrame()
        if df.empty or portfolio_code_col not in df.columns:
            adv = wuut.rename(columns={"PortfolioCode": portfolio_code_col, "ExternalPortfolioCode": advisor_col})
        else:
            df["_hip"] = _norm_join(df[portfolio_code_col])
            _mcols = ["_hip", "Weighted UUT Return", "Holdings"]
            if "Weighted UUT Income" in wuut.columns:
                _mcols.append("Weighted UUT Income")
            adv = df.merge(wuut[_mcols], on="_hip", how="inner")
        _s.rows = int(len(adv)) if isinstance(adv, pd.DataFrame) else ""

    unison_map = {}
    with _uut_step("build_unison_return_map") as _s:
        try:
            from bnp_helpers_return_check import build_unison_return_map
            unison_map, _b, _d = build_unison_return_map(bundle)
        except Exception:
            unison_map = {}
        _s.rows = int(len(unison_map)) if isinstance(unison_map, dict) else ""
    if advisor_col in adv.columns:
        adv["_adv"] = adv[advisor_col].map(_norm_token)
    elif "ExternalPortfolioCode" in adv.columns:
        adv["_adv"] = adv["ExternalPortfolioCode"].map(_norm_token)
        adv = adv.rename(columns={"ExternalPortfolioCode": advisor_col})
    adv["Unison Return"] = adv["_adv"].map(lambda k: unison_map.get(k)) if unison_map else pd.NA

    adv["Weighted UUT Return"] = pd.to_numeric(adv["Weighted UUT Return"], errors="coerce")
    adv["Unison Return"] = pd.to_numeric(adv["Unison Return"], errors="coerce")
    adv["Variance (Unison - Weighted UUT)"] = adv["Unison Return"] - adv["Weighted UUT Return"]

    # v311b: workbook parity. DDetailedReturn tolerance is portfolio-specific and
    # portfolio_df carries it in percentage points (Tolerance Num) and/or decimal
    # form (Tolerance Decimal). Compare on the same decimal basis as Variance.
    if "Tolerance Decimal" in adv.columns:
        row_tol = pd.to_numeric(adv["Tolerance Decimal"], errors="coerce").abs()
    elif "Tolerance Num" in adv.columns:
        row_tol = pd.to_numeric(adv["Tolerance Num"], errors="coerce").abs() / 100.0
    else:
        row_tol = pd.Series(abs(float(tolerance_pct)) / 100.0, index=adv.index, dtype="float64")
    fallback_tol = abs(float(tolerance_pct)) / 100.0
    adv["Portfolio Tolerance (decimal)"] = row_tol.fillna(fallback_tol)

    v = adv["Variance (Unison - Weighted UUT)"]
    adv["Breach"] = ""
    adv.loc[v.notna() & (v.abs() > adv["Portfolio Tolerance (decimal)"]), "Breach"] = "Check"
    adv.loc[v.notna() & (v.abs() <= adv["Portfolio Tolerance (decimal)"]), "Breach"] = "Ok"

    # v321: SLEEVE INCOME (preferred). When the FDV carried per-holding income, the
    # MV-weighted sleeve income ('Weighted UUT Income') is published as the decimal
    # 'Income (decimal)' column - which apply_v311_1 consumes ahead of the
    # portfolio-level 'Income return %'. This puts income on the SAME UUT-sleeve basis
    # as the Weighted UUT Return, matching the workbook's Advisor-UUT Income column.
    if "Weighted UUT Income" in adv.columns:
        adv["Income (decimal)"] = pd.to_numeric(adv["Weighted UUT Income"], errors="coerce")
    # v320: also carry the portfolio's 'Income return %' as the FALLBACK income
    # source (used by apply_v311_1 only when sleeve income is absent). Both flow into
    # the corrected renderer and the export, which read this frame.
    keep = [c for c in [portfolio_code_col, advisor_col, "Portfolio Name",
                        "Unison Return", "Weighted UUT Return", "Holdings",
                        "Income (decimal)",
                        "Income return %", "Income Return %", "Income %",
                        "Tolerance Num", "Tolerance Decimal", "Portfolio Tolerance (decimal)",
                        "Variance (Unison - Weighted UUT)", "Breach"] if c in adv.columns]
    advisor_uut = adv[keep].copy()

    summary = {
        "uut_portfolios": int(len(wuut)),
        "advisor_uut_rows": int(len(advisor_uut)),
        "with_unison": int(advisor_uut["Unison Return"].notna().sum()) if "Unison Return" in advisor_uut.columns else 0,
        "breaches": int((advisor_uut.get("Breach") == "Check").sum()) if "Breach" in advisor_uut.columns else 0,
        "holdings": int(len(holdings)),
        "holdings_priced": matched,
        # Legacy summary field retained for compatibility. This is now only the
        # fallback percentage-point tolerance; breach evaluation uses each row's
        # Portfolio Tolerance (decimal).
        "tolerance_pct": float(tolerance_pct),
        "portfolio_tolerance_rows": int(advisor_uut["Portfolio Tolerance (decimal)"].notna().sum()) if "Portfolio Tolerance (decimal)" in advisor_uut.columns else 0,
    }
    return UutResult(holdings, advisor_uut, summary, "OK", diag)


def render_uut_section(st, bundle: Dict[str, object]) -> None:
    try:
        portfolio_df = bundle.get("portfolio_df", pd.DataFrame()) if isinstance(bundle, dict) else pd.DataFrame()
        st.markdown("**UUT look-through - Advisor-UUT Check (v311)** - weighted underlying "
                    "return of each UUT/PE portfolio vs its Unison return. (Tax + Income applied; "
                    "Stale/Pricing-Frequency deferred.)")
        res = build_advisor_uut_check(portfolio_df, bundle)
        if res.status != "OK":
            st.warning(f"UUT look-through unavailable: {res.status}. Diagnostic: {res.diag}")
            return
        if isinstance(bundle, dict):
            bundle["uut_holdings_df"] = res.holdings_df
            bundle["advisor_uut_df"] = res.advisor_uut_df
            bundle["uut_summary"] = res.summary
        s = res.summary
        st.caption(f"FDV T date {res.diag.get('t_date','?')} ({res.diag.get('t_files','?')} filesets) vs "
                   f"T-1 {res.diag.get('t1_date','?')} ({res.diag.get('t1_files','?')}); "
                   f"{s.get('holdings_priced',0)}/{s.get('holdings',0)} holdings priced.")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("UUT portfolios", s.get("uut_portfolios", 0))
        c2.metric("Underlying holdings", s.get("holdings", 0))
        c3.metric("With Unison return", s.get("with_unison", 0))
        c4.metric("Breaches", s.get("breaches", 0))
        st.markdown("*Advisor-UUT Check* (Variance = Unison Return - Weighted UUT Return):")
        st.dataframe(res.advisor_uut_df, width="stretch", hide_index=True)
        st.download_button("Download Advisor-UUT Check", res.advisor_uut_df.to_csv(index=False).encode("utf-8"),
                           "advisor_uut_check_last_run.csv", "text/csv", key="uut_adv_dl")
        with st.expander("UUT underlying holdings (weighted returns)", expanded=False):
            st.dataframe(res.holdings_df, width="stretch", hide_index=True)
            st.download_button("Download UUT holdings", res.holdings_df.to_csv(index=False).encode("utf-8"),
                               "uut_holdings_last_run.csv", "text/csv", key="uut_hold_dl")
    except Exception:
        pass


# ===================================================================
# v311.2 / v313.1 - UUT SECURITY SCOPE (merged from bnp_helpers_uut_scope)
# ===================================================================
UUT_SCOPE_VERSION = "v311.2/v313.1"

FDV_SUBCLASS_IDX = 18

UUT_EXACT_SUBCLASSES = {"PARTNERSHIPS", "ORDINARY SHARE - PRT"}

UUT_PREFIXES = ("UUT-",)

def is_uut_subclass(subclass: object) -> bool:
    s = str(subclass or "").strip().upper()
    if not s:
        return False
    if any(s.startswith(p.upper()) for p in UUT_PREFIXES):
        return True
    return s in {x.upper() for x in UUT_EXACT_SUBCLASSES}

def _load_uut_scope_legacy(fdv_paths: Any) -> Dict[str, Any]:
    """Original row-by-row scope scan, retained as a fallback."""
    paths = fdv_paths if isinstance(fdv_paths, (list, tuple)) else [fdv_paths]
    securities: Set[str] = set()
    pairs: Set[Tuple[str, str]] = set()
    portfolios: Set[str] = set()
    all_portfolios: Set[str] = set()
    for path in paths:
        resolved = _first_existing(path) or path
        if not resolved or not os.path.exists(resolved):
            continue
        try:
            with open(resolved, encoding="latin-1", newline="") as f:
                r = csv.reader(f); next(r, None)
                for row in r:
                    if len(row) <= FDV_SUBCLASS_IDX:
                        continue
                    port = str(row[FDV_PORT_IDX]).strip()
                    if port:
                        all_portfolios.add(port)
                    if is_uut_subclass(row[FDV_SUBCLASS_IDX]):
                        sec = str(row[FDV_SEC_IDX]).strip()
                        if sec:
                            securities.add(sec)
                        if port and sec:
                            pairs.add((port, sec))
                        if port:
                            portfolios.add(port)
        except Exception:
            continue
    return {"securities": securities, "pairs": pairs, "portfolios": portfolios,
            "all_portfolios": all_portfolios}


def load_uut_scope_from_fdv(fdv_paths: Any) -> Dict[str, Any]:
    """v345: derive the UUT scope from the SHARED FDV frame (vectorised) instead of a
    second row-by-row network scan. Returns the same structure:
        {'securities', 'pairs', 'portfolios', 'all_portfolios'}.
    Falls back to the legacy scan if the shared helper is absent."""
    if not callable(_shared_load_fdv_frame_v345):
        return _load_uut_scope_legacy(fdv_paths)
    frame = _shared_load_fdv_frame_v345(fdv_paths)
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return {"securities": set(), "pairs": set(), "portfolios": set(), "all_portfolios": set()}
    port = frame.get("PortfolioCode", "").astype(str).str.strip()
    sec = frame.get("SecurityCode", "").astype(str).str.strip()
    sub = frame.get("AssetSubClassName", "")
    all_portfolios: Set[str] = set(p for p in port.unique().tolist() if p)
    # vectorised UUT subclass mask (mirrors is_uut_subclass: prefix UUT- or exact set)
    su = sub.astype(str).str.strip().str.upper()
    exact = {x.upper() for x in UUT_EXACT_SUBCLASSES}
    prefixes = tuple(p.upper() for p in UUT_PREFIXES)
    mask = su.isin(exact)
    for pre in prefixes:
        mask = mask | su.str.startswith(pre)
    mport = port[mask]
    msec = sec[mask]
    securities: Set[str] = set(s for s in msec.unique().tolist() if s)
    portfolios: Set[str] = set(p for p in mport.unique().tolist() if p)
    pair_df = pd.DataFrame({"p": mport, "s": msec})
    pair_df = pair_df[(pair_df["p"] != "") & (pair_df["s"] != "")]
    pairs: Set[Tuple[str, str]] = set(map(tuple, pair_df.drop_duplicates().to_numpy().tolist()))
    return {"securities": securities, "pairs": pairs, "portfolios": portfolios,
            "all_portfolios": all_portfolios}

def load_uut_securities_from_workbook_export(path: str,
                                             security_col_candidates=("Security Code", "SecurityCode")) -> Set[str]:
    """Optional explicit override: read the UUT Return tab / a CSV export and
    return its Security Codes. Accepts .xlsx (sheet 'UUT Return') or .csv."""
    out: Set[str] = set()
    resolved = _first_existing(path) or path
    if not resolved or not os.path.exists(resolved):
        return out
    try:
        if resolved.lower().endswith((".xlsx", ".xlsm")):
            import openpyxl, warnings
            warnings.filterwarnings("ignore")
            wb = openpyxl.load_workbook(resolved, read_only=True, data_only=True)
            ws = wb["UUT Return"] if "UUT Return" in wb.sheetnames else wb[wb.sheetnames[0]]
            hdr = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
            sc = None
            for cand in security_col_candidates:
                if cand in hdr:
                    sc = hdr.index(cand); break
            if sc is not None:
                for r in ws.iter_rows(min_row=2, values_only=True):
                    if sc < len(r) and r[sc]:
                        out.add(str(r[sc]).strip())
            wb.close()
        else:
            df = pd.read_csv(resolved, dtype=str)
            for cand in security_col_candidates:
                if cand in df.columns:
                    out |= set(df[cand].dropna().astype(str).str.strip()); break
    except Exception:
        pass
    return out

def resolve_uut_scope(bundle: Dict[str, object], fdv_paths: Any = None) -> Dict[str, Any]:
    """Build the UUT scope from the bundle. Prefers an explicit workbook export
    (bundle['uut_return_export_path']); else derives from FDV subclasses."""
    explicit = bundle.get("uut_return_export_path") if isinstance(bundle, dict) else None
    fdv = fdv_paths or (bundle.get("fdv_files") if isinstance(bundle, dict) else None) or []
    scope = load_uut_scope_from_fdv(fdv) if fdv else {"securities": set(), "pairs": set(), "portfolios": set()}
    if explicit:
        extra = load_uut_securities_from_workbook_export(str(explicit))
        if extra:
            scope["securities"] |= extra
    scope["source"] = ("fdv_subclass" + ("+workbook_export" if explicit else ""))
    return scope


# ===================================================================
# v311.1 / v311.2 - ADVISOR-UUT CORRECTIONS (merged from bnp_helpers_uut_v311_1)
# ===================================================================
# v316: default matches the workbook Mapping tab "Advisor Return Check" EXCLUDE
# Class list (Currency Overlay / Derivative Overlay / Treasury). Cash is NOT
# excluded by the workbook. The live list is read from Static Data mapping_filters
# when available (config-driven); this is the fallback.
EXCLUDE_ASSET_TYPES = {"currency overlay", "derivative overlay", "treasury"}
try:
    from bnp_helpers_static_data import advisor_return_check_excluded_classes as _arc_excluded_classes_v316
except Exception:
    _arc_excluded_classes_v316 = None

# v345: cache the parsed Central Mapping advisor attrs. The workbook lives on a G:/
# network share and was re-opened via openpyxl on EVERY Advisor-UUT (corrected) click
# - the dominant cost of the ~23s warm render. Cache keyed by (resolved path, size,
# mtime) so it is read once per workbook version and reused across clicks.
_CENTRAL_MAPPING_ATTRS_CACHE: Dict[str, Dict[str, Any]] = {}


def load_central_mapping_advisor_attrs(path: str) -> Dict[str, Dict[str, Any]]:
    """advisor_token -> {'asset_type':..., 'tax_rate':...} from Central Mapping.

    v345: cached by (resolved path, size, mtime) to avoid re-opening the G:/ workbook
    on every click. Returns the SAME dict object from cache on a hit."""
    out: Dict[str, Dict[str, Any]] = {}
    resolved = _first_existing(path) or (path if path and os.path.exists(path) else "")
    if not resolved or not os.path.exists(resolved):
        return out
    try:
        _stt = os.stat(resolved)
        _sig = (int(_stt.st_size), int(_stt.st_mtime))
    except Exception:
        _sig = (0, 0)
    _cached = _CENTRAL_MAPPING_ATTRS_CACHE.get(resolved)
    if isinstance(_cached, dict) and _cached.get("sig") == _sig and isinstance(_cached.get("attrs"), dict):
        return _cached["attrs"]
    try:
        import openpyxl, warnings
        warnings.filterwarnings("ignore")
        wb = openpyxl.load_workbook(resolved, read_only=True, data_only=True)
        for sheet in ("Unison Active Advisors", "Off-Unison Active Advisors"):
            if sheet not in wb.sheetnames:
                continue
            ws = wb[sheet]
            rows = ws.iter_rows(min_row=2, values_only=True)
            for r in rows:
                if not r or len(r) < 8:
                    continue
                adv = _norm_token(r[2])  # Advisor Code
                if not adv:
                    continue
                asset_type = str(r[7] or "").strip() if len(r) > 7 else ""
                tax_rate = r[13] if len(r) > 13 else None
                try:
                    tax_rate = float(tax_rate) if tax_rate not in (None, "") else 0.0
                except Exception:
                    tax_rate = 0.0
                out.setdefault(adv, {"asset_type": asset_type, "tax_rate": tax_rate})
        wb.close()
    except Exception:
        pass
    # v345: cache the parsed attrs for this workbook version so later clicks skip the
    # G:/ openpyxl load entirely.
    try:
        _CENTRAL_MAPPING_ATTRS_CACHE[resolved] = {"sig": _sig, "attrs": out}
    except Exception:
        pass
    return out


def clear_central_mapping_cache() -> None:
    """Drop the Central Mapping attrs cache (e.g. on a forced refresh)."""
    try:
        _CENTRAL_MAPPING_ATTRS_CACHE.clear()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# v320 - Income sourcing for the Advisor-UUT variance
# ---------------------------------------------------------------------------
def _parse_pct_to_decimal(x) -> Optional[float]:
    """Parse an income value that may be a percent string ('0.0445%'), a bare
    number in PERCENT units (0.0445), '(x)' negatives, or blank. Returns a float in
    DECIMAL units (0.0445% -> 0.000445), or None. 'Income return %' from the BNP
    DDetailedReturn is in percent, so the numeric is always scaled by /100."""
    if x is None:
        return None
    s = str(x).strip()
    if s in ("", "nan", "None", "-"):
        return None
    s = s.replace("%", "").replace(",", "").strip()
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        return float(s) / 100.0
    except Exception:
        return None


def _norm_hip_code(x) -> str:
    return "".join(ch for ch in str(x or "").upper().strip() if ch.isalnum())


def _resolve_income_decimal(df: pd.DataFrame, income_by_code: Optional[dict],
                            portfolio_code_col: str) -> pd.Series:
    """Return a per-row income Series (DECIMAL), sourced in priority order:
      1) income_by_code override (assumed DECIMAL, keyed by portfolio code), then
      2) a decimal income column already on the frame ('Income (decimal)'), then
      3) a percent income column ('Income return %' / 'Income Return %' / 'Income %')
         parsed to decimal.
    Missing rows default to 0.0 (so the term is inert where income is unavailable)."""
    zero = pd.Series(0.0, index=df.index)
    # 1) explicit override (decimal)
    if income_by_code and portfolio_code_col in df.columns:
        m = {_norm_hip_code(k): v for k, v in income_by_code.items()}
        s = pd.to_numeric(df[portfolio_code_col].map(lambda k: m.get(_norm_hip_code(k))), errors="coerce")
        if s.notna().any():
            return s.fillna(0.0)
    # 2) decimal income column
    if "Income (decimal)" in df.columns:
        s = pd.to_numeric(df["Income (decimal)"], errors="coerce")
        if s.notna().any():
            return s.fillna(0.0)
    # 3) percent income column -> decimal
    for col in ("Income return %", "Income Return %", "Income %"):
        if col in df.columns:
            s = pd.to_numeric(df[col].map(_parse_pct_to_decimal), errors="coerce")
            if s.notna().any():
                return s.fillna(0.0)
    return zero


def apply_v311_1(advisor_uut_df: pd.DataFrame, central_mapping_path: Optional[str] = None,
                 *, advisor_col: str = "External portfolio reference",
                 income_by_code: Optional[dict] = None,
                 uut_portfolios: Optional[set] = None,
                 fdv_all_portfolios: Optional[set] = None,
                 excluded_classes: Optional[set] = None,
                 portfolio_code_col: str = "Portfolio code") -> pd.DataFrame:
    """Post-process the v311 advisor_uut_df: scale-correct (v311.1), narrow the
    population to true UUT/PE funds (v311.2), add Tax Effect, recompute
    Variance/Breach. v320: Income is now WIRED IN (portfolio 'Income return %' in
    decimal), added to the price-only Weighted UUT Return so the reconstructed total
    reconciles against the Unison total return. Franking Credits and the after-ex-rate
    movement remain staged (per request).

    v311.2: if `uut_portfolios` (the runtime UUT scope from bnp_helpers_uut_scope)
    is supplied, the population is restricted to portfolios that actually HOLD UUT
    securities - the workbook-faithful scope - in addition to the v311.1 Central
    Mapping exclusion of cash/overlay/treasury advisors."""
    if not isinstance(advisor_uut_df, pd.DataFrame) or advisor_uut_df.empty:
        return advisor_uut_df
    df = advisor_uut_df.copy()

    # --- BUG A (v311.1): scale Unison to decimal to match Weighted UUT Return ---
    if "Unison Return" in df.columns:
        df["Unison Return (decimal)"] = pd.to_numeric(df["Unison Return"], errors="coerce") / 100.0
    else:
        df["Unison Return (decimal)"] = pd.NA
    wuut = pd.to_numeric(df.get("Weighted UUT Return"), errors="coerce")

    # --- Tax + population from Central Mapping ---
    attrs = load_central_mapping_advisor_attrs(central_mapping_path or "")
    adv_tok = df[advisor_col].map(_norm_token) if advisor_col in df.columns else pd.Series("", index=df.index)
    df["Asset Type"] = adv_tok.map(lambda k: attrs.get(k, {}).get("asset_type", ""))
    df["Tax Rate"] = adv_tok.map(lambda k: attrs.get(k, {}).get("tax_rate", 0.0)).fillna(0.0)

    # v311.1 BUG B / v316: exclude non-UUT classes. The list is config-driven from
    # Static Data mapping_filters (Advisor Return Check EXCLUDE Class), matching the
    # workbook exactly (Currency Overlay / Derivative Overlay / Treasury; NOT Cash).
    _excl_set = {str(x).strip().lower() for x in (excluded_classes or EXCLUDE_ASSET_TYPES)}
    excl = df["Asset Type"].astype(str).str.strip().str.lower().isin(_excl_set)
    in_pop = ~excl
    # v311.2: further restrict to funds that actually HOLD UUT securities.
    # COVERAGE-SAFE: only EXCLUDE a portfolio when we actually have its FDV
    # (it appears in fdv_all_portfolios) AND it holds no UUT security. A portfolio
    # with no FDV coverage this run keeps its v311.1 Central Mapping classification,
    # so partial fileset coverage cannot wrongly drop a genuine UUT fund
    # (e.g. M1IT16/M1IT17 when only one fileset's FDV is loaded).
    if uut_portfolios and portfolio_code_col in df.columns:
        def _norm_hip(x):
            return "".join(ch for ch in str(x or "").upper().strip() if ch.isalnum())
        uut_norm = {_norm_hip(p) for p in uut_portfolios}
        code_norm = df[portfolio_code_col].map(_norm_hip)
        holds_uut = code_norm.isin(uut_norm)
        if fdv_all_portfolios:
            covered = code_norm.isin({_norm_hip(p) for p in fdv_all_portfolios})
        else:
            covered = pd.Series(True, index=df.index)  # no coverage info -> apply to all
        # exclude only covered-but-no-UUT; keep uncovered as-is
        in_pop = in_pop & (~(covered & ~holds_uut))
    df["In UUT population"] = in_pop

    # Tax Effect = -TaxRate * Weighted UUT Return (ex-rate term staged)
    df["Tax Effect"] = -pd.to_numeric(df["Tax Rate"], errors="coerce").fillna(0.0) * wuut.fillna(0.0)

    # v320: WIRE IN INCOME (previously staged at 0). Income is the portfolio's
    # income-return component from the BNP DDetailedReturn ('Income return %'),
    # expressed in DECIMAL. It is ADDED to the price-only Weighted UUT Return so the
    # reconstructed total (price + income) reconciles against the Unison TOTAL
    # return - exactly what the workbook's Advisor-UUT Return Check does:
    #   Variance = Unison - (WeightedUUT + Tax + Franking + Income)
    # (validated to 10dp on the workbook's own three breaches). Franking Credits and
    # the after-ex-rate movement remain staged for now (per request). Source order:
    #   1) explicit income_by_code override (decimal), else
    #   2) a decimal income column already on the frame ('Income (decimal)'), else
    #   3) a percent income column ('Income return %' etc.) parsed to decimal.
    # Absent -> 0.0 (identical to the old staged behaviour, so it degrades safely).
    df["Income"] = _resolve_income_decimal(df, income_by_code, portfolio_code_col)

    # --- Variance (decimal basis) = Unison_dec - (WeightedUUT + Tax + Income) ---
    df["Variance"] = df["Unison Return (decimal)"] - (wuut.fillna(0.0) + df["Tax Effect"] + df["Income"])

    # v311b: use each portfolio's DDetailedReturn tolerance. The preferred column
    # is already decimal; Tolerance Num is percentage points and must be /100.
    if "Portfolio Tolerance (decimal)" in df.columns:
        row_tol = pd.to_numeric(df["Portfolio Tolerance (decimal)"], errors="coerce").abs()
    elif "Tolerance Decimal" in df.columns:
        row_tol = pd.to_numeric(df["Tolerance Decimal"], errors="coerce").abs()
    elif "Tolerance Num" in df.columns:
        row_tol = pd.to_numeric(df["Tolerance Num"], errors="coerce").abs() / 100.0
    else:
        row_tol = pd.Series(float("nan"), index=df.index, dtype="float64")
    df["Portfolio Tolerance (decimal)"] = row_tol.fillna(0.0004)
    df["Tolerance Source"] = row_tol.notna().map({True: "DDetailedReturn portfolio tolerance", False: "Fallback 0.04%"})

    df["Breach"] = ""
    v = pd.to_numeric(df["Variance"], errors="coerce")
    df.loc[v.notna() & (v.abs() > df["Portfolio Tolerance (decimal)"]), "Breach"] = "Check"
    df.loc[v.notna() & (v.abs() <= df["Portfolio Tolerance (decimal)"]), "Breach"] = "Ok"
    # Rows outside the UUT population are marked, not breached.
    df.loc[~df["In UUT population"], "Breach"] = "Excluded (not UUT/PE)"

    order = [c for c in ["Portfolio code", advisor_col, "Portfolio Name", "Asset Type",
                         "Unison Return (decimal)", "Weighted UUT Return", "Tax Rate",
                         "Tax Effect", "Income", "Holdings", "Variance",
                         "Portfolio Tolerance (decimal)", "Tolerance Source",
                         "In UUT population", "Breach"] if c in df.columns]
    return df[order]

def _resolve_central_mapping_path(bundle) -> str:
    """Resolve the Central Mapping workbook path from the bundle's Static Data."""
    try:
        if not isinstance(bundle, dict):
            return ""
        sb = bundle.get("static_data")
        try:
            from bnp_helpers_static_data import get_config_value
            p = str(get_config_value(sb, "central_mapping_workbook", "") or "")
            if p:
                return p
        except Exception:
            pass
        # direct fallback via paths table
        if isinstance(sb, dict):
            paths = sb.get("paths")
            if isinstance(paths, pd.DataFrame) and {"ConfigKey", "ConfigValue"} <= set(paths.columns):
                m = paths.loc[paths["ConfigKey"].astype(str).str.strip().str.lower() == "central_mapping_workbook"]
                if not m.empty:
                    return str(m.iloc[0]["ConfigValue"]).strip()
    except Exception:
        pass
    return ""

def render_v311_1_corrected(st, bundle) -> None:
    """Render the v311.1-corrected Advisor-UUT Check (scale fix + population + tax).

    Reads bundle['advisor_uut_df'] (produced by the v311 render), applies the
    corrections, and displays a corrected panel with downloads. Fully guarded.
    """
    try:
        df = bundle.get("advisor_uut_df") if isinstance(bundle, dict) else None
        if not isinstance(df, pd.DataFrame) or df.empty:
            portfolio_df = bundle.get("portfolio_df", pd.DataFrame()) if isinstance(bundle, dict) else pd.DataFrame()
            base_result = build_advisor_uut_check(portfolio_df, bundle if isinstance(bundle, dict) else {})
            if base_result.status != "OK":
                st.warning(f"Advisor-UUT could not run: {base_result.status}. Diagnostic: {base_result.diag}")
                if isinstance(bundle, dict):
                    bundle["advisor_uut_status"] = base_result.status
                    bundle["advisor_uut_diag"] = base_result.diag
                return
            df = base_result.advisor_uut_df
            if isinstance(bundle, dict):
                bundle["uut_holdings_df"] = base_result.holdings_df
                bundle["advisor_uut_df"] = df
                bundle["uut_summary"] = base_result.summary
        if not isinstance(df, pd.DataFrame) or df.empty:
            st.warning("Advisor-UUT returned no portfolio rows after the portfolio/FDV join.")
            return
        cm_path = _resolve_central_mapping_path(bundle)
        # v311.2: derive the UUT scope (portfolios that hold UUT securities).
        # resolve_uut_scope now lives in THIS module (merged), so call it directly.
        # v345: this is the previously-BLIND per-click path. Time each step so the
        # run-log shows the corrected-panel split (scope / central mapping / apply /
        # render), and confirms the v345 shared-frame + workbook-cache wins.
        uut_portfolios = None
        fdv_all_portfolios = None
        sleeve_pairs = None
        try:
            fdv = bundle.get("fdv_files") if isinstance(bundle, dict) else None
            with _uut_step("corrected: resolve_uut_scope") as _s:
                scope = resolve_uut_scope(bundle if isinstance(bundle, dict) else {}, fdv_paths=fdv)
            uut_portfolios = scope.get("portfolios") or None
            fdv_all_portfolios = scope.get("all_portfolios") or None
            # v325: the (port, sec) UUT-subclass pairs used to SLEEVE-restrict income.
            sleeve_pairs = scope.get("pairs") or None
        except Exception:
            uut_portfolios = None; fdv_all_portfolios = None; sleeve_pairs = None
        # v316: config-driven class exclusion from Static Data mapping_filters
        # (workbook-exact: Currency Overlay / Derivative Overlay / Treasury).
        excluded_classes = None
        try:
            if callable(globals().get("_arc_excluded_classes_v316")):
                _sb = bundle.get("static_data") if isinstance(bundle, dict) else None
                _ec = _arc_excluded_classes_v316(_sb)
                if _ec:
                    excluded_classes = {str(x).strip().lower() for x in _ec}
        except Exception:
            excluded_classes = None
        # separately time the Central Mapping workbook read (G:/ openpyxl, now cached)
        # so the cache hit/miss cost is explicit in the run-log.
        with _uut_step("corrected: load_central_mapping_attrs") as _s:
            _cm_attrs = load_central_mapping_advisor_attrs(cm_path or "")
            _s.rows = int(len(_cm_attrs)) if isinstance(_cm_attrs, dict) else ""
        # v323: workbook-faithful income = SUM over UUT sleeve holdings of
        # -DAssetReturn.Income(port, sec), / GAV per portfolio. Passed as
        # income_by_code (decimal), which apply_v311_1 consumes AHEAD of the v320
        # DDetailedReturn 'Income return %' fallback. Empty -> falls back to v320.
        income_by_code = None
        try:
            with _uut_step("corrected: DAssetReturn sleeve income") as _s:
                income_by_code = build_uut_income_by_code(bundle, sleeve_pairs=sleeve_pairs) or None
                _s.rows = int(len(income_by_code)) if isinstance(income_by_code, dict) else 0
        except Exception:
            income_by_code = None
        # v324 DIAGNOSTIC: surface how income was sourced/computed so anyone can
        # confirm what's going on. The headline reveals the exact failure mode -
        # if 'sleeve == whole-portfolio' is high, uut_holdings_df is spanning the
        # WHOLE portfolio (not the UUT sleeve), so income is diluted and breaches
        # over-fire. Fully guarded; never breaks the panel.
        try:
            _idiag = bundle.get("uut_income_diag_summary") if isinstance(bundle, dict) else None
            _idf = bundle.get("uut_income_diag_df") if isinstance(bundle, dict) else None
            if isinstance(_idiag, dict):
                st.caption(
                    "Income diagnostic (v324) - source: **%s** | evaluated %s portfolios | "
                    "with income: %s | **sleeve == whole-portfolio: %s** (high = uut_holdings_df is "
                    "NOT sleeve-scoped, so income is whole-portfolio and breaches over-fire)."
                    % (str(_idiag.get("dar_source") or _idiag.get("status") or "n/a"),
                       _idiag.get("portfolios_evaluated", "?"),
                       _idiag.get("portfolios_with_income", "?"),
                       _idiag.get("portfolios_sleeve_eq_whole", "?"))
                )
                if isinstance(_idf, pd.DataFrame) and not _idf.empty:
                    with st.expander("UUT income sourcing diagnostic (per portfolio) - sleeve vs whole", expanded=False):
                        st.dataframe(_idf, width="stretch", hide_index=True)
                        st.download_button(
                            "Download UUT income diagnostic",
                            _idf.to_csv(index=False).encode("utf-8"),
                            "uut_income_diagnostic_last_run.csv", "text/csv",
                            key="uut_income_diag_dl")
        except Exception:
            pass
        with _uut_step("corrected: apply_v311_1") as _s:
            out = apply_v311_1(df, cm_path if cm_path else None, income_by_code=income_by_code,
                               uut_portfolios=uut_portfolios,
                               fdv_all_portfolios=fdv_all_portfolios, excluded_classes=excluded_classes)
            _s.rows = int(len(out)) if isinstance(out, pd.DataFrame) else ""
        bundle["advisor_uut_df_v311_1"] = out
        st.markdown("**Advisor-UUT Check - v311.1 corrected** - Unison scaled to decimal "
                    "(fixes the 100x variance), currency-overlay / cash / derivative accounts "
                    "excluded, Tax Effect applied, Income wired in from DAssetReturn "
                    "(-SUM sleeve-holding Income / GAV per portfolio; DDetailedReturn "
                    "'Income return %' fallback). Franking / ex-rate staged.")
        in_pop = int(out["In UUT population"].sum()) if "In UUT population" in out.columns else 0
        real = int((out["Breach"] == "Check").sum()) if "Breach" in out.columns else 0
        c1, c2, c3 = st.columns(3)
        c1.metric("In UUT population", in_pop)
        c2.metric("Excluded (overlay/cash)", int(len(out) - in_pop))
        c3.metric("Real breaches", real)
        st.dataframe(out, width="stretch", hide_index=True)
        st.download_button("Download Advisor-UUT Check (v311.1)", out.to_csv(index=False).encode("utf-8"),
                           "advisor_uut_check_v311_1_last_run.csv", "text/csv", key="uut_v311_1_dl")
    except Exception as exc:
        try:
            st.error(f"Advisor-UUT failed: {type(exc).__name__}: {exc}")
        except Exception:
            pass
        if isinstance(bundle, dict):
            bundle["advisor_uut_status"] = "Failed"
            bundle["advisor_uut_error"] = f"{type(exc).__name__}: {exc}"


def build_advisor_uut_gav_style(bundle: Dict[str, object]):
    """GAV-style wrapper for the Advisor-UUT Check: population/investigation
    (red)/OK (green)/excluded (neutral) + single-tab full pack + invariant.

    Reuses the SAME v311.1-corrected frame the app already shows (built once
    and cached on bundle['advisor_uut_df_v311_1'] if the corrected panel has
    already rendered this session; otherwise computed fresh here with the
    identical inputs - resolve_uut_scope, Central Mapping attrs, DAssetReturn
    sleeve income, apply_v311_1). This is DELIBERATELY the same population the
    Advisor-UUT panel uses - only the presentation changes to the GAV-style
    template. The Advisor-UUT Check's underlying population rule
    (AssetSubClassName-based, via resolve_uut_scope) is UNCHANGED.

    Population = 'In UUT population' True (Check + Ok).
    Investigation (red) = Breach == 'Check'.
    OK (green) = Breach == 'Ok'.
    Excluded (neutral) = Breach == 'Excluded (not UUT/PE)' (i.e. 'In UUT
        population' False) - cash / currency overlay / derivative overlay /
        treasury advisors, or funds that do not hold UUT securities.
    """
    from bnp_helpers_gav_style import GavStyleResult, compute_invariant

    out = bundle.get("advisor_uut_df_v311_1") if isinstance(bundle, dict) else None
    if not isinstance(out, pd.DataFrame) or out.empty:
        portfolio_df = bundle.get("portfolio_df", pd.DataFrame()) if isinstance(bundle, dict) else pd.DataFrame()
        base_df = bundle.get("advisor_uut_df") if isinstance(bundle, dict) else None
        if not isinstance(base_df, pd.DataFrame) or base_df.empty:
            base_result = build_advisor_uut_check(portfolio_df, bundle if isinstance(bundle, dict) else {})
            if base_result.status != "OK":
                return GavStyleResult(status=f"Advisor-UUT could not run: {base_result.status}", diag=base_result.diag)
            base_df = base_result.advisor_uut_df
            if isinstance(bundle, dict):
                bundle["advisor_uut_df"] = base_df
                bundle["uut_holdings_df"] = base_result.holdings_df
        if not isinstance(base_df, pd.DataFrame) or base_df.empty:
            return GavStyleResult(status="Advisor-UUT returned no portfolio rows after the portfolio/FDV join")

        cm_path = _resolve_central_mapping_path(bundle)
        uut_portfolios = fdv_all_portfolios = sleeve_pairs = None
        try:
            fdv = bundle.get("fdv_files") if isinstance(bundle, dict) else None
            scope = resolve_uut_scope(bundle if isinstance(bundle, dict) else {}, fdv_paths=fdv)
            uut_portfolios = scope.get("portfolios") or None
            fdv_all_portfolios = scope.get("all_portfolios") or None
            sleeve_pairs = scope.get("pairs") or None
        except Exception:
            pass
        excluded_classes = None
        try:
            if callable(globals().get("_arc_excluded_classes_v316")):
                _sb = bundle.get("static_data") if isinstance(bundle, dict) else None
                _ec = _arc_excluded_classes_v316(_sb)
                if _ec:
                    excluded_classes = {str(x).strip().lower() for x in _ec}
        except Exception:
            excluded_classes = None
        income_by_code = None
        try:
            income_by_code = build_uut_income_by_code(bundle, sleeve_pairs=sleeve_pairs) or None
        except Exception:
            income_by_code = None
        out = apply_v311_1(base_df, cm_path if cm_path else None, income_by_code=income_by_code,
                            uut_portfolios=uut_portfolios, fdv_all_portfolios=fdv_all_portfolios,
                            excluded_classes=excluded_classes)
        if isinstance(bundle, dict) and isinstance(out, pd.DataFrame):
            bundle["advisor_uut_df_v311_1"] = out

    if not isinstance(out, pd.DataFrame) or out.empty or "Breach" not in out.columns:
        return GavStyleResult(status="Advisor-UUT (corrected) produced no usable rows this run")

    out = out.copy()
    out["Exclusion Reason"] = ""
    excl_mask = out["Breach"].astype(str).eq("Excluded (not UUT/PE)")
    out.loc[excl_mask, "Exclusion Reason"] = "Not in UUT/PE population (cash / currency overlay / derivative overlay / treasury, or no UUT holdings)"
    # v360: standardised "Check" column (Breach retained as-is as the legacy/native label).
    out["Breach (legacy label)"] = out["Breach"]
    out["Check"] = out["Breach"].astype(str).replace({"Excluded (not UUT/PE)": "Excluded"})

    green_df = out[out["Breach"].astype(str).eq("Ok")].copy()
    red_df = out[out["Breach"].astype(str).eq("Check")].copy()
    excluded_df = out[excl_mask].copy()
    population_count = int(len(green_df) + len(red_df))

    ok, detail = compute_invariant(population_count, [len(red_df)], len(green_df))

    return GavStyleResult(
        red_frames=[("Check", red_df)],
        green_df=green_df,
        excluded_df=excluded_df,
        full_df=out,
        population_metrics=[
            ("UUT population", population_count),
            ("UUT checks", int(len(red_df))),
            ("UUT OK", int(len(green_df))),
            ("Excluded (not UUT/PE)", int(len(excluded_df))),
        ],
        invariant_ok=ok,
        invariant_detail=detail,
        status="OK",
        currency_cols=["Income"],
        percent_cols=["Unison Return (decimal)", "Weighted UUT Return", "Tax Rate", "Tax Effect",
                      "Variance", "Portfolio Tolerance (decimal)"],
        population_bool_col="In UUT population",
        control_noun="Advisor-UUT Check",
    )


def render_advisor_uut_gav_style(st, bundle: Dict[str, object]) -> None:
    from bnp_helpers_gav_style import render_gav_style_section
    result = build_advisor_uut_gav_style(bundle)
    if isinstance(bundle, dict):
        bundle["advisor_uut_gav_style_result"] = result
    render_gav_style_section(
        st, control_key="advisor_uut", title="Advisor-UUT Check",
        purpose=("Weighted underlying (look-through) return of each UUT/PE portfolio's holdings vs its Unison "
                 "return, tax- and income-adjusted. Population is funds classified as true UUT/PE (Central "
                 "Mapping class + FDV subclass scope); cash/overlay/treasury advisors and non-UUT funds are "
                 "excluded from the Check/Ok test but retained for audit."),
        result=result, download_filename_prefix="advisor_uut_check",
    )


if __name__ == "__main__":
    import glob
    print(f"[merged UUT module] self-test ({UUT_VERSION} + {UUT_SCOPE_VERSION})")
    fdv = glob.glob("/mnt/user-data/uploads/*DetailedValuationFDV*.csv")
    if len(fdv) >= 2:
        scope = load_uut_scope_from_fdv(fdv)
        print(f"  UUT securities: {len(scope['securities'])} | UUT portfolios: {len(scope['portfolios'])}")
        for s in ["BHP","NAB","RIO"]:
            assert s not in scope["securities"], f"equity {s} leaked into UUT scope"
        t_files, t1_files, gdiag = group_fdv_files_by_date(fdv)
        h = build_uut_return(t_files, t1_files)
        print(f"  holdings: {len(h)} | priced: {int(h['Previous Price'].notna().sum())}")
        print("  OK - merged scope + look-through validated")
    else:
        print("  (no FDV data present; import/API structure verified by compile)")
    # API presence
    for fn in ["group_fdv_files_by_date","build_uut_return","aggregate_weighted_uut_return",
               "build_advisor_uut_check","render_uut_section","is_uut_subclass",
               "load_uut_scope_from_fdv","resolve_uut_scope","apply_v311_1",
               "render_v311_1_corrected"]:
        assert fn in globals(), f"missing {fn}"
    print("  all public functions present: OK")
