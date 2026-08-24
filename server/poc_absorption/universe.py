"""Unbiased causal HIGH_PRICE_PROBE event universe for POC exhaustion research.

Universe membership is intentionally PRICE ONLY. POC migration, TDP pressure,
price-efficiency and all future outcomes are attached after selection and must
never decide whether a raw trigger exists.

The engine preserves two levels:
- raw trigger: every causal high-price probe is retained;
- episode: deterministic clustering of nearby probes for dependence-aware stats.

No retrospective "best trigger" selection is performed.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha1, sha256
import json

import numpy as np
import pandas as pd

EVENT_SCHEMA_VERSION = "POC_PROBE_EVENT_V1"
UNIVERSE_VERSION = "HIGH_PRICE_PROBE_V1"
UNIVERSE_SCHEMA_VERSION = "POC_HIGH_PRICE_PROBE_UNIVERSE_V1"


@dataclass(frozen=True)
class HighPriceProbeConfig:
    lookback_bars: int = 24
    upper_zone_fraction: float = 0.80
    near_high_atr: float = 0.25
    episode_exit_atr: float = 0.50
    max_episode_seconds: int = 1800

    def validate(self) -> None:
        if self.lookback_bars < 2:
            raise ValueError("lookback_bars must be >= 2")
        if not 0.0 < self.upper_zone_fraction < 1.0:
            raise ValueError("upper_zone_fraction must be in (0, 1)")
        if self.near_high_atr < 0:
            raise ValueError("near_high_atr must be >= 0")
        if self.episode_exit_atr <= 0:
            raise ValueError("episode_exit_atr must be > 0")
        if self.max_episode_seconds <= 0:
            raise ValueError("max_episode_seconds must be > 0")

    @property
    def config_hash(self) -> str:
        payload = json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))
        return sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class UniverseResult:
    triggers: pd.DataFrame
    episodes: pd.DataFrame


def _stable_id(*parts: object, prefix: str) -> str:
    raw = "|".join(str(p) for p in parts).encode("utf-8")
    return f"{prefix}_{sha1(raw).hexdigest()[:20]}"


def _validate_bars(frame: pd.DataFrame) -> pd.DataFrame:
    required = {
        "timeframe", "session", "bar_start", "bar_end_seq", "bar_start_seq",
        "high", "low", "close", "atr_n",
    }
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"Missing bar/feature columns: {sorted(missing)}")
    out = frame.copy().reset_index(drop=True)
    seq = pd.to_numeric(out["bar_start_seq"], errors="raise").to_numpy(dtype=np.int64)
    end_seq = pd.to_numeric(out["bar_end_seq"], errors="raise").to_numpy(dtype=np.int64)
    if len(seq) > 1 and np.any(np.diff(seq) <= 0):
        raise ValueError("bar_start_seq must be strictly increasing; universe never sorts input")
    if np.any(end_seq < seq):
        raise ValueError("bar_end_seq precedes bar_start_seq")
    if len(out) and (out["timeframe"].nunique() != 1 or out["session"].nunique() != 1):
        raise ValueError("One universe partition must contain one timeframe and one session")
    return out


def _tick_lookup(ticks: pd.DataFrame) -> dict[int, tuple[pd.Timestamp, float]]:
    required = {"_seq", "datetime", "price"}
    missing = required.difference(ticks.columns)
    if missing:
        raise ValueError(f"Missing tick columns: {sorted(missing)}")
    seq = pd.to_numeric(ticks["_seq"], errors="raise").to_numpy(dtype=np.int64)
    if len(seq) > 1 and np.any(np.diff(seq) <= 0):
        raise ValueError("tick _seq must be strictly increasing; universe never sorts input")
    if len(np.unique(seq)) != len(seq):
        raise ValueError("tick _seq must be unique")
    return {
        int(s): (pd.Timestamp(t), float(p))
        for s, t, p in ticks[["_seq", "datetime", "price"]].itertuples(index=False, name=None)
    }


def _price_probe_state(frame: pd.DataFrame, cfg: HighPriceProbeConfig) -> pd.DataFrame:
    """Compute price-only causal probe state directly from OHLC/ATR columns."""
    cfg.validate()
    high = pd.to_numeric(frame["high"], errors="coerce")
    low = pd.to_numeric(frame["low"], errors="coerce")
    close = pd.to_numeric(frame["close"], errors="coerce")
    atr = pd.to_numeric(frame["atr_n"], errors="coerce")
    lb = cfg.lookback_bars

    rolling_high = high.rolling(lb, min_periods=lb).max()
    rolling_low = low.rolling(lb, min_periods=lb).min()
    width = rolling_high - rolling_low
    upper_threshold = rolling_low + cfg.upper_zone_fraction * width
    close_location = (close - rolling_low).div(width.where(width.abs() > 0))
    high_distance_atr = (rolling_high - close).div(atr.where(atr.abs() > 0))
    prior_high = high.shift(1).rolling(lb, min_periods=lb).max()
    new_high = high >= prior_high
    upper_close = close >= upper_threshold
    near_high = high_distance_atr <= cfg.near_high_atr
    warm = rolling_high.notna() & rolling_low.notna() & atr.notna() & (width > 0)
    is_probe = warm & (upper_close | near_high)

    reason = []
    reason_class = []
    for i in range(len(frame)):
        if not bool(is_probe.iloc[i]):
            reason.append(None)
            reason_class.append(None)
            continue
        tags: list[str] = []
        if bool(new_high.iloc[i]):
            tags.append("NEW_ROLLING_HIGH")
        if bool(upper_close.iloc[i]):
            tags.append("UPPER_RANGE_CLOSE")
        if bool(near_high.iloc[i]):
            tags.append("NEAR_ROLLING_HIGH_ATR")
        reason.append("+".join(tags))
        if bool(upper_close.iloc[i]) and bool(near_high.iloc[i]):
            reason_class.append("BOTH")
        elif bool(upper_close.iloc[i]):
            reason_class.append("UPPER_80_RANGE_ONLY")
        else:
            reason_class.append("NEAR_HIGH_0_25ATR_ONLY")

    return pd.DataFrame({
        "probe_rolling_high": rolling_high,
        "probe_rolling_low": rolling_low,
        "probe_channel_width": width,
        "probe_upper_threshold": upper_threshold,
        "probe_close_location": close_location,
        "probe_high_distance_atr": high_distance_atr,
        "probe_new_rolling_high": new_high.fillna(False),
        "probe_upper_range_close": upper_close.fillna(False),
        "probe_near_high_atr": near_high.fillna(False),
        "probe_warm": warm,
        "is_high_price_probe": is_probe,
        "probe_reason": reason,
        "probe_reason_class": reason_class,
    })


def build_high_price_probe_universe(
    bar_features: pd.DataFrame,
    ticks: pd.DataFrame,
    *,
    dataset_id: str,
    contract: str,
    partition_id: str,
    config: HighPriceProbeConfig = HighPriceProbeConfig(),
    partition_end_reason: str = "PARTITION_END",
) -> UniverseResult:
    """Build raw high-price triggers and deterministic causal episodes.

    Caller passes one valid continuity partition (same contract/session/timeframe,
    no DATA_GAP_BLACKOUT). Rolling probe state may continue across trading days.
    If `trading_date` is present, episode clustering resets at each trading-day
    boundary while rolling selection state remains continuous.
    """
    config.validate()
    bars = _validate_bars(bar_features)
    lookup = _tick_lookup(ticks)
    state = _price_probe_state(bars, config)
    config_hash = config.config_hash

    active_id: str | None = None
    active_start_time: pd.Timestamp | None = None
    active_peak = np.nan
    active_trigger_count = 0
    active_episode_number = -1
    episode_acc: dict[str, dict] = {}
    trigger_rows: list[dict] = []
    prev_trading_date = None
    prev_end_seq: int | None = None
    prev_end_time: pd.Timestamp | None = None

    def close_active(end_seq: int, end_time: pd.Timestamp, reason: str) -> None:
        nonlocal active_id, active_start_time, active_peak, active_trigger_count
        if active_id is None:
            return
        episode_acc[active_id]["episode_end_seq"] = int(end_seq)
        episode_acc[active_id]["episode_end_time"] = end_time
        episode_acc[active_id]["episode_end_reason"] = reason
        active_id = None
        active_start_time = None
        active_peak = np.nan
        active_trigger_count = 0

    for i in range(len(bars)):
        row = bars.iloc[i]
        st = state.iloc[i]
        end_seq = int(row["bar_end_seq"])
        if end_seq not in lookup:
            raise ValueError(f"bar_end_seq {end_seq} not found in physical tick lookup")
        decision_time, decision_price = lookup[end_seq]
        close = float(row["close"])
        if not np.isclose(decision_price, close, rtol=0, atol=1e-12):
            raise ValueError(
                f"decision price mismatch at seq={end_seq}: tick={decision_price}, bar_close={close}"
            )
        atr = float(row["atr_n"]) if pd.notna(row["atr_n"]) else np.nan
        trading_date = str(row["trading_date"]) if "trading_date" in bars.columns else None

        # Episode dependence never crosses a trading-day boundary. This reset is
        # clustering-only; rolling probe state above remains continuous.
        if prev_trading_date is not None and trading_date is not None and trading_date != prev_trading_date:
            close_active(int(prev_end_seq), pd.Timestamp(prev_end_time), "TRADING_DAY_RESET")
        if trading_date is not None:
            prev_trading_date = trading_date

        # Causal timeout is evaluated before current trigger. The episode closes
        # at the frozen deadline itself; a sparse next bar must not inflate the
        # episode duration. The end seq remains the last physical seq known at or
        # before the timeout boundary.
        if active_id is not None and active_start_time is not None:
            elapsed = (decision_time - active_start_time).total_seconds()
            if elapsed >= config.max_episode_seconds:
                timeout_time = active_start_time + pd.Timedelta(seconds=config.max_episode_seconds)
                timeout_seq = int(prev_end_seq) if prev_end_seq is not None else end_seq
                close_active(timeout_seq, timeout_time, "MAX_EPISODE_SECONDS")

        if bool(st["is_high_price_probe"]):
            if active_id is None:
                active_episode_number += 1
                active_id = _stable_id(
                    UNIVERSE_SCHEMA_VERSION, dataset_id, contract, partition_id,
                    row["timeframe"], row["session"], end_seq, prefix="episode",
                )
                active_start_time = decision_time
                active_peak = float(row["high"])
                active_trigger_count = 0
                episode_acc[active_id] = {
                    "event_schema_version": EVENT_SCHEMA_VERSION,
                    "universe_version": UNIVERSE_VERSION,
                    "universe_schema_version": UNIVERSE_SCHEMA_VERSION,
                    "universe_config_hash": config_hash,
                    "dataset_id": dataset_id,
                    "contract": str(contract),
                    "partition_id": partition_id,
                    "timeframe": row["timeframe"],
                    "session": row["session"],
                    "episode_id": active_id,
                    "episode_number": active_episode_number,
                    "episode_start_seq": int(end_seq),
                    "episode_start_time": decision_time,
                    "episode_start_trading_date": trading_date,
                    "first_trigger_price": decision_price,
                    "last_trigger_seq": int(end_seq),
                    "last_trigger_time": decision_time,
                    "last_trigger_trading_date": trading_date,
                    "last_trigger_price": decision_price,
                    "trigger_count": 0,
                    "episode_peak_price": float(row["high"]),
                    "episode_end_seq": None,
                    "episode_end_time": None,
                    "episode_end_reason": None,
                }

            active_trigger_count += 1
            active_peak = max(float(active_peak), float(row["high"]))
            event_id = _stable_id(
                UNIVERSE_SCHEMA_VERSION, dataset_id, contract, partition_id,
                row["timeframe"], row["session"], end_seq, prefix="trigger",
            )
            feature_schema = row.get("feature_schema_version", None)
            snapshot = row.to_dict()
            meta = {
                "event_schema_version": EVENT_SCHEMA_VERSION,
                "universe_version": UNIVERSE_VERSION,
                "universe_schema_version": UNIVERSE_SCHEMA_VERSION,
                "universe_config_hash": config_hash,
                "feature_schema_version": feature_schema,
                "event_id": event_id,
                "episode_id": active_id,
                "episode_trigger_number": active_trigger_count,
                "dataset_id": dataset_id,
                "contract": str(contract),
                "partition_id": partition_id,
                "session": row["session"],
                "timeframe": row["timeframe"],
                "trigger_seq": end_seq,
                "trigger_time": decision_time,
                "trigger_price": decision_price,
                "trigger_reason": st["probe_reason"],
                "trigger_reason_class": st["probe_reason_class"],
                "rolling_high": float(st["probe_rolling_high"]),
                "rolling_low": float(st["probe_rolling_low"]),
                "atr": atr,
                "range_position": float(st["probe_close_location"]),
                "distance_high_atr": float(st["probe_high_distance_atr"]),
                "probe_rolling_high": float(st["probe_rolling_high"]),
                "probe_rolling_low": float(st["probe_rolling_low"]),
                "probe_channel_width": float(st["probe_channel_width"]),
                "probe_upper_threshold": float(st["probe_upper_threshold"]),
                "probe_close_location": float(st["probe_close_location"]),
                "probe_high_distance_atr": float(st["probe_high_distance_atr"]),
                "probe_new_rolling_high": bool(st["probe_new_rolling_high"]),
                "probe_upper_range_close": bool(st["probe_upper_range_close"]),
                "probe_near_high_atr": bool(st["probe_near_high_atr"]),
                "feature_snapshot": snapshot,
            }
            # Flat snapshot remains for columnar analysis; nested snapshot freezes
            # the event-store contract and makes the selection/feature boundary explicit.
            trigger_rows.append({**meta, **snapshot})
            ep = episode_acc[active_id]
            ep["last_trigger_seq"] = end_seq
            ep["last_trigger_time"] = decision_time
            ep["last_trigger_trading_date"] = trading_date
            ep["last_trigger_price"] = decision_price
            ep["trigger_count"] = active_trigger_count
            ep["episode_peak_price"] = active_peak

        # Causal high-region exit. Never deletes previous raw triggers.
        if active_id is not None:
            active_peak = max(float(active_peak), float(row["high"]))
            episode_acc[active_id]["episode_peak_price"] = active_peak
            if np.isfinite(atr) and (active_peak - close) >= config.episode_exit_atr * atr:
                close_active(end_seq, decision_time, "PRICE_EXIT_ATR")

        prev_end_seq = end_seq
        prev_end_time = decision_time

    if active_id is not None and len(bars):
        last_end_seq = int(bars.iloc[-1]["bar_end_seq"])
        last_time, _ = lookup[last_end_seq]
        close_active(last_end_seq, last_time, partition_end_reason)

    triggers = pd.DataFrame(trigger_rows)
    episodes = pd.DataFrame(list(episode_acc.values()))
    if len(triggers):
        if not triggers["event_id"].is_unique:
            raise AssertionError("event_id collision")
        if triggers["trigger_seq"].duplicated().any():
            raise AssertionError("duplicate raw trigger seq in one partition")
    if len(episodes) and not episodes["episode_id"].is_unique:
        raise AssertionError("episode_id collision")
    return UniverseResult(triggers=triggers, episodes=episodes)


def first_trigger_per_episode(triggers: pd.DataFrame) -> pd.DataFrame:
    """Return a research view without mutating/deleting the raw trigger store."""
    if triggers.empty:
        return triggers.copy()
    required = {"episode_id", "episode_trigger_number"}
    missing = required.difference(triggers.columns)
    if missing:
        raise ValueError(f"Missing trigger columns: {sorted(missing)}")
    return triggers.loc[triggers["episode_trigger_number"].eq(1)].reset_index(drop=True)


__all__ = [
    "EVENT_SCHEMA_VERSION",
    "UNIVERSE_VERSION",
    "UNIVERSE_SCHEMA_VERSION",
    "HighPriceProbeConfig",
    "UniverseResult",
    "build_high_price_probe_universe",
    "first_trigger_per_episode",
]
