from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class ExecutionModel:
    execution_model_id: str = "PHYSICAL_MARKET"
    version: str = "V1"
    fill_timing: str = "SIGNAL"
    entry_slippage_points: float = 0.0
    exit_slippage_points: float = 0.0
    commission_points_per_side: float = 0.0
    latency_ms: int = 0
    price_column: str = "price"
    seq_column: str = "_seq"
    time_column: str = "dt"

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "ExecutionModel":
        value = dict(value or {})
        allowed = set(cls.__dataclass_fields__)
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise ValueError(f"unknown execution model fields: {unknown}")
        model = cls(**value)
        model.validate()
        return model

    def validate(self) -> None:
        if self.fill_timing not in {"SIGNAL", "NEXT_TICK"}:
            raise ValueError("fill_timing must be SIGNAL or NEXT_TICK")
        if self.entry_slippage_points < 0 or self.exit_slippage_points < 0:
            raise ValueError("slippage cannot be negative")
        if self.commission_points_per_side < 0:
            raise ValueError("commission cannot be negative")
        if self.latency_ms < 0:
            raise ValueError("latency cannot be negative")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return pd.Timestamp(value).isoformat()
    except Exception:
        return str(value)


def _ensure_path(path: pd.DataFrame, model: ExecutionModel) -> pd.DataFrame:
    required = {model.seq_column, model.price_column}
    missing = required - set(path.columns)
    if missing:
        raise ValueError(f"physical path missing columns: {sorted(missing)}")
    out = path.copy()
    if model.time_column in out.columns:
        out[model.time_column] = pd.to_datetime(out[model.time_column])
    # Never sort here. The caller must supply raw physical row order.
    seq = out[model.seq_column].astype("int64")
    if len(seq) > 1 and not bool((seq.diff().fillna(1) > 0).all()):
        raise ValueError("physical path _seq must be strictly increasing in source order")
    return out


def _adverse_fill(raw_price: float, direction: str, points: float, *, entry: bool) -> float:
    if points <= 0:
        return float(raw_price)
    if entry:
        return float(raw_price + points) if direction == "long" else float(raw_price - points)
    return float(raw_price - points) if direction == "long" else float(raw_price + points)


def _directional_points(direction: str, entry: float, exit_price: float) -> float:
    return float(exit_price - entry) if direction == "long" else float(entry - exit_price)


def _forced_flat_deadline(entry_time: Any, force_flat_time: str | None) -> pd.Timestamp | None:
    if entry_time is None or not force_flat_time:
        return None
    parts = str(force_flat_time).split(":")
    if len(parts) not in {2, 3}:
        raise ValueError("force_flat_time must be HH:MM or HH:MM:SS")
    try:
        hour, minute = int(parts[0]), int(parts[1])
        second = int(parts[2]) if len(parts) == 3 else 0
    except Exception as exc:
        raise ValueError("force_flat_time must be HH:MM or HH:MM:SS") from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59):
        raise ValueError("force_flat_time has invalid clock components")
    entry = pd.Timestamp(entry_time)
    deadline = entry.normalize() + pd.Timedelta(hours=hour, minutes=minute, seconds=second)
    if deadline <= entry:
        deadline += pd.Timedelta(days=1)
    return deadline


def simulate_physical_trade(
    path: pd.DataFrame,
    *,
    direction: str,
    signal_seq: int,
    signal_price: float,
    stop_price: float,
    target_price: float,
    model: ExecutionModel | dict[str, Any] | None = None,
    time_stop_seconds: int | None = None,
    force_flat_time: str | None = None,
) -> dict[str, Any]:
    """Simulate one trade in raw physical order.

    The signal row is not future information. First-hit ordering begins strictly after
    the filled entry row. No sorting is performed. Same-second ties resolve by raw
    physical `_seq`, preserving the project's causal truth boundary.

    `force_flat_time` is an explicit recurring local clock boundary. The engine does
    not infer exchange sessions: the caller must provide the intended clock when a
    portfolio/session policy requires forced flattening.
    """
    if direction not in {"long", "short"}:
        raise ValueError("direction must be long or short")
    model = model if isinstance(model, ExecutionModel) else ExecutionModel.from_dict(model)
    model.validate()
    frame = _ensure_path(path, model)
    seq_col, price_col, time_col = model.seq_column, model.price_column, model.time_column

    candidate = frame.loc[frame[seq_col].astype("int64") >= int(signal_seq)]
    if candidate.empty:
        raise ValueError("signal_seq not present in physical path")

    signal_rows = candidate.loc[candidate[seq_col].astype("int64") == int(signal_seq)]
    if model.fill_timing == "SIGNAL":
        if signal_rows.empty:
            raise ValueError("SIGNAL fill requires exact signal_seq row")
        fill_row = signal_rows.iloc[0]
    else:
        after = frame.loc[frame[seq_col].astype("int64") > int(signal_seq)]
        if after.empty:
            raise ValueError("NEXT_TICK fill has no row after signal")
        fill_row = after.iloc[0]

    if model.latency_ms and time_col in frame.columns:
        base_time = pd.Timestamp(fill_row[time_col])
        eligible_time = base_time + pd.Timedelta(milliseconds=model.latency_ms)
        after_latency = frame.loc[
            (frame[seq_col].astype("int64") >= int(fill_row[seq_col]))
            & (frame[time_col] >= eligible_time)
        ]
        if after_latency.empty:
            raise ValueError("latency pushes fill beyond available path")
        fill_row = after_latency.iloc[0]

    entry_seq = int(fill_row[seq_col])
    raw_entry_price = float(fill_row[price_col])
    # signal_price is persisted for audit; raw physical fill price governs execution.
    entry_price = _adverse_fill(raw_entry_price, direction, model.entry_slippage_points, entry=True)
    risk_points = abs(float(entry_price) - float(stop_price))
    if risk_points <= 0:
        raise ValueError("stop must imply positive risk from actual fill")

    future = frame.loc[frame[seq_col].astype("int64") > entry_seq]
    if future.empty:
        raise ValueError("no physical rows after entry")

    entry_time = fill_row[time_col] if time_col in frame.columns else None
    deadline = None
    if time_stop_seconds is not None and time_stop_seconds > 0 and entry_time is not None:
        deadline = pd.Timestamp(entry_time) + pd.Timedelta(seconds=int(time_stop_seconds))
    force_deadline = _forced_flat_deadline(entry_time, force_flat_time)

    mfe = 0.0
    mae = 0.0
    exit_row = None
    exit_reason = None
    target_price = float(target_price)
    stop_price = float(stop_price)

    for _, row in future.iterrows():
        raw = float(row[price_col])
        favorable = raw - entry_price if direction == "long" else entry_price - raw
        adverse = entry_price - raw if direction == "long" else raw - entry_price
        mfe = max(mfe, favorable)
        mae = max(mae, adverse)

        stop_hit = raw <= stop_price if direction == "long" else raw >= stop_price
        target_hit = raw >= target_price if direction == "long" else raw <= target_price
        if stop_hit:
            exit_row = row
            exit_reason = "STOP"
            break
        if target_hit:
            exit_row = row
            exit_reason = "TARGET"
            break
        if deadline is not None and time_col in frame.columns and pd.Timestamp(row[time_col]) >= deadline:
            exit_row = row
            exit_reason = "TIME"
            break
        if force_deadline is not None and time_col in frame.columns and pd.Timestamp(row[time_col]) >= force_deadline:
            exit_row = row
            exit_reason = "FORCED_FLAT"
            break

    if exit_row is None:
        exit_row = future.iloc[-1]
        exit_reason = "END_OF_DATA"

    raw_exit_price = float(exit_row[price_col])
    exit_price = _adverse_fill(raw_exit_price, direction, model.exit_slippage_points, entry=False)
    gross_points = _directional_points(direction, entry_price, exit_price)
    commission_points = float(model.commission_points_per_side) * 2.0
    net_points = gross_points - commission_points
    gross_r = gross_points / risk_points
    net_r = net_points / risk_points
    mfe_r = mfe / risk_points
    mae_r = mae / risk_points
    capture_ratio = gross_points / mfe if gross_points > 0 and mfe > 0 else 0.0

    exit_time = exit_row[time_col] if time_col in frame.columns else None
    holding_seconds = None
    if entry_time is not None and exit_time is not None:
        holding_seconds = max(0.0, float((pd.Timestamp(exit_time) - pd.Timestamp(entry_time)).total_seconds()))

    return {
        "signal_seq": int(signal_seq),
        "signal_price": float(signal_price),
        "entry_seq": entry_seq,
        "entry_time": _iso(entry_time),
        "entry_price": float(entry_price),
        "raw_entry_price": raw_entry_price,
        "stop_price": stop_price,
        "target_price": target_price,
        "exit_seq": int(exit_row[seq_col]),
        "exit_time": _iso(exit_time),
        "exit_price": float(exit_price),
        "raw_exit_price": raw_exit_price,
        "exit_reason": exit_reason,
        "risk_points": risk_points,
        "mfe_points": float(mfe),
        "mae_points": float(mae),
        "mfe_r": float(mfe_r),
        "mae_r": float(mae_r),
        "gross_points": float(gross_points),
        "net_points": float(net_points),
        "gross_r": float(gross_r),
        "net_r": float(net_r),
        "capture_ratio": float(capture_ratio),
        "commission_points": commission_points,
        "slippage_points": float(model.entry_slippage_points + model.exit_slippage_points),
        "latency_ms": int(model.latency_ms),
        "holding_seconds": holding_seconds,
        "force_flat_time": force_flat_time,
        "execution_model": model.to_dict(),
    }
