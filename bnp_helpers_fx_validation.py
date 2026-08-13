# -*- coding: utf-8 -*-
"""BNP Control App FX helper - FX-only contribution retest.

v305.1 Auto FX contribution basis change:
- Auto FX starting break is DDetailedReturn Actual vs Benchmark only.
- No Over/Under, calculated over/under, or line-level Excess Contribution fallback is applied.
- Price-nil included FX lines remove the full source Asset to Portfolio Contribution.
- Price-bearing included FX lines remove the FX-only portion of source Asset to Portfolio Contribution:
      Asset to Portfolio Contribution * FX Return / Actual Return
- Asset Weight is retained as a diagnostic only and is not used to calculate FX contribution removal.
- If Actual vs Benchmark or Asset to Portfolio Contribution is unavailable, the relevant value remains blank.
"""
from __future__ import annotations

from typing import List, Optional, Tuple
import re
import pandas as pd


def _norm(x):
    return re.sub(r"[^a-z0-9]+", "", str(x).strip().lower())


def _first_col(df, names: List[str]) -> str:
    if not isinstance(df, pd.DataFrame) or df.empty:
        return ""
    lookup = {_norm(c): c for c in df.columns}
    exact = {str(c).strip(): c for c in df.columns}
    for n in names:
        if n in exact:
            return exact[n]
        if _norm(n) in lookup:
            return lookup[_norm(n)]
    return ""


def _num(x):
    def clean(v):
        if pd.isna(v):
            return pd.NA
        s = str(v).strip()
        if s == "":
            return pd.NA
        neg = s.startswith("(") and s.endswith(")")
        s = s.strip("()").replace(",", "").replace("$", "").replace("%", "")
        try:
            out = float(s)
            return -out if neg else out
        except Exception:
            return pd.NA

    if isinstance(x, pd.Series):
        return pd.to_numeric(x.map(clean), errors="coerce")
    return pd.to_numeric(pd.Series([clean(x)]), errors="coerce").iloc[0]


def _pp_from_series(series: pd.Series, col_name: str = "", *, decimal_hint: bool = False) -> pd.Series:
    values = _num(series)
    norm_col = _norm(col_name)
    if decimal_hint or norm_col.endswith("decimal") or norm_col in {"calculatedactualvbenchmarkdiffnum", "volatilityovertolerancenum"}:
        values = values * 100.0
    return values


def _independent_fx_map(exchange_rate_df: Optional[pd.DataFrame]) -> Tuple[pd.DataFrame, str]:
    fx = exchange_rate_df if isinstance(exchange_rate_df, pd.DataFrame) else pd.DataFrame()
    empty = pd.DataFrame(columns=["CCY", "Independent FX Return", "Independent FX Source", "Independent FX Label"])
    if fx.empty:
        return empty, "No independent FX rows available"

    code_col = _first_col(fx, ["Code", "Currency", "CCY"])
    daily_col = _first_col(fx, ["Daily %", "Daily%", "Daily Return", "Daily Return %"])
    src_col = _first_col(fx, ["Source"])
    label_col = _first_col(fx, ["Index", "Currency Name", "Name"])
    if not code_col or not daily_col:
        return empty, "Independent FX code or Daily % column not found"

    s = _num(fx[daily_col])
    med = s.abs().median(skipna=True)
    if pd.notna(med) and med <= 0.10:
        s = s * 100.0
        note = "Independent Daily % scaled x100 to report percent units; sign inverted to match report FX convention"
    else:
        note = "Independent Daily % treated as report percent units; sign inverted to match report FX convention"

    out = pd.DataFrame()
    out["CCY"] = fx[code_col].astype(str).str.strip().str.upper()
    out["Independent FX Return"] = -s
    out["Independent FX Source"] = fx[src_col].astype(str).str.strip() if src_col else ""
    out["Independent FX Label"] = fx[label_col].astype(str).str.strip() if label_col else out["CCY"]
    out = out[(out["CCY"] != "") & out["Independent FX Return"].notna()].drop_duplicates("CCY")
    return out.reset_index(drop=True), note


def _portfolio_context(portfolio_df: Optional[pd.DataFrame]) -> pd.DataFrame:
    """Build the portfolio context used by Auto explained by FX.

    v305 policy:
    - Starting break is DDetailedReturn Actual vs Benchmark only.
    - No Over/Under, calculated over/under, Actual Return less Benchmark Return, or contribution fallback.
    """
    pf = portfolio_df if isinstance(portfolio_df, pd.DataFrame) else pd.DataFrame()
    cols = [
        "Portfolio", "Portfolio code", "Portfolio Name", "Hot / Cold", "Is HOT", "Status",
        "Largest Tier 1 driver", "Actual Portfolio Return", "Benchmark Return",
        "Actual vs Benchmark", "Tolerance", "Calculated Outside Tolerance",
        "ARC Error Risk Ratio", "Starting Break Basis",
    ]
    if pf.empty:
        return pd.DataFrame(columns=cols)

    def blank_num():
        return pd.Series(float("nan"), index=pf.index, dtype="float64")

    def pp_col(c: str, *, decimal_hint: bool = False) -> pd.Series:
        if not c or c not in pf.columns:
            return blank_num()
        return _pp_from_series(pf[c], c, decimal_hint=decimal_hint)

    port = _first_col(pf, ["Portfolio code", "Portfolio", "PortfolioCode"])
    name = _first_col(pf, ["Portfolio Name", "Name"])
    hot = _first_col(pf, ["Hot / Cold", "HotCold"])
    status = _first_col(pf, ["Status", "Tolerance Bucket"])
    driver = _first_col(pf, ["Largest Tier 1 driver", "Largest Tier 1 Driver", "Tier 1 driver", "Largest Driver", "Composition", "Top asset types", "Transaction nature"])
    actual_ret = _first_col(pf, ["Actual Portfolio Return", "Actual Return", "Asset return %", "Asset Return", "Portfolio Actual Return", "Actual Return Num", "Asset return % Decimal"])
    benchmark_ret = _first_col(pf, ["Benchmark Return", "Benchmark return", "Benchmark Return Num", "Benchmark return %", "Benchmark Return Decimal"])
    actual_vs_benchmark = _first_col(pf, [
        "Actual vs Benchmark", "Actual vs Benchmark Num", "Actual vs Benchmark Decimal",
        "Actual v Benchmark", "Actual v Benchmark Num", "Actual V Benchmark", "Actual V Benchmark Num",
    ])
    tol = _first_col(pf, ["Tolerance", "Tolerance Num", "Tolerance Decimal"])
    arc = _first_col(pf, ["ARC Error Risk Ratio", "ARC Error Risk %", "ARC Error Risk Ratio Decimal", "Error Risk Ratio Decimal"])

    out = pd.DataFrame(index=pf.index)
    out["Portfolio"] = pf[port].astype(str).str.strip() if port else ""
    out["Portfolio code"] = out["Portfolio"]
    out["Portfolio Name"] = pf[name].astype(str).str.strip() if name else ""
    out["Hot / Cold"] = pf[hot].astype(str).str.strip() if hot else ""
    out["Is HOT"] = out["Hot / Cold"].eq("Hot")
    out["Status"] = pf[status].astype(str).str.strip() if status else ""
    out["Largest Tier 1 driver"] = pf[driver].astype(str).str.strip() if driver else "Unclassified"

    out["Actual Portfolio Return"] = pp_col(actual_ret)
    out["Benchmark Return"] = pp_col(benchmark_ret)
    out["Actual vs Benchmark"] = pp_col(actual_vs_benchmark, decimal_hint=("Decimal" in str(actual_vs_benchmark)))
    out["Tolerance"] = pp_col(tol).abs()
    out["Calculated Outside Tolerance"] = (out["Actual vs Benchmark"].abs() - out["Tolerance"].abs()).clip(lower=0)

    out["Starting Break Basis"] = "DDetailedReturn Actual vs Benchmark"
    out.loc[out["Actual vs Benchmark"].isna(), "Starting Break Basis"] = "None - Actual vs Benchmark unavailable"

    if arc:
        arc_raw = pp_col(arc, decimal_hint=("Decimal" in str(arc))).abs()
        arc_median = arc_raw.dropna().median() if isinstance(arc_raw, pd.Series) else pd.NA
        if pd.notna(arc_median) and 0 < float(arc_median) <= 1.0 and "Decimal" not in str(arc):
            out["ARC Error Risk Ratio"] = arc_raw * 100.0
        else:
            out["ARC Error Risk Ratio"] = arc_raw
    else:
        out["ARC Error Risk Ratio"] = pd.NA

    return out[out["Portfolio"].astype(str).str.strip() != ""].drop_duplicates("Portfolio").reset_index(drop=True)[cols]


def build_portfolio_fx_validation(
    report_df: Optional[pd.DataFrame],
    exchange_rate_df: Optional[pd.DataFrame],
    *,
    portfolio_df: Optional[pd.DataFrame] = None,
    exclude_base_ccy: str = "AUD",
    materiality_dollar: float = 1.0,
    line_match_tolerance_dollar: float = 100.0,
):
    report = report_df if isinstance(report_df, pd.DataFrame) else pd.DataFrame()
    fx_map, note = _independent_fx_map(exchange_rate_df)
    ctx = _portfolio_context(portfolio_df)
    controls = [
        {"Measure": "Independent FX scale note", "Value": note},
        {"Measure": "Independent FX currencies available", "Value": int(len(fx_map))},
        {"Measure": "FX retest basis", "Value": "Starting break is DDetailedReturn Actual vs Benchmark. No Over/Under, calculated over/under, or contribution fallback is applied."},
        {"Measure": "FX contribution basis", "Value": "Full line contribution for price-nil lines; Asset to Portfolio Contribution x FX Return / Actual Return for price-bearing lines."},
        {"Measure": "FX pure-line dollar check basis", "Value": "For pure FX rows only, subtract transaction amount from current FDV before comparing report FX dollars to independent FX dollars"},
        {"Measure": "FX line inclusion tolerance", "Value": float(line_match_tolerance_dollar)},
    ]
    if report.empty:
        return ctx, pd.DataFrame(), pd.DataFrame(controls)

    port = _first_col(report, ["Portfolio", "Portfolio code", "Portfolio Code"])
    ccy = _first_col(report, ["CCY", "Currency"])
    fdv = _first_col(report, ["FDV Valuation Curr_Day", "FDV Valuation Current Day", "FDV Valuation Curr Day", "FDV Valuation"])
    fxret = _first_col(report, ["FX Return"])
    actual_return_col = _first_col(report, ["Actual Return", "Actual return", "ActualReturn"])
    price_ret = _first_col(report, ["Price Return", "PriceReturn"])
    asset_to_portfolio = _first_col(report, [
        "Asset to Portfolio Contributions", "Asset to Portfolio Contribution",
        "Asset To Portfolio Contributions", "Asset To Portfolio Contribution",
        "AssetToPortfolioContributions", "AssetToPortfolioContribution",
    ])
    exc = _first_col(report, ["Excess Contribution"])
    asset_weight = _first_col(report, ["Asset Weight", "AssetWeight"])
    transactions_col = _first_col(report, ["All Transactions", "AllTransactions", "Transactions", "Transaction Amount", "TransactionAmount"])
    asset_type_col = _first_col(report, ["Asset Type", "AssetType"])
    asset_type_desc_col = _first_col(report, ["Asset Type description", "Asset Type Description", "AssetTypeDescription", "Asset Type Desc", "AssetTypeDesc"])
    asset_code_col = _first_col(report, ["Asset Code", "AssetCode"])

    required = [("Portfolio", port), ("CCY", ccy), ("FDV Valuation Curr_Day", fdv), ("FX Return", fxret)]
    missing = [n for n, c in required if not c]
    if missing:
        controls.append({"Measure": "Missing required report columns", "Value": ", ".join(missing)})
        return ctx, pd.DataFrame(), pd.DataFrame(controls)
    if not asset_to_portfolio:
        controls.append({"Measure": "Missing Asset to Portfolio Contribution column", "Value": "No Asset to Portfolio Contribution fallback is applied"})
    if not actual_return_col:
        controls.append({"Measure": "Missing Actual Return column", "Value": "Price-bearing FX-only contribution cannot be calculated without Actual Return"})

    d = pd.DataFrame()
    d["Portfolio"] = report[port].astype(str).str.strip()
    d["CCY"] = report[ccy].astype(str).str.strip().str.upper()
    d["FDV Valuation Curr_Day"] = _num(report[fdv])
    d["Report FX Return"] = _num(report[fxret])
    d["Actual Return"] = _num(report[actual_return_col]) if actual_return_col else pd.NA
    d["Price Return"] = _num(report[price_ret]) if price_ret else 0.0
    d["Price Return"] = d["Price Return"].fillna(0.0)
    d["Asset to Portfolio Contribution"] = _num(report[asset_to_portfolio]) if asset_to_portfolio else pd.NA
    d["Excess Contribution"] = _num(report[exc]) if exc else pd.NA
    d["Asset Weight"] = _num(report[asset_weight]) if asset_weight else pd.NA
    d["Transaction Amount"] = _num(report[transactions_col]) if transactions_col else 0.0
    d["Price Return Is Nil"] = d["Price Return"].abs() <= 1e-9

    asset_type_text = report[asset_type_col].astype(str).str.strip().str.upper() if asset_type_col else pd.Series("", index=report.index, dtype="object")
    asset_type_desc_text = report[asset_type_desc_col].astype(str).str.strip().str.upper() if asset_type_desc_col else pd.Series("", index=report.index, dtype="object")
    asset_code_text = report[asset_code_col].astype(str).str.strip().str.upper() if asset_code_col else pd.Series("", index=report.index, dtype="object")
    d["Pure FX Line"] = (
        asset_type_text.str.startswith("ZF")
        | asset_code_text.str.startswith("ZF")
        | asset_type_desc_text.str.contains("FOREIGN EXCHANGE", na=False)
        | asset_type_desc_text.eq("FX")
    )

    d["FX Transaction Adjustment Applied"] = 0.0
    transaction_adjustment_mask = d["Pure FX Line"] & d["Transaction Amount"].notna() & (d["Transaction Amount"].abs() > 1e-12)
    d.loc[transaction_adjustment_mask, "FX Transaction Adjustment Applied"] = d.loc[transaction_adjustment_mask, "Transaction Amount"]
    d["FX Valuation Amount For Dollar Check"] = d["FDV Valuation Curr_Day"] - d["FX Transaction Adjustment Applied"]
    d["FX Dollar Check Basis"] = "FDV Valuation Curr_Day"
    d.loc[transaction_adjustment_mask, "FX Dollar Check Basis"] = "FDV Valuation Curr_Day less transaction amount for pure FX line"

    actual_nonzero = d["Actual Return"].abs() > 1e-12
    d["Effective Contribution Weight"] = pd.NA
    d.loc[actual_nonzero, "Effective Contribution Weight"] = (
        d.loc[actual_nonzero, "Asset to Portfolio Contribution"]
        / d.loc[actual_nonzero, "Actual Return"]
    )
    d["Calculated FX-only Contribution"] = pd.NA
    d.loc[actual_nonzero, "Calculated FX-only Contribution"] = (
        d.loc[actual_nonzero, "Effective Contribution Weight"]
        * d.loc[actual_nonzero, "Report FX Return"]
    )

    for out_col, candidates in {
        "Asset Code": ["Asset Code", "AssetCode"],
        "Asset Name": ["Asset Name", "AssetName"],
        "Asset Type": ["Asset Type", "AssetType"],
        "Asset Type description": ["Asset Type description", "Asset Type Description", "AssetTypeDescription"],
        "Trust/Sector": ["Trust/Sector", "Trust Sector"],
        "Effective_date": ["Effective_date", "Effective Date"],
    }.items():
        c = _first_col(report, candidates)
        d[out_col] = report[c].astype(str).str.strip() if c else ""

    d = d[(d["CCY"] != "") & (d["CCY"] != str(exclude_base_ccy or "AUD").upper())].copy()
    d = d.merge(fx_map, on="CCY", how="left")
    d["FX Match Status"] = d["Independent FX Return"].apply(lambda x: "Matched" if pd.notna(x) else "No independent FX")
    d["Report FX $"] = d["FX Valuation Amount For Dollar Check"] * d["Report FX Return"] / 100.0
    d["Independent FX $"] = d["FX Valuation Amount For Dollar Check"] * d["Independent FX Return"] / 100.0
    d["FX Return Difference"] = d["Report FX Return"] - d["Independent FX Return"]
    d["FX $ Difference"] = d["Report FX $"] - d["Independent FX $"]
    d["Abs FX $ Difference"] = d["FX $ Difference"].abs()
    d["FX Line Included In Auto Explain"] = d["FX Match Status"].eq("Matched") & d["Abs FX $ Difference"].notna() & (d["Abs FX $ Difference"] <= float(line_match_tolerance_dollar or 0))
    d["FX Line Ignore Reason"] = ""
    d.loc[d["FX Match Status"].ne("Matched"), "FX Line Ignore Reason"] = "No independent FX rate"
    d.loc[d["FX Match Status"].eq("Matched") & ~d["FX Line Included In Auto Explain"], "FX Line Ignore Reason"] = "FX line outside dollar tolerance"

    included = d["FX Line Included In Auto Explain"].fillna(False).astype(bool)
    price_nil = d["Price Return Is Nil"].fillna(False).astype(bool)

    d["FX Removal Basis"] = "Not included"
    d.loc[included & price_nil, "FX Removal Basis"] = "Full Asset to Portfolio Contribution - price return nil"
    d.loc[included & ~price_nil, "FX Removal Basis"] = "FX-only share of Asset to Portfolio Contribution - price-bearing asset"
    missing_calc = included & ~price_nil & d["Calculated FX-only Contribution"].isna()
    d.loc[missing_calc, "FX Removal Basis"] = "Not removed - Actual Return or Asset to Portfolio Contribution unavailable"

    d["FX Full Line Contribution Removed"] = pd.Series(0.0, index=d.index, dtype="float64")
    d.loc[included & price_nil, "FX Full Line Contribution Removed"] = d.loc[included & price_nil, "Asset to Portfolio Contribution"].fillna(0.0).astype(float)
    d["FX-only Contribution Removed"] = pd.Series(0.0, index=d.index, dtype="float64")
    fx_only_mask = included & ~price_nil & d["Calculated FX-only Contribution"].notna()
    d.loc[fx_only_mask, "FX-only Contribution Removed"] = d.loc[fx_only_mask, "Calculated FX-only Contribution"].astype(float)
    d["FX Matched Contribution Removed"] = d["FX Full Line Contribution Removed"] + d["FX-only Contribution Removed"]

    if d.empty:
        return ctx, d, pd.DataFrame(controls)

    grouped = d.groupby("Portfolio", dropna=False).agg(
        FX_Line_Count=("Portfolio", "size"),
        FX_Matched_Line_Count=("FX Line Included In Auto Explain", lambda s: int(pd.Series(s).fillna(False).astype(bool).sum())),
        FX_Price_Nil_Line_Count=("Price Return Is Nil", lambda s: int(pd.Series(s).fillna(False).astype(bool).sum())),
        FX_Pure_Line_Count=("Pure FX Line", lambda s: int(pd.Series(s).fillna(False).astype(bool).sum())),
        FX_Pure_Line_Transaction_Adjusted_Count=("FX Transaction Adjustment Applied", lambda s: int((_num(pd.Series(s)).abs() > 1e-12).sum())),
        FX_Pure_Line_Transaction_Adjustment=("FX Transaction Adjustment Applied", "sum"),
        Matched_FX_Full_Line_Contribution_Removed=("FX Full Line Contribution Removed", "sum"),
        Matched_FX_Only_Contribution_Removed=("FX-only Contribution Removed", "sum"),
        Matched_FX_Contribution_Removed=("FX Matched Contribution Removed", "sum"),
        Source_Asset_to_Portfolio_Contribution_Total=("Asset to Portfolio Contribution", "sum"),
        Source_Excess_Contribution_Total=("Excess Contribution", "sum"),
        Matched_FX_Dollar_Difference=("FX $ Difference", "sum"),
        Sum_Abs_FX_Dollar_Difference=("Abs FX $ Difference", "sum"),
        Largest_Abs_Line_FX_Dollar_Difference=("Abs FX $ Difference", "max"),
        Compared_Currency_Count=("CCY", pd.Series.nunique),
    ).reset_index()

    if not ctx.empty:
        s = ctx.merge(grouped, on="Portfolio", how="left")
    else:
        s = grouped.copy()
        s["Portfolio code"] = s["Portfolio"]
        s["Is HOT"] = True
        s["Hot / Cold"] = "Hot"
        s["Actual vs Benchmark"] = pd.NA
        s["Tolerance"] = pd.NA
        s["ARC Error Risk Ratio"] = pd.NA
        s["Starting Break Basis"] = "No portfolio context"

    count_cols = ["FX_Line_Count", "FX_Matched_Line_Count", "FX_Price_Nil_Line_Count", "FX_Pure_Line_Count", "FX_Pure_Line_Transaction_Adjusted_Count", "Compared_Currency_Count"]
    for col in count_cols:
        s[col] = pd.to_numeric(s.get(col, 0), errors="coerce").fillna(0).astype(int)

    amount_cols = [
        "FX_Pure_Line_Transaction_Adjustment", "Matched_FX_Full_Line_Contribution_Removed",
        "Matched_FX_Only_Contribution_Removed", "Matched_FX_Contribution_Removed",
        "Source_Asset_to_Portfolio_Contribution_Total", "Source_Excess_Contribution_Total",
        "Matched_FX_Dollar_Difference", "Sum_Abs_FX_Dollar_Difference", "Largest_Abs_Line_FX_Dollar_Difference",
    ]
    for col in amount_cols:
        s[col] = pd.to_numeric(s.get(col, 0), errors="coerce").fillna(0.0)

    s = s.rename(columns={
        "FX_Line_Count": "FX Line Count",
        "FX_Matched_Line_Count": "FX Matched Line Count",
        "FX_Price_Nil_Line_Count": "FX Price Nil Line Count",
        "FX_Pure_Line_Count": "FX Pure Line Count",
        "FX_Pure_Line_Transaction_Adjusted_Count": "FX Pure Line Transaction Adjusted Count",
        "FX_Pure_Line_Transaction_Adjustment": "FX Pure Line Transaction Adjustment",
        "Matched_FX_Full_Line_Contribution_Removed": "Matched FX Full Line Contribution Removed",
        "Matched_FX_Only_Contribution_Removed": "Matched FX-only Contribution Removed",
        "Matched_FX_Contribution_Removed": "Matched FX Contribution Removed",
        "Source_Asset_to_Portfolio_Contribution_Total": "Source Asset to Portfolio Contribution Total",
        "Source_Excess_Contribution_Total": "Source Excess Contribution Total",
        "Matched_FX_Dollar_Difference": "Matched FX Dollar Difference",
        "Sum_Abs_FX_Dollar_Difference": "Sum Abs FX Dollar Difference",
        "Largest_Abs_Line_FX_Dollar_Difference": "Largest Abs Line FX Dollar Difference",
        "Compared_Currency_Count": "Compared Currency Count",
    })

    s["FX Ignored Line Count"] = (s["FX Line Count"] - s["FX Matched Line Count"]).clip(lower=0)
    s["Price-Bearing Non-AUD Lines"] = (s["FX Matched Line Count"] - s["FX Price Nil Line Count"]).clip(lower=0)
    s["Total FX Removal Applied"] = s["Matched FX Contribution Removed"]
    s["Residual Actual vs Benchmark After FX Removal"] = _num(s["Actual vs Benchmark"]) - _num(s["Total FX Removal Applied"])
    s["Remaining Actual vs Benchmark After FX Removal"] = s["Residual Actual vs Benchmark After FX Removal"]
    s["Remaining Outside Tolerance"] = (s["Remaining Actual vs Benchmark After FX Removal"].abs() - _num(s["Tolerance"]).abs()).clip(lower=0)
    s["Remaining Within Tolerance"] = s["Remaining Outside Tolerance"].fillna(float("inf")) <= 1e-9
    s["ARC Available"] = _num(s["ARC Error Risk Ratio"]).notna()
    s["Remaining Outside ARC Error Risk"] = (s["Remaining Actual vs Benchmark After FX Removal"].abs() - _num(s["ARC Error Risk Ratio"]).abs()).clip(lower=0)
    s["Remaining Within ARC Error Risk"] = s["ARC Available"] & (s["Remaining Outside ARC Error Risk"].fillna(float("inf")) <= 1e-9)

    matched = s["FX Matched Line Count"].fillna(0).astype(int) > 0
    hot = s.get("Is HOT", pd.Series(True, index=s.index)).fillna(False).astype(bool)
    fx_removal_applied = _num(s["Total FX Removal Applied"]).abs().fillna(0.0) > 1e-12
    s["FX Removal Applied"] = fx_removal_applied
    explained = hot & matched & fx_removal_applied & (s["Remaining Within Tolerance"] | s["Remaining Within ARC Error Risk"])

    s["Auto Explained by FX"] = explained.map({True: "Yes", False: "No"})
    s["Post FX Retest Status"] = "Not auto explained"
    s.loc[hot & matched & ~fx_removal_applied, "Post FX Retest Status"] = "No FX removal applied"
    s.loc[explained & s["Remaining Within Tolerance"], "Post FX Retest Status"] = "Within tolerance after FX removal"
    s.loc[explained & ~s["Remaining Within Tolerance"] & s["Remaining Within ARC Error Risk"], "Post FX Retest Status"] = "Within ARC error risk after FX removal"
    s["Retest Method"] = "Actual vs Benchmark less matched FX contribution removal"

    s["FX Auto Explanation Diagnostic"] = ""
    s.loc[~hot, "FX Auto Explanation Diagnostic"] = "Portfolio is not HOT"
    s.loc[hot & ~matched, "FX Auto Explanation Diagnostic"] = "No matched FX lines within dollar tolerance"
    s.loc[hot & matched & ~fx_removal_applied, "FX Auto Explanation Diagnostic"] = "Matched FX lines found, but total FX removal applied is zero; not treated as auto explained by FX"
    s.loc[explained, "FX Auto Explanation Diagnostic"] = "Matched non-zero FX removal amount applied; remaining Actual vs Benchmark is within tolerance or ARC error risk"
    s.loc[hot & matched & fx_removal_applied & ~explained, "FX Auto Explanation Diagnostic"] = "Matched FX removal amount applied; remaining Actual vs Benchmark remains outside tolerance and ARC error risk"

    preferred = [
        "Portfolio", "Portfolio code", "Portfolio Name", "Hot / Cold", "Status", "Largest Tier 1 driver",
        "Auto Explained by FX", "Post FX Retest Status", "FX Auto Explanation Diagnostic", "Retest Method",
        "Actual vs Benchmark", "Tolerance", "Calculated Outside Tolerance", "ARC Error Risk Ratio",
        "Actual Portfolio Return", "Benchmark Return", "Starting Break Basis",
        "Source Asset to Portfolio Contribution Total", "Source Excess Contribution Total",
        "FX Line Count", "FX Matched Line Count", "FX Price Nil Line Count", "FX Pure Line Count", "FX Pure Line Transaction Adjusted Count", "FX Pure Line Transaction Adjustment",
        "Price-Bearing Non-AUD Lines", "FX Ignored Line Count",
        "Matched FX Full Line Contribution Removed", "Matched FX-only Contribution Removed", "Matched FX Contribution Removed", "Total FX Removal Applied", "FX Removal Applied",
        "Residual Actual vs Benchmark After FX Removal", "Remaining Actual vs Benchmark After FX Removal", "Remaining Outside Tolerance", "Remaining Within Tolerance", "Remaining Outside ARC Error Risk", "Remaining Within ARC Error Risk",
        "Matched FX Dollar Difference", "Sum Abs FX Dollar Difference", "Largest Abs Line FX Dollar Difference", "Compared Currency Count", "ARC Available",
    ]
    s = s[[c for c in preferred if c in s.columns] + [c for c in s.columns if c not in preferred]]
    controls.append({"Measure": "Auto explained by FX YES count", "Value": int(s["Auto Explained by FX"].eq("Yes").sum()) if not s.empty else 0})
    return s, d, pd.DataFrame(controls)


__all__ = ["build_portfolio_fx_validation"]
