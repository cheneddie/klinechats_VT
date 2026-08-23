"""M5 Dev6 deterministic event-sanity sampling and evidence validation.

This module only chooses cases for manual/replay QA. It never changes event
membership or outcome values and defines no trading threshold, P&L, or Edge.
"""
from __future__ import annotations
from dataclasses import dataclass
from hashlib import sha256
import numpy as np
import pandas as pd

EVENT_SANITY_SCHEMA_VERSION = "POC_M5_EVENT_SANITY_V1"
SANITY_SAMPLING_VERSION = "M5_DEV6_SANITY_SAMPLE_V5"
SANITY_CATEGORIES = ("strong_mfe", "strong_mae", "high_balance", "structure_reversal", "no_reaction")
REQUIRED_COLUMNS = {
    "event_key", "session", "trading_day_int", "trigger_sec", "atr",
    "mfe_30m_atr", "mae_30m_atr", "balance_5m_eff",
    "balance_5m_two_sided_min_atr", "break_30m", "break_second_approx",
    "sanity_full_30m",
}

@dataclass(frozen=True)
class SanitySampleConfig:
    per_category: int = 25
    day_quota: int = 6
    night_quota: int = 19
    month_cap: int = 3
    min_observed_span_30m_seconds: int = 1740
    def validate(self) -> None:
        if self.per_category < 1 or self.day_quota < 0 or self.night_quota < 0:
            raise ValueError("invalid sanity sample counts")
        if self.day_quota + self.night_quota != self.per_category:
            raise ValueError("session quotas must sum to per_category")
        if self.month_cap < 1 or self.min_observed_span_30m_seconds < 0:
            raise ValueError("invalid sanity coverage constraint")


def _prepare(outcomes: pd.DataFrame) -> pd.DataFrame:
    miss = REQUIRED_COLUMNS - set(outcomes.columns)
    if miss:
        raise ValueError(f"event sanity outcomes missing columns: {sorted(miss)}")
    x = outcomes.copy()
    if x.event_key.isna().any() or not x.event_key.is_unique:
        raise ValueError("event_key must be non-null and unique")
    if not set(x.session.astype(str)).issubset({"day", "night"}):
        raise ValueError("unsupported session")
    for c in ("trigger_sec", "trading_day_int"):
        x[c] = pd.to_numeric(x[c], errors="raise").astype("int64")
    for c in ("atr", "mfe_30m_atr", "mae_30m_atr", "balance_5m_eff", "balance_5m_two_sided_min_atr", "break_second_approx"):
        x[c] = pd.to_numeric(x[c], errors="coerce")
    if (x.atr.dropna() <= 0).any():
        raise ValueError("ATR must be positive")
    x["break_delay_seconds"] = x.break_second_approx - x.trigger_sec
    bad_break = x.break_30m.eq(True) & ~x.break_delay_seconds.between(0, 1800, inclusive="both")
    if bool(bad_break.any()):
        raise ValueError("break timestamp is not a valid trigger-relative 30m delay")
    valid_balance = x.balance_5m_eff.notna() & x.balance_5m_two_sided_min_atr.notna()
    x["balance_score"] = np.nan
    x.loc[valid_balance, "balance_score"] = (
        x.loc[valid_balance, "balance_5m_two_sided_min_atr"].rank(pct=True, method="average")
        + (1 - x.loc[valid_balance, "balance_5m_eff"].rank(pct=True, method="average"))
    )
    x["reaction_atr_30m"] = x[["mfe_30m_atr", "mae_30m_atr"]].max(axis=1)
    x["reaction_points_30m"] = x.reaction_atr_30m * x.atr
    x["no_reaction_atr_pct"] = x.groupby("session").reaction_atr_30m.rank(pct=True, method="average")
    x["no_reaction_points_pct"] = x.groupby("session").reaction_points_30m.rank(pct=True, method="average")
    x["no_reaction_score"] = x[["no_reaction_atr_pct", "no_reaction_points_pct"]].max(axis=1)
    x["month"] = pd.to_datetime(x.trading_day_int, unit="D", origin="unix").dt.month.astype(int)
    x["_sanity_hash"] = x.event_key.astype(str).map(lambda s: sha256(s.encode()).hexdigest())
    return x


def _pick(frame: pd.DataFrame, metric: str, ascending: bool, cfg: SanitySampleConfig, chosen: set[str]) -> pd.DataFrame:
    ranked = frame.loc[~frame.event_key.astype(str).isin(chosen)].dropna(subset=[metric]).sort_values(
        [metric, "_sanity_hash"], ascending=[ascending, True], kind="stable"
    )
    quotas = {"day": cfg.day_quota, "night": cfg.night_quota}
    sc = {"day": 0, "night": 0}; mc = {m: 0 for m in range(1, 13)}; dates: set[int] = set(); idx = []
    for i, r in ranked.iterrows():
        sess = str(r.session); month = int(r.month); day = int(r.trading_day_int)
        if sc[sess] >= quotas[sess] or mc[month] >= cfg.month_cap or day in dates:
            continue
        idx.append(i); sc[sess] += 1; mc[month] += 1; dates.add(day)
        if len(idx) == cfg.per_category:
            break
    if len(idx) != cfg.per_category:
        raise ValueError(f"insufficient sanity candidates under coverage constraints: {len(idx)}")
    return ranked.loc[idx].copy()


def select_event_sanity_sample(outcomes: pd.DataFrame, config: SanitySampleConfig = SanitySampleConfig()) -> pd.DataFrame:
    config.validate(); x = _prepare(outcomes); base = x.loc[x.sanity_full_30m.astype(bool)].copy()
    chosen: set[str] = set(); pieces = []
    specs = (
        ("strong_mfe", base, "mfe_30m_atr", False),
        ("strong_mae", base, "mae_30m_atr", False),
        ("high_balance", base, "balance_score", False),
        ("structure_reversal", base.loc[base.break_30m.eq(True)], "break_delay_seconds", True),
        ("no_reaction", base.loc[base.break_30m.eq(False)], "no_reaction_score", True),
    )
    for cat, frame, metric, asc in specs:
        y = _pick(frame, metric, asc, config, chosen)
        y["sanity_category"] = cat; y["category_rank"] = np.arange(1, len(y) + 1)
        pieces.append(y); chosen.update(y.event_key.astype(str))
    out = pd.concat(pieces, ignore_index=True)
    ordered_ids = out.event_key.astype(str).tolist()
    sample_hash = sha256("\n".join(ordered_ids).encode()).hexdigest()
    out["event_sanity_schema_version"] = EVENT_SANITY_SCHEMA_VERSION
    out["sanity_sampling_version"] = SANITY_SAMPLING_VERSION
    out["sanity_sample_event_ids_sha256"] = sample_hash
    out["sanity_session_quota"] = f"day:{config.day_quota}|night:{config.night_quota}"
    out["sanity_month_cap"] = config.month_cap
    out["sanity_min_observed_span_30m_seconds"] = config.min_observed_span_30m_seconds
    return out.drop(columns=["_sanity_hash"], errors="ignore")


def validate_sanity_sample(sample: pd.DataFrame, config: SanitySampleConfig = SanitySampleConfig()) -> dict:
    config.validate(); expected = config.per_category * len(SANITY_CATEGORIES)
    req = {"event_key", "sanity_category", "category_rank", "session", "trading_day_int", "sanity_full_30m", "sanity_sampling_version", "sanity_sample_event_ids_sha256"}
    miss = req - set(sample.columns)
    if miss: raise ValueError(f"sanity sample missing columns: {sorted(miss)}")
    if len(sample) != expected or sample.event_key.isna().any() or not sample.event_key.is_unique:
        raise ValueError("sanity sample row/event-key integrity failure")
    ids = sample.event_key.astype(str).tolist(); expected_hash = sha256("\n".join(ids).encode()).hexdigest()
    hashes = set(sample.sanity_sample_event_ids_sha256.astype(str).unique())
    if hashes != {expected_hash}: raise ValueError("sanity sample event-id hash mismatch")
    if set(sample.sanity_sampling_version.astype(str).unique()) != {SANITY_SAMPLING_VERSION}: raise ValueError("sanity sampling version drift")
    rows = {}; ok = True
    for cat in SANITY_CATEGORIES:
        g = sample.loc[sample.sanity_category.astype(str).eq(cat)]
        month = pd.to_datetime(pd.to_numeric(g.trading_day_int), unit="D", origin="unix").dt.month
        checks = {
            "N": len(g), "unique_dates": int(g.trading_day_int.nunique()), "day": int(g.session.astype(str).eq("day").sum()),
            "night": int(g.session.astype(str).eq("night").sum()), "max_per_month": int(month.value_counts().max()) if len(g) else 0,
            "full_observation": bool(g.sanity_full_30m.astype(bool).all()),
        }
        p = checks == {"N": config.per_category, "unique_dates": config.per_category, "day": config.day_quota, "night": config.night_quota, "max_per_month": checks["max_per_month"], "full_observation": True} and checks["max_per_month"] <= config.month_cap
        if cat == "structure_reversal": p = p and bool(g.break_30m.eq(True).all()) and bool(pd.to_numeric(g.break_delay_seconds).between(0,1800).all())
        if cat == "no_reaction": p = p and bool(g.break_30m.eq(False).all())
        checks["pass"] = bool(p); ok &= bool(p); rows[cat] = checks
    return {"schema_version": EVENT_SANITY_SCHEMA_VERSION, "sampling_version": SANITY_SAMPLING_VERSION, "events": len(sample), "sample_event_ids_sha256": expected_hash, "categories": rows, "all_pass": bool(ok)}


def validate_replay_ledger(sample: pd.DataFrame, ledger: pd.DataFrame, config: SanitySampleConfig = SanitySampleConfig()) -> dict:
    s = validate_sanity_sample(sample, config)
    req = {"event_key", "pass", "mismatch_fields", "observation_span_seconds", "sanity_sampling_version", "sanity_sample_event_ids_sha256"}
    miss = req - set(ledger.columns)
    if miss: raise ValueError(f"sanity replay ledger missing columns: {sorted(miss)}")
    if ledger.event_key.isna().any() or not ledger.event_key.is_unique or set(ledger.event_key.astype(str)) != set(sample.event_key.astype(str)):
        raise ValueError("sanity replay event-key mismatch")
    passed = ledger["pass"].astype(str).str.lower().isin({"true", "1"})
    mismatch = ledger.mismatch_fields.fillna("").astype(str).str.strip().ne("")
    span = pd.to_numeric(ledger.observation_span_seconds, errors="coerce")
    hashes = set(ledger.sanity_sample_event_ids_sha256.astype(str).unique())
    versions = set(ledger.sanity_sampling_version.astype(str).unique())
    ok = bool(passed.all() and not mismatch.any() and span.ge(config.min_observed_span_30m_seconds).all() and hashes == {s["sample_event_ids_sha256"]} and versions == {SANITY_SAMPLING_VERSION})
    return {"schema_version": "POC_M5_DEV6_RAW_REPLAY_V1", "events": len(ledger), "passed": int(passed.sum()), "mismatches": int((~passed | mismatch).sum()), "min_observed_span_seconds": float(span.min()), "all_pass": ok}


def validate_visual_manifest(sample: pd.DataFrame, manifest: dict, config: SanitySampleConfig = SanitySampleConfig()) -> dict:
    s = validate_sanity_sample(sample, config); cats = manifest.get("categories", [])
    by = {str(x.get("sanity_category")): x for x in cats}; ok = True
    for cat in SANITY_CATEGORIES:
        x = by.get(cat, {}); ok &= int(x.get("panels_reviewed", -1)) == config.per_category and int(x.get("visual_mismatches", -1)) == 0 and str(x.get("visual_verdict")) == "PASS"
    ok &= int(manifest.get("total_panels_reviewed", -1)) == config.per_category * len(SANITY_CATEGORIES)
    ok &= int(manifest.get("total_visual_mismatches", -1)) == 0
    ok &= str(manifest.get("sampling_version")) == SANITY_SAMPLING_VERSION
    ok &= str(manifest.get("sample_event_ids_sha256")) == s["sample_event_ids_sha256"]
    ok &= bool(manifest.get("all_pass", False))
    return {"schema_version": "POC_M5_DEV6_VISUAL_REVIEW_V1", "panels": int(manifest.get("total_panels_reviewed", 0)), "mismatches": int(manifest.get("total_visual_mismatches", 0)), "all_pass": bool(ok)}
