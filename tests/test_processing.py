import pandas as pd
from bnp_processor_factory import make_processor
import bnp_helpers_processing as proc


# Simple dummy functions used to configure processing helpers
def _parse_date_from_path(path: str):
    return "2026-08-13"


def _folder_fingerprint(path: str) -> str:
    return "fingerprint-1"


def _load_day_files(folder: str, progress_callback=None, progress_label=None):
    return {}


def _string_series(df, col):
    return df[col].astype(str)


def _safe_series(df, col):
    return df[col]


def _apply_fdv_exclusion(df, threshold, current_fdv_col):
    # Simple implementation: keep rows where CurrentFDVValueNum >= threshold
    if current_fdv_col not in df.columns:
        return df, 0, 0
    mask = pd.to_numeric(df.get(current_fdv_col), errors="coerce").fillna(0) >= threshold
    excluded_count = int((~mask).sum())
    return df[mask].copy(), excluded_count, 0


# Configure the module-level processing helpers for tests
make_processor(
    cache_version="test",
    required_file_keywords=[],
    parse_date_from_path_fn=_parse_date_from_path,
    folder_fingerprint_fn=_folder_fingerprint,
    load_day_files_fn=_load_day_files,
    string_series_fn=_string_series,
    safe_series_fn=_safe_series,
    apply_fdv_exclusion_fn=_apply_fdv_exclusion,
)


def test_resolve_dassetreturn_excess_by_portfolio():
    dar = pd.DataFrame(
        {
            "Portfolio": ["P1", "P1", "P2"],
            "Excess Contribution": [0.1, 0.2, 0.05],
        }
    )

    res = proc._resolve_dassetreturn_excess_by_portfolio(dar)
    # Ensure P1 total is 0.3 and P2 total 0.05
    totals = dict(zip(res["Portfolio"], res["DAssetReturn Excess Contribution Total"]))
    assert abs(totals.get("P1", 0) - 0.3) < 1e-9
    assert abs(totals.get("P2", 0) - 0.05) < 1e-9


def test_resolve_dassetreturn_contribution_by_portfolio():
    dar = pd.DataFrame(
        {
            "Portfolio": ["P1", "P1", "P2"],
            "Asset to Portfolio Contributions": [0.4, 0.6, 1.0],
        }
    )
    res = proc._resolve_dassetreturn_contribution_by_portfolio(dar)
    totals = dict(zip(res["Portfolio"], res["DAssetReturn Asset to Portfolio Contribution Total"]))
    assert abs(totals.get("P1", 0) - 1.0) < 1e-9
    assert abs(totals.get("P2", 0) - 1.0) < 1e-9


def test_prepare_portkey_frame():
    df = pd.DataFrame({"code": [" A ", "B", ""]})
    res = proc._prepare_portkey_frame(df, "code", output_name="Portfolio")
    # should strip whitespace and drop blank
    assert "Portfolio" in res.columns
    assert res["Portfolio"].tolist() == ["A", "B"]
    assert "portkey" in res.columns
