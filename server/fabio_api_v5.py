from __future__ import annotations

import os

# Importing V4 installs the validated V4 causal/replay/research routes first.
from . import fabio_api_v4 as v4
from .v5.api import EVENT_DB, install
from .v5.parity import install_parity
from .v5.replay_api import install_replay

app = install(v4.base)
app = install_replay(app, event_db=EVENT_DB, data_root=v4.base.ROOT)
app = install_parity(app)


def main():
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("FABIO_API_PORT", "8765")))


if __name__ == "__main__":
    main()
