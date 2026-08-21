# FABIO_REAL_EVIDENCE_V1_20260821

This directory is the repository snapshot for completed real-data evidence as of 2026-08-21.

Start with [`FULL_REPORT_20260821.md`](FULL_REPORT_20260821.md).

## Gate snapshot

- G0 Software Integrity: **PASS**
- G1 Raw Data Truth: **completed evidence bundle for supplied 2024/2025 sources; 2024 has one missing expected day-session (2024-12-27), 2025 is a partial-year source ending 2025-12-19**
- G2/G3: **NOT COMPLETE — no intermediate scanner performance is evidence**
- 2024 strategy validation: **not opened**
- 2026 final holdout: **sealed**

Raw Parquet files are not stored in GitHub. Use `registry/source_manifest.json` and `registry/source_sha256.txt` to bind a run to exact source bytes.

The original campaign pre-registration lives at `config/research/evidence_campaign_v1.json`. Coverage-policy amendment 001 is additive; the original pre-registration is not silently overwritten.

## Restoring compressed audit artifacts

Large JSON audit files are preserved losslessly as `*.json.gz.b64`. Example:

```bash
base64 -d 2025_discovery_g1/contract_selection_audit.json.gz.b64 | gunzip > contract_selection_audit.json
```

The decoded bytes are the completed local evidence artifact; `MANIFEST.json` records both repository-file and decoded SHA-256 values.
