# -*- coding: utf-8 -*-
"""Transaction Listing helpers for BNP Control App v239.

v239 transaction control-break rules:
- Transaction Listing is a targeted control-break adjustment layer, not a broad second-pass performance engine.
- Eligible transaction categories are FX and derivatives.
- Cash/liquidity rows are eligible only when they are clearly linked to derivative/FX mechanics.
- Market asset/share-style transactions are excluded from transaction control-break adjustment because they should already flow through actual return.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import pandas as pd

from bnp_helpers_columns import find_col, normalise_join_key_series

TRANSACTION_CONTROL_BREAK_ELIGIBLE_PREFIXES = {"FU", "CO", "PO", "ZF"}
TRANSACTION_CONTROL_BREAK_CONDITIONAL_PREFIXES = {"ZL", "DS"}
TRANSACTION_CONTROL_BREAK_EXCLUDED_PREFIXES = {"OS", "CN", "FI", "RI"}
TRANSACTION_CONTROL_BREAK_CONDITIONAL_TOKENS = (
    "MARGIN", "MRGIN", "FUT", "FUTURE", "FUTURES", "FX", "FOREIGN EXCHANGE",
    "FORWARD", "SPOT", "DRIFT", "DERIV", "DERIVATIVE", "SETTLEMENT REALISED FX",
)

TXN_EXPLAIN_OUTPUT_COLUMNS: List[str] = [
    "Auto Explained by Transaction Listing",
    "Transaction Listing Case Type",
    "Transaction Listing Pathway Matched",
    "Transaction Listing Signed NetConsideration",
    "Transaction Listing Signed NetConsideration Pathway 1",
    "Transaction Listing % Previous FDV",
"Transaction Listing Starting Break",
"Transaction Listing Tolerance",
"Transaction Listing Effect % Previous FDV",
"Transaction Listing Break After Exclusion",
"Transaction Listing Within Tolerance After Exclusion",
"Transaction Listing Exclusion Test Result",
    "Transaction Listing Previous FDV",
    "Transaction Listing Control Break Eligible Rows",
    "Transaction Listing Control Break Ineligible Rows",
    "Transaction Listing Eligible Asset Prefixes",
    "Transaction Listing Ineligible Asset Prefixes",
    "Transaction Listing Eligible Scope",
    "Transaction Listing Candidate Status",
    "Transaction Listing Diagnostic Note",
]


def _norm_text(series: pd.Series) -> pd.Series:
    return (
        series.astype(str)
        .str.strip()
        .str.upper()
        .str.replace(r"\s+", " ", regex=True)
    )


def _safe_num(series: pd.Series) -> pd.Series:
    if series is None:
        return pd.Series(dtype="float64")
    return pd.to_numeric(
        series.astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("$", "", regex=False)
        .str.strip()
        .replace({"": pd.NA}),
        errors="coerce",
    )


def _default_output_df(index=None) -> pd.DataFrame:
    return pd.DataFrame(index=index if index is not None else pd.RangeIndex(0), columns=TXN_EXPLAIN_OUTPUT_COLUMNS)


def ensure_transactionlisting_columns(df: Optional[pd.DataFrame]) -> pd.DataFrame:
    if df is None:
        return _default_output_df()
    out = df.copy()
    defaults = {
        "Auto Explained by Transaction Listing": "No",
        "Transaction Listing Case Type": "",
        "Transaction Listing Pathway Matched": "",
        "Transaction Listing Signed NetConsideration": float("nan"),
        "Transaction Listing Signed NetConsideration Pathway 1": float("nan"),
        "Transaction Listing % Previous FDV": float("nan"),
"Transaction Listing Starting Break": float("nan"),
"Transaction Listing Tolerance": float("nan"),
"Transaction Listing Effect % Previous FDV": float("nan"),
"Transaction Listing Break After Exclusion": float("nan"),
"Transaction Listing Within Tolerance After Exclusion": False,
"Transaction Listing Exclusion Test Result": "Not tested",
        "Transaction Listing Previous FDV": float("nan"),
        "Transaction Listing Control Break Eligible Rows": 0,
        "Transaction Listing Control Break Ineligible Rows": 0,
        "Transaction Listing Eligible Asset Prefixes": "",
        "Transaction Listing Ineligible Asset Prefixes": "",
        "Transaction Listing Eligible Scope": "FX/derivatives only; conditional cash only when linked to derivative/FX mechanics",
        "Transaction Listing Candidate Status": "No match",
        "Transaction Listing Diagnostic Note": "",
    }
    for col, default in defaults.items():
        if col not in out.columns:
            out[col] = default
        elif isinstance(default, str):
            out[col] = out[col].fillna(default)
    return out


def resolve_transactionlisting_columns(txn_df: Optional[pd.DataFrame]) -> Dict[str, Optional[str]]:
    if txn_df is None or txn_df.empty:
        return {
            "portfolio_code": None,
            "transaction_type": None,
            "tran_type_code": None,
            "net_consideration": None,
            "asset_category_sub_code": None,
            "asset_class_name": None,
            "asset_subclass_code": None,
            "asset_subclass_name": None,
            "transaction_group_name": None,
            "security_long_name": None,
            "narrative": None,
        }
    return {
        "portfolio_code": find_col(txn_df, ["Portfolio code", "Portfolio", "portfolio", "PortfolioCode"]),
        "transaction_type": find_col(txn_df, ["TransactionType", "Transaction Type", "Txn Type"]),
        "tran_type_code": find_col(txn_df, ["TranTypeCode", "Transaction Type Code", "Tran Type Code"]),
        "net_consideration": find_col(txn_df, ["NetConsideration", "Net Consideration", "Net Consideration Amount"]),
        "asset_category_sub_code": find_col(txn_df, ["AssetCategorySubCode", "Asset Category Sub Code", "Asset category sub-code"]),
        "asset_class_name": find_col(txn_df, ["AssetClassName", "Asset Class Name"]),
        "asset_subclass_code": find_col(txn_df, ["AssetSubClassCode", "Asset SubClass Code", "Asset Sub Class Code"]),
        "asset_subclass_name": find_col(txn_df, ["AssetSubClassName", "Asset SubClass Name", "Asset Sub Class Name"]),
        "transaction_group_name": find_col(txn_df, ["TransactionGroupName", "Transaction Group Name"]),
        "security_long_name": find_col(txn_df, ["SecurityLongName", "Security Long Name", "Security Name"]),
        "narrative": find_col(txn_df, ["Narrative", "Description", "Comment"]),
    }


def _portfolio_prev_fdv_num(portfolio_row: pd.Series) -> float:
    for key in ["FDV Valuation(Previous Day) Num", "FDV Valuation(Previous Day)", "FDV Valuation Prev_Day", "FDV Valuation Prev Day"]:
        value = pd.to_numeric(portfolio_row.get(key, pd.NA), errors="coerce")
        if pd.notna(value):
            return float(value)
    return float("nan")


def _series_from_col(df: pd.DataFrame, col: Optional[str], default: str = "") -> pd.Series:
    if col and col in df.columns:
        return df[col].astype(str).fillna("")
    return pd.Series([default] * len(df), index=df.index, dtype="object")


def _derive_asset_prefix(work: pd.DataFrame, cols: Dict[str, Optional[str]]) -> pd.Series:
    code_col = cols.get("asset_category_sub_code")
    prefix = _series_from_col(work, code_col).str.strip().str.upper().str[:2]
    return prefix.fillna("")


def _conditional_text(work: pd.DataFrame, cols: Dict[str, Optional[str]]) -> pd.Series:
    text_parts = []
    for key in [
        "transaction_type", "tran_type_code", "asset_class_name", "asset_subclass_code",
        "asset_subclass_name", "transaction_group_name", "security_long_name", "narrative",
    ]:
        text_parts.append(_series_from_col(work, cols.get(key)))
    text = text_parts[0]
    for part in text_parts[1:]:
        text = text.str.cat(part, sep=" ", na_rep="")
    return _norm_text(text)


def apply_transaction_control_break_eligibility(txn_df: Optional[pd.DataFrame]) -> pd.DataFrame:
    """Add transaction control-break eligibility columns.

    This function does not decide whether a portfolio is explained; it only says which
    TransactionListing rows are allowed to participate in control-break adjustment.
    """
    if txn_df is None or not isinstance(txn_df, pd.DataFrame) or txn_df.empty:
        return pd.DataFrame()
    out = txn_df.copy()
    cols = resolve_transactionlisting_columns(out)
    out["Transaction Control Break Asset Prefix"] = _derive_asset_prefix(out, cols)
    condition_text = _conditional_text(out, cols)
    prefix = out["Transaction Control Break Asset Prefix"]
    direct = prefix.isin(TRANSACTION_CONTROL_BREAK_ELIGIBLE_PREFIXES)
    conditional = prefix.isin(TRANSACTION_CONTROL_BREAK_CONDITIONAL_PREFIXES) & condition_text.apply(
        lambda text: any(token in str(text) for token in TRANSACTION_CONTROL_BREAK_CONDITIONAL_TOKENS)
    )
    excluded = prefix.isin(TRANSACTION_CONTROL_BREAK_EXCLUDED_PREFIXES)
    out["Transaction Control Break Eligible"] = (direct | conditional) & ~excluded
    out["Transaction Control Break Eligibility Reason"] = "Excluded - ordinary market asset/share-style or non-eligible category"
    out.loc[direct, "Transaction Control Break Eligibility Reason"] = "Eligible - FX/derivative asset prefix"
    out.loc[conditional, "Transaction Control Break Eligibility Reason"] = "Eligible - conditional cash/liquidity linked to derivative/FX mechanics"
    out.loc[prefix.eq(""), "Transaction Control Break Eligibility Reason"] = "Excluded - asset prefix unavailable"
    out["Transaction Control Break Eligible Scope"] = "FX/derivatives only; conditional cash only when linked to derivative/FX mechanics"
    return out



def _first_numeric_from_row(row: pd.Series, candidates: List[str]) -> float:
    for key in candidates:
        value = pd.to_numeric(row.get(key, pd.NA), errors="coerce")
        if pd.notna(value):
            return float(value)
    return float("nan")


def _portfolio_control_break_num(portfolio_row: pd.Series) -> float:
    """Return the portfolio break in percentage-points, matching dashboard tolerance units."""
    return _first_numeric_from_row(portfolio_row, [
        "Calculated over/under",
        "Over/Under Num",
        "Transaction-aware Control Break",
        "Source Calculated over/under",
        "Actual vs Benchmark Num",
        "Actual vs Benchmark",
    ])


def _portfolio_tolerance_num(portfolio_row: pd.Series) -> float:
    """Return tolerance in percentage-points, matching Calculated over/under units."""
    return _first_numeric_from_row(portfolio_row, ["Tolerance Num", "Tolerance"])

def build_transactionlisting_case_summary(txn_df: Optional[pd.DataFrame], hot_portfolio_df: Optional[pd.DataFrame]) -> pd.DataFrame:
    """Build portfolio-level TransactionListing exclusion retest summary.

    v306.5.3 behaviour:
    - Eligible TransactionListing rows are still identified using the v239 FX/derivatives rules.
    - The portfolio is only auto explained by transactions when excluding the signed
      eligible NetConsideration effect brings the remaining break within tolerance.
    - All amounts are retained for audit: starting break, tolerance, transaction
      effect, adjusted break and pass/fail result.
    """
    empty = pd.DataFrame(columns=["Portfolio code"] + TXN_EXPLAIN_OUTPUT_COLUMNS)
    if hot_portfolio_df is None or hot_portfolio_df.empty:
        return empty
    hot = hot_portfolio_df.copy()
    if "Portfolio code" not in hot.columns:
        return empty
    hot["Portfolio code"] = hot["Portfolio code"].astype(str).str.strip()
    hot = hot[hot["Portfolio code"] != ""].copy()
    if hot.empty:
        return empty
    base = hot[["Portfolio code"]].drop_duplicates().copy()
    base["portkey"] = normalise_join_key_series(base["Portfolio code"])
    base = base[base["portkey"].replace("", pd.NA).notna()].copy()
    if txn_df is None or txn_df.empty:
        out = ensure_transactionlisting_columns(base[["Portfolio code"]].copy())
        out["Transaction Listing Candidate Status"] = "No TransactionListing source rows"
        out["Transaction Listing Diagnostic Note"] = "No TransactionListing source rows were available for the hot portfolio population"
        return out

    cols = resolve_transactionlisting_columns(txn_df)
    port_col = cols["portfolio_code"]
    amt_col = cols["net_consideration"]
    if port_col is None or amt_col is None:
        out = ensure_transactionlisting_columns(base[["Portfolio code"]].copy())
        out["Transaction Listing Candidate Status"] = "Missing TransactionListing columns"
        notes = []
        if port_col is None:
            notes.append("Portfolio code column not resolved")
        if amt_col is None:
            notes.append("NetConsideration column not resolved")
        out["Transaction Listing Diagnostic Note"] = "; ".join(notes)
        out["Transaction Listing Case Type"] = "Eligible FX/Derivatives transaction control-break adjustment"
        return out

    work = apply_transaction_control_break_eligibility(txn_df)
    work[port_col] = work[port_col].astype(str).str.strip()
    work["portkey"] = normalise_join_key_series(work[port_col])
    work = work[work["portkey"].replace("", pd.NA).notna()].copy()
    work = work[work["portkey"].isin(base["portkey"])].copy()
    if work.empty:
        out = ensure_transactionlisting_columns(base[["Portfolio code"]].copy())
        out["Transaction Listing Candidate Status"] = "No transaction rows for hot portfolios"
        out["Transaction Listing Case Type"] = "Eligible FX/Derivatives transaction control-break adjustment"
        return out

    work["_net_consideration_num"] = _safe_num(work[amt_col])
    eligible = work[work["Transaction Control Break Eligible"].fillna(False).astype(bool)].copy()
    if eligible.empty:
        out = ensure_transactionlisting_columns(base[["Portfolio code"]].copy())
        ineligible_by_port = work.groupby(port_col, dropna=False).size().to_dict()
        out["Transaction Listing Case Type"] = "Eligible FX/Derivatives transaction control-break adjustment"
        out["Transaction Listing Candidate Status"] = "No eligible FX/derivative transaction rows"
        out["Transaction Listing Control Break Ineligible Rows"] = out["Portfolio code"].map(lambda p: int(ineligible_by_port.get(p, 0)))
        out["Transaction Listing Diagnostic Note"] = "Transaction rows existed, but were excluded by v239 control-break eligibility rules"
        return out

    hot_prev_map = hot.set_index("Portfolio code").to_dict(orient="index")
    rows = []
    for portfolio_code, grp in eligible.groupby(port_col, sort=False):
        portfolio_code = str(portfolio_code).strip()
        if not portfolio_code:
            continue
        total = float(grp["_net_consideration_num"].sum())
        port_ctx = pd.Series(hot_prev_map.get(portfolio_code, {}))
        prev_fdv = _portfolio_prev_fdv_num(port_ctx)
        pct_prev_fdv = float(total / prev_fdv) if pd.notna(prev_fdv) and abs(prev_fdv) > 0 else float("nan")
        txn_effect_pp = float(pct_prev_fdv * 100.0) if pd.notna(pct_prev_fdv) else float("nan")
        starting_break = _portfolio_control_break_num(port_ctx)
        tolerance = _portfolio_tolerance_num(port_ctx)
        adjusted_break = starting_break - txn_effect_pp if pd.notna(starting_break) and pd.notna(txn_effect_pp) else float("nan")
        within_after = bool(pd.notna(adjusted_break) and pd.notna(tolerance) and abs(float(adjusted_break)) <= abs(float(tolerance)))
        if within_after:
            auto_explained = "Candidate"
            candidate_status = "Candidate - within tolerance after transaction exclusion"
            test_result = "Pass - within tolerance after excluding signed eligible NetConsideration"
        elif pd.isna(starting_break) or pd.isna(tolerance):
            auto_explained = "No"
            candidate_status = "Not tested - missing starting break or tolerance"
            test_result = "Not tested - missing starting break or tolerance"
        elif pd.isna(txn_effect_pp):
            auto_explained = "No"
            candidate_status = "Not tested - missing previous FDV or transaction effect"
            test_result = "Not tested - missing previous FDV or transaction effect"
        else:
            auto_explained = "No"
            candidate_status = "Failed - outside tolerance after transaction exclusion"
            test_result = "Fail - outside tolerance after excluding signed eligible NetConsideration"

        all_for_port = work[work[port_col].astype(str).str.strip().eq(portfolio_code)].copy()
        ineligible = all_for_port[~all_for_port["Transaction Control Break Eligible"].fillna(False).astype(bool)]
        eligible_prefixes = ", ".join(sorted({str(x).strip() for x in grp["Transaction Control Break Asset Prefix"].tolist() if str(x).strip()}))
        ineligible_prefixes = ", ".join(sorted({str(x).strip() for x in ineligible["Transaction Control Break Asset Prefix"].tolist() if str(x).strip()}))
        rows.append({
            "Portfolio code": portfolio_code,
            "Auto Explained by Transaction Listing": auto_explained,
            "Transaction Listing Case Type": "Eligible FX/Derivatives transaction control-break adjustment",
            "Transaction Listing Pathway Matched": "FX/derivatives eligibility rule plus tolerance retest",
            "Transaction Listing Signed NetConsideration": total,
            "Transaction Listing Signed NetConsideration Pathway 1": total,
            "Transaction Listing % Previous FDV": pct_prev_fdv,
            "Transaction Listing Starting Break": starting_break,
            "Transaction Listing Tolerance": tolerance,
            "Transaction Listing Effect % Previous FDV": txn_effect_pp,
            "Transaction Listing Break After Exclusion": adjusted_break,
            "Transaction Listing Within Tolerance After Exclusion": bool(within_after),
            "Transaction Listing Exclusion Test Result": test_result,
            "Transaction Listing Previous FDV": prev_fdv,
            "Transaction Listing Control Break Eligible Rows": int(len(grp)),
            "Transaction Listing Control Break Ineligible Rows": int(len(ineligible)),
            "Transaction Listing Eligible Asset Prefixes": eligible_prefixes,
            "Transaction Listing Ineligible Asset Prefixes": ineligible_prefixes,
            "Transaction Listing Eligible Scope": "FX/derivatives only; conditional cash only when linked to derivative/FX mechanics",
            "Transaction Listing Candidate Status": candidate_status,
            "Transaction Listing Diagnostic Note": (
                f"Eligible rows={int(len(grp))}; excluded rows={int(len(ineligible))}; "
                f"starting_break_pp={starting_break}; txn_effect_pp={txn_effect_pp}; "
                f"adjusted_break_pp={adjusted_break}; tolerance_pp={tolerance}; rule=v306.5.3 transaction exclusion retest"
            ),
        })
    summary = pd.DataFrame(rows)
    out = base[["Portfolio code"]].merge(summary, on="Portfolio code", how="left")
    out = ensure_transactionlisting_columns(out)
    out.loc[out["Transaction Listing Candidate Status"].astype(str).str.strip().eq("No match"), "Transaction Listing Candidate Status"] = "No eligible FX/derivative transaction rows"
    return out

def build_transactionlisting_detail_rows(txn_rows: Optional[pd.DataFrame], portfolio_row: pd.Series) -> pd.DataFrame:
    if txn_rows is None or txn_rows.empty:
        return pd.DataFrame()
    cols = resolve_transactionlisting_columns(txn_rows)
    amt_col = cols["net_consideration"]
    work = apply_transaction_control_break_eligibility(txn_rows)
    if amt_col is not None and amt_col in work.columns:
        work["NetConsideration Num"] = _safe_num(work[amt_col])
    preferred = [
        "Transaction Control Break Eligible",
        "Transaction Control Break Eligibility Reason",
        "Transaction Control Break Asset Prefix",
        "Transaction Control Break Eligible Scope",
    ]
    for key in ["transaction_type", "tran_type_code", "asset_category_sub_code", "asset_class_name", "asset_subclass_code", "asset_subclass_name", "net_consideration"]:
        col = cols.get(key)
        if col and col in work.columns:
            preferred.append(col)
    if "NetConsideration Num" in work.columns:
        preferred.append("NetConsideration Num")
    seen = set()
    ordered = []
    for col in preferred + [c for c in work.columns if not str(c).startswith("_")]:
        if col not in seen and col in work.columns:
            ordered.append(col)
            seen.add(col)
    return work[ordered].copy()


__all__ = [
    "TXN_EXPLAIN_OUTPUT_COLUMNS",
    "TRANSACTION_CONTROL_BREAK_ELIGIBLE_PREFIXES",
    "TRANSACTION_CONTROL_BREAK_CONDITIONAL_PREFIXES",
    "TRANSACTION_CONTROL_BREAK_EXCLUDED_PREFIXES",
    "ensure_transactionlisting_columns",
    "resolve_transactionlisting_columns",
    "apply_transaction_control_break_eligibility",
    "build_transactionlisting_case_summary",
    "build_transactionlisting_detail_rows",
]
