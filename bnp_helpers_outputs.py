# -*- coding: utf-8 -*-
"""
bnp_helpers_outputs.py  (v314 - Outputs: in-app control summary + SF/Trust status)
v314.1 FIX: Arrow serialization error on the 'Population' (and 'Exceptions')
columns. Those columns mixed empty strings ('') with ints in one object column,
which Streamlit's pyarrow.Table.from_pandas cannot convert. They are now rendered
as consistent STRINGS, and a belt-and-braces _arrow_safe() guard is applied to
every st.dataframe so no future mixed-type column can trigger this again.

Replaces the legacy workbook "Create Outputs" with in-app panels; no Excel written.
  1. CONTROL SUMMARY - one row per ARC-replacement control: exception count + RAG.
  2. SF / TRUST STATUS DASHBOARDS - mirror the workbook sign-off rows, computed on
     each entity's (NULIS / MLCI) subset.
All figures are READ from dataframes the other checks already place on the bundle.
Nothing is recomputed here - presentation/rollup only.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import pandas as pd

OUTPUTS_VERSION = "v314.1"

STATUS_OK = "Ok"
STATUS_CHECK = "Check"
STATUS_NA = "n/a"


def _df(bundle: Dict[str, object], key: str) -> pd.DataFrame:
    v = bundle.get(key) if isinstance(bundle, dict) else None
    return v if isinstance(v, pd.DataFrame) else pd.DataFrame()


def _count_where(df: pd.DataFrame, col: str, value) -> int:
    if not isinstance(df, pd.DataFrame) or df.empty or col not in df.columns:
        return 0
    if isinstance(value, (list, tuple, set)):
        return int(df[col].astype(str).str.strip().isin([str(x) for x in value]).sum())
    return int((df[col].astype(str).str.strip() == str(value)).sum())


def _norm_token(v) -> str:
    t = str(v or "").strip()
    first = t.split()[0] if t else ""
    return "".join(ch for ch in first.upper() if ch.isalnum())


def _norm_key(v) -> str:
    return "".join(ch for ch in str(v or "").upper().strip() if ch.isalnum())


# ---------------------------------------------------------------------------
# Arrow-safe display guard
# ---------------------------------------------------------------------------
def _arrow_safe(df: pd.DataFrame) -> pd.DataFrame:
    """Make a display dataframe Arrow-serialisable for st.dataframe.

    Any object column that mixes strings with numbers (e.g. '' and ints) breaks
    Streamlit's Arrow conversion. Coerce such mixed object columns to string so
    display never raises. Clean/numeric-only columns are left untouched.
    """
    if not isinstance(df, pd.DataFrame) or df.empty:
        return df
    out = df.copy()
    for col in out.columns:
        s = out[col]
        if s.dtype == object:
            has_num = s.map(lambda x: isinstance(x, (int, float)) and not isinstance(x, bool)).any()
            has_str = s.map(lambda x: isinstance(x, str)).any()
            if has_num and has_str:
                out[col] = s.map(lambda x: "" if x is None else str(x))
    return out


# ---------------------------------------------------------------------------
# Entity map (NULIS / MLCI) for the SF vs Trust split
# ---------------------------------------------------------------------------
def build_entity_map(bundle: Dict[str, object]) -> Dict[str, str]:
    """Return {key -> 'NULIS'|'MLCI'} keyed by BOTH advisor token and Hiport, so
    any check dataframe can be tagged by entity. Sources, in order:
      1. the v308 universe result (Central Mapping 'Entity' + Advisor/Hiport),
      2. portfolio_df 'Entity' column if present."""
    emap: Dict[str, str] = {}

    def _norm_entity(x) -> str:
        s = str(x or "").strip().upper()
        if s.startswith("NULIS"):
            return "NULIS"
        if s.startswith("MLCI"):
            return "MLCI"
        return ""

    uni = bundle.get("_universe_result_v308") if isinstance(bundle, dict) else None
    udf = getattr(uni, "universe_df", None) if uni is not None else None
    if isinstance(udf, pd.DataFrame) and not udf.empty and "Entity" in udf.columns:
        adv_col = "Advisor Code" if "Advisor Code" in udf.columns else None
        hip_col = "Hiport Code" if "Hiport Code" in udf.columns else None
        for _, r in udf.iterrows():
            ent = _norm_entity(r.get("Entity"))
            if not ent:
                continue
            if adv_col and r.get(adv_col):
                emap.setdefault(_norm_token(r[adv_col]), ent)
            if hip_col and r.get(hip_col):
                emap.setdefault(_norm_key(r[hip_col]), ent)

    pf = _df(bundle, "portfolio_df")
    if not pf.empty and "Entity" in pf.columns:
        code_col = "Portfolio code" if "Portfolio code" in pf.columns else None
        adv_col = "External portfolio reference" if "External portfolio reference" in pf.columns else None
        for _, r in pf.iterrows():
            ent = _norm_entity(r.get("Entity"))
            if not ent:
                continue
            if code_col and r.get(code_col):
                emap.setdefault(_norm_key(r[code_col]), ent)
            if adv_col and r.get(adv_col):
                emap.setdefault(_norm_token(r[adv_col]), ent)
    return emap


def _entity_series(df: pd.DataFrame, emap: Dict[str, str]) -> pd.Series:
    """Tag each row of a check df with NULIS/MLCI using whatever key it exposes."""
    if not isinstance(df, pd.DataFrame) or df.empty or not emap:
        return pd.Series([""] * (0 if not isinstance(df, pd.DataFrame) else len(df)),
                         index=(df.index if isinstance(df, pd.DataFrame) else None), dtype="object")
    ent = pd.Series("", index=df.index, dtype="object")
    for col, keyfn in [("Portfolio code", _norm_key), ("External portfolio reference", _norm_token),
                       ("Advisor", _norm_token), ("Portfolio", _norm_key)]:
        if col in df.columns:
            k = df[col].map(keyfn)
            cand = k.map(lambda x: emap.get(x, ""))
            ent = ent.where(ent.ne(""), cand)
    return ent


def _hotcold_counts(bundle: Dict[str, object], entity: Optional[str] = None,
                    emap: Optional[Dict[str, str]] = None) -> Dict[str, int]:
    pf = _df(bundle, "portfolio_df")
    out = {"OUT": 0, "Hot": 0, "Cold": 0, "No source": 0}
    if pf.empty or "Hot / Cold" not in pf.columns:
        return out
    hc = pf["Hot / Cold"].astype(str).str.strip()
    if "Within Tolerance" in pf.columns:
        outm = ~pf["Within Tolerance"].fillna(True).astype(bool)
    else:
        outm = hc.isin(["Hot", "Cold", "No BP Impact row", "No Error Risk row", "No ARC match"])
    if entity and emap:
        ent = _entity_series(pf, emap)
        outm = outm & ent.eq(entity)
    out["OUT"] = int(outm.sum())
    out["Hot"] = int((outm & hc.eq("Hot")).sum())
    out["Cold"] = int((outm & hc.eq("Cold")).sum())
    out["No source"] = int((outm & hc.isin(["No BP Impact row", "No Error Risk row", "No ARC match"])).sum())
    return out


# ---------------------------------------------------------------------------
# 1. Control summary
# ---------------------------------------------------------------------------
def build_control_summary(bundle: Dict[str, object]) -> pd.DataFrame:
    """One row per control: exceptions + status, rolled up from bundle results."""
    rows: List[Dict[str, Any]] = []

    def _s(x) -> str:
        # Consistent string rendering so a column never mixes '' with ints.
        if x is None or x == "":
            return ""
        if isinstance(x, bool):
            return str(x)
        if isinstance(x, (int, float)):
            try:
                return f"{int(x):,}"
            except Exception:
                return str(x)
        return str(x)

    def add(control, exceptions, population, note=""):
        exceptions = int(exceptions) if exceptions is not None else None
        status = (STATUS_NA if exceptions is None
                  else (STATUS_CHECK if exceptions > 0 else STATUS_OK))
        # v314.1: Exceptions and Population are STRINGS (mixing '' and ints in one
        # object column breaks Streamlit's Arrow serialization).
        rows.append({"Control": control,
                     "Exceptions": ("" if exceptions is None else _s(exceptions)),
                     "Population": _s(population),
                     "Status": status, "Note": note})

    # Universe
    us = bundle.get("universe_reconciliation_summary") if isinstance(bundle, dict) else None
    if isinstance(us, dict):
        add("Portfolios - missing from BNP", int(us.get("missing_from_bnp", 0)), us.get("universe", ""), "mapped but absent today")
        add("Portfolios - unmapped in BNP", int(us.get("unmapped_in_bnp", 0)), us.get("bnp_today", ""), "in BNP, not mapped")
    else:
        add("Portfolios reconciliation", None, "", "not run this session")

    # GAV
    gav = _df(bundle, "gav_check_df")
    add("GAV", _count_where(gav, "Check", "Check"), len(gav) or "", "|% impact| > tol")

    # Return recon + OUT (Unison)
    rsum = bundle.get("return_check_summary") if isinstance(bundle, dict) else None
    if isinstance(rsum, dict):
        add("Advisor Return - reconciliation", rsum.get("recon_true_anomalies", rsum.get("recon_checks", 0)), rsum.get("portfolios", ""), f"|Unison - BNP| > tol (true anomalies; {int(rsum.get('recon_sign_flips', 0))} sign-flips excluded)")
        add("Advisor Return - OUT", rsum.get("out_unison_basis", 0), rsum.get("portfolios", ""), "|Unison - Benchmark| >= tol")
    else:
        rc = _df(bundle, "return_check_df")
        add("Advisor Return - reconciliation", _count_where(rc, "Return recon Check", "Check"), len(rc) or "")

    # Error risk Hot/Cold
    hc = _hotcold_counts(bundle)
    add("Error Risk - Hot", hc["Hot"], hc["OUT"], "Hot portfolios among OUT")

    # UUT look-through (v311.1 corrected)
    uut = _df(bundle, "advisor_uut_df_v311_1")
    add("Advisor-UUT", _count_where(uut, "Breach", "Check"),
        _count_where(uut, "In UUT population", "True") or (len(uut) or ""), "Unison vs weighted UUT (Income staged)")

    # Ancillary
    clr = _df(bundle, "clearing_check_df")
    add("Clearing", _count_where(clr, "Check", "Check"), len(clr) or "", "|End balance| > $1")
    nn = _df(bundle, "negative_nav_df")
    add("Negative NAV", _count_where(nn, "Negative NAV flag", "True"), len(nn) or "")

    # Price integrity
    add("Stale Price", _count_where(_df(bundle, "stale_price_df"), "Stale Price Check", "Stale"),
        len(_df(bundle, "stale_price_df")) or "")
    add("Material Movement", len(_df(bundle, "material_movement_df")) or 0,
        "", ">1% / <-0.5% on UUT holdings")

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 2. SF / Trust Status Dashboards (mirror the workbook)
# ---------------------------------------------------------------------------
def build_status_dashboard(bundle: Dict[str, object], entity: str,
                           emap: Optional[Dict[str, str]] = None) -> pd.DataFrame:
    """Mirror the workbook 'Status Dashboard' for entity in {'SF','Trust'},
    computing each row's count on that entity's SUBSET only (NULIS vs MLCI)."""
    ent_code = "NULIS" if entity == "SF" else "MLCI"
    have_split = bool(emap)

    gav = _df(bundle, "gav_check_df")
    rc = _df(bundle, "return_check_df")
    clr = _df(bundle, "clearing_check_df")

    if have_split:
        gav_ent = _entity_series(gav, emap)
        rc_ent = _entity_series(rc, emap)
        clr_ent = _entity_series(clr, emap)
        unison_fails = int(((rc.get("Return recon Check", pd.Series(dtype=object)).astype(str).str.strip() == "Check")
                            & rc_ent.eq(ent_code)).sum()) if "Return recon Check" in rc.columns else 0
        out_unison = int((rc.get("OUT (Unison basis)", pd.Series(dtype=object)).fillna(False).astype(bool)
                          & rc_ent.eq(ent_code)).sum()) if "OUT (Unison basis)" in rc.columns else 0
        gav_checks = int(((gav.get("Check", pd.Series(dtype=object)).astype(str).str.strip() == "Check")
                          & gav_ent.eq(ent_code)).sum()) if "Check" in gav.columns else 0
        clearing = int(((clr.get("Check", pd.Series(dtype=object)).astype(str).str.strip() == "Check")
                        & clr_ent.eq(ent_code)).sum()) if "Check" in clr.columns else 0
        advisor_fails = int(_hotcold_counts(bundle, entity=ent_code, emap=emap)["Hot"])
    else:
        rsum = bundle.get("return_check_summary") if isinstance(bundle, dict) else {}
        rsum = rsum if isinstance(rsum, dict) else {}
        unison_fails = int(rsum.get("recon_checks", _count_where(rc, "Return recon Check", "Check")))
        out_unison = int(rsum.get("out_unison_basis", 0))
        gav_checks = int(_count_where(gav, "Check", "Check"))
        clearing = int(_count_where(clr, "Check", "Check"))
        advisor_fails = int(_hotcold_counts(bundle)["Hot"])

    nav_ror = gav_checks + out_unison

    def outcome(n):
        return STATUS_CHECK if n > 0 else STATUS_OK
    rows = [
        {"Check": "Unison fails", "Count": unison_fails, "Outcome": outcome(unison_fails)},
        {"Check": "Advisor fails (error risk)", "Count": advisor_fails, "Outcome": outcome(advisor_fails)},
        {"Check": "NAV Check & ROR Check", "Count": nav_ror, "Outcome": outcome(nav_ror)},
        {"Check": "Investment & cash clearing", "Count": clearing, "Outcome": outcome(clearing)},
    ]
    df = pd.DataFrame(rows)
    df.attrs["entity"] = "NULIS (Statutory Funds)" if entity == "SF" else "MLCI (Trusts)"
    df.attrs["entity_split"] = have_split
    return df


@dataclass
class OutputsResult:
    control_summary_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    sf_status_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    trust_status_df: pd.DataFrame = field(default_factory=pd.DataFrame)
    overall_status: str = STATUS_OK
    entity_split: bool = False


def build_outputs(bundle: Dict[str, object]) -> OutputsResult:
    cs = build_control_summary(bundle)
    emap = build_entity_map(bundle)
    sf = build_status_dashboard(bundle, "SF", emap)
    tr = build_status_dashboard(bundle, "Trust", emap)
    overall = STATUS_CHECK if (not cs.empty and (cs["Status"] == STATUS_CHECK).any()) else STATUS_OK
    res = OutputsResult(cs, sf, tr, overall)
    res.entity_split = bool(emap)
    return res


def render_outputs_section(st, bundle: Dict[str, object]) -> None:
    """Render Portfolio Numbers -> Outputs (control summary + SF/Trust status)."""
    try:
        res = build_outputs(bundle)
        if isinstance(bundle, dict):
            bundle["control_summary_df"] = res.control_summary_df
            bundle["sf_status_df"] = res.sf_status_df
            bundle["trust_status_df"] = res.trust_status_df

        st.markdown("**Control summary & sign-off (v314)** - replaces the workbook "
                    "Create Outputs / SF & Trusts Checklist. All in-app; no Excel written.")
        badge = "OK - all controls within tolerance" if res.overall_status == STATUS_OK else "CHECK - one or more controls have exceptions"
        (st.success if res.overall_status == STATUS_OK else st.warning)(badge)

        st.markdown("**Control summary**")
        st.dataframe(_arrow_safe(res.control_summary_df), width="stretch", hide_index=True)
        st.download_button("Download control summary", res.control_summary_df.to_csv(index=False).encode("utf-8"),
                           "control_summary_last_run.csv", "text/csv", key="v314_summary_dl")

        c1, c2 = st.columns(2)
        with c1:
            st.markdown(f"**SF Status Dashboard** - {res.sf_status_df.attrs.get('entity','')}")
            st.dataframe(_arrow_safe(res.sf_status_df), width="stretch", hide_index=True)
        with c2:
            st.markdown(f"**Trust Status Dashboard** - {res.trust_status_df.attrs.get('entity','')}")
            st.dataframe(_arrow_safe(res.trust_status_df), width="stretch", hide_index=True)

        if res.entity_split:
            st.caption("Status dashboards mirror the workbook sign-off rows (Unison fails / "
                       "Advisor fails (error risk) / NAV Check & ROR Check / Investment & cash "
                       "clearing), computed on each entity's SUBSET (NULIS vs MLCI, from the "
                       "Central Mapping List). SF and Trust counts therefore differ.")
        else:
            st.warning("Entity split unavailable - the Universe (Central Mapping) is not loaded "
                       "this run, so SF and Trust show the COMBINED figures. Open the Universe "
                       "panel (or ensure central_mapping_workbook is configured) to split by "
                       "NULIS/MLCI.")
    except Exception:
        pass


if __name__ == "__main__":
    import pyarrow as pa
    print(f"[{OUTPUTS_VERSION}] outputs self-test + Arrow serialization")
    bundle = {
        "universe_reconciliation_summary": {"universe": 457, "bnp_today": 328, "missing_from_bnp": 5, "unmapped_in_bnp": 29},
        "gav_check_df": pd.DataFrame({"Check": ["Ok"] * 191 + ["Check"] * 3}),
        "return_check_summary": {"portfolios": 194, "recon_checks": 18, "out_unison_basis": 87},
        "portfolio_df": pd.DataFrame({"Hot / Cold": ["Hot"] * 50 + ["Cold"] * 74 + ["No BP Impact row"] * 29 + [""] * 175,
                                      "Within Tolerance": [False] * 153 + [True] * 175}),
        "advisor_uut_df_v311_1": pd.DataFrame({"Breach": ["Check"] * 12 + ["Ok"] * 17 + ["Excluded (not UUT/PE)"] * 74,
                                               "In UUT population": [True] * 29 + [False] * 74}),
        "clearing_check_df": pd.DataFrame({"Check": ["Check"] * 189 + ["Ok"] * 807}),
        "negative_nav_df": pd.DataFrame({"Negative NAV flag": [True] * 3 + [False] * 280}),
        "stale_price_df": pd.DataFrame({"Stale Price Check": ["Stale"] * 380 + ["Ok"] * 1370}),
        "material_movement_df": pd.DataFrame({"x": range(5)}),
    }
    res = build_outputs(bundle)
    cs = res.control_summary_df
    print(cs.to_string(index=False))
    # THE regression test: the exact operation Streamlit does that was crashing.
    pa.Table.from_pandas(_arrow_safe(cs))
    pa.Table.from_pandas(_arrow_safe(res.sf_status_df))
    pa.Table.from_pandas(_arrow_safe(res.trust_status_df))
    # also prove the raw (unguarded) summary now serialises too (root-cause fix):
    pa.Table.from_pandas(cs)
    assert cs["Population"].dtype == object and (cs["Population"].map(type).eq(str)).all(), "Population must be all-string"
    assert (cs["Exceptions"].map(type).eq(str)).all(), "Exceptions must be all-string"
    print("\nPASS: Arrow serialization OK (Population/Exceptions all-string; _arrow_safe applied)")
