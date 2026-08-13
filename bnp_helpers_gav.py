# -*- coding: utf-8 -*-
"""
bnp_helpers_gav.py  (v309 GAV Check; v309.1 Acc Balance path-resolver fix)

PURPOSE
-------
Replicates the legacy workbook GAV Check (Unison vs BNP return check, cols I..N):

    I  Unison NAV   = SUMIFS('Acc Balance'!Q:Q, D:D=Advisor, E:E="9018")   (NAV)
    J  Deferred Tax = SUMIFS('Acc Balance'!W:W, D:D=Advisor, E:E="2500")
    K  BNP GAV      = SUMIF(DAssetReturn!C:C=Hiport, DAssetReturn!W:W)       (FDV Val Curr_Day)
    L  GAV Diff     = I - J - K
    M  % impact     = IF(ABS(I) > 2, L / I, 0)
    N  Check        = IF(ABS(M) > 0.01%, "Check", "Ok")

KEYS (approach (a); advisor<->Hiport is 1:1 so no reconciliation needed)
    * NAV and Deferred Tax key on the ADVISOR code
      (portfolio_df["External portfolio reference"] == Acc Balance Element Code).
    * BNP GAV keys on the HIPORT / Portfolio code
      (portfolio_df["Portfolio code"] == DAssetReturn Portfolio).

v309.1 FIX
----------
The app's generic Tableau CSV reader only tries utf-8/cp1252/latin1 and CANNOT
read the Acc Balance crosstab, which is UTF-16 / tab-delimited / 3 header rows.
As a result bundle["acc_balance_df"] arrives EMPTY and the panel reported
"source not found". This module now RESOLVES THE ACC BALANCE FILE PATH from the
Tableau metadata already in the bundle (tableau_file_meta_df ExpectedPath/
ResolvedPath for ReportKey="acc_balance", or tableau_folder + "Acc Balance.csv",
or Static Data source_reports) and loads it with the robust UTF-16-aware
load_acc_balance() below. No app change and no change to bnp_helpers_tableau.py.

DATA CONTRACTS (verified against real 2026-07-31 extracts)
    Acc Balance.csv : UTF-16, TAB-delimited, 3 header rows. Field-row columns by
        position: idx3 Element Code (advisor), idx4 Account Code, idx16 Balance
        End (holds 9018 NAV), idx22 Balance End (holds 2500 Deferred Tax).
    DAssetReturn    : 2 preamble lines then header; Portfolio = col C;
        FDV Valuation Curr_Day = col W. BNP GAV = sum FDV Valuation Curr_Day.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import csv, io, os
from io import BytesIO
import pandas as pd

GAV_VERSION = "v309.4"

NAV_ACCOUNT_CODE = "9018"
DEFERRED_TAX_ACCOUNT_CODE = "2500"
ACC_ELEMENT_IDX = 3
ACC_ACCOUNT_IDX = 4
ACC_NAV_VALUE_IDX = 16
ACC_DEFTAX_VALUE_IDX = 22
DEFAULT_GAV_TOLERANCE_PCT = 0.01
ACC_BALANCE_FILENAME = "Acc Balance.csv"

try:
    from bnp_helpers_columns import normalise_join_key_series as _norm_join
except Exception:
    def _norm_join(s: pd.Series) -> pd.Series:
        return s.astype(str).str.strip().str.upper().str.replace(r"\s+", "", regex=True)

try:
    from bnp_helpers_static_data import (
        get_threshold_value as _get_threshold_value,
        get_active_table as _get_active_table,
        get_config_value as _get_config_value,
    )
except Exception:
    _get_threshold_value = None
    _get_active_table = None
    _get_config_value = None


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


def _root_variants(path: str) -> List[str]:
    p = str(path or "").strip()
    if not p:
        return []
    bs = chr(92); variants = [p]
    if p.upper().startswith("G:" + bs):
        variants.append(bs + bs + "hq.local" + bs + "Corp" + bs + p[3:].lstrip(bs))
    elif p.lower().startswith((bs + bs + "hq.local" + bs + "corp" + bs).lower()):
        variants.append("G:" + bs + p[len(bs + bs + "hq.local" + bs + "Corp" + bs):])
    out, seen = [], set()
    for v in variants:
        if v.lower() not in seen:
            seen.add(v.lower()); out.append(v)
    return out


def _first_existing(path: str) -> str:
    for cand in _root_variants(path):
        if cand and os.path.exists(cand):
            return cand
    return ""


# ---------------------------------------------------------------------------
# Source loaders / aggregators
# ---------------------------------------------------------------------------
def load_acc_balance(path: str) -> pd.DataFrame:
    """Read the raw Acc Balance crosstab into a tidy per-row frame.

    Robust to the UTF-16 / tab / 3-header-row Tableau layout. Returns columns:
    Advisor, Account Code, NAV Value (idx16), DefTax Value (idx22).
    """
    resolved = _first_existing(path) or path
    encodings = ["utf-16", "utf-16-le", "utf-8-sig", "utf-8", "latin-1"]
    rows: List[List[str]] = []
    for enc in encodings:
        try:
            with io.open(resolved, encoding=enc) as f:
                cand = list(csv.reader(f, delimiter="\t"))
            # Valid only if the tab split produced the wide crosstab.
            if cand and max((len(r) for r in cand[:6]), default=0) > 10:
                rows = cand
                break
        except Exception:
            continue
    if not rows or len(rows) < 4:
        return pd.DataFrame(columns=["Advisor", "Account Code", "NAV Value", "DefTax Value"])
    data = rows[3:]
    recs = []
    for r in data:
        if len(r) <= ACC_DEFTAX_VALUE_IDX:
            continue
        recs.append({
            "Advisor": str(r[ACC_ELEMENT_IDX]).strip(),
            "Account Code": str(r[ACC_ACCOUNT_IDX]).strip(),
            "NAV Value": _num(r[ACC_NAV_VALUE_IDX]),
            "DefTax Value": _num(r[ACC_DEFTAX_VALUE_IDX]),
        })
    return pd.DataFrame(recs)


def aggregate_unison_nav_deftax(acc_df: pd.DataFrame) -> pd.DataFrame:
    """Per-advisor Unison NAV (acct 9018) and Deferred Tax (acct 2500)."""
    if not isinstance(acc_df, pd.DataFrame) or acc_df.empty or "Account Code" not in acc_df.columns:
        return pd.DataFrame(columns=["Advisor norm", "Advisor", "Unison NAV", "Deferred Tax"])
    acc = acc_df.copy()
    acc["_acct"] = acc["Account Code"].astype(str).str.strip()
    nav = (acc.loc[acc["_acct"] == NAV_ACCOUNT_CODE]
              .groupby("Advisor")["NAV Value"].sum().rename("Unison NAV"))
    dtx = (acc.loc[acc["_acct"] == DEFERRED_TAX_ACCOUNT_CODE]
              .groupby("Advisor")["DefTax Value"].sum().rename("Deferred Tax"))
    out = pd.concat([nav, dtx], axis=1).reset_index()
    out["Advisor norm"] = _norm_join(out["Advisor"])
    out["Unison NAV"] = pd.to_numeric(out["Unison NAV"], errors="coerce").fillna(0.0)
    out["Deferred Tax"] = pd.to_numeric(out["Deferred Tax"], errors="coerce").fillna(0.0)
    return out[["Advisor norm", "Advisor", "Unison NAV", "Deferred Tax"]]


def _resolve_dar_columns(dar: pd.DataFrame):
    if not isinstance(dar, pd.DataFrame) or dar.empty:
        return None, None
    def find(cands):
        norm = {str(c).strip().lower().replace(" ", "").replace("_", ""): c for c in dar.columns}
        for cand in cands:
            k = cand.strip().lower().replace(" ", "").replace("_", "")
            if k in norm:
                return norm[k]
        return None
    port = find(["Portfolio", "Portfolio code", "PortfolioCode"])
    fdv = find(["FDV Valuation Curr_Day", "FDV Valuation CurrDay", "FDV Valuation Current",
                "FDV Valuation Curr Day", "FDVValuationCurrDay"])
    return port, fdv


def aggregate_bnp_gav(dar: pd.DataFrame) -> pd.DataFrame:
    port, fdv = _resolve_dar_columns(dar)
    if port is None or fdv is None:
        return pd.DataFrame(columns=["Hiport norm", "BNP GAV"])
    d = dar[[port, fdv]].copy()
    d["_val"] = pd.to_numeric(d[fdv].astype(str).str.replace(",", "", regex=False), errors="coerce")
    g = d.groupby(port)["_val"].sum().rename("BNP GAV").reset_index()
    g["Hiport norm"] = _norm_join(g[port])
    g["BNP GAV"] = pd.to_numeric(g["BNP GAV"], errors="coerce").fillna(0.0)
    return g[["Hiport norm", "BNP GAV"]]


# ---------------------------------------------------------------------------
# Central Mapping class enrichment
# ---------------------------------------------------------------------------
def enrich_portfolio_class_from_mapping(portfolio_df: pd.DataFrame, bundle: Optional[Dict[str, object]] = None) -> pd.DataFrame:
    """Populate portfolio Class from Central Mapping Asset Type.

    The normalised Hiport code is primary; advisor code is a guarded fallback.
    Existing non-blank Class values are retained. The mapping is obtained from the
    cached universe result when available, otherwise loaded from Static Data's
    central_mapping_workbook path.
    """
    if not isinstance(portfolio_df, pd.DataFrame) or portfolio_df.empty:
        return portfolio_df.copy() if isinstance(portfolio_df, pd.DataFrame) else pd.DataFrame()
    out = portfolio_df.copy()
    if "Class" not in out.columns:
        out["Class"] = ""
    mapping = pd.DataFrame()
    try:
        uni_res = bundle.get("_universe_result_v308") if isinstance(bundle, dict) else None
        candidate = getattr(uni_res, "universe_df", None) if uni_res is not None else None
        if isinstance(candidate, pd.DataFrame) and not candidate.empty:
            mapping = candidate.copy()
        else:
            from bnp_helpers_universe import load_universe
            uni_res = load_universe(bundle.get("static_data") if isinstance(bundle, dict) else None)
            candidate = getattr(uni_res, "universe_df", None)
            if isinstance(candidate, pd.DataFrame) and not candidate.empty:
                mapping = candidate.copy()
                if isinstance(bundle, dict):
                    bundle["_universe_result_v308"] = uni_res
    except Exception:
        mapping = pd.DataFrame()
    if mapping.empty or "Asset Type" not in mapping.columns:
        return out

    if "Hiport Code norm" not in mapping.columns:
        mapping["Hiport Code norm"] = _norm_join(mapping.get("Hiport Code", pd.Series(dtype="object")))
    hip_map = (mapping.loc[mapping["Hiport Code norm"].astype(str).str.strip().ne(""), ["Hiport Code norm", "Asset Type"]]
               .drop_duplicates("Hiport Code norm").set_index("Hiport Code norm")["Asset Type"].astype(str).to_dict())
    hip_key = out["Portfolio code norm"].astype(str) if "Portfolio code norm" in out.columns else _norm_join(out.get("Portfolio code", pd.Series("", index=out.index)))
    mapped = hip_key.map(hip_map).fillna("")

    if "Advisor Code" in mapping.columns and "External portfolio reference" in out.columns:
        adv = mapping[["Advisor Code", "Asset Type"]].copy()
        adv["_adv"] = _norm_join(adv["Advisor Code"])
        adv_map = (adv.loc[adv["_adv"].astype(str).str.strip().ne(""), ["_adv", "Asset Type"]]
                   .drop_duplicates("_adv").set_index("_adv")["Asset Type"].astype(str).to_dict())
        mapped = mapped.mask(mapped.astype(str).str.strip().eq(""), _norm_join(out["External portfolio reference"]).map(adv_map).fillna(""))

    blank = out["Class"].isna() | out["Class"].astype(str).str.strip().eq("")
    out.loc[blank, "Class"] = mapped.loc[blank]
    return out

# ---------------------------------------------------------------------------
# GAV Check
# ---------------------------------------------------------------------------
@dataclass
class GavResult:
    gav_df: pd.DataFrame
    summary: Dict[str, Any] = field(default_factory=dict)
    tolerance_pct: float = DEFAULT_GAV_TOLERANCE_PCT
    status: str = "OK"
    detail: str = ""
    full_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    treasury_excluded_df: pd.DataFrame = field(default_factory=pd.DataFrame)


def build_gav_check(portfolio_df: pd.DataFrame, acc_balance: Any, dar: pd.DataFrame,
                    *, tolerance_pct: float = DEFAULT_GAV_TOLERANCE_PCT,
                    portfolio_code_col: str = "Portfolio code",
                    advisor_col: str = "External portfolio reference",
                    class_col: str = "Class") -> GavResult:
    """Build the GAV control population and retain excluded Treasury evidence.

    ``gav_df`` is the authoritative checked population. ``full_df`` retains every
    portfolio, while ``treasury_excluded_df`` contains rows classified as Treasury.
    Treasury rows are never labelled Ok and do not contribute to control totals.
    """
    if not isinstance(portfolio_df, pd.DataFrame) or portfolio_df.empty or portfolio_code_col not in portfolio_df.columns:
        return GavResult(pd.DataFrame(), {}, tolerance_pct, "No portfolio_df", "portfolio_df missing/empty")

    acc_df = load_acc_balance(acc_balance) if isinstance(acc_balance, str) else acc_balance
    nav_dtx = aggregate_unison_nav_deftax(acc_df)
    gav = aggregate_bnp_gav(dar)
    if nav_dtx.empty and gav.empty:
        return GavResult(pd.DataFrame(), {}, tolerance_pct, "No sources", "Acc Balance and DAssetReturn both unavailable")

    out = portfolio_df.copy()
    out["_hiport_norm"] = out["Portfolio code norm"].astype(str) if "Portfolio code norm" in out.columns else _norm_join(out[portfolio_code_col])
    out["_advisor_norm"] = _norm_join(out[advisor_col]) if advisor_col in out.columns else ""
    if class_col not in out.columns:
        out[class_col] = ""

    keep = [c for c in [portfolio_code_col, advisor_col, "Portfolio Name", class_col] if c in out.columns]
    base = out[keep + ["_hiport_norm", "_advisor_norm"]].copy()
    if not nav_dtx.empty:
        base = base.merge(nav_dtx.drop(columns=["Advisor"]), left_on="_advisor_norm", right_on="Advisor norm", how="left").drop(columns=["Advisor norm"], errors="ignore")
    for c in ["Unison NAV", "Deferred Tax"]:
        if c not in base.columns:
            base[c] = 0.0
        base[c] = pd.to_numeric(base[c], errors="coerce").fillna(0.0)
    if not gav.empty:
        base = base.merge(gav, left_on="_hiport_norm", right_on="Hiport norm", how="left").drop(columns=["Hiport norm"], errors="ignore")
    if "BNP GAV" not in base.columns:
        base["BNP GAV"] = 0.0
    base["BNP GAV"] = pd.to_numeric(base["BNP GAV"], errors="coerce").fillna(0.0)

    is_treasury = base[class_col].astype(str).str.strip().str.casefold().eq("treasury")
    base["In GAV Check population"] = ~is_treasury
    base["GAV Check scope"] = "Included"
    base.loc[is_treasury, "GAV Check scope"] = "Excluded: Treasury"
    base["Comment"] = ""
    base.loc[is_treasury, "Comment"] = "Treasury portfolios are excluded from the GAV control population."

    base["GAV Diff"] = base["Unison NAV"] - base["Deferred Tax"] - base["BNP GAV"]
    tol = float(tolerance_pct) / 100.0
    nav_ok = base["Unison NAV"].abs() > 2
    base["% impact"] = 0.0
    base.loc[nav_ok, "% impact"] = base.loc[nav_ok, "GAV Diff"] / base.loc[nav_ok, "Unison NAV"]
    base["Check"] = "Ok"
    base.loc[(~is_treasury) & (base["% impact"].abs() > tol), "Check"] = "Check"
    base.loc[is_treasury, "Check"] = "Excluded"

    base = base.drop(columns=["_hiport_norm", "_advisor_norm"], errors="ignore")
    order = [c for c in [portfolio_code_col, advisor_col, "Portfolio Name", class_col,
                         "In GAV Check population", "GAV Check scope", "Comment",
                         "Unison NAV", "Deferred Tax", "BNP GAV", "GAV Diff", "% impact", "Check"] if c in base.columns]
    full_df = base[order].copy()
    checked_df = full_df.loc[full_df["In GAV Check population"].fillna(False)].copy().reset_index(drop=True)
    treasury_df = full_df.loc[~full_df["In GAV Check population"].fillna(False)].copy().reset_index(drop=True)

    n_check = int(checked_df["Check"].eq("Check").sum())
    summary = {
        "full_portfolios": int(len(full_df)),
        "portfolios": int(len(checked_df)),
        "checks": n_check,
        "ok": int(checked_df["Check"].eq("Ok").sum()),
        "treasury_excluded": int(len(treasury_df)),
        "tolerance_pct": float(tolerance_pct),
        "nav_matched": int(checked_df["Unison NAV"].abs().gt(0).sum()),
        "gav_matched": int(checked_df["BNP GAV"].abs().gt(0).sum()),
    }
    return GavResult(checked_df, summary, float(tolerance_pct), "OK",
                     f"{n_check} checked portfolio(s) exceed |% impact| > {tolerance_pct}%; {len(treasury_df)} Treasury portfolio(s) excluded.",
                     full_df=full_df, treasury_excluded_df=treasury_df)

def _resolve_tolerance(static_bundle) -> float:
    if static_bundle is not None and callable(_get_threshold_value):
        try:
            return float(_get_threshold_value(static_bundle, "gav_pct_impact_tolerance_pct", DEFAULT_GAV_TOLERANCE_PCT))
        except Exception:
            pass
    return DEFAULT_GAV_TOLERANCE_PCT


def _acc_balance_path_from_meta(meta: Any) -> str:
    """Extract the acc_balance path from a tableau_file_meta_df."""
    if not isinstance(meta, pd.DataFrame) or meta.empty or "ReportKey" not in meta.columns:
        return ""
    row = meta[meta["ReportKey"].astype(str).str.strip().str.lower() == "acc_balance"]
    if row.empty:
        return ""
    for col in ["ResolvedPath", "ExpectedPath"]:
        if col in row.columns:
            p = _first_existing(str(row.iloc[0][col] or "").strip())
            if p:
                return p
    return ""


def _acc_balance_path_from_static(static_bundle) -> str:
    """Resolve <tableau date folder>/Acc Balance.csv via Static Data if possible."""
    if static_bundle is None or not callable(_get_active_table):
        return ""
    try:
        sr = _get_active_table(static_bundle, "source_reports")
        fn = ACC_BALANCE_FILENAME
        if isinstance(sr, pd.DataFrame) and not sr.empty and "ReportKey" in sr.columns:
            r = sr[sr["ReportKey"].astype(str).str.strip().str.lower() == "acc_balance"]
            if not r.empty and "FileName" in r.columns:
                fn = str(r.iloc[0]["FileName"]).strip() or ACC_BALANCE_FILENAME
        return fn  # filename only; joined with folder by caller
    except Exception:
        return ACC_BALANCE_FILENAME


def resolve_acc_balance_source(bundle: Dict[str, object]) -> Any:
    """Return a tidy Acc Balance frame, a resolvable path, or None.

    Prefers the FILE PATH (loaded with the UTF-16-aware reader) over any
    pre-loaded bundle frame, because the app's generic Tableau reader cannot
    parse the UTF-16 crosstab and leaves acc_balance_df empty/garbage.
    """
    if not isinstance(bundle, dict):
        return None
    tb = bundle.get("tableau") if isinstance(bundle.get("tableau"), dict) else {}

    # v319: acc_balance_path override removed. Acc Balance is resolved from the
    # Tableau date folder under tableau_root (via tableau_file_meta_df / tableau_folder,
    # falling back to re-running the Tableau loader below).

    # A) A genuinely tidy frame already present (e.g. tests / future loaders).
    for src in (bundle, tb):
        for k in ("acc_balance_tidy_df", "acc_balance_df", "acc_balance"):
            v = src.get(k) if isinstance(src, dict) else None
            if isinstance(v, pd.DataFrame) and not v.empty and {"Advisor", "Account Code"} <= set(v.columns):
                return v

    # B) Resolve the file path from Tableau metadata and load it robustly.
    for meta in (bundle.get("tableau_file_meta_df"), tb.get("tableau_file_meta_df") if isinstance(tb, dict) else None):
        p = _acc_balance_path_from_meta(meta)
        if p:
            return p

    # C) tableau_folder + Acc Balance filename.
    folder = bundle.get("tableau_folder") or (tb.get("tableau_folder") if isinstance(tb, dict) else "")
    if folder:
        fn = _acc_balance_path_from_static(bundle.get("static_data")) or ACC_BALANCE_FILENAME
        p = _first_existing(os.path.join(str(folder), fn)) or _first_existing(os.path.join(str(folder), ACC_BALANCE_FILENAME))
        if p:
            return p

    # E) LAST RESORT (v309.2): the bundle the panel received has no Tableau keys
    # at all (the Tableau enrichment wrapper did not run on THIS bundle). Re-derive
    # the Acc Balance path ourselves using the Tableau helper + Static Data + the
    # run date, if those are available. Fully guarded; network scan is acceptable
    # here because it only runs when every in-bundle path has failed.
    try:
        run_date = None
        for k in ("run_date", "RunDate", "effective_date", "EffectiveDate"):
            v = bundle.get(k)
            if v:
                run_date = v; break
        if run_date is None:
            folder = bundle.get("tableau_folder") or ""
        static_bundle = bundle.get("static_data")
        if run_date is not None and static_bundle is not None:
            import bnp_helpers_tableau as _tab
            tabres = _tab.prepare_tableau_sources(run_date, static_bundle=static_bundle)
            if isinstance(tabres, dict):
                p = _acc_balance_path_from_meta(tabres.get("tableau_file_meta_df"))
                if p:
                    return p
                fol = tabres.get("tableau_folder")
                if fol:
                    cand = _first_existing(os.path.join(str(fol), ACC_BALANCE_FILENAME))
                    if cand:
                        return cand
    except Exception:
        pass
    return None


def diagnose_acc_balance_source(bundle: Dict[str, object]) -> Dict[str, Any]:
    """Explain WHY Acc Balance could not be resolved from the bundle.

    Returns a dict with a checks dataframe, the tableau meta dataframe (if any),
    and printable key listings. Pure/read-only; used by the panel's failure branch.
    """
    checks: List[Dict[str, Any]] = []
    def add(step, result, detail=""):
        checks.append({"Step": step, "Result": result, "Detail": str(detail)[:300]})

    if not isinstance(bundle, dict):
        add("bundle type", "FAIL", f"bundle is {type(bundle).__name__}, not dict")
        return {"checks_df": pd.DataFrame(checks), "tableau_meta_df": pd.DataFrame(),
                "bundle_keys_text": "", "tableau_subkeys_text": ""}

    keys = sorted([str(k) for k in bundle.keys()])
    add("bundle keys present", "INFO", f"{len(keys)} keys")

    # dar
    dar = bundle.get("dar")
    add("bundle['dar']", "OK" if isinstance(dar, pd.DataFrame) and not dar.empty else "MISSING/EMPTY",
        f"rows={len(dar) if isinstance(dar, pd.DataFrame) else 'n/a'}")

    # acc_balance_df (top level)
    a = bundle.get("acc_balance_df")
    add("bundle['acc_balance_df']",
        "PRESENT-BUT-EMPTY" if isinstance(a, pd.DataFrame) and a.empty else
        ("PRESENT" if isinstance(a, pd.DataFrame) else "MISSING"),
        f"rows={len(a) if isinstance(a, pd.DataFrame) else 'n/a'}; "
        f"cols={list(a.columns)[:6] if isinstance(a, pd.DataFrame) else 'n/a'}")

    # tableau sub-bundle
    tb = bundle.get("tableau")
    tableau_subkeys_text = ""
    if isinstance(tb, dict):
        tableau_subkeys_text = ", ".join(sorted(str(k) for k in tb.keys()))
        tad = tb.get("acc_balance_df")
        add("bundle['tableau']", "PRESENT", f"{len(tb)} keys")
        add("bundle['tableau']['acc_balance_df']",
            "PRESENT-BUT-EMPTY" if isinstance(tad, pd.DataFrame) and tad.empty else
            ("PRESENT" if isinstance(tad, pd.DataFrame) else "MISSING"),
            f"rows={len(tad) if isinstance(tad, pd.DataFrame) else 'n/a'}")
    else:
        add("bundle['tableau']", "MISSING", "no tableau sub-bundle attached to this bundle")

    # tableau_folder
    folder = bundle.get("tableau_folder") or (tb.get("tableau_folder") if isinstance(tb, dict) else "")
    add("tableau_folder", "OK" if folder else "MISSING", folder or "(empty)")

    # tableau_file_meta_df
    meta = bundle.get("tableau_file_meta_df")
    if not (isinstance(meta, pd.DataFrame) and not meta.empty) and isinstance(tb, dict):
        meta = tb.get("tableau_file_meta_df")
    meta_out = meta if isinstance(meta, pd.DataFrame) else pd.DataFrame()
    if isinstance(meta, pd.DataFrame) and not meta.empty:
        add("tableau_file_meta_df", "PRESENT", f"rows={len(meta)}; cols={list(meta.columns)[:8]}")
        if "ReportKey" in meta.columns:
            row = meta[meta["ReportKey"].astype(str).str.strip().str.lower() == "acc_balance"]
            if row.empty:
                add("meta ReportKey=acc_balance", "MISSING", "no acc_balance row in metadata")
            else:
                r0 = row.iloc[0]
                exp = str(r0.get("ExpectedPath", "") or "")
                res = str(r0.get("ResolvedPath", "") or "")
                add("meta acc_balance ExpectedPath", "OK" if exp else "EMPTY", exp or "(empty)")
                add("meta acc_balance ResolvedPath", "OK" if res else "EMPTY", res or "(empty)")
                add("meta acc_balance Loaded", str(r0.get("Loaded", "")), f"rows={r0.get('Rows','')}; enc={r0.get('Encoding','')}; err={r0.get('Error','')}")
                # does the path exist from here?
                for label, p in [("ExpectedPath exists", exp), ("ResolvedPath exists", res)]:
                    if p:
                        found = _first_existing(p)
                        add(label, "YES" if found else "NO", found or f"os.path.exists False for all variants of: {p}")
    else:
        add("tableau_file_meta_df", "MISSING", "no Tableau metadata on this bundle - the Tableau source wrapper may not have run on the bundle the GAV panel receives")

    # final resolver result
    resolved = resolve_acc_balance_source(bundle)
    add("resolve_acc_balance_source()", "PATH" if isinstance(resolved, str) else ("FRAME" if isinstance(resolved, pd.DataFrame) else "None"),
        resolved if isinstance(resolved, str) else "")

    return {
        "checks_df": pd.DataFrame(checks),
        "tableau_meta_df": meta_out,
        "bundle_keys_text": ", ".join(keys),
        "tableau_subkeys_text": tableau_subkeys_text,
    }


def _gav_full_pack_bytes(full_df: pd.DataFrame, checks_df: pd.DataFrame,
                         ok_df: pd.DataFrame, treasury_df: pd.DataFrame) -> bytes:
    """Create the standalone full GAV evidence workbook used by the section button."""
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        full_df.to_excel(writer, sheet_name="GAV Full Pack", index=False)
        checks_df.to_excel(writer, sheet_name="GAV Checks", index=False)
        ok_df.to_excel(writer, sheet_name="GAV OK", index=False)
        treasury_df.to_excel(writer, sheet_name="Treasury Excluded", index=False)
        for ws in writer.book.worksheets:
            ws.freeze_panes = "A2"
            for cells in ws.columns:
                try:
                    width = max(len(str(c.value or "")) for c in cells[:250]) + 2
                    ws.column_dimensions[cells[0].column_letter].width = min(max(width, 10), 60)
                except Exception:
                    pass
    return output.getvalue()


def _solid_frame_style(df: pd.DataFrame, colour: str):
    """Return a Styler with one accessible, light status colour across all cells."""
    return df.style.set_properties(**{"background-color": colour, "color": "#1f2937"})


def render_gav_section(st, bundle: Dict[str, object]) -> None:
    """Render Portfolio Numbers -> GAV Check evidence section. Fully guarded."""
    try:
        portfolio_df = bundle.get("portfolio_df", pd.DataFrame()) if isinstance(bundle, dict) else pd.DataFrame()
        if not isinstance(portfolio_df, pd.DataFrame) or portfolio_df.empty:
            return
        static_bundle = bundle.get("static_data") if isinstance(bundle, dict) else None
        dar = bundle.get("dar", pd.DataFrame()) if isinstance(bundle, dict) else pd.DataFrame()
        acc = resolve_acc_balance_source(bundle)
        tol = _resolve_tolerance(static_bundle)
        st.markdown("**GAV Check**")
        st.caption("The GAV Check compares Unison NAV, less Deferred Tax, with BNP GAV for portfolios within the control population. Portfolios classified as Treasury in the Central Mapping List are excluded from the check and exception totals, and are reported separately. The full GAV download retains all portfolios, including their Class and exclusion reason.")
        if acc is None:
            diag = diagnose_acc_balance_source(bundle)
            st.warning(f"GAV Check unavailable - Acc Balance not found. {diag.get('detail', '')}")
            return
        portfolio_df = enrich_portfolio_class_from_mapping(portfolio_df, bundle)
        res = build_gav_check(portfolio_df, acc, dar, tolerance_pct=tol)
        if res.status != "OK":
            st.warning(f"GAV Check unavailable: {res.status}. {res.detail}")
            return
        checked = res.gav_df.copy()
        check_df = checked.loc[checked["Check"].astype(str).str.strip().eq("Check")].copy().reset_index(drop=True)
        ok_df = checked.loc[checked["Check"].astype(str).str.strip().eq("Ok")].copy().reset_index(drop=True)
        treasury_df = res.treasury_excluded_df.copy()
        if isinstance(bundle, dict):
            bundle["gav_check_df"] = checked
            bundle["gav_full_df"] = res.full_df
            bundle["gav_treasury_excluded_df"] = treasury_df
            bundle["gav_check_summary"] = res.summary
        s = res.summary
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("GAV population", s.get("portfolios", 0))
        c2.metric("GAV checks", s.get("checks", 0))
        c3.metric("GAV OK", s.get("ok", 0))
        c4.metric("Treasury excluded", s.get("treasury_excluded", 0))

        pack = _gav_full_pack_bytes(res.full_df, check_df, ok_df, treasury_df)
        st.download_button(
            "Download full GAV pack",
            data=pack,
            file_name="GAV_Full_Pack.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="download_full_gav_pack",
        )

        st.markdown(f"**GAV checks requiring investigation ({len(check_df)})**")
        if check_df.empty:
            st.success("No GAV checks require investigation.")
        else:
            st.dataframe(_solid_frame_style(check_df, "#FDECEC"), width="stretch", hide_index=True)

        st.markdown(f"**GAV checks OK ({len(ok_df)})**")
        if ok_df.empty:
            st.info("No GAV rows are currently classified as Ok.")
        else:
            st.dataframe(_solid_frame_style(ok_df, "#EAF7EA"), width="stretch", hide_index=True)

        st.markdown(f"**Treasury portfolios excluded from GAV Check ({len(treasury_df)})**")
        if isinstance(treasury_df, pd.DataFrame) and not treasury_df.empty:
            st.dataframe(treasury_df, width="stretch", hide_index=True)
        else:
            st.info("No Treasury portfolios were identified from the Central Mapping Class for this population.")
    except Exception as exc:
        st.warning(f"GAV Check could not be rendered: {type(exc).__name__}: {exc}")

if __name__ == "__main__":
    print(f"[{GAV_VERSION}] GAV self-test (synthetic)")
    portfolio = pd.DataFrame({
        "Portfolio code": ["M1AAA", "M1BBB", "M1TRE"],
        "External portfolio reference": ["AAAPUA", "BBBPUA", "TREPUA"],
        "Portfolio Name": ["Alpha", "Beta", "Treasury Fund"],
        "Class": ["Cash", "Equity", "Treasury"]})
    acc = pd.DataFrame({
        "Advisor": ["AAAPUA", "AAAPUA", "BBBPUA", "TREPUA"],
        "Account Code": ["9018", "2500", "9018", "9018"],
        "NAV Value": [1_000_000.0, None, 500_000.0, 9_999.0],
        "DefTax Value": [None, 10_000.0, None, None]})
    dar = pd.DataFrame({
        "Portfolio": ["M1AAA", "M1AAA", "M1BBB", "M1TRE"],
        "FDV Valuation Curr_Day": [600_000.0, 390_050.0, 500_000.0, 9_999.0]})
    res = build_gav_check(portfolio, acc, dar, tolerance_pct=0.01)
    print(res.gav_df.to_string(index=False))
    row = res.gav_df.set_index("Portfolio code")
    assert abs(row.loc["M1AAA", "GAV Diff"] - (-50.0)) < 1e-6
    assert row.loc["M1TRE", "Unison NAV"] == 0.0 and row.loc["M1TRE", "BNP GAV"] == 0.0
    assert (res.gav_df["Check"] == "Ok").all()
    print("  synthetic OK")

    # v309.1 path-resolver test: simulate the real app bundle where the Tableau
    # reader failed (empty acc_balance_df) but recorded the file path in meta.
    real = "/mnt/user-data/uploads/Acc Balance.csv"
    if os.path.exists(real):
        bundle = {
            "acc_balance_df": pd.DataFrame(),  # empty, as the UTF-16 read fails in-app
            "tableau_file_meta_df": pd.DataFrame([{"ReportKey": "acc_balance",
                "ExpectedPath": real, "ResolvedPath": real}]),
            "tableau": {"acc_balance_df": pd.DataFrame()},
        }
        src = resolve_acc_balance_source(bundle)
        print(f"  resolver returned: {'PATH' if isinstance(src, str) else type(src).__name__} -> {src if isinstance(src, str) else ''}")
        assert isinstance(src, str) and os.path.exists(src), "resolver should return the real path"
        acc_tidy = load_acc_balance(src)
        nd = aggregate_unison_nav_deftax(acc_tidy)
        print(f"  advisors with NAV/DefTax: {len(nd)} | total NAV: {nd['Unison NAV'].sum():,.0f}")
        assert len(nd) > 100 and nd["Unison NAV"].sum() > 1e9
        print("  v309.1 path-resolver OK")
