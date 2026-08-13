# -*- coding: utf-8 -*-
"""
bnp_helpers_universe.py  (v308 - Universe & identity)

PURPOSE
-------
Builds the MASTER PORTFOLIO UNIVERSE from the Central Mapping List and reconciles
it against the portfolios actually present in today's BNP data (portfolio_df).
This adds the two controls the BNP-derived universe structurally cannot provide:

  * "Missing from BNP today" - a mapped/expected portfolio absent from today's
    BNP DDetailedReturn (the drop-out control; workbook Central Mapping List
    col A: =COUNTIF('DDetailed return'!C:C, Hiport) > 0).
  * "Unmapped in BNP"        - a portfolio present in BNP today but not in the
    mapping list (surfaces e.g. the 29 'No Error Risk row' codes for follow-up).

DESIGN (per agreed v308 decisions)
----------------------------------
  * Master source = 'Unison Active Advisors' + 'Off-Unison Active Advisors' ONLY
    (v319: 'Active Pools & Micky' and 'Terminated Advisors' are no longer loaded).
  * Join key = Hiport Code (the display/control key) normalised with the SAME
    normalise_join_key_series used everywhere else, so the universe join is
    identical to the error-risk join (auditable, no divergent logic).
  * Self-contained: reads the central_mapping_workbook path from Static Data
    'paths' (already loaded) with code-level defaults; requires NO change to the
    existing static-data / ingestion load paths.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import os
import pandas as pd

UNIVERSE_VERSION = "v308.1"

# Reuse the app's canonical join-key normaliser for identical matching.
try:
    from bnp_helpers_columns import normalise_join_key_series as _norm_join
except Exception:
    def _norm_join(s: pd.Series) -> pd.Series:  # safe fallback
        return s.astype(str).str.strip().str.upper().str.replace(r"\s+", "", regex=True)

# Static Data accessors (optional import; loader also has direct fallbacks).
try:
    from bnp_helpers_static_data import get_config_value as _get_config_value, get_active_table as _get_active_table
except Exception:
    _get_config_value = None
    _get_active_table = None

DEFAULT_MAPPING_PATH_KEY = "central_mapping_workbook"

# Sheet -> (hiport column, advisor column, extra flags). Column names are matched
# flexibly (case/space-insensitive) so minor header drift does not break loading.
UNIVERSE_SHEETS: List[Dict[str, Any]] = [
    # v319: universe loads ONLY the two advisor sheets (Active Pools & Micky and
    # Terminated Advisors removed per request).
    {"sheet": "Unison Active Advisors", "hiport": "Hiport Code", "advisor": "Advisor Code",
     "source": "Unison Active Advisors", "terminated": False},
    {"sheet": "Off-Unison Active Advisors", "hiport": "Hiport Code", "advisor": "Advisor Code",
     "source": "Off-Unison Active Advisors", "terminated": False},
]

CANON_COLS = ["Source", "Entity", "Advisor Code", "Hiport Code", "Name", "Group",
              "Asset Type", "Advisor Type", "Closing/Active", "Terminated"]


PORTFOLIOS_CONTROL_SOURCE = "Unison Active Advisors"

def portfolio_control_universe(universe_df: pd.DataFrame) -> pd.DataFrame:
    """Return the Portfolios-control population: Unison Active Advisors only."""
    if not isinstance(universe_df, pd.DataFrame) or universe_df.empty or "Source" not in universe_df.columns:
        return pd.DataFrame(columns=(universe_df.columns if isinstance(universe_df, pd.DataFrame) else None))
    source = universe_df["Source"].astype(str).str.strip()
    return universe_df.loc[source.eq(PORTFOLIOS_CONTROL_SOURCE)].copy().reset_index(drop=True)

@dataclass
class UniverseResult:
    universe_df: pd.DataFrame
    meta_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    exception_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    source_file: str = ""
    status: str = "OK"


def _find_col(df: pd.DataFrame, name: str) -> Optional[str]:
    if df is None or df.empty:
        return None
    norm = {str(c).strip().lower().replace(" ", "").replace("_", "").replace("/", ""): c for c in df.columns}
    key = str(name).strip().lower().replace(" ", "").replace("_", "").replace("/", "")
    return norm.get(key)


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


def _resolve_mapping_path(static_bundle: Optional[Dict[str, object]]) -> str:
    configured = ""
    if static_bundle is not None and callable(_get_config_value):
        try:
            configured = str(_get_config_value(static_bundle, DEFAULT_MAPPING_PATH_KEY, "") or "")
        except Exception:
            configured = ""
    if not configured and isinstance(static_bundle, dict):
        paths = static_bundle.get("paths")
        if isinstance(paths, pd.DataFrame) and {"ConfigKey", "ConfigValue"} <= set(paths.columns):
            m = paths.loc[paths["ConfigKey"].astype(str).str.strip().str.lower().eq(DEFAULT_MAPPING_PATH_KEY)]
            if not m.empty:
                configured = str(m.iloc[0]["ConfigValue"]).strip()
    for cand in _root_variants(configured):
        if os.path.exists(cand):
            return cand
    return configured  # return configured even if missing, for a clear message


def load_universe(static_bundle: Optional[Dict[str, object]] = None,
                  mapping_path: Optional[str] = None) -> UniverseResult:
    """Load and concatenate the universe sheets into one normalised dataframe."""
    path = str(mapping_path or _resolve_mapping_path(static_bundle) or "")
    meta_rows: List[Dict[str, Any]] = []
    exc_rows: List[Dict[str, Any]] = []

    if not path or not os.path.exists(path):
        exc_rows.append({"Severity": "Error", "Check": "CentralMappingWorkbook",
                         "Detail": f"File not found: {path or '(no path configured)'}"})
        return UniverseResult(pd.DataFrame(columns=CANON_COLS + ["Hiport Code norm"]),
                              pd.DataFrame(meta_rows), pd.DataFrame(exc_rows), path, "Missing source")

    try:
        xl = pd.ExcelFile(path, engine="openpyxl")
        available = set(xl.sheet_names)
    except Exception as exc:
        exc_rows.append({"Severity": "Error", "Check": "OpenWorkbook", "Detail": f"{type(exc).__name__}: {exc}"})
        return UniverseResult(pd.DataFrame(columns=CANON_COLS + ["Hiport Code norm"]),
                              pd.DataFrame(meta_rows), pd.DataFrame(exc_rows), path, "Error")

    frames: List[pd.DataFrame] = []
    for cfg in UNIVERSE_SHEETS:
        sheet = cfg["sheet"]
        if sheet not in available:
            meta_rows.append({"Sheet": sheet, "Loaded": False, "Rows": 0, "Detail": "Sheet not present"})
            continue
        try:
            raw = pd.read_excel(path, sheet_name=sheet, engine="openpyxl")
        except Exception as exc:
            exc_rows.append({"Severity": "Warning", "Check": "LoadSheet", "Detail": f"{sheet}: {exc}"})
            continue
        hip = _find_col(raw, cfg["hiport"]); adv = _find_col(raw, cfg["advisor"])
        if not hip:
            exc_rows.append({"Severity": "Warning", "Check": "HiportColumn",
                             "Detail": f"{sheet}: no '{cfg['hiport']}' column"})
            meta_rows.append({"Sheet": sheet, "Loaded": False, "Rows": 0, "Detail": "No hiport column"})
            continue
        out = pd.DataFrame()
        out["Hiport Code"] = raw[hip].astype(str).str.strip()
        out["Advisor Code"] = raw[adv].astype(str).str.strip() if adv else ""
        for canon, cand in [("Entity", "Entity"), ("Name", "Name"), ("Group", "Group"),
                            ("Asset Type", "Asset Type"), ("Advisor Type", "Advisor Type"),
                            ("Closing/Active", "Closing/Active")]:
            col = _find_col(raw, cand)
            out[canon] = raw[col].astype(str).str.strip() if col else ""
        out["Source"] = cfg["source"]
        out["Terminated"] = bool(cfg.get("terminated", False))
        out = out[(out["Hiport Code"] != "") & (out["Hiport Code"].str.lower() != "nan") & (out["Hiport Code"] != "-")]
        frames.append(out)
        meta_rows.append({"Sheet": sheet, "Loaded": True, "Rows": int(len(out)),
                          "Detail": f"hiport={hip}; advisor={adv or '(none)'}"})

    if not frames:
        return UniverseResult(pd.DataFrame(columns=CANON_COLS + ["Hiport Code norm"]),
                              pd.DataFrame(meta_rows), pd.DataFrame(exc_rows), path, "Empty")

    universe = pd.concat(frames, ignore_index=True)[CANON_COLS]
    universe["Hiport Code norm"] = _norm_join(universe["Hiport Code"])
    # De-duplicate on the join key, keeping the first (active sheets are listed
    # before Terminated, so an active mapping wins over a terminated duplicate).
    dupes = int(universe["Hiport Code norm"].duplicated(keep="first").sum())
    if dupes:
        meta_rows.append({"Sheet": "(dedup)", "Loaded": True, "Rows": dupes,
                          "Detail": "Duplicate Hiport keys collapsed (active precedence over terminated)"})
    universe = universe.drop_duplicates(subset=["Hiport Code norm"], keep="first").reset_index(drop=True)
    return UniverseResult(universe, pd.DataFrame(meta_rows), pd.DataFrame(exc_rows), path, "OK")


@dataclass
class UniverseReconciliation:
    matched_df: pd.DataFrame
    missing_from_bnp_df: pd.DataFrame
    unmapped_in_bnp_df: pd.DataFrame
    summary: Dict[str, int]


def reconcile_universe(universe_df: pd.DataFrame, portfolio_df: pd.DataFrame,
                       *, portfolio_code_col: str = "Portfolio code",
                       expected_source: Optional[str] = None,
                       full_universe_df: Optional[pd.DataFrame] = None) -> UniverseReconciliation:
    """Reconcile expected mappings to BNP while testing unmapped against full mapping.

    ``expected_source`` scopes expected, matched and missing totals. ``full_universe_df``
    prevents known Off-Unison rows being mislabelled as unmapped when the expected
    population is restricted to Unison Active Advisors.
    """
    scoped = universe_df.copy() if isinstance(universe_df, pd.DataFrame) else pd.DataFrame()
    if expected_source and not scoped.empty and "Source" in scoped.columns:
        scoped = scoped.loc[scoped["Source"].astype(str).str.strip().eq(str(expected_source).strip())].copy()
    full = full_universe_df.copy() if isinstance(full_universe_df, pd.DataFrame) else (universe_df.copy() if isinstance(universe_df, pd.DataFrame) else pd.DataFrame())
    if not isinstance(portfolio_df, pd.DataFrame) or portfolio_df.empty or portfolio_code_col not in portfolio_df.columns:
        return UniverseReconciliation(pd.DataFrame(), pd.DataFrame(), pd.DataFrame(),
                                      {"universe": int(len(scoped)), "bnp_today": 0, "matched": 0,
                                       "missing_from_bnp": 0, "unmapped_in_bnp": 0})
    pf = portfolio_df.copy()
    pf["_key"] = pf["Portfolio code norm"].astype(str) if "Portfolio code norm" in pf.columns else _norm_join(pf[portfolio_code_col])
    for frame in (scoped, full):
        if "Hiport Code norm" not in frame.columns:
            frame["Hiport Code norm"] = _norm_join(frame.get("Hiport Code", pd.Series(dtype="object")))

    expected_keys = set(scoped["Hiport Code norm"].astype(str))
    full_keys = set(full["Hiport Code norm"].astype(str))
    pf_keys = set(pf["_key"].astype(str))
    matched_keys = expected_keys & pf_keys
    missing_keys = expected_keys - pf_keys
    unmapped_keys = pf_keys - full_keys

    matched_df = scoped[scoped["Hiport Code norm"].isin(matched_keys)].copy()
    matched_df.insert(0, "Reconciliation", "In expected universe & BNP")
    missing_df = scoped[scoped["Hiport Code norm"].isin(missing_keys)].copy()
    missing_df.insert(0, "Reconciliation", "Missing from BNP today")
    pf_cols = [c for c in [portfolio_code_col, "External portfolio reference", "Portfolio Name", "Status Normalised", "Hot / Cold"] if c in pf.columns]
    unmapped_df = pf.loc[pf["_key"].isin(unmapped_keys), pf_cols].copy()
    unmapped_df.insert(0, "Reconciliation", "Present in BNP; absent from complete mapping")

    summary = {"universe": int(len(scoped)), "bnp_today": int(len(pf)),
               "matched": int(len(matched_df)), "missing_from_bnp": int(len(missing_df)),
               "unmapped_in_bnp": int(len(unmapped_df))}
    return UniverseReconciliation(matched_df, missing_df, unmapped_df, summary)

def render_universe_section(st, bundle: Dict[str, object]) -> None:
    """Render the Portfolio Numbers -> Universe evidence section in Streamlit.

    Reads portfolio_df + static_data from the dashboard bundle, loads/caches the
    universe, reconciles, and shows summary metrics + the three evidence frames.
    Fully guarded so it can never break the render.
    """
    try:
        portfolio_df = bundle.get("portfolio_df", pd.DataFrame()) if isinstance(bundle, dict) else pd.DataFrame()
        static_bundle = bundle.get("static_data") if isinstance(bundle, dict) else None
        if not isinstance(portfolio_df, pd.DataFrame) or portfolio_df.empty:
            return
        uni_res = bundle.get("_universe_result_v308") if isinstance(bundle, dict) else None
        if not isinstance(uni_res, UniverseResult):
            uni_res = load_universe(static_bundle)
            if isinstance(bundle, dict):
                bundle["_universe_result_v308"] = uni_res
        recon = reconcile_universe(uni_res.universe_df, portfolio_df, expected_source=PORTFOLIOS_CONTROL_SOURCE, full_universe_df=uni_res.universe_df)
        if isinstance(bundle, dict):
            bundle["universe_reconciliation_summary"] = recon.summary
            bundle["universe_missing_from_bnp_df"] = recon.missing_from_bnp_df
            bundle["universe_unmapped_in_bnp_df"] = recon.unmapped_in_bnp_df

        st.markdown("**Portfolio universe reconciliation (v308.1)**")
        if uni_res.status != "OK":
            st.warning(f"Universe source not loaded ({uni_res.status}): {uni_res.source_file or 'no path configured'}. "
                       "Reconciliation unavailable until the Central Mapping List is reachable.")
            return
        st.caption("Portfolios control = Unison Active Advisors only. Off-Unison Active Advisors are excluded from expected, matched and missing totals. BNP portfolios are treated as unmapped only when absent from the complete Central Mapping universe.")
        s = recon.summary
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Universe (mapped)", s["universe"])
        c2.metric("BNP today", s["bnp_today"])
        c3.metric("In both", s["matched"])
        c4.metric("Missing from BNP", s["missing_from_bnp"])
        c5.metric("Unmapped in BNP", s["unmapped_in_bnp"])

        st.markdown("*Missing from BNP today* - mapped/expected portfolios absent from today's BNP (incl. retained terminated codes):")
        st.dataframe(recon.missing_from_bnp_df, width="stretch", hide_index=True)
        st.download_button("Download 'missing from BNP today'",
                           recon.missing_from_bnp_df.to_csv(index=False).encode("utf-8"),
                           "universe_missing_from_bnp_last_run.csv", "text/csv", key="uni_missing_dl")

        st.markdown("*Unmapped in BNP* - portfolios in today's BNP not found in the Central Mapping List:")
        st.dataframe(recon.unmapped_in_bnp_df, width="stretch", hide_index=True)
        st.download_button("Download 'unmapped in BNP'",
                           recon.unmapped_in_bnp_df.to_csv(index=False).encode("utf-8"),
                           "universe_unmapped_in_bnp_last_run.csv", "text/csv", key="uni_unmapped_dl")

        with st.expander("Universe load detail", expanded=False):
            if isinstance(uni_res.meta_df, pd.DataFrame) and not uni_res.meta_df.empty:
                st.dataframe(uni_res.meta_df, width="stretch", hide_index=True)
            if isinstance(uni_res.exception_df, pd.DataFrame) and not uni_res.exception_df.empty:
                st.dataframe(uni_res.exception_df, width="stretch", hide_index=True)
    except Exception:
        pass


def build_portfolios_reconciliation_gav_style(bundle: Dict[str, object]):
    """GAV-style wrapper for the Portfolios reconciliation control, using
    matched / missing / unmapped / excluded terminology (Q2: missing and
    unmapped are TWO SEPARATE red frames - never merged into one).

    matched   = green  - in the Unison Active Advisors control population AND present in BNP today.
    missing   = red #1 - mapped/expected (Unison Active Advisors) but absent from BNP today.
    unmapped  = red #2 - present in BNP today but absent from the COMPLETE Central Mapping universe.
    excluded  = neutral - Off-Unison Active Advisors rows: known/mapped, but out of scope for
                this specific Portfolios control (which tests Unison Active Advisors only).
    """
    from bnp_helpers_gav_style import GavStyleResult, compute_invariant

    portfolio_df = bundle.get("portfolio_df", pd.DataFrame()) if isinstance(bundle, dict) else pd.DataFrame()
    static_bundle = bundle.get("static_data") if isinstance(bundle, dict) else None
    if not isinstance(portfolio_df, pd.DataFrame) or portfolio_df.empty:
        return GavStyleResult(status="No portfolio detail available for the selected day")

    uni_res = bundle.get("_universe_result_v308") if isinstance(bundle, dict) else None
    if not isinstance(uni_res, UniverseResult):
        uni_res = load_universe(static_bundle)
        if isinstance(bundle, dict):
            bundle["_universe_result_v308"] = uni_res
    if uni_res.status != "OK":
        return GavStyleResult(status=f"Universe source not loaded ({uni_res.status}): "
                                      f"{uni_res.source_file or 'no path configured'}")

    recon = reconcile_universe(uni_res.universe_df, portfolio_df,
                                expected_source=PORTFOLIOS_CONTROL_SOURCE,
                                full_universe_df=uni_res.universe_df)

    matched_df = recon.matched_df.rename(columns={"Reconciliation": "Portfolios Status"}).copy()
    if not matched_df.empty:
        matched_df["Portfolios Status"] = "Matched"
    missing_df = recon.missing_from_bnp_df.rename(columns={"Reconciliation": "Portfolios Status"}).copy()
    if not missing_df.empty:
        missing_df["Portfolios Status"] = "Missing"
    unmapped_df = recon.unmapped_in_bnp_df.rename(columns={"Reconciliation": "Portfolios Status"}).copy()
    if not unmapped_df.empty:
        unmapped_df["Portfolios Status"] = "Unmapped"

    # Excluded (neutral): Off-Unison Active Advisors - known/mapped but out of
    # this control's scope (the control tests Unison Active Advisors only).
    full_uni = uni_res.universe_df.copy() if isinstance(uni_res.universe_df, pd.DataFrame) else pd.DataFrame()
    excluded_df = pd.DataFrame()
    if not full_uni.empty and "Source" in full_uni.columns:
        excluded_df = full_uni.loc[full_uni["Source"].astype(str).str.strip().ne(PORTFOLIOS_CONTROL_SOURCE)].copy()
        if not excluded_df.empty:
            excluded_df["Portfolios Status"] = "Excluded"
            excluded_df["Exclusion Reason"] = excluded_df["Source"].astype(str).map(
                lambda s: f"Source = '{s}' - out of Portfolios control scope (Unison Active Advisors only)"
            )

    # v360: paired "In Portfolios population" boolean (matched/missing/unmapped
    # = True, Off-Unison Active Advisors excluded rows = False), mirroring GAV
    # Check's convention. "Portfolios Status" (Matched/Missing/Unmapped/
    # Excluded) is kept as the control's own vocabulary per the reviewer's
    # earlier instruction, rather than forced into the generic "Check" label.
    for d in (matched_df, missing_df, unmapped_df):
        if isinstance(d, pd.DataFrame) and not d.empty:
            d["In Portfolios population"] = True
    if isinstance(excluded_df, pd.DataFrame) and not excluded_df.empty:
        excluded_df["In Portfolios population"] = False

    population_count = int(len(matched_df) + len(missing_df) + len(unmapped_df))
    ok, detail = compute_invariant(population_count, [len(missing_df), len(unmapped_df)], len(matched_df))

    full = build_full_pack_df_universe(matched_df, missing_df, unmapped_df, excluded_df)

    return GavStyleResult(
        red_frames=[("Missing", missing_df), ("Unmapped", unmapped_df)],
        green_df=matched_df,
        excluded_df=excluded_df,
        full_df=full,
        population_metrics=[
            ("Portfolios population (Unison Active Advisors + BNP)", population_count),
            ("Missing from BNP", int(len(missing_df))),
            ("Unmapped in BNP", int(len(unmapped_df))),
            ("Matched", int(len(matched_df))),
        ],
        invariant_ok=ok,
        invariant_detail=detail,
        status="OK",
        diag=dict(recon.summary),
        population_bool_col="In Portfolios population",
        control_noun="Portfolios",
    )


def build_full_pack_df_universe(matched_df, missing_df, unmapped_df, excluded_df) -> pd.DataFrame:
    "Local single-tab stacker (avoids importing the shared status/':Ok'-style tagger, since this control uses its own 'Portfolios Status' vocabulary)."
    parts = [d for d in (matched_df, missing_df, unmapped_df, excluded_df) if isinstance(d, pd.DataFrame) and not d.empty]
    if not parts:
        return pd.DataFrame(columns=["Portfolios Status"])
    all_cols: List[str] = []
    for p in parts:
        for c in p.columns:
            if c not in all_cols:
                all_cols.append(c)
    parts = [p.reindex(columns=all_cols) for p in parts]
    return pd.concat(parts, ignore_index=True, sort=False)


def render_portfolios_reconciliation_gav_style(st, bundle: Dict[str, object]) -> None:
    from bnp_helpers_gav_style import render_gav_style_section, GavStyleResult
    result = build_portfolios_reconciliation_gav_style(bundle)
    if isinstance(bundle, dict):
        bundle["portfolios_reconciliation_gav_style_result"] = result
    render_gav_style_section(
        st, control_key="portfolios_reconciliation", title="Portfolios reconciliation",
        purpose=("Reconciles the Central Mapping List (Unison Active Advisors) against the portfolios "
                 "actually present in today's BNP data. Missing = mapped/expected but absent from BNP today. "
                 "Unmapped = present in BNP today but absent from the complete mapping. Off-Unison Active "
                 "Advisors are excluded from this control's population (out of scope), but retained for audit."),
        result=result, download_filename_prefix="portfolios_reconciliation",
    )


if __name__ == "__main__":
    print(f"[{UNIVERSE_VERSION}] universe self-test")
    # Synthetic offline fixtures.
    uni = pd.DataFrame({
        "Source": ["Unison Active Advisors"]*4 + ["Terminated Advisors"],
        "Entity": ["NULIS"]*5, "Advisor Code": ["ACU35PUA","NSIFXPUA","GONE01","OLD99","TERM01"],
        "Hiport Code": ["M1CU35","M1NAFI","M1GONE","M1OLD9","M1TERM"], "Name": ["a","b","c","d","e"],
        "Group": [""]*5, "Asset Type": [""]*5, "Advisor Type": [""]*5, "Closing/Active": [""]*5,
        "Terminated": [False,False,False,False,True]})
    uni["Hiport Code norm"] = _norm_join(uni["Hiport Code"])
    pf = pd.DataFrame({"Portfolio code": ["M1CU35","M1NAFI","M1NEW1"],
                       "External portfolio reference": ["ACU35PUA","NSIFXPUA","NEW01PUA"],
                       "Portfolio Name": ["a","b","new"], "Status Normalised": ["OUT","OUT","OUT"]})
    r = reconcile_universe(uni, pf)
    print("  summary:", r.summary)
    print("  missing_from_bnp:", sorted(r.missing_from_bnp_df["Hiport Code"].tolist()))
    print("  unmapped_in_bnp :", sorted(r.unmapped_in_bnp_df["Portfolio code"].tolist()))
    assert r.summary["matched"] == 2
    assert set(r.missing_from_bnp_df["Hiport Code"]) == {"M1GONE","M1OLD9","M1TERM"}
    assert set(r.unmapped_in_bnp_df["Portfolio code"]) == {"M1NEW1"}
    print("  OK")
