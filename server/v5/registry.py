from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


ALLOWED_ROLES = {"STATE", "EDGE_GATE", "EXECUTION_GATE"}
ALLOWED_CLASSIFICATIONS = {
    "CORE", "OPTIONAL", "STATE", "REDUNDANT", "HARMFUL", "REGIME_DEPENDENT", "INSUFFICIENT"
}
EVIDENCE_LEVELS = {
    "L0": "Concept",
    "L1": "Synthetic tested",
    "L2": "Single-year diagnostic",
    "L3": "Multi-year consistent",
    "L4": "Frozen OOS",
    "L5": "Cost / latency robust",
    "L6": "Live parity / paper",
}
TRAINING_STATUSES = {"MACHINE_VERIFIED", "HUMAN_REVIEWED", "DISPUTED", "GOLD_CONSENSUS", "EXCLUDED"}


@dataclass(frozen=True)
class NodeDefinition:
    node_id: str
    branch: str
    role: str
    parent: str | None
    label: dict[str, str]
    yes_reason_codes: tuple[str, ...]
    no_reason_codes: tuple[str, ...]
    visual: dict[str, Any]
    training_eligible: bool
    production_eligible: bool

    @property
    def label_zh(self) -> str:
        return self.label.get("zh_TW") or self.node_id


class NodeRegistry:
    def __init__(self, nodes: dict[str, NodeDefinition], schema_version: int = 1):
        self.nodes = nodes
        self.schema_version = int(schema_version)
        self._validate()

    def _validate(self) -> None:
        if not self.nodes:
            raise ValueError("node registry is empty")
        for node_id, node in self.nodes.items():
            if node.node_id != node_id:
                raise ValueError(f"node id mismatch: {node_id} != {node.node_id}")
            if node.role not in ALLOWED_ROLES:
                raise ValueError(f"invalid role for {node_id}: {node.role}")
            if node.parent and node.parent not in self.nodes:
                raise ValueError(f"missing parent for {node_id}: {node.parent}")
            overlap = set(node.yes_reason_codes) & set(node.no_reason_codes)
            if overlap:
                raise ValueError(f"reason code appears in YES and NO for {node_id}: {sorted(overlap)}")

    def get(self, node_id: str) -> NodeDefinition:
        try:
            return self.nodes[node_id]
        except KeyError as exc:
            raise KeyError(f"unknown node: {node_id}") from exc

    def items(self) -> Iterable[tuple[str, NodeDefinition]]:
        return self.nodes.items()

    def branch_nodes(self, branch: str, *, training_only: bool = False) -> list[NodeDefinition]:
        out = []
        for node in self.nodes.values():
            if node.branch not in {branch, "COMMON"}:
                continue
            if training_only and not node.training_eligible:
                continue
            out.append(node)
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "nodes": {
                node_id: {
                    "branch": n.branch,
                    "role": n.role,
                    "parent": n.parent,
                    "label": n.label,
                    "yes_reason_codes": list(n.yes_reason_codes),
                    "no_reason_codes": list(n.no_reason_codes),
                    "visual": n.visual,
                    "training_eligible": n.training_eligible,
                    "production_eligible": n.production_eligible,
                }
                for node_id, n in self.nodes.items()
            },
        }


def _load_payload(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    # node_registry.yaml is deliberately JSON-compatible YAML so the core has no
    # hard dependency on PyYAML.  If teams later use richer YAML syntax, PyYAML
    # is supported when installed.
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore
        except Exception as exc:  # pragma: no cover - optional dependency path
            raise RuntimeError("registry is not JSON-compatible YAML and PyYAML is unavailable") from exc
        payload = yaml.safe_load(text)
    if not isinstance(payload, dict):
        raise ValueError("registry root must be a mapping")
    return payload


def load_registry(path: str | Path) -> NodeRegistry:
    p = Path(path)
    payload = _load_payload(p)
    raw_nodes = payload.get("nodes")
    if not isinstance(raw_nodes, dict):
        raise ValueError("registry.nodes must be a mapping")
    nodes: dict[str, NodeDefinition] = {}
    for node_id, raw in raw_nodes.items():
        if not isinstance(raw, dict):
            raise ValueError(f"node {node_id} must be a mapping")
        nodes[node_id] = NodeDefinition(
            node_id=node_id,
            branch=str(raw.get("branch") or "COMMON").upper(),
            role=str(raw.get("role") or "STATE").upper(),
            parent=raw.get("parent"),
            label=dict(raw.get("label") or {}),
            yes_reason_codes=tuple(str(x) for x in (raw.get("yes_reason_codes") or [])),
            no_reason_codes=tuple(str(x) for x in (raw.get("no_reason_codes") or [])),
            visual=dict(raw.get("visual") or {}),
            training_eligible=bool(raw.get("training_eligible", False)),
            production_eligible=bool(raw.get("production_eligible", False)),
        )
    return NodeRegistry(nodes, schema_version=int(payload.get("schema_version") or 1))
