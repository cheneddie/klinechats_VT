from __future__ import annotations

import os

from . import fabio_api as base
from . import v4_release_engine as _release_engine  # applies tested V4.1 release semantics
from .v4_api_final import install
from .v4_training_api import install_training
from .v4_research_api import install_research_release

app = install(base)
app = install_training(base)
app = install_research_release(base)


def main():
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("FABIO_API_PORT", "8765")))


if __name__ == "__main__":
    main()
