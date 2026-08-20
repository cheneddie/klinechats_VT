from __future__ import annotations

import os

from . import fabio_api as base
from .v4_api_final import install
from .v4_training_api import install_training

app = install(base)
app = install_training(base)


def main():
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("FABIO_API_PORT", "8765")))


if __name__ == "__main__":
    main()
