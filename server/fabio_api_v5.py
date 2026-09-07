from __future__ import annotations

import os

# Importing V4 installs the validated V4 causal/replay/research routes first.
from . import fabio_api_v4 as v4
from .v5.api import EVENT_DB, install
from .v5.candidate_api import install_candidate_api
from .v5.compare_api import install_compare_api
from .v5.jobs_api import install_jobs_api
from .v5.monitor_api import install_monitor_api
from .v5.parity import install_parity
from .v5.production_deployment_api import install_production_deployment_api
from .v5.production_evidence_api import install_production_evidence_api
from .v5.replay_api import install_replay
from .v5.strategy_api import install_strategy_api

app = install(v4.base)
app = install_replay(app, event_db=EVENT_DB, data_root=v4.base.ROOT)
app = install_parity(app)
app = install_strategy_api(app, event_db=EVENT_DB, data_root=v4.base.ROOT)
app = install_compare_api(app, event_db=EVENT_DB)
app = install_monitor_api(app, event_db=EVENT_DB)
app = install_candidate_api(app, event_db=EVENT_DB, data_root=v4.base.ROOT)
app = install_production_evidence_api(app, event_db=EVENT_DB)
app = install_production_deployment_api(app, event_db=EVENT_DB)
app = install_jobs_api(app, event_db=EVENT_DB, data_root=v4.base.ROOT)


def main():
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("FABIO_API_PORT", "8765")))


if __name__ == "__main__":
    main()
