"""Small helper utilities for the processing refactor.

Contains two light-weight helpers intended for later integration into the
Processor refactor:

- DiagnosticsCollector: typed collector for diagnostics and exceptions with
  DataFrame export helpers.
- ProgressReporter: thin adapter that accepts the Streamlit progress/status
  objects and exposes an abstracted update(percent, status, summary, level)
  method. A simple console fallback is provided for headless test runs.

These helpers are intentionally independent and non-invasive so the refactor
can adopt them incrementally with minimal merge friction.
"""
from typing import List, Dict, Any, Optional
import pandas as pd


class DiagnosticsCollector:
    """Collect diagnostics and exceptions for a single processing run.

    Usage:
      collector = DiagnosticsCollector(run_date, source_folder, fingerprint, cache_version)
      collector.add_diag(metric, value, status="INFO", detail="")
      collector.add_exc(category, message, severity="Warning")
      diag_df, exc_df = collector.to_dataframes()
    """

    def __init__(
        self,
        run_date: Any,
        source_folder: str,
        fingerprint: str,
        cache_version: str,
    ) -> None:
        self.run_date = run_date
        self.source_folder = source_folder
        self.fingerprint = fingerprint
        self.cache_version = cache_version
        self._diags: List[Dict[str, Any]] = []
        self._exceptions: List[Dict[str, Any]] = []

    def add_diag(self, metric: Any, value: Any, status: str = "INFO", detail: str = "") -> None:
        self._diags.append({
            "RunDate": self.run_date,
            "SourceFolder": self.source_folder,
            "FolderFingerprint": self.fingerprint,
            "Metric": "" if pd.isna(metric) else str(metric),
            "Value": "" if pd.isna(value) else str(value),
            "Status": "" if pd.isna(status) else str(status),
            "Detail": "" if pd.isna(detail) else str(detail),
            "CacheVersion": self.cache_version,
        })

    def add_exc(self, category: str, message: str, severity: str = "Warning") -> None:
        self._exceptions.append({
            "RunDate": self.run_date,
            "SourceFolder": self.source_folder,
            "FolderFingerprint": self.fingerprint,
            "Category": category,
            "Severity": severity,
            "Message": message,
            "CacheVersion": self.cache_version,
        })

    def to_dataframes(self) -> (pd.DataFrame, pd.DataFrame):
        return pd.DataFrame(self._diags), pd.DataFrame(self._exceptions)


class ProgressReporter:
    """Abstract progress updater used by Processor.

    The implementation accepts optional Streamlit objects (progress_bar, status_text,
    summary_text). If those are None, a minimal console-based reporter is used which
    only records the last status.
    """

    def __init__(
        self,
        progress_bar: Optional[Any] = None,
        status_text: Optional[Any] = None,
        summary_text: Optional[Any] = None,
    ) -> None:
        self.progress_bar = progress_bar
        self.status_text = status_text
        self.summary_text = summary_text
        self.last = {"percent": 0, "status": "", "summary": ""}

    def update(self, percent: int, status: Optional[str] = None, summary: Optional[str] = None, level: str = "info") -> None:
        bounded = max(0, min(100, int(percent)))
        self.last["percent"] = bounded
        if self.progress_bar is not None:
            try:
                self.progress_bar.progress(bounded)
            except Exception:
                pass
        if self.status_text is not None and status is not None:
            try:
                if level == "success":
                    self.status_text.success(status)
                elif level == "warning":
                    self.status_text.warning(status)
                elif level == "error":
                    self.status_text.error(status)
                else:
                    self.status_text.info(status)
            except Exception:
                pass
        if self.summary_text is not None and summary is not None:
            try:
                self.summary_text.caption(summary)
            except Exception:
                pass
        if self.progress_bar is None and self.status_text is None:
            # headless: keep last status only
            if status is not None:
                self.last["status"] = status
            if summary is not None:
                self.last["summary"] = summary
