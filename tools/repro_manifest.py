from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = (
    "requirements-server.txt",
    "package.json",
    "pnpm-lock.yaml",
    "config/research/node_registry.yaml",
    "config/strategies/MR_BROAD_V3.json",
    "config/strategies/BO_RETEST_V2.json",
)


def sha256(path: Path) -> str | None:
    if not path.exists():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def git_commit() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except Exception:
        return None


def version(name: str) -> str | None:
    try:
        mod = __import__(name)
        return str(getattr(mod, "__version__", None) or getattr(mod, "VERSION", None))
    except Exception:
        return None


def manifest() -> dict:
    payload = {
        "schema": "KLINECHATS_REPRO_MANIFEST_V1",
        "git_commit": git_commit(),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "packages": {
            "fastapi": version("fastapi"),
            "pydantic": version("pydantic"),
            "pyarrow": version("pyarrow"),
            "pandas": version("pandas"),
            "numpy": version("numpy"),
        },
        "files": {name: sha256(ROOT / name) for name in FILES},
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    payload["manifest_sha256"] = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return payload


if __name__ == "__main__":
    output = manifest()
    target = ROOT / "repro-manifest.json"
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output, ensure_ascii=False, indent=2))
