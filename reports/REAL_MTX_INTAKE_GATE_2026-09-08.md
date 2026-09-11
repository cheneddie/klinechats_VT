# P2 Real MTX Intake Gate — Closeout

Date: 2026-09-08  
Repository: `cheneddie/klinechats_VT`  
Branch: `research-integrity-p0`  
Integration base: `fabio-decision-gym-v4`  

## Verdict

- P0 execution truth: **CLOSED**
- P1 Production Value Gates: **IMPLEMENTED / GREEN**
- P2 Real MTX source-intake plumbing: **IMPLEMENTED / GREEN**
- Real MTX source files in the current runtime: **NOT AVAILABLE**
- Real Discovery / Validation / Final Holdout evidence: **NOT STARTED**
- Real MR edge: **NOT PROVEN**
- Real BO edge: **NOT PROVEN**
- `main` merge: **NOT PERFORMED**

The purpose of this P2 work is to ensure that a real MTX research campaign cannot begin from an unverified file or from a synthetic fixture accidentally treated as market evidence.

## Real MTX Intake V1

Core module:

`server/v5/data_intake.py`

CLI:

`tools/real_mtx_intake.py`

Policy identifier:

`REAL_MTX_INTAKE_V1`

Required Parquet columns:

`datetime, product, expiry, price, volume, side`

The intake scanner is streaming. It does not load an annual multi-million-row source into memory at once and it does not sort physical rows before QA.

### Immutable source identity

The report records:

- physical file SHA-256
- file size
- Parquet row count
- Parquet row-group count and per-group row counts
- Arrow schema
- Parquet creator / format metadata
- expected year inferred from or supplied alongside the source
- deterministic report hash independent of local absolute path and generation timestamp

The physical SHA-256 remains the source identity. The report hash identifies the intake interpretation of that source.

## Hard fail-closed checks

The following checks are data-integrity / replayability requirements, not trading-performance preferences:

1. `NOT_SYNTHETIC_SOURCE`
   - filenames identified as synthetic are rejected by default
   - `--allow-synthetic` exists only for QA fixtures

2. `PARQUET_READABLE`
   - PyArrow must open the physical file

3. `NONEMPTY_PARQUET`
   - source must contain rows

4. `REQUIRED_COLUMNS`
   - all six production columns must exist

5. `ROW_GROUP_ROW_COUNT`
   - sum of row-group rows must equal Parquet metadata row count

6. `SCANNED_ROW_COUNT`
   - streamed physical rows must equal metadata row count

7. `DATETIME_COMPLETE`
   - no null/unparseable physical datetime rows

8. `PHYSICAL_TIME_ORDER`
   - physical source timestamps must not move backward
   - no sorting is performed to hide a reversal

9. `MTX_OUTRIGHT_PRESENT`
   - at least one MTX outright contract matching `^\d{6}$`

10. `MTX_OUTRIGHT_PRICE_VALID`
    - outright price must be finite and > 0

11. `MTX_OUTRIGHT_VOLUME_VALID`
    - outright volume must be finite and >= 0

12. `DAY_SESSION_MTX_OUTRIGHT_PRESENT`
    - at least one MTX outright row must exist in the configured day session, default `08:45:00–13:45:00`

13. `EXPECTED_YEAR_PRESENT`
    - when an expected year is supplied/inferred, at least one valid MTX outright row must belong to that year

The Gate deliberately does not invent a hard percentage for annual-year purity. Taiwan futures night-session/calendar boundaries and actual vendor packaging must be examined from the real files first. The timestamp-year distribution and expected-year share are reported for review.

## Descriptive source diagnostics

The report also records without silently converting them into trading thresholds:

- all product counts
- MTX expiry distribution
- outright vs non-outright/spread rows
- side-value distribution
- timestamp year distribution
- same-second physical density
- maximum number of physical rows in one second
- day-session per-date/per-contract volume
- volume-dominant contract by trading date
- calendar-front contract by trading date
- dominant-contract roll count
- front-contract roll count
- ambiguous volume days where the top contract is less than 10% above the second contract

These diagnostics are intended for contract-policy audit before scanner trust.

## Timestamp-resolution defect found by CI

The first implementation exposed a real compatibility defect under Pandas 2.3 / PyArrow:

- a Parquet `timestamp(ms)` column can remain millisecond-resolution after conversion to Pandas;
- integer extraction was initially interpreted as nanoseconds;
- same-second grouping therefore collapsed unrelated timestamps into oversized groups.

A first attempted fix using `DatetimeIndex.asi8` was still insufficient because modern Pandas preserves the index resolution in `asi8`.

The final implementation explicitly normalizes:

`pd.DatetimeIndex(vd).as_unit("ns").asi8`

Regression now writes the same physical fixture as:

- `timestamp(ms)`
- `timestamp(us)`
- `timestamp(ns)`

and requires identical:

- physical reversal count
- same-second group statistics
- start timestamp
- end timestamp

This regression is part of the Real MTX Intake CI and Strategy Lab main CI.

## Real campaign governance

Core module:

`server/v5/campaigns.py`

Real campaign constructor:

`create_real_mtx_campaign(...)`

Real dataset registration:

`register_real_mtx_dataset(...)`

A Real MTX campaign carries:

- `source_class = REAL_MTX`
- `dataset_evidence_policy = REAL_MTX_INTAKE_V1`

`register_real_mtx_dataset()` runs the physical intake itself and stores the passing intake report inside the campaign dataset metadata together with the exact source SHA-256 and observed timestamp bounds.

### Freeze is fail-closed

For a `REAL_MTX_INTAKE_V1` campaign, `freeze_campaign()` re-verifies every dataset record:

- source class
- evidence policy
- intake PASS status
- synthetic flag
- failed-check list
- intake SHA-256 == campaign dataset SHA-256
- intake source filename == campaign source filename
- intake expected year == campaign dataset year
- intake report hash validity

A caller may still use the legacy low-level `register_campaign_dataset()` for backwards-compatible synthetic/legacy fixtures, but a campaign declaring `REAL_MTX_INTAKE_V1` cannot freeze from such a manually inserted SHA-only dataset.

V5 storage already protects frozen campaign datasets with SQLite triggers. After campaign freeze, direct INSERT / UPDATE / DELETE on `campaign_datasets` is rejected, and the frozen campaign row itself is immutable.

## Candidate / Production Gate provenance

Module:

`server/v5/real_mtx_provenance.py`

For a Candidate whose D/V/H chain declares Real MTX evidence:

- all Discovery / Validation / Final Holdout roles must use `REAL_MTX_INTAKE_V1`
- every role campaign must remain frozen
- every role must contain a Real MTX dataset
- every intake report must still verify against SHA/file/year/report hash
- Real + legacy role mixing fails with `MIXED_REAL_AND_LEGACY_CAMPAIGN`

Pure synthetic/legacy engineering campaigns are reported as `NOT_APPLICABLE`; they do not masquerade as Real MTX evidence and they remain usable for software QA.

The public Production Gate adds an immutable check:

`REAL_MTX_INTAKE_PROVENANCE`

and freezes the Real-MTX provenance object inside the append-only Production Value Audit companion record.

## Automated regression

Dedicated workflow:

`.github/workflows/real-mtx-intake-ci.yml`

It verifies:

- intake module / campaign / provenance compilation
- structural real-Parquet PASS
- deterministic report hash
- ms/us/ns timestamp-resolution invariance
- physical timestamp reversal FAIL
- invalid price/volume FAIL
- synthetic filename default FAIL
- QA-only synthetic override PASS
- valid Real campaign registration + freeze PASS
- SHA-only low-level insertion into a Real campaign cannot freeze
- tampered intake report hash cannot freeze
- synthetic source cannot register as Real MTX
- all-Real D/V/H candidate provenance PASS
- mixed Real/legacy D/V/H provenance FAIL
- Production Value audit freezes Real-MTX provenance check

All of these tests are also included in the Strategy Lab main CI suite.

## Final audited code head

`5a748ae525069e6fc5468ea5ff792c004009b9db`

Comparison with `fabio-decision-gym-v4` at this code head:

- **205 commits ahead**
- **0 commits behind**
- merge base `5c12e8fe810184220d5bf15f215855f12b6030e8`

GitHub Actions at this code head:

- V5 Research CI run `34188426699`: **PASS**
- Browser Release QA run `34188426646`: **PASS**
- Real MTX Intake CI run `34188426622`: **PASS**
- Strategy Lab Feature QA run `34188426616`: **PASS**
- Strategy Lab CI run `34188426649`: **PASS**

Strategy Lab main CI additionally confirms:

- P0 regression: PASS
- P1 Production Value dedicated regression: PASS
- P2 Intake / campaign / provenance dedicated regressions: PASS
- public build: PASS
- synthetic physical-Parquet E2E: PASS
- production/deployment synthetic governance: PASS
- runtime screenshots: PASS
- reproducibility manifest: PASS

## Real-data execution boundary

No real `MTX_2024.parquet`, `MTX_2025.parquet` or `MTX_2026.parquet` is currently available in the active runtime of this conversation.

Therefore this P2 closeout proves **source-intake/governance readiness only**. It is not a new backtest and contains no new real-market result.

When the exact source files are available, the next governed sequence is:

1. run `tools/real_mtx_intake.py` on every physical source;
2. inspect SHA-256, schema, coverage, expiry distribution, physical ordering and contract-day diagnostics;
3. create a `REAL_MTX_INTAKE_V1` campaign;
4. register files through `register_real_mtx_dataset()`;
5. freeze campaign only after all source evidence passes;
6. run scanner + Event Sanity;
7. freeze Discovery;
8. run formal MR/BO Discovery backtests;
9. optimize Discovery only;
10. freeze Candidate and concentration policy;
11. Validation without retuning;
12. Final Holdout without retuning;
13. cost / latency / portfolio stress;
14. Production Value audit including MR/BO reward structure, ATR 10%, month/year concentration;
15. real historical↔live parity and paper evidence;
16. only then Production Gate / Deployment.

Synthetic data must never substitute for a missing real source file.
