# Stage 1 2024 Evidence Manifest

This directory preserves the real MTX 2024 Stage 1 systematic baseline diagnostic and adversarial reassessment.

## Evidence boundary

Source used by the run: `MTX_2024(2).parquet`  
Raw source rows: **50,862,751**  
Raw Parquet is intentionally not committed to GitHub; it remains source-of-truth market data outside Git.

Canonical headline metrics are the **physical-path-resolved** files. Earlier checkpoint artifacts are preserved only for audit and must not override the canonical physical-resolved summary.

## Current research state

- Production-approved strategies: **0**
- Naked ORB: **KILL**
- Failed Breakout price-only: **KILL as standalone**
- Baseline VWAP Z2.5: **KILL as standalone**
- Primary frozen OOS candidate: **Large-Gap conditioned OR15 breakout**
- Secondary OOS-only hypothesis: **regime-filtered VWAP**
- No more 2024 tuning is permitted before independent-year testing

## Files

### Human-readable reports

- `STAGE1_2024_REAL_DIAGNOSTIC.md` — original real-data single-year diagnostic
- `STAGE1_2024_REASSESSMENT.md` — adversarial Kill / Keep review
- `../STAGE1_SYSTEMATIC_2024_CURRENT_STATUS_2026-08-24.md` — authoritative current status + next-stage plan

### Canonical metrics / QA

- `stage1_summary_2024_physical_resolved.csv`
- `stage1_bootstrap_2024_physical_resolved.csv`
- `stage1_2024_reassessment_key_metrics.csv`
- `stage1_top_direction_2024.csv`
- `stage1_top_monthly_2024.csv`
- `minute_qa_2024.json`
- `stage1_validation_2024.json`

### Reproduction scripts

- `repro/build_minutes_chunk.py`
- `repro/finalize_minutes.py`
- `repro/backtest_stage1_2024.py`

`backtest_stage1_2024.py` is the baseline minute-bar generator. Its original same-minute ambiguity behavior was conservative stop-first; the published canonical headline results were subsequently corrected using raw physical tick order for the 13 ambiguous cases. The canonical files are explicitly named `physical_resolved`.

## Important integrity rules

1. Raw physical row order is truth; do not sort raw ticks by timestamp/price.
2. `_seq` must be assigned before filters.
3. Only MTX outright six-digit expiries enter the strategy path; spread/combo rows are excluded.
4. Different expiries must never be mixed into one profile or one execution path.
5. Same-minute stop/target ambiguity must be resolved from original physical tick order.
6. This 2024 research is a **single-year diagnostic**, not final OOS validation.
7. Large-Gap OR15 is frozen for independent-year falsification; changing the rule after seeing OOS is a fail, not a rescue.

## SHA-256 provenance from the ChatGPT research runtime

| Local artifact | SHA-256 |
|---|---|
| `STAGE1_2024_REAL_DIAGNOSTIC.md` | `4e184344be6885e4381183021bdd3d7032365e3fc1b7b0391a7cf9901b9232f6` |
| `STAGE1_2024_REASSESSMENT.md` | `a3f8667bf78a1674e77cb46e9f4d9e6a655e6bb5984bf0f1aea1926f45e00a8f` |
| `stage1_summary_2024_physical_resolved.csv` | `5a7d1d9b291509f458dd9e285419450304e172951ebfd5683e25d943f4225a72` |
| `stage1_trades_2024_physical_resolved.csv` | `6e289acb27d64e88d1ed18e5870f33c122ab723e7f156a23d65e029f15a16885` |
| `stage1_bootstrap_2024_physical_resolved.csv` | `f2d9284e0edf6233662701a75c4ca54d777b109edf83ff25c5e975d3befdacad` |
| `stage1_top_monthly_2024.csv` | `d37e86fa7d6afe1a2330d987dd7cf973c281c652559c224fc159365ab8fc0ca3` |
| `stage1_top_direction_2024.csv` | `8497c83cde9e87addd5f6f3a0391a8e1a56e8f49fa903824bbd6657e3bd2fd00` |
| `stage1_2024_reassessment_key_metrics.csv` | `117b08adee0a10eb75518e4c912ed7f58a2e4c35b1fbc0fd5f7062b0deb45717` |
| `backtest_stage1_2024.py` | `2145ece4f64c8cbc54b1d2c12d2e7d06b0250ade7a63a01f8aa2af5eb97d50bd` |
| `build_minutes_chunk.py` | `9222b7e0277b0054991e3fbfa3c1e9f443121c65de1a4158e129f6c6770e0c26` |
| `finalize_minutes.py` | `4ad61536f7b91866f58483fe949dc6d8571ced2f95ac885e388397dd85eb55c1` |
| `minute_qa_2024.json` | `9ae26a9e8a0c554abd16cabf45f2b2e92b8aa4f683a28c5bda45ca48be81e565` |
| `stage1_validation_2024.json` | `c92d575c043a9515878538dc867403537f092bda893a2354c91a52d8138d88e9` |

The full physical-resolved trade CSV hash is preserved above as provenance even where the repository review surface focuses on summaries and reproducible research rules.
