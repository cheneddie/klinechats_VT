# Fabio Real Evidence Campaign — 2026-08-21 完整報告

> Campaign: `FABIO_REAL_EVIDENCE_V1_20260821`  
> Repository: `cheneddie/klinechats_VT`  
> Research branch: `fabio-decision-gym-v4`  
> Methodology tested commit: `53dbd9450922cfd24385e9f98b116d0d912e21e5`  
> Scope of this report: completed G0/G1 evidence and research-governance work only. No incomplete G2/G3 result is promoted as evidence.

## 1. Executive conclusion

This campaign has moved from product/tool construction into real-data evidence work. The completed work establishes software integrity, source identity, physical-row-order truth, causal contract-selection auditability, an exchange-calendar-aware Previous Value coverage guard, and a sealed final-holdout registry.

At this snapshot:

- **G0 Software Integrity: PASS.** Eight GitHub workflows passed on the methodology commit after the Exchange Calendar V2 regression fix.
- **G1 Raw Data Truth: substantially complete for the supplied 2024 Validation source and 2025 Discovery source.**
- **2025 is not a full-year source.** It contains 236 regular day sessions ending 2025-12-19 versus the frozen TAIFEX calendar total of 243; seven expected sessions after 2025-12-19 are absent. It is therefore labelled `PARTIAL_YEAR_SOURCE`, not “full 2025”.
- **2024 contains a real source-coverage anomaly.** The frozen calendar expects a regular session on 2024-12-27 but the source contains no day-session rows for that date. Previous Value must therefore not bridge 2024-12-26 to 2024-12-30.
- **2026 remains sealed.** Only source hash, file/footer/schema metadata and calendar registration have been recorded; no strategy events, outcomes, PnL, edge or threshold information has been inspected.
- **No strategy edge claim is made in this report.** The retained 2025 G2/G3 diagnostic has not completed, so event counts, strict outcomes, reverse audit, ablation, bootstrap/FDR and regime/ATR freeze are not yet evidence.

## 2. Frozen research roles

| Year | Role | Permitted use at this stage | Forbidden use |
|---|---|---|---|
| 2025 | Discovery | feature/node/regime/management discovery after G1 passes | claiming OOS validation |
| 2024 | Validation Reserved | G1 source QA; later confirmatory validation after Discovery freeze | threshold/feature/regime selection |
| 2026 | Final Holdout | file hash/footer/calendar metadata only | any strategy outcome inspection before intentional holdout opening |

The original pre-registration remains at `config/research/evidence_campaign_v1.json`. Its hard rules remain active, including preservation of raw physical row order, use of only six-digit MTX outright expiries, causal calendar-front contract selection, and strict separation of Discovery/Validation/Holdout.

## 3. Coverage-policy amendment

The original pre-registration used `CALENDAR_GAP_V1`: a gap longer than three calendar days reset Previous Value. That rule was intentionally conservative but was discovered to be too coarse because legitimate exchange closures such as Lunar New Year can exceed three days.

The incomplete run produced under that rule was discarded before its edge results were accepted. The active campaign policy is now:

- coverage policy: `TAIFEX_SESSION_CALENDAR_V2`
- frozen calendar: `TAIFEX_REGULAR_SESSION_V1_20260821`
- logic: reset Previous Value only when an **expected TAIFEX regular session is missing from the source**; official closures do not count as source gaps.

The original pre-registration is not silently rewritten. The change is recorded as `methodology/coverage_policy_amendment_001.json`.

Relevant methodology commits:

1. `e86742d92c69315d02149dce4a9a6259ff7c64d0` — freeze TAIFEX regular-session calendar.
2. `8a9e00ae631c9975d240ba68f804042c3692ba2a` — use frozen TAIFEX session calendar in coverage guard.
3. `53dbd9450922cfd24385e9f98b116d0d912e21e5` — regression tests distinguishing exchange closures from source gaps.

## 4. G0 — Software Integrity

The methodology commit passed all eight workflows:

- CI
- V4 CI
- V4 Final QA Watchdog
- V5 Research CI
- V5 Training CI
- V5 Final Watchdog
- Browser release QA
- Stage screenshot

This establishes that the coverage/calendar regression did not require relaxing the causal contract policy or raw-order invariants. The earlier generic-CI failure was traced to a synthetic test fixture that incorrectly kept the expired `202503` contract after the third Wednesday; the fixture was corrected rather than weakening production contract selection.

## 5. G1 — 2024 Validation source

### Source identity

- supplied filename: `MTX_2024(4).parquet`
- bytes: **173,260,633**
- SHA-256: `6f76ecde2c6d9c13fe5381ffe0798fe05668a7d1e8abe85c7b0125581d5eb25c`
- physical rows: **50,862,751**
- row groups: **49**
- source-role: `VALIDATION_RESERVED`
- selection-safe: **false**

The hash matches the previously audited 2024 source, so the re-upload did not change the Validation bytes.

### Raw/source-order truth

- MTX rows: **50,862,751**
- six-digit outright rows: **50,862,689**
- spread/combo rows removed: **62**
- day-session outright rows: **27,016,535**
- timestamp backwards: **0**
- adjacent same-timestamp rows: **41,522,864**
- nulls in datetime/product/expiry/volume/side: **0**
- physical row-order QA: **PASS**

The very high same-second density reinforces the core invariant: datetime cannot be used to reconstruct within-second order. `_seq` must be assigned from physical Parquet row order before filtering, and raw ticks must never be re-sorted.

### Contract audit

- observed regular day sessions: **241**
- causal calendar-front roll switches: **12**
- days with multiple outright candidates: **0**
- causal-front vs completed-day dominant-volume mismatch: **0**, but this is only diagnostic because the source effectively exposes one outright candidate per observed day. It does not validate dominant-volume selection as causal.

### Exchange-calendar coverage

Frozen 2024 expected regular sessions: **242**. Observed: **241**.

The missing expected day is:

- **2024-12-27**

Therefore the profile chain must reset before 2024-12-30; `previous_profile` from 2024-12-26 may not be silently bridged across the missing expected session.

Long gaps caused by official exchange closures are not data gaps. Examples explicitly encoded in the frozen calendar include Typhoon GAEMI (2024-07-24/25), KRATHON (2024-10-02/03) and KONG-REY (2024-10-31).

## 6. G1 — 2025 Discovery source

### Source identity

- supplied filename: `MTX_2025(5).parquet`
- bytes: **146,569,961**
- SHA-256: `774b6f62b1e1a30ec159c7402b6967045ea3d99b59bfb16aeb0e0462a7a15156`
- physical rows: **39,416,621**
- row groups: **38**
- observed source range: `2024-12-31 15:00:00` through `2025-12-19 13:44:59`

### Raw/source-order truth

- MTX rows: **39,416,621**
- six-digit outright rows: **39,416,516**
- spread/combo rows removed: **105**
- day-session rows: **19,861,188**
- raw vendor volume sum: **108,060,010**
- normalized research volume `/2`: **54,030,005**
- timestamp backwards: **0**
- adjacent same-timestamp rows: **31,047,171**
- adjacent same-timestamp rate: **78.7667%**
- nulls in datetime/product/expiry/volume/side: **0**

### Side field

Counts:

- `0`: 17,396,367
- `+1`: 10,994,281
- `-1`: 11,025,973

`side` remains a tick-direction proxy only. It is not true aggressor classification, bid/ask delta, CVD, or a direct absorption label.

### Contract audit

- observed day sessions: **236**
- roll switches: **12**
- days with multiple outright candidates: **0**
- non-outright/spread rows are excluded before strategy research.

### Exchange-calendar completeness

Frozen TAIFEX 2025 MTX trading days: **243**. Source observed day sessions: **236**. Coverage ratio: **97.1193%**.

Missing expected sessions:

- 2025-12-22
- 2025-12-23
- 2025-12-24
- 2025-12-26
- 2025-12-29
- 2025-12-30
- 2025-12-31

Therefore the correct label is:

`2025 DISCOVERY / PARTIAL_YEAR_SOURCE / 2025-01-02 through 2025-12-19 / 236 of 243 sessions`

The file is suitable for Discovery over its observed frozen window, but reports must never describe it as a complete 2025 calendar year.

## 7. 2026 Final Holdout registry

- supplied filename: `MTX_2026(4).parquet`
- bytes: **137,413,619**
- SHA-256: `304f7d4e531374c3d4776f0c4d0e93e135dbd96c8b74956e9eb629fadbc957d6`
- Parquet rows: **36,158,882**
- row groups: **35**
- strategy outcomes inspected: **false**

A schema difference was recorded: 2024/2025 `volume` is physically DOUBLE, while the supplied 2026 footer reports `volume` as INT64. This is a data-engineering compatibility item for the future holdout-opening procedure; it is not evidence of strategy behavior.

No 2026 event, edge, PnL, node pass rate, winner/loser distribution, ATR selection, regime selection or management selection has been inspected.

## 8. Research methodology already frozen before edge acceptance

The pre-registration defines, among other items:

- Discovery 2025 → Validation 2024 → Final Holdout 2026.
- primary bootstrap cluster = trading day; 10,000 repetitions; 95% CI.
- Benjamini-Hochberg FDR `q=0.10` within pre-registered hypothesis families.
- Validation Max DD rejection threshold = **10R**.
- Execution-stress Max DD rejection threshold = **12R**.
- maximum single-month share of positive-month R = **30%**.
- baseline execution = next physical tick after decision; same-tick fill forbidden.
- latency stresses = +3 ticks, +5 ticks, +1 second, +3 seconds.
- production-v1 scope = day-session intraday only; overnight disabled.
- risk per trade = 1R; max daily loss = 2R; max concurrent positions = 1.
- Shadow ≥ 20 trading days; Paper ≥ 20 trading days and ≥ 50 combined executable entries before capital promotion.
- Structural Score, Edge Score and Learnability Score are separate.

ATR representative scale, causal-regime thresholds, forced-flat cutoff and cooldown seconds are intentionally not frozen yet; they may be selected only inside the 2025 Discovery window and then must be frozen before 2024 Validation is opened.

## 9. What has NOT been completed

The following must not be inferred from this evidence bundle:

- no completed 2025 strict-entry performance result;
- no completed relaxed opportunity outcome set;
- no completed reverse-node audit / sequential contribution / ablation evidence on the real 2025 source;
- no day-cluster bootstrap or FDR result;
- no frozen ATR representative scale;
- no frozen causal Regime Engine thresholds;
- no 2024 confirmatory strategy validation;
- no 2026 holdout result;
- no execution-stress production approval;
- no Shadow/Paper/live approval.

The previously started 2025 scanner run under the superseded calendar-gap rule was invalidated. A run started after the Exchange Calendar V2 change did not complete within the execution window, so its intermediate event counts are not retained as evidence and are intentionally absent from this repository bundle.

## 10. Required next sequence

1. Run the official release scanner on the 2025 Discovery source from a clean Event Store using `TAIFEX_SESSION_CALENDAR_V2`.
2. Persist a complete reproducibility manifest: research_run_id, Git commit, raw-source SHA-256, config hash, scanner/contract/coverage/outcome/management versions, Python and dependency versions.
3. Pass physical decision/entry sanity checks.
4. Compute relaxed opportunity outcomes and strict-entry outcomes from physical future ticks.
5. Run reverse audit, sequential contribution and ablation.
6. Create concrete Hypothesis Registry entries before accepting family-level tests.
7. Run trading-day cluster bootstrap and BH-FDR.
8. Select/freeze the representative volatility scale, causal-regime thresholds, forced-flat cutoff and cooldown using 2025 only.
9. Freeze the Discovery candidate generation.
10. Only then open 2024 for confirmatory Validation.
11. Keep 2026 sealed until the candidate and all permitted pre-holdout rules are frozen and the holdout is intentionally opened.

## 11. Evidence bundle layout

```text
evidence/real_campaign/FABIO_REAL_EVIDENCE_V1_20260821/
├── README.md
├── FULL_REPORT_20260821.md
├── MANIFEST.json
├── g0/
│   └── ci_status.json
├── methodology/
│   └── coverage_policy_amendment_001.json
├── registry/
│   ├── source_manifest.json
│   ├── source_sha256.txt
│   └── 2026_holdout_metadata.json
├── 2024_validation_g1/
│   ├── g1_raw_contract_summary.json
│   ├── parquet_metadata.json
│   ├── contract_selection_audit.json.gz.b64
│   ├── date_counts_all.json.gz.b64
│   ├── exchange_calendar_coverage_v2.json
│   └── sha256.txt
└── 2025_discovery_g1/
    ├── g1_raw_contract_summary.json
    ├── parquet_metadata.json
    ├── contract_selection_audit.json.gz.b64
    ├── date_counts_day_session_raw_volume.json
    └── exchange_calendar_coverage.json
```

## 12. Raw-data storage policy

The 132–173 MB Parquet sources are intentionally not committed to GitHub. Large completed JSON audit artifacts are stored losslessly as `*.json.gz.b64` text so they can be committed through the repository interface without truncation. Restore with `base64 -d FILE.json.gz.b64 | gunzip > FILE.json`. Repository evidence references exact raw bytes through SHA-256 and metadata. This avoids bloating Git history and, more importantly, prevents accidental strategy access to the 2026 final holdout through ordinary repository tooling.

## 13. Official calendar references used

- Taiwan Futures Exchange, 2025 Holiday Schedule (Revised version).
- Taiwan Futures Exchange, annual trading statistics: 2025 MTX number of trading days = 243.
- Taiwan Futures Exchange notices for 2024 Typhoon GAEMI closure on July 24–25.
- Taiwan Futures Exchange notices for 2024 Typhoon KRATHON closure on October 2–3.
- Taiwan Futures Exchange notice for 2024 Typhoon KONG-REY closure on October 31.

These references support the calendar/coverage layer only; they do not provide or validate strategy edge.
