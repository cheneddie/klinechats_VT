from __future__ import annotations
import re
OUTRIGHT_RE = re.compile(r"^\d{6}$")

def is_outright(expiry: object) -> bool:
    return bool(OUTRIGHT_RE.fullmatch(str(expiry)))
