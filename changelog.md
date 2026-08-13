# BNP Control App - Changelog

Version history for `bnp_control_app.py` and its `bnp_helpers_*.py` modules, 
extracted from the in-code version-history comments (module docstring plus inline 
`## vX.Y.Z:` notes) so the main application file can be trimmed of narrative comment 
blocks without losing the audit trail. Newest first.

> **Source note:** v279 through v306.13.21a, and v307-v314 (the ARC-replacement stage 
notes, interleaved with the v340+ performance work in the source), are transcribed 
directly from the `bnp_control_app.py` module docstring. Entries from v315 onward are 
condensed from inline version comments elsewhere in the same file and the relevant 
`bnp_helpers_*.py` modules. Nothing below is invented - every entry traces to an actual 
comment in the reviewed source files.

---

### v369 - HOTFIX (production break, user-reported)
**Two genuine bugs were introduced by the v368 cleanup and had to be reverted/fixed. This entry documents both, with full root-cause detail, since v368's "confirmed via full-codebase search" claims were WRONG for these two cases.**

**Bug 1 (reported by user, `NameError: name 'load_day_files' is not defined`):** the v368 removal of this file's bare `load_day_files()` wrapper missed that `process_day()` passed it as a bare function reference - `configure_processing(..., load_day_files_fn=load_day_files, ...)` - not a direct call. My v368 search only checked for call-syntax (`load_day_files(`), which does not match a name used as a kwarg value with no parentheses. **Fix**: pointed `load_day_files_fn` directly at `ingestion_v162.load_day_files` (the live, correct ingestion pipeline this app already uses elsewhere) instead of restoring the deleted thin wrapper.

**Bug 2 (found during post-incident audit, not yet reported by user but would have broken `load_day_files_v183_aggregated_cached`, the v184 fallback path):** `_bnp_source_file_aggregated_v183` - the real per-keyword file-aggregation helper - was accidentally deleted during the EARLIER v365 cleanup (mis-scoped as part of a dead-instrumentation-block removal). It was never dead; `load_day_files_v183_aggregated_cached` calls it directly and unconditionally. **Fix**: restored the function verbatim from the pre-cleanup source.

**Root-cause of both misses**: my searches for "confirmed zero callers" relied on regex patterns like `functionname\(` (call syntax) and simple `grep -c` counts, which do not reliably distinguish "no callers" from "referenced as a bare value/reference, or accidentally caught in a larger block deletion." Post-incident, I re-verified using a proper AST-based diff: every function defined in the ORIGINAL (pre-cleanup) file was compared against every function still defined in the current file, and every removed name was checked for ANY remaining `ast.Name` Load-context reference (covering calls, bare-value assignment, kwarg values, and dict/list values alike) - not just regex call patterns. This caught both bugs definitively and confirmed no further instances of this failure mode exist in the current file. One additional flagged reference, `_dar_low_timing_add` (from the v365 diagnostic-block removal), was verified SAFE: both remaining call sites are wrapped in `if callable(globals().get("_dar_low_timing_add")):` guards, so the missing function safely no-ops rather than raising. The five classification-function aliases from v364 (`_apply_non_arc_bpimpact_classification_v306_13_17/_18/_19`, `_apply_bpimpact_hotcold_force_v306_13_21`, `_apply_basis_impact_error_risk_classification_v306_14_0`) were also verified SAFE - all five are intentionally re-created via module-level assignment to the working v306.14.5 classifier, exactly as designed and documented in v364.

**Verification performed**: full AST-based diff (every original top-level function vs current top-level functions, cross-checked against every remaining Name-node reference in the file) run twice - once to find the bugs, once after fixing to confirm zero remaining dangling references. `py_compile` and `ast.parse` both pass. **Net line change**: 16,304 -> 16,458 lines (+154, from restoring the deleted `_bnp_source_file_aggregated_v183` function).

### v368
Multi-part cleanup at user request: (1) **Removed ARC as an input source entirely.** ARC is no longer used anywhere in the pipeline - confirmed the three former `arc_v162` pass-through wrappers in `bnp_control_app.py` (`_inspect_arc_workbook`, `_load_excel_sheet_normalised`, `_find_arc_workbook_for_date`) had ZERO callers anywhere in the app or any helper module, and the live error-risk classifier already sources exclusively from BP Impact Tool.xlsb via `bnp_helpers_error_risk.py` (confirmed in v367). Removed the `import bnp_helpers_arc as arc_v162` line and all three wrapper functions from `bnp_control_app.py`; **deleted `bnp_helpers_arc.py` entirely** (535 lines) - the file is no longer part of the codebase. (2) **Removed the Parity Matrix audit-index feature** at user request: removed the `from bnp_helpers_parity import render_parity_tab` import, its dispatch-dict entry, its `_render_pn_arc_panel` call branch, its display-label map entry, its "Within tolerance" status-map entry, and its listing in the Control checks tab's 13-section list (now 12) from `bnp_control_app.py`; removed the `_parity_frame()` helper and the Parity Matrix sheet write from `bnp_helpers_reconciliation_export.py`'s single-day export workbook (the exported workbook no longer includes a Parity Matrix tab); **deleted `bnp_helpers_parity.py` entirely** (129 lines) - the file is no longer part of the codebase. (3) **Removed a confirmed-dead CSV/HEADER ingestion subtree** (~223 lines) from `bnp_control_app.py`: a 12-function cluster (`_try_read_text`, `_sniff_delimiter`, `_robust_csv_to_df`, `_cell_clean`, `_row_profile`, `_detect_header_rows`, `_find_header_row_by_tokens`, `normalize_header`, `_describe_header_contract`, `_header_contract_met`, `_select_header_rows_for_keyword`, `_should_exclude_report_file`) plus this file's own bare `load_csv_keyword` and `load_day_files` wrappers, plus two entry points (`load_day_files_cached`, `load_day_files_detailed_cached`) - traced end-to-end and confirmed every one of these had ZERO live callers (the cluster only called itself, and both entry points into it were themselves uncalled). This was an orphaned generation predating the v181-v184 loader family cleaned up in v365; the live ingestion pipeline (`bnp_helpers_ingestion.py`, imported as `ingestion_v162`) was already being called correctly and separately via its qualified `ingestion_v162.X` names elsewhere in the file (e.g. inside `_bnp_source_file_diagnostics_v182`) - those call sites are untouched. **File count**: 22 -> 20 `.py` files (target of <=20 met). **Net result this pass**: `bnp_control_app.py` 16,563 -> 16,304 lines (~259 lines removed across all three changes); combined running total from the pre-cleanup baseline: 19,369 -> 16,304 lines (~3,065 lines, ~15.8%). Verified via `py_compile`/`ast.parse` after every edit, plus full-codebase grep confirming zero dangling references to any removed name.

### v367
Full sweep of every wrap chain in the file (35 distinct `_..._wrapped` flags across ~11 wrapped function names), specifically checking each for the same "shadowed by a later plain redefinition" dead-code pattern found in v364/v365/v366. **Confirmed and removed one more fully-dead chain**: `_prepare_arc_error_risk` had THREE unconditional top-level `def` statements (the original ARC-workbook-based version, a v306.13.15 "No-ARC-workbook replacement", and the final v306.13.16 "Non-ARC replacement") plus a v306.13.9 "BP Impact Tool Error Risk Source Wrapper" wrap sandwiched between the first two. Since Python only keeps the last top-level binding of a name, and none of these three `def`s nor the wrap were inside any conditional guard, only the LAST definition (v306.13.16) was ever actually bound and called - the original def, the v306.13.9 wrap, and the v306.13.15 def (plus its three private helpers `_empty_removed_arc_mapping_df_v306_13_15`/`_empty_removed_arc_portfolio_df_v306_13_15`/`_removed_arc_sheet_meta_v306_13_15`, confirmed used nowhere else) never executed. Removed all of it (~165 lines); `arc_v162` (the module) and its other thin wrappers (`_inspect_arc_workbook`, `_load_excel_sheet_normalised`, `_find_arc_workbook_for_date`) are unrelated and were left untouched, since they're still used by `bnp_helpers_reconciliation_export.py`'s backfill ledger. **Everything else checked was confirmed LIVE, genuine, correctly-chained functional logic - not dead code**: the `_bnp_source_file_aggregated_v184` wraps (v306.13.7.3/7.4 slim projection, v306.13.7.5 selected-column parser), all 17 wraps of `_prepare_out_dashboard_bundle` (verified each calls through to its captured predecessor, whether named `_original` or `_pre_<patch>`), the `_hot_resolution_sets` na17/18/19 aliases (harmless since those names now point at the final classifier), the toggle-gated `_TREND_HISTORY_FAST_SOURCE_PROFILE_ACTIVE` wraps of `load_day_files_v184_readcsv_cached`/`_load_bnp_source_persistent_cached` (real Trend History fast-profile business logic, not diagnostics), the `_tier1_count_frame_from_assignments`/`_render_executive_flow_bar` er142 fallback wraps, the `_render_portfolio_fx_validation_tab`/`_prepare_out_dashboard_bundle` afx148 Auto-FX-rebuild wrap, and the single-shot `folder_fingerprint` memoisation wrap. **Net result this pass**: 16,728 -> 16,563 lines (-165); combined running total from the pre-cleanup baseline: 19,369 -> 16,563 lines (~2,806 lines, ~14.5%). Verified via `py_compile`/`ast.parse`, plus an automated AST check confirming every remaining nested wrap of `_prepare_out_dashboard_bundle`/`_hot_resolution_sets` genuinely calls its captured predecessor.

### v366
Untangled and removed the "COMMON VALIDATION CANDIDATE RUNTIME DIAGNOSTICS v306.13.6.7" block (~150 lines), the item flagged for careful chain-of-custody tracing in v365. Traced all three of its wraps individually: (1) its wrap of `_trend_common_candidate_snapshot_df` was confirmed DEAD - a later plain `def` redefinition of that name further down the file (kept, unchanged) completely overwrites this closure, so it never ran; this also made the standalone `_common_candidate_runtime_preflight()` helper dead, since it was only called from inside that unreachable wrapper. (2) Its wrap of `_write_trend_cache` WAS live (no later redefinition shadowed it) but only added two diagnostic log entries around the real cache write - pure instrumentation overhead with no behavioural effect; removed, restoring `_write_trend_cache` to its single real definition. (3) Its wrap of `_build_or_refresh_executive_trend_history` WAS live and a genuine link in the real decorator chain (`dar75 -> dar73 -> trend_perf -> THIS -> trend_timing -> core`, each wrap capturing a reference to the previous version rather than clobbering the name) - it only reset/logged diagnostic rows and stored `common_candidate_runtime_diagnostics_df`/`..._summary_df` on the result dict, confirmed via full-file search that neither key is ever read elsewhere and their CSV writes were already stubbed to no-ops. Removing this link is transparent: the next wrap up (`trend_perf_profile`) now simply captures the `trend_timing`-wrapped version instead, exactly as if this link had never existed. All 5 helper functions in the block (`_common_candidate_runtime_diag_reset/_add/_df/_summary/_write_files` plus `_common_candidate_runtime_preflight`) were confirmed called only from within this self-contained block before removal. **Net result**: 16,872 -> 16,728 lines (-144); combined running total from the pre-cleanup baseline: 19,369 -> 16,728 lines (~2,641 lines, ~13.6%). Verified via `py_compile`/`ast.parse`, plus confirmed `_write_trend_cache` now has exactly one definition and the `_build_or_refresh_executive_trend_history` decorator chain is intact end-to-end.

### v365
Phase 2 dead-code removal (Option 2, items 1-3). **Item 1 - legacy BNP file loaders**: removed `load_day_files_v181_detailed_cached` and `load_day_files_v182_fast_detailed_cached` (~300 lines) - confirmed via full-file search that neither was ever called; `process_day` only calls `load_day_files_v184_readcsv_cached` (primary) with `load_day_files_v183_aggregated_cached` as its fallback (both kept, unchanged). **Item 2 - inert instrumentation blocks**: removed 4 diagnostic-only patches whose own header comments say "diagnostic-only" and whose output dataframes (`dar_trend_dependency_trace_df`, `dar_parse_low_level_timing_df`, `dar_retained_column_usage_trace_df`, `dar_profile_ab_comparison_df`, `fx_workbook_discovery_diagnostics_df`) were confirmed write-only (stored on the result/bundle dict but never read anywhere else) and had their CSV writes already stubbed to no-ops in an earlier cleanup - `DAssetReturn TREND DEPENDENCY + LOW-LEVEL TIMING TRACE v306.13.7.2`, `DAssetReturn SELECTED PARSER TIMING LABEL + COLUMN USAGE TRACE PATCH v306.13.7.5.1`, `TREND PERFORMANCE PROFILE + FX EXTERNALS DIAGNOSTICS PATCH v306.13.7.6`, and `v306.13.7.6b COMPLETE PATCH`. Each of these wrapped `_dar75_selected_column_parser`, `_prepare_exchange_rate_source`, `_bnp_source_file_aggregated_v184`, `build_unexplained_minimum_validation_sets`, `build_unexplained_common_validation_candidates` and/or `_build_or_refresh_executive_trend_history` purely to add timing/trace overhead; removing the wrapper blocks restores each function to its real, unwrapped definition with zero behaviour change (functional patches v306.13.7.3/7.4 "slim projection + header probe" and v306.13.7.5 "parser-level selected-column reader", which are NOT diagnostic-only, were deliberately left untouched). **Item 3 - duplicate-name function re-definitions**: removed the first (dead, superseded) definition of `_trend_common_candidate_snapshot_df` and the first two of three (dead, superseded) definitions of `_render_common_candidate_trend_chart` - Python keeps only the last top-level `def` of a given name, so the earlier bodies never executed; only the final definition of each (kept, unchanged) is actually bound at render time. **Note/flagged for a future pass, not touched this round**: a "common candidate diagnostic" wrapper block (~former line 10125) reassigns `_trend_common_candidate_snapshot_df`, `_write_trend_cache` and `_build_or_refresh_executive_trend_history` together; it is itself overwritten by the later plain redefinition of `_trend_common_candidate_snapshot_df` kept in this pass, but its interaction with `_write_trend_cache`/`_build_or_refresh_executive_trend_history` needs more careful chain-of-custody tracing before removal, given multiple other wraps of `_build_or_refresh_executive_trend_history` elsewhere in the file - left in place out of caution. **Net result this pass**: 18,212 -> 16,872 lines (~1,340 removed); combined with the v364 Phase 1 removal, total reduction from the pre-cleanup baseline is 19,369 -> 16,872 lines (~2,497 lines, ~13%). Verified via `py_compile` and `ast.parse` after every individual block removal.

### v364
Phase 1 dead-code removal (Option 2): removed 5 confirmed-dead classification function bodies plus their single-use private helpers - `_apply_non_arc_bpimpact_classification_v306_13_17/_18/_19`, `_apply_bpimpact_hotcold_force_v306_13_21`, and `_apply_basis_impact_error_risk_classification_v306_14_0`. Each of these had its name reassigned to `_apply_basis_impact_error_risk_classification_v306_14_5` by the module-level alias-recreation block before any caller could invoke it, so the bodies never executed (~1,160 lines removed, 19,369 -> 18,212). All "# Wrap ..." self-registration blocks and the alias-recreation block itself were left untouched (they still work correctly via Python's late-bound global name resolution) - zero behaviour change, verified via `py_compile`/`ast.parse` before and after. Also simplified a redundant triple call (`_19` -> `_18` -> `_17` in sequence, all resolving to the same function) in `_render_overview_tab` down to a single direct call to `_apply_basis_impact_error_risk_classification_v306_14_5`.

### v363
Static data consolidation: local_price_validation_template now defaults to a same-app-folder filename (was a personal C:\Users\cxp029\... path) - clears the v362 'not portable' flag automatically. bnp_helpers_price_integrity.py's Material Movement population now reads its GLGroupName/PortfolioCode include-exclude lists from Static Data mapping_filters -> 'Valuation T' (the same rows the UUT look-through already uses) instead of a separate hard-coded copy, with the old constants kept only as a fallback. Removed a dead, never-called duplicate month-alias builder (_build_month_aliases) from bnp_helpers_static_data.py. Extracted the historical version-history comment blocks out of the module docstring into this CHANGELOG.md.

### v362
Input Sources tab added (renamed from the former 'Data Sources' sub-section, moved before Portfolio Numbers, with a single 'Download all' button); Control checks tab added (13 ARC/GAV-style panels); flags any local machine-specific ('C:\Users\...') Static Data path as 'not portable'.

### v361
Liquidity rebuilt to the full GAV-style template with its own four-bucket population (=100% / >=80%<100% / rest / excluded); fixed the Advisor Return Check 100x display bug on fields already stored in percent units.

### v360
$/% number formatting standardised on-screen and in downloads; added paired 'In <control> population'/'<control> scope' columns, 'Human in the Loop comment'/'Username' annotation columns, and a standardised 'Check' status column across all GAV-style controls.

### v359
GAV-style population/Check/Ok/Excluded template (single-tab full pack + invariant) applied to every remaining control: UUT Material Price MVT, Stale Price Check, Advisor Return Check, Advisor-UUT Check, Investment/Cash Clearing, Negative NAV, Portfolios reconciliation.

### v358.4
UUT Material Price MVT population rebased from the AssetSubClassName UUT-scope rule to DetailedValuationFDV GLGroupName scope (AUD Unlisted Trusts/Equity, Unlisted Intl Equities/Trust), excluding M2STT2/M2STT4.

### v358.3
Added a shared build_price_integrity population-rebuild helper (price_integrity_frames) shared by the Stale Price and Material Movement panels.

### v358.1
GAV-style class enrichment (enrich_portfolio_class_from_mapping) applied ahead of the GAV build so Class is available for the workbook-scoped OUT gate.

### v357.1
Re-applied the v354 basis-impact classification memoisation, which had been lost across a v352.1->v355->v356->v357 rebuild, so the classifier does not needlessly recompute on every Streamlit rerun.

### v357
Control-break source-integrity check rebased from summed DAssetReturn Excess Contribution (noisy, 30 mismatches, median gap 0.38pp) to DDetailedReturn Actual Return vs summed Asset-to-Portfolio Contributions (tighter, 17-portfolio list, median gap 0.0000) at the same 1bp tolerance.

### v356
Control-break mismatch warning replaced with a ranked, read-only table; fixed a Static Data validator false-alarm ('Error' status) caused by code-owned sheets (source_file_keywords etc.) still being demanded as required; added an FX workbook path cache.

### v355
Prototype: native-Streamlit-widget executive summary card as an A/B alternative to the custom-HTML component (sidebar toggle, default off) - a UX trade-off vs the blue-gradient HTML card.

### v352.1
Crash fix: guarded a dormant legacy ARC-schema consumer that KeyError'd ('External portfolio reference norm') once the v352 BP Impact fix started populating arc_portfolio_df.

### v352
Folder-scan three-tier caching (persisted manifest / incremental month-folder probe / full-scan fallback) cutting the morning date-folder scan from ~14s to ms; executive-render HTML transport change; BP Impact Advisor-key fix.

### v351
FDV pickle-persist replacing the v350 Parquet + copy-local experiment (run-logs showed copy-local made things worse); removed the calamine fast-Excel-engine toggle (no measurable gain, dtype risk).

### v350
FDV Parquet-persist + copy-local network read experiment to attack the ~23s first FDV read (later superseded by v351's pickle approach, which also drops the on-disk Parquet on a forced refresh).

### v349
Instrumented the uninstrumented cold-load handoff gap, surfacing the BNP cache miss reason and whether the cache file existed at entry.

### v346.1
Fixed the calamine-engine sidebar toggle disappearing when an unrelated setup step threw; made each setup step independently guarded.

### v346
Shared cached Excel reader (in-process + persisted) for the FX workbook and Error Risk Report, so each file version is parsed from the network at most once.

### v345
Shared cached Excel/FDV reader: every physical FDV file is read from the network at most once per process and reused by UUT, price integrity and enrichment. On a forced source refresh, the shared FDV per-file cache is dropped.

### v344
Deep timing dive: instrumented every warm-up check individually; memoised the non-ARC BP-Impact classification passes per date instead of per click; added Advisor-UUT internal step-timing hooks.

### v343
FDV loader rewritten to the same vectorised, named-column, quote-aware path used by the other BNP reports; the BM lookup is now a vectorised DataFrame indexed by the normalised join key.

### v342
Diagnostics cleanup: collapsed three near-identical source-load diagnostic renderers into one flat panel; added the deep per-step timing run-log with CSV export ('Option B').

### v341
Fenced every dashboard section/tab render so one section's exception surfaces as st.error() instead of silently killing the whole page; guarded the On UNISON sub-section dispatch specifically.

### v340
Removed the dev-only executive-trend-snapshot debug dump that could crash the section radio when Show Debug was on.

### v336
Scoped the Portfolio Numbers sub-sections to the SAME portfolio group (On UNISON/Off UNISON/IISL) as the rest of the dashboard.

### v335
ARC check panels no longer fail silently - a throw in one panel surfaces as a visible warning instead of a blank section.

### v334
One shared placeholder created BEFORE the executive-group render to prevent duplicate widget keys.

### v333
Executive group radio now renders via one shared placeholder, avoiding a double-render flash.

### v332
Input Sources panel lists every configured path from Static Data 'paths' sheet.

### v331
Deterministic first-load landing on Portfolio Numbers -> Reconciliation export, primed once per session before any widget with those keys is created.

### v330
Ensures the base advisor_uut_df exists (built silently) before the corrected panel is rendered.

### v329
Folded a source-file signature into the bundle cache key (previously the cache could serve a stale bundle when only file contents, not the date, changed).

### v328
Eager warm-up: every Portfolio Numbers check is fired at load finish so the on-load Reconciliation export is complete without the user clicking through each panel.

### v327
Guarantees Unison NAV is computed at bundle-prepare time so the workbook NAV=0 gate always fires, regardless of which section a user opens first; single collapsed pipeline replacing 7 render-side monkey-patches.

### v326
Wired in excluded_from_bnp_reports population exclusions (M2STT2/M2STT4/M7MLCH) and added the workbook-scoped OUT column (Advisor Return Check class exclusions + NAV=0 gate) as an additive, reason-coded column.

### v325
Warm-up: populate every check's bundle dataframes ONCE after the source files load, ahead of any panel being opened.

### v324
Added the IISL Central Mapping List (Mandates, Status=Active) as a third portfolio group (On UNISON / Off UNISON / IISL).

### v323
The ARC check panels are now rendered as sub-sections of Portfolio Numbers; benchmark names (BM Mapping) moved from the ARC workbook to Static Data 'bm_mapping'.

### v321
Sleeve income sourced from DAssetReturn per underlying holding (MV-weighted), matching the workbook's Advisor-UUT Return Check Income column; dropped the 'ARC Asset Type of portfolio' column from Unexplained.

### v320
One consolidated Advisor-UUT section (asset-type split removed); Income wired into the Advisor-UUT variance from DDetailedReturn 'Income return %'.

### v319
Removed the acc_balance_path override - GAV resolves Acc Balance from the Tableau date folder only. Universe now loads only Unison Active Advisors + Off-Unison Active Advisors.

### v318
Moved the sidebar 'Asset-type code map' editor into Static Data 'asset_type_code_map'; sidebar editor removed.

### v317
Config-only: default_exclude_amount, fx_line_match_tolerance_dollar and current_account_dominance_threshold_pct now sourced from Static Data 'thresholds'; the equivalent sidebar widgets were removed.

### v316
Manual, ad-hoc multi-day backfill reconciliation: per-day app-vs-ARC ledger with a colour-coded coverage heatmap written to an exported workbook.

### v315
Added the ARC-named 'Download everything' reconciliation workbook - one .xlsx whose tabs are named exactly like the ARC workbook sheets they reconcile to; added display labels pairing each app sub-section with its ARC sheet name (keys unchanged).

### v314
Outputs: in-app Control Summary + SF/Trust Status Dashboards replacing the workbook 'Create Outputs'. Housekeeping: removed dead diagnostic-timing code, deduped exchange_rates (141 dead lines).

### v313.1
Material Price Movement now flags ONLY UUT securities (3,308 -> 5 on the validation date), removing equity noise.

### v313
ARC replacement Stage 6 - Price integrity: Stale Price (BNP DStalePrice report) and Material Price Movement (two-day FDV price return, >1% / <-0.5%, holdings >=1% weight). Validated on 31/30 Jul: 380 stale flags of 1,750; 440 material movements (from 3,308 unscoped).

### v312
ARC replacement Stage 5 - Ancillary checks: Investment & Cash Clearing (Acc Balance 4999/0055), Negative NAV (acct 9018 excl. Currency Overlay), Liquidity % (Current Account FDV / NAV). Validated on 30 Jul: Investment 181 / Cash 8 Check; 20 negative NAV -> 17 overlay excluded -> 3 genuine flags.

### v311b
Fixed the UUT T-1 resolver to load the PREVIOUS-DAY DetailedValuationFDV from its own date folder (fixes blank t1_date / zero weighted UUT return).

### v311.2
Full UUT scope: runtime UUT/PE security identifier from FDV AssetSubClassName, coverage-safe against partial fileset loads.

### v311.1
Advisor-UUT correctness fixes: Unison Return scaled to decimal (fixing a ~100x variance error), population restricted to true UUT/PE (excluding Cash/Overlay/Treasury), Tax Effect applied, Income staged.

### v311
ARC replacement Stage 4 - UUT look-through: Advisor-UUT Check computes the weighted underlying return of UUT/PE holdings from two DetailedValuationFDV day files, reconciled against Unison return (Variance, Breach at tolerance). Validated to 7dp against the workbook Book2 anchor (13/13 portfolios).

### v310.1
Hot/Cold realignment: error-risk severity now uses the SAME Unison-vs-benchmark deviation as the v310 OUT (replacing the BNP-internal deviation). Validated on 31 Jul: correct on the app decimal scale and scale-invariant.

### v310
ARC replacement Stage 3 - Advisor Return Check core: Unison Return from Tableau SF/Trust price; PRIMARY OUT changed to |Unison Return - Benchmark| >= Tolerance, replicating workbook cols Q/W/AB/AC/AD. Prior BNP-internal OUT retained as a reconciliation column with an OUT reclassification audit; Unison-vs-BNP return reconciliation added (>return_recon_tolerance_pct). THIS VERSION CHANGES THE OUT BASIS.

### v309
ARC replacement Stage 2 - GAV Check: Unison NAV (Acc Balance 9018) - Deferred Tax (2500) - BNP GAV (DAssetReturn FDV Valuation Curr_Day); flags |% impact| > gav_pct_impact_tolerance_pct (Static Data). Treasury class zeroes NAV/GAV per the workbook.

### v308
ARC replacement Stage 1 - Universe & identity: master portfolio universe from the Central Mapping List (Unison Active Advisors + Off-Unison + Pools/Micky; Terminated Advisors retained), reconciled against today's BNP data - adds 'missing from BNP today' and 'unmapped in BNP' controls. Read-only under Portfolio Numbers / Diagnostic support.

### v307
ARC replacement Stage 0 - Foundations & slim config: added the ARC Parity Matrix audit index and the Hot/Cold invariant (No source + Cold + Hot == OUT) to the v306.14.5 classifier; moved structural contracts (source keywords, excluded tokens, header contracts) out of Static Data.xlsx into code to slim it to a single config surface. No calculation results changed.

### v306.13.21a
Fixed a pandas iterable-length mismatch in the BP Impact match-key assignment mask.

### v306.13.21
Forced BP Impact Hot/Cold from diagnosed Advisor matches where prior patches populated the match key/ratio but left Hot/Cold stale.

### v306.13.20
Added BP Impact match diagnostics: source dataframe, portfolio keys, Advisor/name-token matches, CSV exports.

### v306.13.19
Added a BP Impact Advisor fallback from Portfolio Name's first token where External portfolio reference is absent.

### v306.13.18
Fixed the BP Impact match by joining External portfolio reference to Advisor instead of Portfolio code.

### v306.13.17
Applied non-ARC BP Impact classification directly to portfolio_df so Portfolio Numbers updates even with the ARC workbook removed.

### v306.13.16
Replaced ARC portfolio coverage with the BP Impact Tool Error Risk Report so OUT portfolios no longer collapse to 'No ARC' after ARC workbook removal.

### v306.13.15
Removed ARC workbook Mapping and Unison-vs-BNP-return-check usage; retained the BP Impact Tool Error Risk source.

### v306.13.14
Fixed the nested ARC Error Risk diagnostic status so source-load checks align with the ARC mapping preview.

### v306.13.13
Fixed a STATIC_DATA_BUNDLE NameError by adding a resilient Static Data bootstrap and safe source-wrapper references.

### v306.13.12
Fixed the Portfolio Numbers source-load diagnostics hook with a late-binding wrapper before the app entrypoint.

### v306.13.11
Moved source-load diagnostics into Portfolio Numbers / Diagnostic support, including Tableau CSV and BP Impact Tool Error Risk load status.

### v306.13.9
Error-risk source changed from the ARC workbook to BP Impact Tool.xlsb / Error Risk Report.

### v306.13.8
Static Data workbook now drives paths, source-report contracts and thresholds; Tableau/Unison BO CSVs loaded into the dashboard bundle.

### v306.13.1
Fixed Trend chart stack order/colours (Within=green, Cold=amber, Hot=red); reorganised Unexplained review into a sub-section selector.

### v306.13.0
Trend Portfolio Numbers now splits Outside tolerance into Hot/Cold with red/amber/green colours; Unexplained review reorganised into Summary/Common candidates/Near-zero/Other; removed Portfolio validation plan; added Excel prompt-template injection.

### v306.12.6
Trend History charts now show only Within/Outside tolerance in Portfolio Numbers, centre labels inside each stacked segment, and place Unexplained at the top of the Hot waterfall chart.

### v306.12.5
Replaced deprecated use_container_width with width='stretch'/'content'.

### v306.12.4
Removed Total portfolios from the Trend Portfolio Numbers chart; added stacked-column data labels; removed the % metrics chart.

### v306.12.3
Changed all Trend History charts to stacked column charts with dd/mm/yy x-axis date labels.

### v306.12.2
Fixed the Trend History date_input warning fully by not priming session_state before creating the date widget.

### v306.12.1
Fixed a Streamlit session-state/widget default warning using date-scoped dashboard radio keys (Trend History date_input).

### v306.12.0
Added Trend History Excel export: summary, driver movement, pivot, parameters, diagnostics, exceptions and a build/write log.

### v306.11.0
Added the Trend History UI: date-range build/refresh controls, cache status tables and executive trend charts.

### v306.10.0
Added persisted executive trend cache/index helpers for date-range snapshot reuse and stale-date rebuild detection.

### v306.9.0
Added the executive trend snapshot foundation: dashboard-aligned summary and long-form driver-movement dataframes for the selected date.

### v306.8.11
Added an Unexplained download button generating a Word document of date-aware security-level Copilot Researcher prompts.

### v306.8.10
Fixed a Streamlit session-state/widget default warning using date-scoped dashboard radio keys.

### v306.8.9
Aligned Hot driver ordering to the dashboard driver-movement order; removed the parent Auto Explained how-to; reset dashboard state to Unexplained on load/date change.

### v306.8.8
Removed summary expanders from Nil actual return / Current Account dominated; Outside tolerance now shows the full list directly.

### v306.8.7
Renamed Portfolio Count to Portfolio Numbers; aligned sub-section labels; added Within-tolerance detail; added Hot/Cold tooltip definitions.

### v306.8.6
Renamed the automated explanation area to 'Auto Explained'; moved FX / Nil actual return / Current Account dominated into focused sub-sections.

### v306.8.5
Dashboard layout tidy-up: moved OUT review under Portfolio Count sub-tabs; removed several redundant summary rows.

### v306.8.4
Restored the Nil actual return waterfall tuple assignment after a render-fix cleanup regression.

### v306.8.3
Fixed a misplaced Current Account ZL01 source-row expander that had leaked into Nil actual return.

### v306.8.2
Fixed the Current Account numerator by resolving FDV Valuation Curr_Day aliases before the generic current-FDV aliases.

### v306.8.0
Current Account dominated classification changed to DAssetReturn ZL01 current FDV / DDetailedReturn current FDV with a configurable sidebar threshold.

### v306.7.4.2
Restored dashboard section render comparisons by removing key-normalisation before label-based section branches.

### v306.7.4.1
Fixed a Streamlit sidebar persisted-number-widget warning by avoiding value= after session-state priming.

### v306.7.4
Fixed selected dashboard section state; removed legacy Unexplained driver expanders; persisted sidebar review settings.

### v306.7.3
Added common-candidate coverage summary, cumulative coverage, uncovered portfolio detail and a near-zero-actual-yet-benchmark-movement category.

### v306.7.2
Added reviewer-facing common validation candidates and portfolio validation plan tables for Unexplained directional validation.

### v306.7.1
Removed the residual-overshoot diagnostic; changed minimum validation to directional-support logic (same-direction holdings can validate even when they overshoot).

### v306.7.0
Added the Unexplained minimum validation set engine and diagnostics for same-direction DAssetReturn contribution rows.

### v306.6.0
Added Unexplained source-row sections for all DAssetReturn and TransactionListing rows across residual unexplained portfolios.

### v306.5.9
Removed legacy row-by-row Tier 1 assignment functions; the vectorised assignment path is now the single source of truth.

### v306.5.8
Executive Driver Movement now reuses the shared prepared Tier 1 assignment table instead of building its own.

### v306.5.7
Fixed the Tier 1 assignment denominator fallback to use summed DAssetTypeReturn previous FDV when dashboard rows lack it.

### v306.5.6
Fixed DAssetTypeReturn Tier 1 driver resolution to prefer Asset Type Code before Asset Type description; preserved return-contribution ranking.

### v306.5.5
Fixed the Nil actual return drilldown merge-key retention; added a 'No DAssetTypeReturn driver' note.

### v306.5.4
Added the Nil actual return waterfall bucket after Auto FX and before transaction explanations; executive table/section order updated.

### v306.5.3
Current Account dominated now performs a true transaction-exclusion tolerance retest using signed eligible NetConsideration.

### v306.5.2
Rebased the progress bar on v306.4.9 while retaining the v306.5.0 Current Account dominated waterfall logic; fixed transaction detail helper calls.

### v306.5.0
Current Account dominated tab aligned to the executive waterfall; transaction explanations use only the HOT portfolios remaining after Auto FX removal.

### v306.4.8
Loading-progress iframe is actively cleared/replaced on each render so the overall timer stops when the load completes.

### v306.4.7
Fixed st.iframe usage by passing the HTML string directly, without deprecated/unsupported scrolling arguments.

### v306.4.6
Loading-progress live timer applies only to the overall timer; individual phase times update only on completion; replaced deprecated components.html with st.iframe.

### v306.4.5
Loading progress uses a browser-side live timer while a real long-running load is active, then stops on completion.

### v306.4.4
Loading progress now appears immediately at the start of a real date load/rebuild so long BNP loads show activity from 0 seconds.

### v306.4.3
Suppressed the blank loading-progress strip on cache-hit section changes; progress now renders only during a real date load/rebuild.

### v306.4.2
Removed debug timing tables and source-detail executive timing while retaining full user-wait performance diagnostics.

### v306.4.1
Fixed current-run timing classification for cached bundles; added executive-summary session reuse for faster section navigation.

### v306.4.0
Added session-level date-folder and dashboard-bundle caching so section navigation reuses state unless date/settings/cache-refresh changes.

### v306.3.0
Added full-rerun user-wait timing across scan, controls, bundle preparation, executive summary, section render, and a combined timing CSV export.

### v306.2.2
Fixed BNP report reconciliation by removing an accidental HOT-waterfall tuple return from the DAssetReturn contribution detail builder.

### v306.2.1
Added selected-section render timing diagnostics with per-section totals and CSV export.

### v306.1
Deferred row-level detail loading for Portfolio Drill-through/transaction detail; transaction eligibility prepared once per bundle, detail rows fetched by selected portfolio.

### v306.0
Precomputed shared Tier 1 driver assignments, HOT waterfall sets, Auto FX section frames, and display-safe frames to reduce repeated render work.

### v305.3.1
Removed the obsolete sidebar date-folder rescan button; added a visible independent FX match-tolerance control.

### v305.2
Added a sidebar control for the independent FX dollar matching tolerance, passed into both Auto FX validation runs.

### v305.1
Auto FX display updated to the Asset-to-Portfolio Contribution basis; removed Excess Contribution / Asset Weight as calculation drivers.

### v305.0
Auto FX starting break changed to DDetailedReturn Actual vs Benchmark only; removed Over/Under and Excess Contribution fallbacks.

### v304.7.1
Added robust missing-section explainer insertion for BNP report reconciliation and Unexplained sections.

### v304.7
Added plain-English review/audit explainers to each dashboard section for handover users.

### v304.6
Added the executive dashboard styling refresh: section selector, cards, progress strip, driver movement table.

### v304.5
HOT explanation waterfall now applies FX first, then transaction-listing only to remaining HOT portfolios; driver movement counts reconcile.

### v304.4
Removed the persistent/manual date-folder scan cache so each app open scans expected date folders directly and loads the latest available BNP date.

### v304.3.1
Hotfix: made the folder_fingerprint_override backward-compatible when an older processing helper is present.

### v304.3
Added a folder-fingerprint override into process_day and context-init timing to remove duplicate fingerprint work.

### v304.2
Bypassed process_day's persistent write/read by default for one-day loads; replaced the DAssetReturn pandas usecols with a custom first-41-field parser.

### v304.1
Fixed sidebar expand/collapse hit-testing after the v304 date-navigation z-index change; narrowed the z-index boost to date navigation only.

### v304
Fixed the date-navigation click overlay; added a DAssetReturn first-41-column fast parser; added process_day internal timing split.

### v303
TransactionListing source load reads only the first 54 columns; ARC workbook inspection skipped in normal mode (SHOW_DEBUG only).

### v302.1
Hotfix: added a missing time import in the ARC helper needed for ARC sub-timing instrumentation.

### v302
Cleaned BNP cache diagnostics; uses the v184 read_csv rebuild path; adds process_day cache detail and ARC/FX sub-timings.

### v301
Added persistent per-date BNP source cache and persistent process_day core cache; ARC/FX unchanged except diagnostics retained.

### v300
Replaced the recursive BNP root manifest with a safe daily date-folder cache to prevent startup blocking; retained v299 optimisations.

### v299
Added persistent daily recursive BNP manifest cache, lazy detail-index build, and faster TransactionListing mapper core.

### v298
Added active-section rendering, vectorised OUT Tier 1 assignment fast path, transaction-mapper split diagnostics, and BNP cache-hit timing context.

### v297
Root-cause CSS fix for the sidebar toggle; header remains interactive while deploy/toolbar chrome is hidden.

### v296
Holistic timing diagnostics added for loading stages, BNP load, portfolio/ARC/FX sub-steps, render tabs, and per-portfolio Tier 1 assignment.

### v294
Build-executive-summary Tier 1 assignments use OUT-only population while retaining per-step diagnostics.

### v293
Build-executive-summary diagnostics added with per-step timings and row counts.

### v292
Reverted v291 keyed-groupby executive summary path; retained the faster v290 OUT-only Tier 1 assignment cache.

### v291
Executive summary driver views use a keyed groupby path from cached Tier 1 assignments to avoid repeated merge/crosstab work.

### v284
DDetailed Actual Return source-of-truth reconciliation uses recalculated DAssetReturn line contributions as primary; reported contribution retained as audit comparison.

### v283
BNP reconciliation primary basis changed to reported DAssetReturn contribution; calculated line reconstruction retained as diagnostic only.

### v282
BNP reconciliation now uses a single reported DAssetReturn contribution basis; variance-only outputs removed.

### v281
FX auto-explanation now requires non-zero FX removal, avoiding 'Yes / after FX removal / No FX removal' contradictions.

### v280
Date header rendered through a stable top container; loading-stage updates remain confined to the dashboard progress panel.

### v279
Streamlit chrome header/toolbar made non-interactive to prevent the Deploy toolbar overlay from blocking date-navigation clicks.

---

## Appendix A - `Static Data.xlsx` change log (mirrors the workbook's own `change_log` sheet)

- **2026-08-12** - *paths*: v363: local_price_validation_template changed from a personal, machine-specific path (C:\Users\cxp029\Downloads\Latest\...) to './local_price_validation_evidence_template.xlsx', resolved relative to the app folder. No code change needed - bnp_control_app.py already reads this key at startup via _apply_static_data_config_v306_13_8()/_set_path_global(). Also clears the v362 'Local (this machine only) - not portable' flag this path previously triggered in Input Sources.
- **2026-08-12** - *mapping_filters*: v363: bnp_helpers_price_integrity.py's UUT Material Price MVT population (resolve_material_movement_scope) now reads its include GLGroupName / exclude PortfolioCode lists from mapping_filters -> 'Valuation T' (the same rows already used for the UUT look-through population) instead of a separate hard-coded copy of the identical values. Hard-coded sets retained as a fallback only.
- **2026-08-09** - *excluded_from_bnp_reports / thresholds*: v326: wired in the exclusions (see workbook change_log for full detail).
- **2026-08-09** - *excluded_from_bnp_reports*: v325: added the sheet (M2STT2, M2STT4, M7MLCH).
- **2026-08-03** - *paths / reference_sources*: v324: added the IISL Central Mapping List reference (Mandates, Status=Active).
- **2026-08-03** - *paths / bnp_helpers_gav*: v319: removed the acc_balance_path override; GAV resolves Acc Balance from the Tableau date folder only.
- **2026-08-03** - *asset_type_code_map*: v318: moved the sidebar asset-type code map into Static Data.
- **2026-08-03** - *mapping_filters*: v316: added mapping_filters (workbook Mapping-tab include/exclude lists).
- **2026-08-03** - *bm_mapping*: v315: added BM Mapping, moved from the ARC workbook.
- **2026-08-03** - *date_folder_rules / folder_month_aliases*: v309.3 FIX: restored these two sheets after their v307 removal broke Tableau date-folder resolution.
- **2026-08-03** - *ALL*: v307: slimmed config; moved structural sheets (source_file_keywords, excluded_filename_tokens, header_contracts) to code.
- **2026-07-16** - *Initial template*: Initial Static Data workbook.