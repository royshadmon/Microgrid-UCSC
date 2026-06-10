# `services/` — application code

Everything that runs above the streaming layer lives here. Three siblings:

```
services/
├── iems/                       # The IEMS application
├── remote-gui/                 # AnyLog Remote-GUI (upstream vendor clone)
└── remote-gui-iems-plugin/     # Our IEMS plug-in that grafts onto Remote-GUI
```

## `iems/` — the IEMS application

The four-domain IEMS pass from Adabi 2016, implemented as Python modules:

| Subfolder            | Domain                          | Responsibility                                                                 |
|----------------------|---------------------------------|--------------------------------------------------------------------------------|
| `load/`              | Load (Adabi 5.3)                | AnyLog reads, LLM4NILM disaggregation, anomaly checks, shedding ranking        |
| `inference/`         | Load (production NILM)          | ONNX-based per-panel disaggregation, the inference loop, additive rules        |
| `generation/`        | Generation (Adabi 5.2)          | Derived solar from grid/utility tie, PG&E TOU classification                   |
| `storage/`           | Storage (Adabi 5.4)             | Modeled battery SOC, dispatch policy                                           |
| `decision_support/`  | DSS (Adabi 5.2.1.3)             | Dollar-denominated recommendations, optimizer, AUTO/USER rule tree, shedding bridge |
| `prompts/`           | (data)                          | Per-panel prompt templates fed to LLM4NILM                                     |
| `models/`            | (data)                          | Trained ONNX models and `panel{N}_norm.json` configs                           |
| `training/`          | (offline)                       | PyTorch training pipeline that produces the ONNX models                        |
| `web/`               | UI                              | Standalone Node dashboard (`server.js`)                                        |
| `runner.py`          | Orchestrator                    | `run_iems_cycle()` — the single entry point the UIs call                       |
| `config.py`          | Constants                       | `CHANNELS`, `APPLIANCES`, `TOU_RATES`, `LOAD_PANELS`, `CRITICAL_APPLIANCES`    |
| `weather.py`         | External signal                 | Open-Meteo fetcher; injected as context into NILM and DSS                      |

The orchestrator is `runner.py`. Reading its top of file is the fastest way to understand how the modules compose:

```python
from iems.weather              import get_weather, get_weather_history
from iems.load.anylog_query    import fetch_all_panels, fetch_channel
from iems.load.disaggregator   import disaggregate_panel        # LLM4NILM path
from iems.inference.onnx_disaggregator import disaggregate_panel_onnx  # ONNX path (default)
from iems.load.mobile_load     import reconcile_vacuum
from iems.load.anomaly         import run_all_anomaly_checks
from iems.load.shedding        import rank_shed_candidates
from iems.generation.solar_forecast  import get_solar_forecast
from iems.generation.grid_analytics  import classify_now
from iems.storage.battery_model      import get_virtual_soc, update_virtual_soc
from iems.storage.dispatch           import get_dispatch_recommendation
from iems.decision_support.rule_tree    import tag_action, determine_flow_branch
from iems.decision_support.recommender  import build_recommendations
```

Each subfolder has its own `.md` file under `docs/services/iems/`.

## `remote-gui/` — upstream Remote-GUI clone

Vendored clone of AnyLog's Remote-GUI repo. Treated as read-only — no IEMS code goes in here. Bringing it up gives a Node back-end (`local-cli-backend`) and a React front-end (`local-cli-fe-full`) at port `3001`. See `docs/services/remote_gui/DOCUMENTATION.md` for the user-facing guide and `docs/services/remote_gui/FEATURE_CONFIG_README.md` for the feature flag system.

## `remote-gui-iems-plugin/` — our plug-in

The two files that turn Remote-GUI into an IEMS console:

```
services/remote-gui-iems-plugin/
├── backend/
│   └── iems_router.py     # FastAPI router mounted at /iems on local-cli-backend
└── frontend/
    ├── IemsPage.js        # React page registered under /dashboard/iems
    └── iems_api.js        # fetch helpers for the page
```

`iems_router.py` exposes `/iems/cycle`, `/iems/health`, `/iems/onnx/snapshot`, `/iems/onnx/models`, and `/iems/nilm/recent`. Internally each handler calls `iems.runner.run_iems_cycle()` or a helper from `iems.inference`. Kept in a separate folder (not inside `remote-gui/`) so the vendor clone stays clean — install copies these files into the right Remote-GUI subdirectories.
