"""POC absorption / reversal research primitives."""

from .bars import (
    BAR_RESOLUTIONS,
    BarAccumulator,
    CompletedBar,
    DevelopingPocSnapshot,
    build_bars,
    build_developing_poc,
    volume_profile_levels,
)
from .universe import (
    EVENT_SCHEMA_VERSION,
    UNIVERSE_VERSION,
    UNIVERSE_SCHEMA_VERSION,
    HighPriceProbeConfig,
    UniverseResult,
    build_high_price_probe_universe,
    first_trigger_per_episode,
)
from .outcomes import (
    OUTCOME_SCHEMA_VERSION,
    OUTCOME_CONTRACT_VERSION,
    FROZEN_EVENT_SCHEMA_VERSION,
    FROZEN_UNIVERSE_VERSION,
    FROZEN_UNIVERSE_SCHEMA_VERSION,
    FROZEN_UNIVERSE_CONFIG_HASH,
    FROZEN_FEATURE_SCHEMA_VERSION,
    FROZEN_HORIZONS,
    IMMUTABLE_EVENT_COLUMNS,
    JoinIntegrityReport,
    event_store_fingerprint,
    build_event_manifest,
    validate_probe_events,
    make_probe_outcome_skeleton,
    validate_probe_outcomes,
)
from .physical_outcomes import (
    PHYSICAL_PATH_SCHEMA_VERSION,
    HORIZON_SECONDS,
    PhysicalOutcomeDiagnostics,
    compute_physical_tick_outcomes,
    compute_physical_tick_outcomes_with_diagnostics,
)
from .balance_outcomes import (
    BALANCE_SCHEMA_VERSION,
    BALANCE_REFERENCE_SCHEMA_VERSION,
    BALANCE_METRICS,
    BALANCE_COUNT_METRICS,
    build_balance_reference_manifest,
    compute_balance_outcomes,
)

__all__ = [
    "BAR_RESOLUTIONS", "BarAccumulator", "CompletedBar", "DevelopingPocSnapshot",
    "build_bars", "build_developing_poc", "volume_profile_levels",
    "EVENT_SCHEMA_VERSION", "UNIVERSE_VERSION", "UNIVERSE_SCHEMA_VERSION",
    "HighPriceProbeConfig", "UniverseResult", "build_high_price_probe_universe", "first_trigger_per_episode",
    "OUTCOME_SCHEMA_VERSION", "OUTCOME_CONTRACT_VERSION", "FROZEN_EVENT_SCHEMA_VERSION",
    "FROZEN_UNIVERSE_VERSION", "FROZEN_UNIVERSE_SCHEMA_VERSION", "FROZEN_UNIVERSE_CONFIG_HASH",
    "FROZEN_FEATURE_SCHEMA_VERSION", "FROZEN_HORIZONS", "IMMUTABLE_EVENT_COLUMNS", "JoinIntegrityReport",
    "event_store_fingerprint", "build_event_manifest", "validate_probe_events", "make_probe_outcome_skeleton", "validate_probe_outcomes",
    "PHYSICAL_PATH_SCHEMA_VERSION", "HORIZON_SECONDS", "PhysicalOutcomeDiagnostics",
    "compute_physical_tick_outcomes", "compute_physical_tick_outcomes_with_diagnostics",
    "BALANCE_SCHEMA_VERSION", "BALANCE_REFERENCE_SCHEMA_VERSION", "BALANCE_METRICS", "BALANCE_COUNT_METRICS",
    "build_balance_reference_manifest", "compute_balance_outcomes",
]
