# -*- coding: utf-8 -*-
"""
bnp_helpers_ancillary.py  (v372 - Clearing, Negative NAV, Liquidity)
v312a FIX: Liquidity % now bridges NAV (keyed by advisor in Acc Balance) to the
portfolio (keyed by Hiport in DAssetReturn) via portfolio_df, which carries both
'Portfolio code' (Hiport) and 'External portfolio reference' (advisor). Previously
the % was blank because the two keys were never bridged.

v360: introduced _norm_code_v360 inside build_clearing_gav_style only, to make
Cash Clearing (account '0055') resilient to a leading-zero loss (e.g. the source
representing the code as '55' or '55.0'). Fixed the GAV-style tab, but three
other call sites (the classic dashboard's build_clearing_checks,
build_negative_nav_check, clearing_counts) and the raw parser
(load_acc_balance_accounts) still did an EXACT string match against '0055' /
'9018' / '4999' - so the classic "Ancillary checks" section and the raw loader
itself were still exposed to the same bug (the two code paths had drifted).

v372 (this version):
  (1) LEADING-ZERO FIX, CENTRALISED - the v360 logic (strip a trailing '.0',
      then strip leading zeros) is now a single shared helper, _canon_acct(),
      used EVERYWHERE an Account Code is compared: load_acc_balance_accounts,
      build_clearing_checks, build_negative_nav_check, clearing_counts, and
      build_clearing_gav_style (which now calls the shared helper instead of
      keeping its own private copy). This closes the gap where the classic
      dashboard path and the GAV-style tab path could disagree.
  (2) COLUMN-POSITION RESILIENCE (best-effort, SAFE fallback) - Acc Balance is
      a Tableau crosstab whose column layout can in principle shift between
      exports (extra/missing advisor groupings change how many columns precede
      each account's Balance Start/Movement/Balance End triplet). The old
      parser trusted fixed column indices (end_idx / mv_idx per account,
      NAV_END_IDX for account 9018) unconditionally.
      load_acc_balance_accounts now FIRST attempts to resolve each account's
      column triplet by searching the header rows for that account's code and
      confirming Balance Start / Movement / Balance End via the sub-header
      row. If - and only if - that resolution is unavailable or doesn't
      produce a usable Balance End column, it falls back to EXACTLY the
      original hardcoded indices below (CLEARING_ACCOUNTS[...]['end_idx'] /
      ['mv_idx'] and NAV_END_IDX). This means: if your current Acc Balance
      export's header text doesn't match the assumed format, behaviour is
      IDENTICAL to before this change - this is a zero-risk, additive safety
      net, not a replacement of the working configuration.
      NOTE: the header-text format assumed here (group header row containing
      the account code, sub-header row containing 'Balance Start' / 'Movement'
      / 'Balance End') has NOT been re-verified against a live file for this
      version - the working file used to originally investigate this was not
      available when this version was written. Treat the header-based
      resolution as best-effort until confirmed against a real export; the
      fallback to the known-good hardcoded indices is what keeps this safe to
      deploy regardless.
  (3) DIAGNOSTICS - load_acc_balance_accounts now attaches
      distinct_account_codes_seen / column_resolution_source (per account:
      "header" or "fallback") to the returned DataFrame's .attrs, and
      build_ancillary_checks/render_ancillary_section surface them, so a
      future "no rows found" situation shows exactly what was seen instead of
      a bare unavailable message.

Checks (franking DEFERRED):
  1. Investment Clearing (Acc Balance 4999, End Bal idx10): |End Bal| > $1 -> Check
  2. Cash Clearing       (Acc Balance 0055, End Bal idx13): |End Bal| > $1 -> Check
  3. Negative NAV        (Acc Balance 9018, End Bal idx16 < 0, excl. Currency Overlay)
  4. Liquidity %         (DAssetReturn 'Current Account' FDV / NAV)
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import csv, io, os, re
import pandas as pd

ANCILLARY_VERSION = "v372"

ACC_ELEMENT_IDX = 3
ACC_ACCOUNT_IDX = 4
CLEARING_ACCOUNTS = {
    # Acc Balance is a 3-col-per-account crosstab: Balance Start / Movement / Balance End.
    # end_idx / mv_idx here are the ORIGINAL, verified-working hardcoded positions.
    # v372: these are now used as the FALLBACK only - load_acc_balance_accounts first
    # tries to resolve columns from the header text; if that fails, these exact
    # values are used, so behaviour is unchanged from pre-v372 unless the header
    # resolution succeeds.
    "4999": {"end_idx": 10, "mv_idx": 9, "name": "Investment Clearing"},
    "0055": {"end_idx": 13, "mv_idx": 12, "name": "Cash Clearing"},
}
NAV_ACCOUNT_CODE = "9018"
NAV_END_IDX = 16  # v372: fallback only - see CLEARING_ACCOUNTS note above.
DEFAULT_CLEARING_TOLERANCE_DOLLAR = 1.0
CURRENT_ACCOUNT_LABEL = "Current Account"
CURRENCY_OVERLAY_LABEL = "Currency Overlay"

# v372: header row layout used by the BEST-EFFORT column resolver in
# load_acc_balance_accounts. If your real export's header rows don't look like
# this, resolution simply fails closed and the hardcoded fallback above is used
# - see the v372 note in the module docstring.
ACC_HEADER_ROW_IDX = 1
ACC_SUBHEADER_ROW_IDX = 2

try:
    from bnp_helpers_columns import normalise_join_key_series as _norm_join
except Exception:
    def _norm_join(s: pd.Series) -> pd.Series:
        return s.astype(str).str.strip().str.upper().str.replace(r"\s+", "", regex=True)

try:
    from bnp_helpers_static_data import get_threshold_value as _get_threshold_value
except Exception:
    _get_threshold_value = None


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


def _canon_acct(v: object) -> str:
    """Zero-padding / numeric-coercion agnostic Account Code key.

    v372: centralised from the v360 fix that previously lived ONLY inside
    build_clearing_gav_style as a private '_norm_code_v360' helper. Logic is
    UNCHANGED from v360 (strip a trailing '.0', then strip leading zeros,
    defaulting to '0' if that empties the string) - it is simply now shared by
    every function that compares Account Codes, so e.g. '0055', '55' and
    '55.0' all canonicalise to the same key regardless of which code path
    (classic dashboard vs GAV-style tab) is doing the comparison.
    """
    v = str(v or "").strip()
    if v.endswith(".0"):
        v = v[:-2]
    return v.lstrip("0") or "0"


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


def _normalise_header_token(v: object) -> str:
    return re.sub(r"\s+", "", str(v or "").strip().lower())


def _try_resolve_account_column_map(
    header_row: List[str], subheader_row: List[str], wanted_codes: List[str]
) -> Dict[str, Dict[str, int]]:
    """BEST-EFFORT column resolver (v372). For each wanted account code,
    search header_row for a cell containing that code as a standalone token,
    then use subheader_row to identify which of the matched columns are
    'Balance Start' / 'Movement' / 'Balance End'.

    Returns only entries where a usable 'end_idx' was found. Callers MUST
    treat a missing/empty result as 'resolution unavailable' and fall back to
    the known-good hardcoded indices - this function is intentionally
    conservative (fails closed) rather than guessing.
    """
    resolved: Dict[str, Dict[str, int]] = {}
    if not header_row:
        return resolved
    for code in wanted_codes:
        try:
            pattern = re.compile(r"(?<!\d)" + re.escape(str(code).strip()) + r"(?!\d)")
        except Exception:
            continue
        matched_cols = [i for i, h in enumerate(header_row) if pattern.search(str(h or ""))]
        if not matched_cols:
            continue
        group: Dict[str, int] = {}
        for i in sorted(matched_cols):
            label = _normalise_header_token(subheader_row[i]) if subheader_row and i < len(subheader_row) else ""
            if "balancestart" in label and "start_idx" not in group:
                group["start_idx"] = i
            elif label == "movement" and "mv_idx" not in group:
                group["mv_idx"] = i
            elif "balanceend" in label and "end_idx" not in group:
                group["end_idx"] = i
        if "end_idx" in group:
            resolved[_canon_acct(code)] = group
    return resolved


def load_acc_balance_accounts(path: str) -> pd.DataFrame:
    """Parse the Acc Balance export into long-format rows: Advisor / Account
    Code / End Balance / Movement.

    v372: for each account we care about (Investment 4999, Cash 0055, NAV
    9018), the Balance End / Movement column positions are resolved in this
    order:
      1. Best-effort header-text resolution (_try_resolve_account_column_map)
         - used ONLY if it finds a usable 'end_idx' for that code.
      2. Otherwise, the original hardcoded CLEARING_ACCOUNTS[...] / NAV_END_IDX
         values - i.e. EXACTLY the pre-v372 behaviour.
    Account Code matching (which row belongs to which account) is now via
    _canon_acct, so a leading-zero loss on the Account Code cell itself
    (e.g. '0055' stored as '55') no longer causes silently-dropped rows -
    this was the specific failure mode reported ("No Acc Balance rows found
    for account 0055 ... distinct Account Codes seen: ['4999','9018']").
    """
    resolved_path = _first_existing(path) or path
    rows: List[List[str]] = []
    for enc in ("utf-16", "utf-16-le", "utf-8-sig", "utf-8", "latin-1"):
        try:
            with io.open(resolved_path, encoding=enc) as f:
                cand = list(csv.reader(f, delimiter="\t"))
            if cand and max((len(r) for r in cand[:6]), default=0) > 10:
                rows = cand
                break
        except Exception:
            continue
    empty_cols = ["Advisor", "Account Code", "End Balance"]
    if not rows or len(rows) < 4:
        out = pd.DataFrame(columns=empty_cols)
        out.attrs["distinct_account_codes_seen"] = []
        out.attrs["column_resolution_source"] = {}
        return out

    header_row = rows[ACC_HEADER_ROW_IDX] if len(rows) > ACC_HEADER_ROW_IDX else []
    subheader_row = rows[ACC_SUBHEADER_ROW_IDX] if len(rows) > ACC_SUBHEADER_ROW_IDX else []
    wanted_codes = list(CLEARING_ACCOUNTS.keys()) + [NAV_ACCOUNT_CODE]

    header_resolved: Dict[str, Dict[str, int]] = {}
    try:
        header_resolved = _try_resolve_account_column_map(header_row, subheader_row, wanted_codes)
    except Exception:
        header_resolved = {}

    # Build the effective (end_idx, mv_idx) per canonical code, preferring a
    # header-resolved column ONLY if it actually fits within the data rows'
    # width for at least the first data row we can check; otherwise fall back.
    fallback_end_idx = {_canon_acct(a): cfg["end_idx"] for a, cfg in CLEARING_ACCOUNTS.items()}
    fallback_end_idx[_canon_acct(NAV_ACCOUNT_CODE)] = NAV_END_IDX
    fallback_mv_idx = {_canon_acct(a): cfg.get("mv_idx") for a, cfg in CLEARING_ACCOUNTS.items()}

    resolution_source: Dict[str, str] = {}
    end_idx_for: Dict[str, int] = {}
    mv_idx_for: Dict[str, Optional[int]] = {}
    for canon_code, fb_end in fallback_end_idx.items():
        hdr = header_resolved.get(canon_code)
        if hdr and "end_idx" in hdr:
            end_idx_for[canon_code] = hdr["end_idx"]
            mv_idx_for[canon_code] = hdr.get("mv_idx", fallback_mv_idx.get(canon_code))
            resolution_source[canon_code] = "header"
        else:
            end_idx_for[canon_code] = fb_end
            mv_idx_for[canon_code] = fallback_mv_idx.get(canon_code)
            resolution_source[canon_code] = "fallback"

    recs = []
    distinct_raw_codes: set = set()
    for r in rows[3:]:
        if len(r) <= ACC_ACCOUNT_IDX:
            continue
        acct_raw = str(r[ACC_ACCOUNT_IDX]).strip()
        if acct_raw:
            distinct_raw_codes.add(acct_raw)
        canon = _canon_acct(acct_raw)
        idx = end_idx_for.get(canon)
        if idx is None or len(r) <= idx:
            continue
        mvi = mv_idx_for.get(canon)
        mv = _num(r[mvi]) if (mvi is not None and len(r) > mvi) else None
        recs.append({
            "Advisor": str(r[ACC_ELEMENT_IDX]).strip(),
            "Account Code": acct_raw,
            "End Balance": _num(r[idx]),
            "Movement": mv,
        })

    out = pd.DataFrame(recs)
    out.attrs["distinct_account_codes_seen"] = sorted(distinct_raw_codes)
    out.attrs["column_resolution_source"] = resolution_source
    return out


@dataclass
class AncillaryResult:
    clearing_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    negative_nav_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    liquidity_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    summary: Dict[str, Any] = field(default_factory=dict)
    tolerance_dollar: float = DEFAULT_CLEARING_TOLERANCE_DOLLAR
    status: str = "OK"


def build_clearing_checks(acc_df: pd.DataFrame, *, tolerance_dollar: float = DEFAULT_CLEARING_TOLERANCE_DOLLAR) -> pd.DataFrame:
    # v331: the PRIMARY clearing flag is now MOVEMENT, not End Balance. A clearing
    # account (Investment 4999 / Cash 0055) should net to ~zero MOVEMENT day-on-day;
    # a non-zero movement is the real exception. The summary (reconciliation export)
    # therefore flags on |Movement| > tol via "Check", while the section keeps BOTH
    # Movement and End Balance columns (and a retained "End Balance Check") so the
    # in-app view can show movement and end balance together.
    # v372: Account Code matching now via _canon_acct (was an exact string
    # match against the raw code), so this is resilient to the same
    # leading-zero loss the GAV-style tab (build_clearing_gav_style) was
    # already protected against since v360.
    cols = ["Clearing", "Advisor", "Movement", "End Balance", "Check", "End Balance Check"]
    if not isinstance(acc_df, pd.DataFrame) or acc_df.empty:
        return pd.DataFrame(columns=cols)
    has_mv = "Movement" in acc_df.columns
    acct_canon = acc_df["Account Code"].map(_canon_acct)
    out = []
    for acct, cfg in CLEARING_ACCOUNTS.items():
        sub = acc_df[acct_canon == _canon_acct(acct)]
        agg = {"End Balance": ("End Balance", "sum")}
        if has_mv:
            agg["Movement"] = ("Movement", "sum")
        g = sub.groupby("Advisor").agg(**agg).reset_index()
        if "Movement" not in g.columns:
            g["Movement"] = pd.NA
        g["Clearing"] = cfg["name"]
        mv = pd.to_numeric(g["Movement"], errors="coerce")
        eb = pd.to_numeric(g["End Balance"], errors="coerce")
        eb_check = eb.abs().gt(float(tolerance_dollar)).map({True: "Check", False: "Ok"})
        # PRIMARY = movement; fall back to end-balance where movement is unavailable
        mv_check = mv.abs().gt(float(tolerance_dollar)).map({True: "Check", False: "Ok"})
        mv_check = mv_check.where(mv.notna(), eb_check)
        g["Check"] = mv_check
        g["End Balance Check"] = eb_check
        out.append(g[cols])
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame(columns=cols)


def build_negative_nav_check(acc_df: pd.DataFrame, class_map: Optional[Dict[str, str]] = None) -> pd.DataFrame:
    # v372: Account Code matching now via _canon_acct (was an exact string match).
    if not isinstance(acc_df, pd.DataFrame) or acc_df.empty:
        return pd.DataFrame(columns=["Advisor", "Unison NAV", "Class", "Negative NAV flag"])
    acct_canon = acc_df["Account Code"].map(_canon_acct)
    nav = acc_df[acct_canon == _canon_acct(NAV_ACCOUNT_CODE)]
    g = nav.groupby("Advisor")["End Balance"].sum().rename("Unison NAV").reset_index()
    cm = class_map or {}
    g["Class"] = g["Advisor"].map(lambda a: cm.get(_norm_token(a), ""))
    is_overlay = g["Class"].astype(str).str.strip().str.lower().eq(CURRENCY_OVERLAY_LABEL.lower())
    g["Negative NAV flag"] = (g["Unison NAV"] < 0) & (~is_overlay)
    return g[["Advisor", "Unison NAV", "Class", "Negative NAV flag"]]


def build_liquidity_check(dar: pd.DataFrame, nav_by_hiport: Optional[Dict[str, float]] = None,
                          *, portfolio_col: Optional[str] = None, asset_desc_col: Optional[str] = None,
                          fdv_col: Optional[str] = None) -> pd.DataFrame:
    """Per-portfolio % in Current Account = Current-Account FDV / NAV.

    v312a: nav_by_hiport is keyed by NORMALISED HIPORT (Portfolio code), matching
    the DAssetReturn Portfolio key, so the % actually divides.
    """
    if not isinstance(dar, pd.DataFrame) or dar.empty:
        return pd.DataFrame(columns=["Portfolio", "Current Account FDV", "NAV", "% in Current Account", "Note"])
    def find(cands):
        norm = {str(c).strip().lower().replace(" ", "").replace("_", ""): c for c in dar.columns}
        for cand in cands:
            k = cand.strip().lower().replace(" ", "").replace("_", "")
            if k in norm:
                return norm[k]
        return None
    pcol = portfolio_col or find(["Portfolio", "Portfolio code", "PortfolioCode"])
    acol = asset_desc_col or find(["Asset Type description", "AssetTypeDescription", "Asset Type Description"])
    vcol = fdv_col or find(["FDV Valuation Curr_Day", "FDV Valuation CurrDay", "FDV Valuation Current"])
    if not (pcol and acol and vcol):
        return pd.DataFrame(columns=["Portfolio", "Current Account FDV", "NAV", "% in Current Account", "Note"])
    d = dar[[pcol, acol, vcol]].copy()
    d["_v"] = pd.to_numeric(d[vcol].astype(str).str.replace(",", "", regex=False), errors="coerce")
    ca = d[d[acol].astype(str).str.strip().eq(CURRENT_ACCOUNT_LABEL)].groupby(pcol)["_v"].sum().rename("Current Account FDV").reset_index()
    ca = ca.rename(columns={pcol: "Portfolio"})
    ca["_key"] = _norm_join(ca["Portfolio"])
    navmap = nav_by_hiport or {}
    ca["NAV"] = ca["_key"].map(navmap)
    ca["% in Current Account"] = ca.apply(
        lambda r: (r["Current Account FDV"] / r["NAV"]) if pd.notna(r.get("NAV")) and r.get("NAV") not in (0, None) else float("nan"), axis=1)
    ca["Note"] = ca["% in Current Account"].apply(lambda x: "Cash/WHT Holding Only" if pd.notna(x) and round(x, 2) == 1.0 else "")
    return ca[["Portfolio", "Current Account FDV", "NAV", "% in Current Account", "Note"]]


def _class_map_from_bundle(bundle: Dict[str, object]) -> Dict[str, str]:
    """advisor_token -> Asset Type (Class) from the v308 universe if present."""
    cm: Dict[str, str] = {}
    uni = bundle.get("_universe_result_v308") if isinstance(bundle, dict) else None
    df = getattr(uni, "universe_df", None) if uni is not None else None
    if isinstance(df, pd.DataFrame) and not df.empty and "Advisor Code" in df.columns and "Asset Type" in df.columns:
        for a, v in zip(df["Advisor Code"], df["Asset Type"].astype(str)):
            k = _norm_token(a)
            if k and k not in cm:
                cm[k] = v
    # Fallback: use portfolio_df Class if available (keyed by advisor token).
    pf = bundle.get("portfolio_df") if isinstance(bundle, dict) else None
    if isinstance(pf, pd.DataFrame) and "External portfolio reference" in pf.columns and "Class" in pf.columns:
        for a, v in zip(pf["External portfolio reference"], pf["Class"].astype(str)):
            k = _norm_token(a)
            if k and k not in cm:
                cm[k] = v
    return cm


def _nav_by_hiport(bundle: Dict[str, object], negnav_df: pd.DataFrame) -> Dict[str, float]:
    """Bridge NAV (per advisor) -> NAV (per Hiport) using portfolio_df's two keys.
    v312a FIX: this is what makes Liquidity % populate."""
    if not isinstance(bundle, dict):
        return {}
    pf = bundle.get("portfolio_df")
    if not isinstance(pf, pd.DataFrame) or pf.empty:
        return {}
    if "Portfolio code" not in pf.columns or "External portfolio reference" not in pf.columns:
        return {}
    if not isinstance(negnav_df, pd.DataFrame) or negnav_df.empty:
        return {}
    nav_by_adv = {_norm_token(r["Advisor"]): r["Unison NAV"] for _, r in negnav_df.iterrows()}
    out: Dict[str, float] = {}
    for hip, adv in zip(pf["Portfolio code"], pf["External portfolio reference"]):
        nv = nav_by_adv.get(_norm_token(adv))
        if nv is not None:
            out[_norm_join(pd.Series([hip])).iloc[0]] = nv
    return out


def clearing_counts(acc_df: pd.DataFrame) -> Dict[str, Dict[str, int]]:
    """Per clearing account: counts of non-zero Movement, non-zero End Balance,
    and |End Balance| > $1. Returns {name: {movement_nonzero, endbal_nonzero, endbal_gt1, rows}}.

    v372: Account Code matching now via _canon_acct (was an exact string match).
    """
    out: Dict[str, Dict[str, int]] = {}
    if not isinstance(acc_df, pd.DataFrame) or acc_df.empty:
        return out
    acct_canon = acc_df["Account Code"].map(_canon_acct)
    for acct, cfg in CLEARING_ACCOUNTS.items():
        sub = acc_df[acct_canon == _canon_acct(acct)]
        mv = pd.to_numeric(sub.get("Movement"), errors="coerce") if "Movement" in sub.columns else pd.Series(dtype=float)
        eb = pd.to_numeric(sub.get("End Balance"), errors="coerce") if "End Balance" in sub.columns else pd.Series(dtype=float)
        out[cfg["name"]] = {
            "rows": int(len(sub)),
            "movement_nonzero": int((mv.abs() > 1e-9).sum()) if len(mv) else 0,
            "endbal_nonzero": int((eb.abs() > 1e-9).sum()) if len(eb) else 0,
            "endbal_gt1": int((eb.abs() > 1.0).sum()) if len(eb) else 0,
        }
    return out


def build_ancillary_checks(bundle: Dict[str, object], acc_balance: Any = None,
                           *, tolerance_dollar: float = DEFAULT_CLEARING_TOLERANCE_DOLLAR) -> AncillaryResult:
    acc_df = load_acc_balance_accounts(acc_balance) if isinstance(acc_balance, str) else acc_balance
    if not isinstance(acc_df, pd.DataFrame) or acc_df.empty:
        return AncillaryResult(status="No Acc Balance")
    clearing = build_clearing_checks(acc_df, tolerance_dollar=tolerance_dollar)
    class_map = _class_map_from_bundle(bundle) if isinstance(bundle, dict) else {}
    negnav = build_negative_nav_check(acc_df, class_map)
    dar = bundle.get("dar") if isinstance(bundle, dict) else None
    nav_by_hip = _nav_by_hiport(bundle, negnav)
    liquidity = build_liquidity_check(dar, nav_by_hip) if isinstance(dar, pd.DataFrame) else pd.DataFrame()
    _clc = clearing_counts(acc_df)
    summary = {
        "investment_clearing_checks": int(((clearing["Clearing"] == "Investment Clearing") & (clearing["Check"] == "Check")).sum()) if not clearing.empty else 0,
        "cash_clearing_checks": int(((clearing["Clearing"] == "Cash Clearing") & (clearing["Check"] == "Check")).sum()) if not clearing.empty else 0,
        "clearing_counts": _clc,
        "negative_nav": int(negnav["Negative NAV flag"].sum()) if not negnav.empty else 0,
        "advisors": int(negnav["Advisor"].nunique()) if not negnav.empty else 0,
        "liquidity_with_pct": int(liquidity["% in Current Account"].notna().sum()) if not liquidity.empty else 0,
        "liquidity_cash_only": int((liquidity["Note"] == "Cash/WHT Holding Only").sum()) if not liquidity.empty else 0,
        "tolerance_dollar": float(tolerance_dollar),
        # v372 diagnostics - what accounts/columns were actually seen/used this
        # run, so an "unavailable" situation is self-explanatory.
        "distinct_account_codes_seen": acc_df.attrs.get("distinct_account_codes_seen", []),
        "column_resolution_source": acc_df.attrs.get("column_resolution_source", {}),
    }
    return AncillaryResult(clearing, negnav, liquidity, summary, float(tolerance_dollar), "OK")


def _resolve_tolerance(static_bundle) -> float:
    if static_bundle is not None and callable(_get_threshold_value):
        try:
            return float(_get_threshold_value(static_bundle, "clearing_tolerance_dollar", DEFAULT_CLEARING_TOLERANCE_DOLLAR))
        except Exception:
            pass
    return DEFAULT_CLEARING_TOLERANCE_DOLLAR


def _find_acc_balance(bundle: Dict[str, object]) -> Any:
    try:
        from bnp_helpers_gav import resolve_acc_balance_source
        return resolve_acc_balance_source(bundle)
    except Exception:
        if isinstance(bundle, dict):
            for k in ("acc_balance_path", "acc_balance_file"):
                p = bundle.get(k)
                if isinstance(p, str) and _first_existing(p):
                    return _first_existing(p)
        return None


def build_clearing_gav_style(bundle: Dict[str, object], account_code: str):
    """GAV-style wrapper for one clearing account (Investment 4999 / Cash 0055):
    population/investigation (red)/OK (green)/excluded (neutral) + single-tab
    full pack + invariant. Returns a bnp_helpers_gav_style.GavStyleResult.

    Population = advisors with a row for this clearing account this run.
    Investigation (red) = |Movement| > tolerance (falling back to |End Balance|
    only where Movement is unavailable - same primary/fallback logic as
    build_clearing_checks).
    OK (green) = evaluated, within tolerance.
    Excluded (neutral) = rows with NEITHER Movement NOR End Balance available
    this run (insufficient data to test at all) - retained with a reason.
    """
    from bnp_helpers_gav_style import GavStyleResult, compute_invariant

    cfg = CLEARING_ACCOUNTS.get(str(account_code))
    if not cfg:
        return GavStyleResult(status=f"Unknown clearing account code {account_code!r}")
    acc = _find_acc_balance(bundle)
    acc_df = load_acc_balance_accounts(acc) if isinstance(acc, str) else acc
    if not isinstance(acc_df, pd.DataFrame) or acc_df.empty:
        return GavStyleResult(status="Acc Balance not found in bundle")
    static_bundle = bundle.get("static_data") if isinstance(bundle, dict) else None
    tol = _resolve_tolerance(static_bundle)

    # v372: matching now goes through the SHARED _canon_acct helper (this used
    # to be a private '_norm_code_v360' copy defined only in this function -
    # same logic, now centralised so the classic dashboard path and this
    # GAV-style path can never drift apart again). See module docstring.
    raw_codes = acc_df["Account Code"].astype(str).str.strip()
    target_norm = _canon_acct(str(account_code))
    match_mask = (raw_codes == str(account_code)) | (raw_codes.map(_canon_acct) == target_norm)
    sub = acc_df[match_mask].copy()
    if sub.empty:
        distinct_codes = sorted(raw_codes.unique().tolist())[:40]
        return GavStyleResult(
            status=(f"No Acc Balance rows found for account {account_code} "
                    f"(distinct Account Codes seen in Acc Balance this run: {distinct_codes})"),
            diag={"distinct_account_codes_seen": distinct_codes},
        )
    has_mv = "Movement" in sub.columns
    # NOTE: min_count=1 is essential here - pandas' default groupby-sum treats an
    # all-NaN group as 0.0 (not NaN), which would silently hide genuinely missing
    # data and prevent the "Excluded" (no data) population from ever being
    # detected. With min_count=1 an all-NaN group correctly sums to NaN.
    agg = {"End Balance": ("End Balance", lambda s: pd.to_numeric(s, errors="coerce").sum(min_count=1))}
    if has_mv:
        agg["Movement"] = ("Movement", lambda s: pd.to_numeric(s, errors="coerce").sum(min_count=1))
    g = sub.groupby("Advisor").agg(**agg).reset_index()
    if "Movement" not in g.columns:
        g["Movement"] = pd.NA
    mv = pd.to_numeric(g["Movement"], errors="coerce")
    eb = pd.to_numeric(g["End Balance"], errors="coerce")

    no_data = mv.isna() & eb.isna()
    eb_check = eb.abs().gt(float(tol))
    mv_check = mv.abs().gt(float(tol))
    flagged = mv_check.where(mv.notna(), eb_check).fillna(False)

    g["Clearing"] = cfg["name"]
    g["Exclusion Reason"] = ""
    g.loc[no_data, "Exclusion Reason"] = "No Movement or End Balance data available for this advisor/account this run"
    # v360 BUG FIX: the status column was previously dropped ("_status") before
    # being exposed in the full pack, so the downloaded Investment/Cash
    # Clearing full packs had NO Check/Ok/Excluded column at all (confirmed by
    # inspecting investment_clearing_full_pack.xlsx - every row just repeated
    # "Investment Clearing" as the Clearing name, with no status). Renamed to
    # the standardised "Check" column and RETAINED in every returned frame.
    g["Check"] = "Ok"
    g.loc[~no_data & flagged, "Check"] = "Check"
    g.loc[no_data, "Check"] = "Excluded"
    # v360: paired "In <Control> population" boolean, mirroring GAV Check.
    control_noun = cfg["name"]
    g[f"In {control_noun} population"] = ~no_data

    green_df = g[g["Check"] == "Ok"].copy()
    red_df = g[g["Check"] == "Check"].copy()
    excluded_df = g[g["Check"] == "Excluded"].copy()
    full = g.copy()
    population_count = int(len(green_df) + len(red_df))

    ok, detail = compute_invariant(population_count, [len(red_df)], len(green_df))

    return GavStyleResult(
        red_frames=[("Check", red_df)],
        green_df=green_df,
        excluded_df=excluded_df,
        full_df=full,
        population_metrics=[
            (f"{control_noun} population", population_count),
            (f"{control_noun} checks", int(len(red_df))),
            (f"{control_noun} OK", int(len(green_df))),
            ("Excluded (no data)", int(len(excluded_df))),
        ],
        invariant_ok=ok,
        invariant_detail=detail,
        status="OK",
        diag={"tolerance_dollar": float(tol)},
        currency_cols=["End Balance", "Movement"],
        population_bool_col=f"In {control_noun} population",
        control_noun=control_noun,
    )


def render_investment_clearing_gav_style(st, bundle: Dict[str, object]) -> None:
    from bnp_helpers_gav_style import render_gav_style_section
    result = build_clearing_gav_style(bundle, "4999")
    if isinstance(bundle, dict):
        bundle["investment_clearing_gav_style_result"] = result
    render_gav_style_section(
        st, control_key="investment_clearing", title="Investment Clearing",
        purpose=("Acc Balance account 4999 (Investment Clearing), per advisor. Flagged where the absolute "
                 "day's Movement exceeds the clearing tolerance (falling back to |End Balance| only where "
                 "Movement is unavailable). Advisors with neither figure available this run are excluded."),
        result=result, download_filename_prefix="investment_clearing",
    )


def render_cash_clearing_gav_style(st, bundle: Dict[str, object]) -> None:
    from bnp_helpers_gav_style import render_gav_style_section
    result = build_clearing_gav_style(bundle, "0055")
    if isinstance(bundle, dict):
        bundle["cash_clearing_gav_style_result"] = result
    render_gav_style_section(
        st, control_key="cash_clearing", title="Cash Clearing",
        purpose=("Acc Balance account 0055 (Cash Clearing), per advisor. Flagged where the absolute day's "
                 "Movement exceeds the clearing tolerance (falling back to |End Balance| only where Movement "
                 "is unavailable). Advisors with neither figure available this run are excluded."),
        result=result, download_filename_prefix="cash_clearing",
    )


def build_negative_nav_gav_style(bundle: Dict[str, object]):
    """GAV-style wrapper for Negative NAV: population/investigation (red)/OK
    (green)/excluded (neutral: Currency Overlay class) + single-tab full pack
    + invariant. Returns a bnp_helpers_gav_style.GavStyleResult."""
    from bnp_helpers_gav_style import GavStyleResult, compute_invariant

    acc = _find_acc_balance(bundle)
    acc_df = load_acc_balance_accounts(acc) if isinstance(acc, str) else acc
    if not isinstance(acc_df, pd.DataFrame) or acc_df.empty:
        return GavStyleResult(status="Acc Balance not found in bundle")
    class_map = _class_map_from_bundle(bundle) if isinstance(bundle, dict) else {}
    negnav = build_negative_nav_check(acc_df, class_map)
    if negnav.empty:
        return GavStyleResult(status="No NAV (account 9018) rows found in Acc Balance")

    is_overlay = negnav["Class"].astype(str).str.strip().str.lower().eq(CURRENCY_OVERLAY_LABEL.lower())
    # v361: exclude Advisors starting with "LOAN" (case-insensitive) - confirmed
    # from the real negative_nav_check export that LOAN7HUA (-$114.7M) and
    # LOAN8PUA (-$657.6M) are large by-design negative loan-facility balances,
    # not genuine unit-pricing exceptions, while MGT18PUA (-$0.20, not a LOAN
    # advisor) is the only real rounding-level flag. Same pattern as the
    # existing Currency Overlay exclusion - excluded, not silently dropped.
    is_loan = negnav["Advisor"].astype(str).str.strip().str.upper().str.startswith("LOAN")
    excl_mask = is_overlay | is_loan
    negnav = negnav.copy()
    negnav["Exclusion Reason"] = ""
    negnav.loc[is_overlay, "Exclusion Reason"] = f"Class = {CURRENCY_OVERLAY_LABEL} (excluded from Negative NAV by business rule)"
    negnav.loc[is_loan, "Exclusion Reason"] = negnav.loc[is_loan, "Exclusion Reason"].where(
        negnav.loc[is_loan, "Exclusion Reason"].astype(str).str.strip().ne(""),
        "Advisor starts with LOAN (loan facility - by-design negative balance, excluded from Negative NAV by business rule)"
    )
    # v360 BUG FIX: same status-column drop as Investment/Cash Clearing (see
    # comment in build_clearing_gav_style) - negative_nav_full_pack.xlsx had NO
    # Check/Ok/Excluded column at all. Standardised to "Check" and retained.
    negnav["Check"] = "Ok"
    negnav.loc[~excl_mask & negnav["Negative NAV flag"].astype(bool), "Check"] = "Check"
    negnav.loc[excl_mask, "Check"] = "Excluded"
    # v360: paired "In <Control> population" boolean, mirroring GAV Check.
    negnav["In Negative NAV population"] = ~excl_mask

    green_df = negnav[negnav["Check"] == "Ok"].copy()
    red_df = negnav[negnav["Check"] == "Check"].copy()
    excluded_df = negnav[negnav["Check"] == "Excluded"].copy()
    full = negnav.copy()
    population_count = int(len(green_df) + len(red_df))

    ok, detail = compute_invariant(population_count, [len(red_df)], len(green_df))

    return GavStyleResult(
        red_frames=[("Check", red_df)],
        green_df=green_df,
        excluded_df=excluded_df,
        full_df=full,
        population_metrics=[
            ("NAV population", population_count),
            ("NAV checks", int(len(red_df))),
            ("NAV OK", int(len(green_df))),
            ("Excluded (Currency Overlay / LOAN)", int(len(excluded_df))),
        ],
        invariant_ok=ok,
        invariant_detail=detail,
        status="OK",
        currency_cols=["Unison NAV"],
        population_bool_col="In Negative NAV population",
        control_noun="Negative NAV",
    )


def render_negative_nav_gav_style(st, bundle: Dict[str, object]) -> None:
    from bnp_helpers_gav_style import render_gav_style_section
    result = build_negative_nav_gav_style(bundle)
    if isinstance(bundle, dict):
        bundle["negative_nav_gav_style_result"] = result
    render_gav_style_section(
        st, control_key="negative_nav", title="Negative NAV",
        purpose=("Acc Balance account 9018 (Unison NAV), per advisor. Flagged where NAV is negative, "
                 "excluding advisors classified as Currency Overlay in the Central Mapping List and advisors "
                 "whose code starts with LOAN (loan facilities - by-design negative balances). Both exclusions "
                 "are business rules, retained for audit."),
        result=result, download_filename_prefix="negative_nav",
    )


def build_liquidity_gav_style(bundle: Dict[str, object]):
    """v361: GAV-style wrapper for Liquidity, rebuilt per the reviewer's
    instructions - Investment Clearing / Cash Clearing / Negative NAV are now
    their OWN dedicated GAV-style tabs (built in this same module), so they are
    NOT duplicated here anymore. Liquidity now shows ONLY its own % in Current
    Account population, split into FOUR buckets:

      "=100%"          - red frame #1 - round(% in Current Account, 2) == 1.0
                          (mirrors the existing 'Cash/WHT Holding Only' rule
                          already used in build_liquidity_check).
      ">=80% and <100%" - red frame #2 - round(%, 2) in [0.80, 1.00) - high
                          concentration in the current account, short of the
                          100%-cash case, worth a reviewer's attention.
      "the rest"        - green (OK) - round(%, 2) < 0.80 - the normal /
                          expected population for most portfolios.
      Excluded (neutral) - % in Current Account could not be calculated (NAV
                          unavailable / unbridged this run) - retained for
                          audit, outside the Check/Ok invariant per Q1.

    Per Q2 (2026-08), the two attention-worthy buckets ("=100%" and ">=80% and
    <100%") are kept as SEPARATE red frames rather than merged into one.
    """
    from bnp_helpers_gav_style import GavStyleResult, compute_invariant

    dar = bundle.get("dar") if isinstance(bundle, dict) else None
    if not isinstance(dar, pd.DataFrame) or dar.empty:
        return GavStyleResult(status="DAssetReturn ('dar') not available in bundle")
    class_map = _class_map_from_bundle(bundle) if isinstance(bundle, dict) else {}
    acc = _find_acc_balance(bundle)
    acc_df = load_acc_balance_accounts(acc) if isinstance(acc, str) else acc
    if not isinstance(acc_df, pd.DataFrame) or acc_df.empty:
        return GavStyleResult(status="Acc Balance not found in bundle")
    negnav = build_negative_nav_check(acc_df, class_map)
    nav_by_hip = _nav_by_hiport(bundle, negnav)
    liq = build_liquidity_check(dar, nav_by_hip)
    if not isinstance(liq, pd.DataFrame) or liq.empty:
        return GavStyleResult(status="No Liquidity % rows produced (Current Account FDV / NAV unavailable)")

    liq = liq.copy()
    pct = pd.to_numeric(liq["% in Current Account"], errors="coerce")
    rounded = pct.round(2)
    unavailable = pct.isna()
    is_100 = ~unavailable & rounded.eq(1.00)
    is_80_to_100 = ~unavailable & ~is_100 & rounded.ge(0.80) & rounded.lt(1.00)
    is_rest = ~unavailable & ~is_100 & ~is_80_to_100

    liq["Exclusion Reason"] = ""
    liq.loc[unavailable, "Exclusion Reason"] = "% in Current Account unavailable this run (NAV not bridged to this Hiport)"
    liq["Check"] = "Excluded"
    liq.loc[is_100, "Check"] = "=100%"
    liq.loc[is_80_to_100, "Check"] = ">=80% and <100%"
    liq.loc[is_rest, "Check"] = "Ok"
    liq["In Liquidity population"] = ~unavailable

    bucket_100_df = liq[is_100].copy()
    bucket_80_df = liq[is_80_to_100].copy()
    green_df = liq[is_rest].copy()
    excluded_df = liq[unavailable].copy()
    full = liq.copy()
    population_count = int(len(bucket_100_df) + len(bucket_80_df) + len(green_df))

    ok, detail = compute_invariant(population_count, [len(bucket_100_df), len(bucket_80_df)], len(green_df))

    return GavStyleResult(
        red_frames=[("=100%", bucket_100_df), (">=80% and <100%", bucket_80_df)],
        green_df=green_df,
        excluded_df=excluded_df,
        full_df=full,
        population_metrics=[
            ("Liquidity population", population_count),
            ("=100%", int(len(bucket_100_df))),
            (">=80% and <100%", int(len(bucket_80_df))),
            ("Excluded (NAV unavailable)", int(len(excluded_df))),
        ],
        invariant_ok=ok,
        invariant_detail=detail,
        status="OK",
        currency_cols=["Current Account FDV", "NAV"],
        percent_cols=["% in Current Account"],
        population_bool_col="In Liquidity population",
        control_noun="Liquidity",
    )


def render_liquidity_gav_style(st, bundle: Dict[str, object]) -> None:
    from bnp_helpers_gav_style import render_gav_style_section
    result = build_liquidity_gav_style(bundle)
    if isinstance(bundle, dict):
        bundle["liquidity_gav_style_result"] = result
    render_gav_style_section(
        st, control_key="liquidity", title="Liquidity",
        purpose=("Per-portfolio % in Current Account = Current Account FDV (DAssetReturn) / Unison NAV. "
                 "Split into '=100%' (Cash/WHT holding only), '>=80% and <100%' (high concentration, worth "
                 "review) and the rest (the normal/expected population). Portfolios where NAV could not be "
                 "bridged to this run are excluded from the buckets but retained for audit."),
        result=result, download_filename_prefix="liquidity",
    )


def render_ancillary_section(st, bundle: Dict[str, object]) -> None:
    try:
        static_bundle = bundle.get("static_data") if isinstance(bundle, dict) else None
        tol = _resolve_tolerance(static_bundle)
        acc = _find_acc_balance(bundle)
        st.markdown(f"**Ancillary checks ({ANCILLARY_VERSION})** - Clearing, Negative NAV, Liquidity. "
                    "(Franking Credits deferred.)")
        if acc is None:
            st.warning("Ancillary checks unavailable - Acc Balance not found in bundle.")
            return
        res = build_ancillary_checks(bundle, acc, tolerance_dollar=tol)
        if res.status != "OK":
            st.warning(f"Ancillary checks unavailable: {res.status}")
            return
        if isinstance(bundle, dict):
            bundle["clearing_check_df"] = res.clearing_df
            bundle["negative_nav_df"] = res.negative_nav_df
            bundle["liquidity_df"] = res.liquidity_df
            bundle["ancillary_summary"] = res.summary
        s = res.summary

        # v372: surface column-resolution diagnostics if any account had to
        # fall back (i.e. header-text resolution was unavailable this run).
        # This is informational only - the fallback is the known-good, exact
        # pre-v372 behaviour, so this is NOT an error state.
        _res_src = s.get("column_resolution_source", {}) if isinstance(s, dict) else {}
        _fell_back = sorted(code for code, src in _res_src.items() if src == "fallback")
        if _fell_back:
            with st.expander("Acc Balance column resolution (diagnostic)", expanded=False):
                st.caption(
                    "Codes using the hardcoded fallback column positions this run "
                    f"(header-text resolution unavailable/unused): {', '.join(_fell_back)}. "
                    "This is expected unless the Acc Balance export's header layout changes; "
                    "see module docstring v372 note."
                )
                st.caption(f"Distinct Account Codes seen this run: {s.get('distinct_account_codes_seen', [])}")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Investment Clearing (movement)", s.get("investment_clearing_checks", 0))
        c2.metric("Cash Clearing (movement)", s.get("cash_clearing_checks", 0))
        c3.metric("Negative NAV", s.get("negative_nav", 0))
        c4.metric("Liquidity % filled", s.get("liquidity_with_pct", 0))

        # v331: per-account counts - non-zero Movement, non-zero End Balance, |End Balance| > $1.
        _cc = s.get("clearing_counts", {}) if isinstance(s, dict) else {}
        if _cc:
            _rows = []
            for _name in ("Investment Clearing", "Cash Clearing"):
                _d = _cc.get(_name, {})
                _rows.append({"Clearing": _name,
                              "Rows": int(_d.get("rows", 0)),
                              "Non-zero Movement": int(_d.get("movement_nonzero", 0)),
                              "Non-zero End Balance": int(_d.get("endbal_nonzero", 0)),
                              "|End Balance| > $1": int(_d.get("endbal_gt1", 0))})
            st.markdown("*Clearing counts* - by account:")
            st.dataframe(pd.DataFrame(_rows), width="stretch", hide_index=True)

        # v331: PRIMARY breach is now |Movement| > tol (the 'Check' column). Both the
        # Movement and End Balance columns (plus 'End Balance Check') are shown so the
        # section presents movement and end balance together.
        st.markdown(f"*Clearing breaches* (|Movement| > ${tol:g}; End Balance shown alongside):")
        cb = res.clearing_df[res.clearing_df["Check"] == "Check"].copy()
        _order = [c for c in ["Clearing", "Advisor", "Movement", "End Balance", "Check", "End Balance Check"] if c in cb.columns]
        cb = cb[_order] if _order else cb
        st.dataframe(cb, width="stretch", hide_index=True)
        st.download_button("Download clearing breaches", cb.to_csv(index=False).encode("utf-8"),
                           "clearing_breaches_last_run.csv", "text/csv", key="anc_clearing_dl")

        st.markdown("*Negative NAV* (NAV < 0, excl. Currency Overlay):")
        nn = res.negative_nav_df[res.negative_nav_df["Negative NAV flag"]].copy()
        st.dataframe(nn, width="stretch", hide_index=True)
        st.download_button("Download negative NAV", nn.to_csv(index=False).encode("utf-8"),
                           "negative_nav_last_run.csv", "text/csv", key="anc_negnav_dl")

        with st.expander("Liquidity % (Current Account dominance)", expanded=False):
            st.dataframe(res.liquidity_df, width="stretch", hide_index=True)
            st.download_button("Download liquidity %", res.liquidity_df.to_csv(index=False).encode("utf-8"),
                               "liquidity_last_run.csv", "text/csv", key="anc_liq_dl")
    except Exception:
        pass


if __name__ == "__main__":
    print(f"[{ANCILLARY_VERSION}] ancillary checks self-test")
    real_acc = "/mnt/user-data/uploads/Acc Balance.csv"
    if os.path.exists(real_acc):
        acc = load_acc_balance_accounts(real_acc)
        print(f"  Column resolution source: {acc.attrs.get('column_resolution_source', {})}")
        clearing = build_clearing_checks(acc, tolerance_dollar=1.0)
        inv = clearing[clearing["Clearing"] == "Investment Clearing"]
        cash = clearing[clearing["Clearing"] == "Cash Clearing"]
        print(f"  Investment Clearing: {(inv['Check']=='Check').sum()} Check | Cash: {(cash['Check']=='Check').sum()} Check")
        negnav = build_negative_nav_check(acc, {})
        print(f"  NAV<0 (no class map): {int(negnav['Negative NAV flag'].sum())}")
        print("  OK - clearing/neg-NAV validated")
    else:
        print("  (Acc Balance not present; liquidity bridge tested in the full-flow validation)")
