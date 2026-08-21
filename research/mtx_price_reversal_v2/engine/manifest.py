from __future__ import annotations
from pathlib import Path
import json, hashlib, datetime as dt

def file_sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1<<20),b""): h.update(b)
    return h.hexdigest()

def write_manifest(path: Path, *, run_id: str, strategy_version: str, engine_version: str, git_sha: str, config_hash: str, source_files: list[Path], oos_watermark: str):
    d={"run_id":run_id,"strategy_version":strategy_version,"engine_version":engine_version,"git_sha":git_sha,"config_hash":config_hash,"source_files":[str(p) for p in source_files],"source_hashes":[file_sha256(p) for p in source_files],"oos_watermark":oos_watermark,"started_at":dt.datetime.now(dt.timezone.utc).isoformat()}
    path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(d,indent=2),encoding="utf-8")
    return d
