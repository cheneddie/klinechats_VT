from __future__ import annotations

"""Release adapter for the V4.1 scanner.

The relaxed BO terminal opportunity is anchored at Pullback touch for unbiased
reverse-audit of the Response gate. The *strict* BO strategy, however, may only
enter after Response is causally confirmed.

The supplied MTX vendor volume is two-sided. Fabio research semantics therefore
use normalized ``volume / 2``. The release wrapper performs that normalization
before event construction while preserving immutable physical `_seq` and row
order. Contract selection may still rank raw volume because uniform /2 scaling
cannot change the ranking; its audit table persists both raw and normalized
values.
"""

from . import v4_final_engine as core

_ORIGINAL_FINISH = core._finish_event
_ORIGINAL_SCAN = core.scan_day_v4_final


def _release_finish(e, chain, cfg, strict_entry):
    if e.get("strategy") == "BO":
        nodes = e.get("nodes") or {}
        response = nodes.get("BO_RESPONSE") or {}
        entry_node = nodes.get("BO_ENTRY") or {}
        lvn = e.get("lvn")
        if response.get("answer") and response.get("decision_price") is not None and lvn is not None:
            ep = float(response["decision_price"])
            direction = e.get("direction")
            stop = float(lvn - cfg.bo_stop_points if direction == "long" else lvn + cfg.bo_stop_points)
            risk = abs(ep - stop)
            width = max(float(e.get("value_width") or 0), 1e-9)
            boundary = float(e.get("vah") if direction == "long" else e.get("val"))
            extension = abs(ep - boundary) / width
            outside = ep > float(e.get("vah")) if direction == "long" else ep < float(e.get("val"))
            quality = risk <= cfg.bo_entry_max_risk_points and extension <= cfg.bo_entry_max_extension_vw and outside
            entry_node.update(
                answer=bool(quality),
                seq=response.get("seq"), time=response.get("time"), decision_price=ep,
                anchor_seq=response.get("anchor_seq") or response.get("seq"),
                anchor_time=response.get("anchor_time") or response.get("time"),
                anchor_price=ep,
                reason_code="ENTRY_QUALITY_PASS" if quality else "ENTRY_EXTENSION_OR_RISK_FAIL_AFTER_RESPONSE",
                metrics={"risk_points":risk,"extension_vw":extension,"max_extension_vw":cfg.bo_entry_max_extension_vw,"outside_old_value":outside,"entry_basis":"response_confirmation"},
                schema_version=4,
            )
            nodes["BO_ENTRY"] = entry_node
            target = ep + cfg.bo_target_r*risk if direction == "long" else ep - cfg.bo_target_r*risk
            strict_entry = {"seq":response.get("seq"),"time":response.get("time"),"price":ep,"stop":stop,"target":target} if quality else None
        else:
            entry_node.update(
                answer=False,
                seq=response.get("seq"), time=response.get("time"), decision_price=response.get("decision_price"),
                anchor_seq=response.get("anchor_seq") or response.get("seq"), anchor_time=response.get("anchor_time") or response.get("time"),
                anchor_price=response.get("anchor_price") or response.get("decision_price"),
                reason_code="NO_RESPONSE_NO_STRICT_ENTRY", metrics={"entry_basis":"response_confirmation"}, schema_version=4,
            )
            nodes["BO_ENTRY"] = entry_node
            strict_entry = None
    return _ORIGINAL_FINISH(e, chain, cfg, strict_entry)


# scan_day_v4_final resolves _finish_event from its module globals at runtime.
core._finish_event = _release_finish

ScanConfigV4Final = core.ScanConfigV4Final
migrate_v4_schema = core.migrate_v4_schema
write_events_v4 = core.write_events_v4
_best_valley_leg = core._best_valley_leg


def scan_day_v4_final(g, prior, cfg, file, day, contract):
    """Release scan with source-defined volume normalization and no reordering."""
    work = g.copy()
    if "volume" in work.columns:
        work["volume"] = work["volume"].astype(float) / 2.0
    events = _ORIGINAL_SCAN(work, prior, cfg, file, day, contract)
    for event in events:
        event.setdefault("features", {})["volume_normalization"] = "vendor_volume_div_2"
    return events


__all__ = ["ScanConfigV4Final","scan_day_v4_final","migrate_v4_schema","write_events_v4","_best_valley_leg"]
