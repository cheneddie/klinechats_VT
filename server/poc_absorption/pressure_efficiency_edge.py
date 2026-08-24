"""M6 Dev9 Pressure × Efficiency research helpers.

This module is intentionally descriptive: it builds the predeclared 2x2 map and
cluster-aware diagnostics. It does not define a strategy, optimize thresholds,
or claim true aggressor-side order flow from the tick-direction proxy.
"""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd

DEV9_SCHEMA_VERSION = "POC_M6_PRESSURE_EFFICIENCY_V1"
DEV9_VERDICT = "M6_DEV9_ORIGINAL_BUYING_ABSORPTION_INTERACTION_NOT_SUPPORTED"
FEATURE_CLASSIFICATION = {
    "buy_direction_pressure": "REDUNDANT_OR_CONTRADICTORY_FOR_SHORT_DIRECTION",
    "raw_pressure_magnitude": "ACTIVITY_REGIME_ONLY",
    "price_efficiency": "STATE_PERSISTENCE_NOT_DIRECTIONAL_EDGE",
    "pressure_x_efficiency": "NOT_BUY_SIDE_SPECIFIC_ACTIVITY_X_EFFICIENCY_INTERACTION",
}
CELL_ORDER = ("A", "B", "C", "D")

@dataclass(frozen=True)
class EdgeMapConfig:
    pressure_col: str = "high_zone_positive_volume_q80"
    efficiency_col: str = "impact_per_1000_positive_volume"
    session_col: str = "session"
    split_quantile: float = 0.50

    def validate(self) -> None:
        if not 0 < self.split_quantile < 1:
            raise ValueError("split_quantile must be in (0,1)")


def session_percentile_rank(frame: pd.DataFrame, column: str, session_col: str = "session") -> pd.Series:
    if column not in frame or session_col not in frame:
        raise ValueError(f"missing rank columns: {column}, {session_col}")
    return frame.groupby(session_col, sort=False)[column].rank(pct=True, method="average")


def assign_pressure_efficiency_cells(frame: pd.DataFrame, config: EdgeMapConfig = EdgeMapConfig()) -> pd.DataFrame:
    config.validate()
    missing = {config.pressure_col, config.efficiency_col, config.session_col} - set(frame.columns)
    if missing:
        raise ValueError(f"edge map missing columns: {sorted(missing)}")
    out = frame.copy()
    pr = session_percentile_rank(out, config.pressure_col, config.session_col)
    er = session_percentile_rank(out, config.efficiency_col, config.session_col)
    high_p = pr >= config.split_quantile
    high_e = er >= config.split_quantile
    out["pressure_rank"] = pr
    out["efficiency_rank"] = er
    out["edge_cell"] = np.select(
        [~high_p & high_e, ~high_p & ~high_e, high_p & high_e, high_p & ~high_e],
        ["A", "B", "C", "D"], default="?",
    )
    return out


def cell_outcome_means(frame: pd.DataFrame, outcomes: list[str]) -> pd.DataFrame:
    if "edge_cell" not in frame:
        raise ValueError("assign cells before computing cell means")
    missing = set(outcomes) - set(frame.columns)
    if missing:
        raise ValueError(f"missing outcomes: {sorted(missing)}")
    return frame.groupby("edge_cell", sort=False)[outcomes].mean().reindex(CELL_ORDER)


def d_minus_b(cell_means: pd.DataFrame) -> pd.Series:
    if "B" not in cell_means.index or "D" not in cell_means.index:
        raise ValueError("B and D cells are required")
    return cell_means.loc["D"] - cell_means.loc["B"]


def cluster_ols(y, X, clusters) -> tuple[np.ndarray, np.ndarray]:
    y = np.asarray(y, float); X = np.asarray(X, float); clusters = np.asarray(clusters)
    mask = np.isfinite(y) & np.all(np.isfinite(X), axis=1)
    y, X, clusters = y[mask], X[mask], clusters[mask]
    if len(y) <= X.shape[1] or len(np.unique(clusters)) < 2:
        raise ValueError("insufficient clustered observations")
    beta = np.linalg.lstsq(X, y, rcond=None)[0]
    resid = y - X @ beta
    bread = np.linalg.pinv(X.T @ X)
    meat = np.zeros((X.shape[1], X.shape[1]), float)
    for g in np.unique(clusters):
        score = X[clusters == g].T @ resid[clusters == g]
        meat += np.outer(score, score)
    cov = bread @ meat @ bread
    return beta, np.sqrt(np.maximum(np.diag(cov), 0.0))


def classify_dev9(*, directional_pressure_supported: bool, activity_adjusted_pressure_supported: bool, buy_side_specific: bool, efficiency_directional_edge: bool) -> dict:
    """Freeze Dev9 functional classification; no outcome-derived threshold search."""
    if directional_pressure_supported or activity_adjusted_pressure_supported or buy_side_specific or efficiency_directional_edge:
        return {"verdict": "DEV9_REQUIRES_REVIEW", "classification": None}
    return {"verdict": DEV9_VERDICT, "classification": FEATURE_CLASSIFICATION.copy()}

__all__ = [
    "DEV9_SCHEMA_VERSION", "DEV9_VERDICT", "FEATURE_CLASSIFICATION", "CELL_ORDER",
    "EdgeMapConfig", "session_percentile_rank", "assign_pressure_efficiency_cells",
    "cell_outcome_means", "d_minus_b", "cluster_ols", "classify_dev9",
]
