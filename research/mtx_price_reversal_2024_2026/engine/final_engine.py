from __future__ import annotations

import argparse
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

OUTRIGHT_RE = re.compile(r"^\d{6}$")
FLOW_COLUMNS = ("trsv", "tick_aggr", "dir_count", "volume", "trades")


def _session_labels(dt: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Return (session_key, session_kind) for Taiwan MTX day/night sessions.

    Input datetimes are treated as exchange-local naive timestamps.
    Day: 08:45:00 <= time <= 13:45:00
    Night: 15:00:00 <= time OR time <= 05:00:00
    The after-midnight part is keyed to the previous calendar date.
    Rows outside these ranges receive NA and are excluded.
    """
    d = pd.to_datetime(dt)
    sec = d.dt.hour * 3600 + d.dt.minute * 60 + d.dt.second
    day = (sec >= 8 * 3600 + 45 * 60) & (sec <= 13 * 3600 + 45 * 60)
    night_pm = sec >= 15 * 3600
    night_am = sec <= 5 * 3600

    key = pd.Series(pd.NA, index=d.index, dtype="string")
    kind = pd.Series(pd.NA, index=d.index, dtype="string")
    date = d.dt.strftime("%Y-%m-%d")
    prev_date = (d - pd.Timedelta(days=1)).dt.strftime("%Y-%m-%d")
    key.loc[day] = date.loc[day] + "_D"
    kind.loc[day] = "D"
    key.loc[night_pm] = date.loc[night_pm] + "_N"
    kind.loc[night_pm] = "N"
    key.loc[night_am] = prev_date.loc[night_am] + "_N"
    kind.loc[night_am] = "N"
    return key, kind


def build_second_cache(parquet_path: Path, out_dir: Path) -> dict:
    """Build deterministic per-contract second bars from the raw parquet.

    Critical invariants:
      * preserve parquet row order; never sort equal-second raw trades
      * exclude spread/non-outright expiry strings
      * vendor volume is two-sided and is divided by two
      * tick-level aggressive proxy carries the last non-zero tick direction only
        within the same contract/session; it resets at a new session
      * row-group boundary seconds are consolidated by first_seq/last_seq
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    parts = out_dir / "_parts"
    parts.mkdir(exist_ok=True)

    pf = pq.ParquetFile(parquet_path)
    seq_offset = 0
    carry: dict[tuple[str, str], float] = {}
    audit = {
        "file": str(parquet_path),
        "rows": int(pf.metadata.num_rows),
        "row_groups": int(pf.num_row_groups),
        "outright_rows": 0,
        "spread_rows": 0,
        "outside_session_rows": 0,
        "bad_side_rows": 0,
        "non_integer_half_volume_rows": 0,
    }

    part_paths: list[Path] = []
    for rg in range(pf.num_row_groups):
        tab = pf.read_row_group(rg, columns=["datetime", "expiry", "price", "volume", "side"])
        df = tab.to_pandas()
        n_raw = len(df)
        df["seq"] = np.arange(seq_offset, seq_offset + n_raw, dtype=np.int64)
        seq_offset += n_raw

        expiry_s = df["expiry"].astype(str)
        outright = expiry_s.str.fullmatch(OUTRIGHT_RE.pattern, na=False)
        audit["outright_rows"] += int(outright.sum())
        audit["spread_rows"] += int((~outright).sum())
        df = df.loc[outright].copy()
        if df.empty:
            continue

        df["expiry"] = df["expiry"].astype(str)
        df["side"] = pd.to_numeric(df["side"], errors="coerce")
        df["price"] = pd.to_numeric(df["price"], errors="coerce")
        raw_vol = pd.to_numeric(df["volume"], errors="coerce")
        audit["bad_side_rows"] += int((~df["side"].isin([-1, 0, 1])).sum())
        half = raw_vol / 2.0
        audit["non_integer_half_volume_rows"] += int((np.abs(half - np.round(half)) > 1e-9).sum())
        df["volume"] = half

        key, kind = _session_labels(df["datetime"])
        df["session_key"] = key
        df["session_kind"] = kind
        outside = df["session_key"].isna()
        audit["outside_session_rows"] += int(outside.sum())
        df = df.loc[~outside].copy()
        if df.empty:
            continue

        # Tick-level aggressor proxy. Iterate only over contract/session groups in
        # this row group; row order inside every group remains raw parquet order.
        df["aggr_dir"] = np.nan
        for (exp, sk), idx in df.groupby(["expiry", "session_key"], sort=False).groups.items():
            loc = np.asarray(list(idx))
            s = df.loc[loc, "side"].to_numpy(dtype=np.float64)
            d = np.where(s != 0, s, np.nan)
            prior = carry.get((exp, sk), np.nan)
            if len(d) and np.isnan(d[0]) and not np.isnan(prior):
                d[0] = prior
            d = pd.Series(d).ffill().to_numpy(dtype=np.float64)
            # Before the first known direction, proxy contribution is zero.
            d0 = np.nan_to_num(d, nan=0.0)
            df.loc[loc, "aggr_dir"] = d0
            nz = d[~np.isnan(d)]
            if len(nz):
                carry[(exp, sk)] = float(nz[-1])

        df["trsv_trade"] = df["side"].to_numpy(dtype=float) * df["volume"].to_numpy(dtype=float)
        df["tick_aggr_trade"] = df["aggr_dir"].to_numpy(dtype=float) * df["volume"].to_numpy(dtype=float)
        df["ts"] = pd.to_datetime(df["datetime"]).astype("int64") // 1_000_000_000

        keys = ["expiry", "session_key", "session_kind", "ts"]
        g = df.groupby(keys, sort=False, observed=True)
        sec = g.agg(
            first_seq=("seq", "min"),
            last_seq=("seq", "max"),
            open=("price", "first"),
            high=("price", "max"),
            low=("price", "min"),
            close=("price", "last"),
            volume=("volume", "sum"),
            trsv=("trsv_trade", "sum"),
            dir_count=("side", "sum"),
            tick_aggr=("tick_aggr_trade", "sum"),
            trades=("seq", "size"),
        ).reset_index()
        p = parts / f"rg_{rg:03d}.csv"
        sec.to_csv(p, index=False)
        part_paths.append(p)

    # Deterministic consolidation. We process each expiry independently so an
    # interrupted/restarted run never appends duplicate seconds.
    expiries: set[str] = set()
    for p in part_paths:
        use = pd.read_csv(p, usecols=["expiry"])
        expiries.update(use["expiry"].astype(str).unique())

    contract_summary = []
    for exp in sorted(expiries):
        chunks = []
        for p in part_paths:
            x = pd.read_csv(p)
            x["expiry"] = x["expiry"].astype(str)
            x = x.loc[x["expiry"] == exp]
            if not x.empty:
                chunks.append(x)
        if not chunks:
            continue
        x = pd.concat(chunks, ignore_index=True)
        keys = ["expiry", "session_key", "session_kind", "ts"]
        # Seconds split by row-group boundaries are combined by sequence order.
        rows = []
        for _, z in x.groupby(keys, sort=False, observed=True):
            z = z.sort_values("first_seq", kind="stable")
            rows.append({
                "expiry": exp,
                "session_key": z["session_key"].iloc[0],
                "session_kind": z["session_kind"].iloc[0],
                "ts": int(z["ts"].iloc[0]),
                "first_seq": int(z["first_seq"].min()),
                "last_seq": int(z["last_seq"].max()),
                "open": float(z.loc[z["first_seq"].idxmin(), "open"]),
                "high": float(z["high"].max()),
                "low": float(z["low"].min()),
                "close": float(z.loc[z["last_seq"].idxmax(), "close"]),
                "volume": float(z["volume"].sum()),
                "trsv": float(z["trsv"].sum()),
                "dir_count": float(z["dir_count"].sum()),
                "tick_aggr": float(z["tick_aggr"].sum()),
                "trades": int(z["trades"].sum()),
            })
        c = pd.DataFrame(rows).sort_values(["ts", "first_seq"], kind="stable")
        c.to_csv(out_dir / f"{exp}.csv", index=False)
        contract_summary.append({"expiry": exp, "seconds": len(c), "sessions": c["session_key"].nunique()})

    pd.DataFrame(contract_summary).to_csv(out_dir / "contracts_summary.csv", index=False)
    (out_dir / "audit.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
    return audit


@dataclass(frozen=True)
class StrategySpec:
    signal: str
    lookback: int
    quantile: float
    holding: int
    latency_after_confirmation: int = 1
    cost_points: float = 2.0
    previous_contracts: int = 3


def _full_session(z: pd.DataFrame) -> pd.DataFrame:
    z = z.sort_values(["ts", "first_seq"], kind="stable").copy()
    idx = np.arange(int(z.ts.min()), int(z.ts.max()) + 1, dtype=np.int64)
    base = z.set_index("ts").reindex(idx)
    base.index.name = "ts"
    base["observed"] = base["first_seq"].notna()
    base["close"] = base["close"].ffill()
    for col in FLOW_COLUMNS:
        base[col] = base[col].fillna(0.0)
    # OHLC are deliberately left NaN on no-trade seconds. Execution can happen
    # only on observed seconds and path extrema use observed prints only.
    return base


def _signal_series(s: pd.DataFrame, spec: StrategySpec) -> pd.Series:
    if spec.signal == "price":
        return s["close"] - s["close"].shift(spec.lookback)
    if spec.signal not in {"trsv", "tick_aggr", "dir_count"}:
        raise ValueError(f"unsupported signal: {spec.signal}")
    return s[spec.signal].rolling(spec.lookback, min_periods=spec.lookback).sum()


def _contract_signal_distribution(contract_file: Path, spec: StrategySpec) -> np.ndarray:
    x = pd.read_csv(contract_file)
    vals = []
    for _, z in x.groupby("session_key", sort=False):
        s = _full_session(z)
        sig = _signal_series(s, spec).dropna().to_numpy(dtype=float)
        if len(sig):
            vals.append(sig)
    return np.concatenate(vals) if vals else np.array([], dtype=float)


def backtest_cache(cache_dir: Path, spec: StrategySpec, out_csv: Path | None = None) -> pd.DataFrame:
    files = {p.stem: p for p in cache_dir.glob("*.csv") if OUTRIGHT_RE.fullmatch(p.stem)}
    contracts = sorted(files)
    dist_cache: dict[str, np.ndarray] = {}
    trades: list[dict] = []
    global_position_until = -math.inf

    for i, exp in enumerate(contracts):
        if i < spec.previous_contracts:
            continue
        prev = contracts[i - spec.previous_contracts:i]
        train_vals = []
        for pexp in prev:
            if pexp not in dist_cache:
                dist_cache[pexp] = _contract_signal_distribution(files[pexp], spec)
            if len(dist_cache[pexp]):
                train_vals.append(dist_cache[pexp])
        if not train_vals:
            continue
        threshold = float(np.quantile(np.concatenate(train_vals), spec.quantile))

        x = pd.read_csv(files[exp])
        for sk, z in x.groupby("session_key", sort=False):
            s = _full_session(z)
            sig = _signal_series(s, spec)
            crossing = (sig <= threshold) & (sig.shift(1) > threshold)
            signal_times = sig.index[crossing.fillna(False)].to_numpy(dtype=np.int64)
            observed_times = s.index[s["observed"]].to_numpy(dtype=np.int64)
            if not len(observed_times):
                continue

            for signal_ts in signal_times:
                # The complete second t becomes knowable at the first print/time
                # in second t+1. An additional N-second latency therefore makes
                # the earliest fill t + 1 + N.
                earliest = int(signal_ts + 1 + spec.latency_after_confirmation)
                j = int(np.searchsorted(observed_times, earliest, side="left"))
                if j >= len(observed_times):
                    continue
                entry_ts = int(observed_times[j])
                if entry_ts <= global_position_until:
                    continue
                target_exit = entry_ts + spec.holding
                k = int(np.searchsorted(observed_times, target_exit, side="left"))
                if k >= len(observed_times):
                    # Never carry a fixed-time exit over the session boundary.
                    continue
                exit_ts = int(observed_times[k])
                entry = s.loc[entry_ts]
                exit_ = s.loc[exit_ts]
                entry_price = float(entry["open"])
                exit_price = float(exit_["open"])
                gross = exit_price - entry_price

                path = s.loc[(s.index >= entry_ts) & (s.index <= exit_ts) & s["observed"]]
                mfe = float(path["high"].max() - entry_price) if len(path) else np.nan
                mae = float(path["low"].min() - entry_price) if len(path) else np.nan
                trades.append({
                    "contract": exp,
                    "session_key": sk,
                    "session_kind": str(z["session_kind"].iloc[0]),
                    "signal_ts": int(signal_ts),
                    "signal_dt": pd.to_datetime(signal_ts, unit="s"),
                    "threshold": threshold,
                    "signal_value": float(sig.loc[signal_ts]),
                    "entry_ts": entry_ts,
                    "entry_dt": pd.to_datetime(entry_ts, unit="s"),
                    "entry_seq": int(entry["first_seq"]),
                    "entry_price": entry_price,
                    "exit_ts": exit_ts,
                    "exit_dt": pd.to_datetime(exit_ts, unit="s"),
                    "exit_seq": int(exit_["first_seq"]),
                    "exit_price": exit_price,
                    "gross": gross,
                    "net": gross - spec.cost_points,
                    "mfe": mfe,
                    "mae": mae,
                })
                global_position_until = exit_ts

    out = pd.DataFrame(trades)
    if out_csv is not None:
        out_csv.parent.mkdir(parents=True, exist_ok=True)
        out.to_csv(out_csv, index=False, encoding="utf-8-sig")
    return out


def summarize(trades: pd.DataFrame, costs: Iterable[float] = (0, 1, 2, 3)) -> dict:
    if trades.empty:
        return {"n": 0}
    g = trades["gross"].to_numpy(dtype=float)
    wins = g[g > 0].sum()
    losses = -g[g < 0].sum()
    result = {
        "n": int(len(trades)),
        "gross_mean": float(np.mean(g)),
        "median": float(np.median(g)),
        "win_rate": float(np.mean(g > 0)),
        "profit_factor_gross": None if losses == 0 else float(wins / losses),
        "positive_contracts": int((trades.groupby("contract")["gross"].mean() > 0).sum()),
        "contracts": int(trades["contract"].nunique()),
    }
    cut = int(np.ceil(len(g) * 0.01))
    if len(g) > cut:
        result["gross_mean_without_top1pct_winners"] = float(np.mean(np.sort(g)[:-cut]))
    eq = np.cumsum(g)
    result["max_drawdown_gross_points"] = float(np.min(eq - np.maximum.accumulate(eq)))
    for c in costs:
        result[f"net_mean_cost_{c:g}"] = float(np.mean(g - c))
    return result


def _parse_spec(text: str) -> StrategySpec:
    # signal,lookback,quantile,holding,latency,cost
    a = text.split(",")
    if len(a) not in (4, 5, 6):
        raise ValueError("spec must be signal,L,q,H[,latency[,cost]]")
    return StrategySpec(
        signal=a[0], lookback=int(a[1]), quantile=float(a[2]), holding=int(a[3]),
        latency_after_confirmation=int(a[4]) if len(a) >= 5 else 1,
        cost_points=float(a[5]) if len(a) >= 6 else 2.0,
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="MTX order-flow research final deterministic engine")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build-cache")
    b.add_argument("parquet", type=Path)
    b.add_argument("out", type=Path)
    r = sub.add_parser("backtest")
    r.add_argument("cache", type=Path)
    r.add_argument("--spec", required=True, help="signal,L,q,H[,latency[,cost]]")
    r.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    if args.cmd == "build-cache":
        print(json.dumps(build_second_cache(args.parquet, args.out), indent=2))
    else:
        spec = _parse_spec(args.spec)
        t = backtest_cache(args.cache, spec, args.out)
        print(json.dumps(summarize(t), indent=2))


if __name__ == "__main__":
    main()
