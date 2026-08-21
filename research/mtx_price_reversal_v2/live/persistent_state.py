from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
import hashlib
import json
import sqlite3


@dataclass(frozen=True)
class StrategyState:
    strategy_version: str
    active_contract: str | None = None
    position_qty: int = 0
    entry_order_id: str | None = None
    stop_order_id: str | None = None
    last_processed_seq: int | None = None
    last_signal_id: str | None = None


def deterministic_signal_id(strategy_version: str, contract: str, signal_seq: int) -> str:
    raw=f"{strategy_version}|{contract}|{int(signal_seq)}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:32]


class SQLiteStateStore:
    """Small transactional state store for restart/idempotency safety."""

    def __init__(self, path: Path):
        self.path=Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(self.path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS state (k TEXT PRIMARY KEY, v TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS signals (signal_id TEXT PRIMARY KEY, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
        self.db.commit()

    def save_state(self, s: StrategyState) -> None:
        payload=json.dumps(asdict(s),sort_keys=True)
        with self.db:
            self.db.execute("INSERT INTO state(k,v) VALUES('strategy',?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",(payload,))

    def load_state(self) -> StrategyState | None:
        row=self.db.execute("SELECT v FROM state WHERE k='strategy'").fetchone()
        return None if row is None else StrategyState(**json.loads(row[0]))

    def claim_signal(self, signal_id: str) -> bool:
        try:
            with self.db:
                self.db.execute("INSERT INTO signals(signal_id) VALUES(?)",(signal_id,))
            return True
        except sqlite3.IntegrityError:
            return False

    def close(self):
        self.db.close()
