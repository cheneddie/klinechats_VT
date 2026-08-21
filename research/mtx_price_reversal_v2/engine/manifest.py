from __future__ import annotations

from pathlib import Path
import datetime as dt
import hashlib
import json
import os
import platform
import sys

import numpy as np
import pandas as pd


def file_sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(1<<20),b""):
            h.update(b)
    return h.hexdigest()


def source_descriptor(path: Path) -> dict:
    p=Path(path)
    return {"path":str(p),"size_bytes":p.stat().st_size,"sha256":file_sha256(p)}


def environment_descriptor() -> dict:
    try:
        import pyarrow
        pav=pyarrow.__version__
    except Exception:
        pav=None
    return {"python":sys.version.split()[0],"numpy":np.__version__,"pandas":pd.__version__,"pyarrow":pav,"os":platform.platform(),"timezone":os.environ.get("TZ")}


def write_manifest(path: Path, *, run_id: str, strategy_version: str, engine_version: str, git_sha: str, config_hash: str, source_files: list[Path], oos_watermark: str, random_seed: int = 7):
    d={"run_id":run_id,"strategy_version":strategy_version,"engine_version":engine_version,"git_sha":git_sha,"config_hash":config_hash,"sources":[source_descriptor(p) for p in source_files],"oos_watermark":oos_watermark,"random_seed":int(random_seed),"environment":environment_descriptor(),"started_at":dt.datetime.now(dt.timezone.utc).isoformat()}
    path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(d,indent=2),encoding="utf-8"); return d
