from __future__ import annotations

from fastapi import HTTPException

from .v4_replay_final import TIMEFRAME_RULES, replay_trading_window


def install_training(base):
    """Add a replay endpoint that cuts raw physical ticks before bar aggregation."""
    app = base.app

    @app.get("/api/v4/training-replay/{event_id}")
    def training_replay(
        event_id: str,
        node_id: str,
        days_before: int = 1,
        timeframe: str = "1m",
        session: str = "full",
    ):
        if timeframe not in TIMEFRAME_RULES:
            raise HTTPException(400, f"unsupported timeframe: {timeframe}")
        if session not in {"full", "day"}:
            raise HTTPException(400, "session must be full or day")
        con = base.connect(base.DB)
        try:
            r = con.execute("SELECT * FROM events WHERE event_id=?", (event_id,)).fetchone()
            if not r:
                raise HTTPException(404, "case not found")
            event = base.event_row(r)
            meta = base.node_meta(con, event_id)
            if node_id not in meta:
                raise HTTPException(404, f"node not found in case: {node_id}")
            event["nodeMeta"] = meta
            cutoff = meta[node_id].get("decision_time") or meta[node_id].get("anchor_time")
            if not cutoff:
                raise HTTPException(409, f"node has no causal decision time: {node_id}")
        finally:
            con.close()
        payload = replay_trading_window(
            base.ROOT, event, meta, node_id=node_id,
            before=max(0, min(5, days_before)), after=0,
            timeframe=timeframe, session=session, cutoff_time=cutoff,
        )
        return {
            "case": event, **payload, "center_node": node_id,
            "visual_schema": 4, "decision_price_source": "persisted_physical_seq",
            "hide_future": True, "cutoff_basis": "physical ticks before timeframe aggregation",
        }

    return app
