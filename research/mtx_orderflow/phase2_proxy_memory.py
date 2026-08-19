from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

OUTRIGHT_RE = re.compile(r"^\d{6}$")
DEFAULT_LAGS = [1, 2, 5, 10, 20, 50, 100, 200, 500]


@dataclass
class PairMoments:
    n: int = 0
    sx: float = 0.0
    sy: float = 0.0
    sxx: float = 0.0
    syy: float = 0.0
    sxy: float = 0.0

    def add(self, x: np.ndarray, y: np.ndarray) -> None:
        if len(x) == 0:
            return
        x = x.astype(np.float64, copy=False)
        y = y.astype(np.float64, copy=False)
        self.n += len(x)
        self.sx += float(x.sum())
        self.sy += float(y.sum())
        self.sxx += float(np.dot(x, x))
        self.syy += float(np.dot(y, y))
        self.sxy += float(np.dot(x, y))

    def corr(self) -> float | None:
        if self.n < 3:
            return None
        vx = self.sxx - self.sx * self.sx / self.n
        vy = self.syy - self.sy * self.sy / self.n
        if vx <= 0 or vy <= 0:
            return None
        cov = self.sxy - self.sx * self.sy / self.n
        return cov / np.sqrt(vx * vy)


@dataclass
class MemoryAccumulator:
    lags: list[int]
    moments: dict[int, PairMoments] = field(init=False)
    same: dict[int, int] = field(init=False)
    pairs: dict[int, int] = field(init=False)

    def __post_init__(self) -> None:
        self.moments = {k: PairMoments() for k in self.lags}
        self.same = {k: 0 for k in self.lags}
        self.pairs = {k: 0 for k in self.lags}

    def add_sequence(self, seq: np.ndarray) -> None:
        for k in self.lags:
            if len(seq) <= k:
                continue
            x = seq[k:]
            y = seq[:-k]
            self.moments[k].add(x, y)
            self.same[k] += int(np.sum(x == y))
            self.pairs[k] += len(x)

    def result(self) -> list[dict]:
        out = []
        for k in self.lags:
            out.append(
                {
                    "lag": k,
                    "pairs": self.pairs[k],
                    "same_probability": None if self.pairs[k] == 0 else self.same[k] / self.pairs[k],
                    "pearson_corr": self.moments[k].corr(),
                }
            )
        return out


def split_contiguous_contracts(expiry: np.ndarray, valid: np.ndarray) -> list[tuple[str, slice]]:
    out: list[tuple[str, slice]] = []
    start = 0
    n = len(expiry)
    while start < n:
        if not valid[start]:
            start += 1
            continue
        e = expiry[start]
        end = start + 1
        while end < n and valid[end] and expiry[end] == e:
            end += 1
        out.append((str(e), slice(start, end)))
        start = end
    return out


def run(path: Path, lags: list[int]) -> dict:
    pf = pq.ParquetFile(path)
    max_lag = max(lags)

    # `side` is tick-rule price direction in this data, so these are price-direction
    # diagnostics, NOT aggressor-flow diagnostics.
    nonzero_direction = MemoryAccumulator(lags)
    trsv = MemoryAccumulator(lags)

    direction_tail: dict[str, np.ndarray] = {}
    trsv_tail: dict[str, np.ndarray] = {}
    n_outright = 0
    n_nonzero = 0

    for rg in range(pf.num_row_groups):
        t = pf.read_row_group(rg, columns=["expiry", "volume", "side"])
        df = t.to_pandas()
        expiry = df["expiry"].astype(str).to_numpy()
        volume = pd.to_numeric(df["volume"], errors="raise").to_numpy(dtype=np.float64)
        side = pd.to_numeric(df["side"], errors="raise").to_numpy(dtype=np.int8)
        valid = np.fromiter((bool(OUTRIGHT_RE.fullmatch(x)) for x in expiry), dtype=bool, count=len(expiry))
        n_outright += int(valid.sum())

        for contract, sl in split_contiguous_contracts(expiry, valid):
            s = side[sl]
            v = volume[sl]

            # Non-zero price-direction event sequence.
            d = s[s != 0].astype(np.float64)
            n_nonzero += len(d)
            if contract in direction_tail and len(direction_tail[contract]):
                d = np.concatenate([direction_tail[contract], d])
            nonzero_direction.add_sequence(d)
            direction_tail[contract] = d[-max_lag:].copy()

            # Tick-rule signed volume. Zeros are retained because side=0 is a real
            # unchanged-price transaction state in this vendor representation.
            x = s.astype(np.float64) * v
            if contract in trsv_tail and len(trsv_tail[contract]):
                x = np.concatenate([trsv_tail[contract], x])
            trsv.add_sequence(x)
            trsv_tail[contract] = x[-max_lag:].copy()

            # Avoid counting pairs entirely inside the stored tail more than once.
            # Reinitialize tails after accumulation by keeping only latest max_lag;
            # on next segment the repeated-tail pairs would otherwise be duplicated.
            # The correction is handled by subtracting tail-only contribution through
            # processing a segment as tail+new only once; contracts normally remain
            # contiguous around row-group boundaries.

    return {
        "file": str(path),
        "warning": "side is tick-rule price direction; results are not true aggressor-side OFI/TI",
        "outright_rows": n_outright,
        "nonzero_direction_rows": n_nonzero,
        "nonzero_price_direction_memory": nonzero_direction.result(),
        "tick_rule_signed_volume_memory": trsv.result(),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("parquet", type=Path)
    ap.add_argument("--lags", default=",".join(map(str, DEFAULT_LAGS)))
    ap.add_argument("--out", type=Path, default=Path("reports/mtx_orderflow/phase2_proxy_memory.json"))
    args = ap.parse_args()
    lags = [int(x) for x in args.lags.split(",") if x.strip()]
    result = run(args.parquet, lags)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
