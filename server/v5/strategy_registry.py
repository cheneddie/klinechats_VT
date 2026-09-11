from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

STRATEGY_SCHEMA_VERSION = 1

MR_CHAIN = (
    "AUC_ATTEMPT",
    "MR_REJECTION",
    "MR_CLEAR_RECLAIM",
    "MR_RECLAIM_LEG",
    "MR_LVN",
    "MR_PULLBACK",
    "MR_ENTRY",
)
BO_CHAIN = (
    "AUC_ATTEMPT",
    "BO_DISPLACEMENT",
    "BO_ACCEPTANCE",
    "BO_IMPULSE_LEG",
    "BO_LVN",
    "BO_PULLBACK",
    "BO_RESPONSE",
    "BO_ENTRY",
)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _get_path(data: dict[str, Any], path: str, default: Any = None) -> Any:
    cur: Any = data
    for key in path.split("."):
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def _set_path(data: dict[str, Any], path: str, value: Any) -> None:
    keys = path.split(".")
    cur = data
    for key in keys[:-1]:
        nxt = cur.get(key)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[key] = nxt
        cur = nxt
    cur[keys[-1]] = value


@dataclass(frozen=True)
class ParameterSpec:
    path: str
    kind: str
    default: Any
    scope: str
    requires_rescan: bool
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    values: tuple[Any, ...] = ()
    description: str = ""

    def validate(self, value: Any) -> Any:
        if self.kind == "bool":
            if not isinstance(value, bool):
                raise ValueError(f"{self.path} requires bool")
            return value
        if self.kind == "int":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{self.path} requires int")
            value = int(value)
        elif self.kind == "float":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{self.path} requires float")
            value = float(value)
        elif self.kind == "enum":
            if value not in self.values:
                raise ValueError(f"{self.path} must be one of {list(self.values)}")
            return value
        elif self.kind == "str":
            if not isinstance(value, str):
                raise ValueError(f"{self.path} requires str")
            return value
        else:
            raise ValueError(f"unsupported parameter kind: {self.kind}")
        if self.minimum is not None and value < self.minimum:
            raise ValueError(f"{self.path} below minimum {self.minimum}")
        if self.maximum is not None and value > self.maximum:
            raise ValueError(f"{self.path} above maximum {self.maximum}")
        return value


@dataclass(frozen=True)
class StrategyDefinition:
    strategy_id: str
    version: str
    name: str
    family: str
    description: str
    schema_version: int
    node_chain: tuple[str, ...]
    parameters: tuple[ParameterSpec, ...]
    definition: dict[str, Any]
    source_path: str | None
    definition_hash: str

    @property
    def strategy_key(self) -> str:
        return f"{self.strategy_id}@{self.version}"

    def parameter_map(self) -> dict[str, ParameterSpec]:
        return {p.path: p for p in self.parameters}

    def validate_overrides(self, overrides: dict[str, Any] | None) -> dict[str, Any]:
        overrides = dict(overrides or {})
        specs = self.parameter_map()
        unknown = sorted(set(overrides) - set(specs))
        if unknown:
            raise ValueError(f"unknown strategy parameters: {unknown}")
        return {path: specs[path].validate(value) for path, value in overrides.items()}

    def rescan_parameters(self, overrides: dict[str, Any] | None) -> list[str]:
        clean = self.validate_overrides(overrides)
        specs = self.parameter_map()
        changed = []
        for path, value in clean.items():
            if value != specs[path].default and specs[path].requires_rescan:
                changed.append(path)
        return sorted(changed)

    def resolved_config(self, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
        out = json.loads(json.dumps(self.definition))
        for path, value in self.validate_overrides(overrides).items():
            _set_path(out, path, value)
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy_id": self.strategy_id,
            "version": self.version,
            "strategy_key": self.strategy_key,
            "name": self.name,
            "family": self.family,
            "description": self.description,
            "schema_version": self.schema_version,
            "node_chain": list(self.node_chain),
            "parameters": [asdict(p) for p in self.parameters],
            "definition": self.definition,
            "source_path": self.source_path,
            "definition_hash": self.definition_hash,
        }


def _legacy_identity(raw: dict[str, Any]) -> tuple[str, str, str]:
    name = str(raw.get("name") or "UNNAMED_STRATEGY")
    m = re.match(r"^(.*)_V(\d+)$", name)
    if m:
        strategy_id = m.group(1)
        version = f"V{m.group(2)}"
    else:
        strategy_id = name
        version = str(raw.get("version") or "V1")
    family = str(raw.get("family") or ("MR" if name.startswith("MR_") else "BO" if name.startswith("BO_") else "GENERIC")).upper()
    return strategy_id, version, family


def _parameter(path: str, raw: dict[str, Any], kind: str, scope: str, requires_rescan: bool,
               minimum: float | None = None, maximum: float | None = None, step: float | None = None,
               values: Iterable[Any] = (), description: str = "") -> ParameterSpec | None:
    default = _get_path(raw, path, None)
    if default is None:
        return None
    return ParameterSpec(path, kind, default, scope, requires_rescan, minimum, maximum, step, tuple(values), description)


def _legacy_specs(raw: dict[str, Any], family: str) -> tuple[ParameterSpec, ...]:
    specs: list[ParameterSpec | None] = [
        _parameter("value_area", raw, "float", "detector", True, 0.60, 0.95, 0.01, description="Previous-value profile coverage."),
        _parameter("auction.excursion_pct_value_width", raw, "float", "detector", True, 0.0, 1.0, 0.01),
        _parameter("auction.min_points", raw, "float", "detector", True, 0.0, 100.0, 1.0),
        _parameter("lvn.depth", raw, "float", "detector", True, 0.0, 1.0, 0.05),
        _parameter("lvn.tolerance_points", raw, "float", "detector", True, 0.0, 20.0, 0.5),
        _parameter("stop.points", raw, "float", "execution", False, 0.5, 100.0, 0.5),
        _parameter("target.r", raw, "float", "execution", False, 0.1, 10.0, 0.05),
        _parameter("time_stop_seconds", raw, "int", "execution", False, 1, 7200, 15),
    ]
    if family == "MR":
        specs.extend([
            _parameter("rejection.clear_reclaim_pct_value_width", raw, "float", "detector", True, 0.0, 1.0, 0.01),
            _parameter("rejection.max_seconds", raw, "int", "detector", True, 1, 1800, 5),
            _parameter("leg.turn_confirmation_points", raw, "float", "detector", True, 0.5, 100.0, 0.5),
            _parameter("entry.first_valid_pullback_only", raw, "bool", "gate", True),
        ])
    elif family == "BO":
        for path in (
            "acceptance.outside_ratio",
            "acceptance.displacement_pct_value_width",
            "acceptance.window_seconds",
            "response.points",
        ):
            default = _get_path(raw, path, None)
            if default is not None:
                kind = "int" if path.endswith("seconds") else "float"
                specs.append(ParameterSpec(path, kind, default, "detector", True))
    return tuple(x for x in specs if x is not None)


def _explicit_specs(raw: dict[str, Any]) -> tuple[ParameterSpec, ...] | None:
    items = raw.get("parameter_schema")
    if not isinstance(items, list):
        return None
    out: list[ParameterSpec] = []
    for item in items:
        if not isinstance(item, dict) or not item.get("path"):
            raise ValueError("parameter_schema items require path")
        path = str(item["path"])
        default = item.get("default", _get_path(raw, path, None))
        values = tuple(item.get("values") or ())
        out.append(ParameterSpec(
            path=path,
            kind=str(item.get("kind") or "float"),
            default=default,
            scope=str(item.get("scope") or "gate"),
            requires_rescan=bool(item.get("requires_rescan", True)),
            minimum=item.get("minimum"),
            maximum=item.get("maximum"),
            step=item.get("step"),
            values=values,
            description=str(item.get("description") or ""),
        ))
    return tuple(out)


def normalize_strategy(raw: dict[str, Any], *, source_path: str | None = None) -> StrategyDefinition:
    if not isinstance(raw, dict):
        raise ValueError("strategy definition must be an object")
    strategy_id, version, family = _legacy_identity(raw)
    schema_version = int(raw.get("schema_version") or STRATEGY_SCHEMA_VERSION)
    if schema_version > STRATEGY_SCHEMA_VERSION:
        raise ValueError(f"unsupported strategy schema version {schema_version}")
    chain = tuple(raw.get("node_chain") or (MR_CHAIN if family == "MR" else BO_CHAIN if family == "BO" else ()))
    specs = _explicit_specs(raw) or _legacy_specs(raw, family)
    definition = json.loads(json.dumps(raw))
    definition.setdefault("schema_version", schema_version)
    definition.setdefault("strategy_id", strategy_id)
    definition.setdefault("version", version)
    definition.setdefault("family", family)
    definition.setdefault("node_chain", list(chain))
    return StrategyDefinition(
        strategy_id=strategy_id,
        version=version,
        name=str(raw.get("name") or strategy_id),
        family=family,
        description=str(raw.get("description") or ""),
        schema_version=schema_version,
        node_chain=chain,
        parameters=specs,
        definition=definition,
        source_path=source_path,
        definition_hash=content_hash(definition),
    )


def load_strategy(path: str | Path) -> StrategyDefinition:
    p = Path(path)
    raw = json.loads(p.read_text(encoding="utf-8"))
    return normalize_strategy(raw, source_path=str(p))


def load_strategy_directory(path: str | Path) -> list[StrategyDefinition]:
    root = Path(path)
    if not root.exists():
        return []
    out = [load_strategy(p) for p in sorted(root.glob("*.json"))]
    keys = [x.strategy_key for x in out]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate strategy key in registry")
    return out


def find_strategy(strategies: Iterable[StrategyDefinition], key_or_name: str) -> StrategyDefinition:
    matches = [s for s in strategies if key_or_name in {s.strategy_key, s.name, s.strategy_id}]
    if len(matches) != 1:
        raise KeyError(f"strategy not uniquely found: {key_or_name}")
    return matches[0]
