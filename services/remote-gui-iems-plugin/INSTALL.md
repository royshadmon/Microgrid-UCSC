# IEMS plugin for AnyLog Remote-GUI

This directory is an overlay against the upstream Remote-GUI repo
(`AnyLog-co/Remote-GUI`). Remote-GUI is not vendored in Microgrid-UCSC
because it is third-party code with its own release cadence. Apply
this overlay to a fresh checkout to enable the IEMS feature.

## Layout

```
CLI/local-cli-backend/plugins/iems/   FastAPI router and bootstrap
CLI/local-cli-fe-full/src/plugins/iems/   React page + API client
upstream-patches/                     small diffs against upstream files
```

`upstream-patches/UPSTREAM_REF.txt` records the upstream commit the
patches were captured against.

## Apply

```
git clone https://github.com/AnyLog-co/Remote-GUI.git
cd Remote-GUI
# 1. Drop new plugin files in
cp -R /path/to/Microgrid-UCSC/services/remote-gui-iems-plugin/CLI/* CLI/
# 2. Apply upstream patches (registers plugin, adds scipy)
git apply /path/to/Microgrid-UCSC/services/remote-gui-iems-plugin/upstream-patches/*.patch
# 3. Install python deps and run as usual
pip install -r requirements.txt
```

The patches register the plugin in `feature_config.json`, prepend it
in `plugin_order.json`, and add `scipy` to `requirements.txt`. If
upstream has moved past the captured base, expect to resolve trivial
context drift in those three files by hand.

The plugin expects the IEMS backend at `http://127.0.0.1:8000` (set
via `IEMS_API_BASE` if different). Start the IEMS service from the
Microgrid-UCSC repo before loading the page.
