#!/usr/bin/env python3
"""
Register the IEMS plugin in the remote-gui backend config, at image build time.

This is deliberately the smallest possible change to the shipped GUI: one key
added to feature_config.json, and nothing else.

`feature_config_loader.is_plugin_enabled` returns False for any plugin *absent*
from the "plugins" object, and loader.py skips it. The failure is silent -- the
router imports fine, /plugins/order still lists the plugin, and every route
404s -- so this one key is not optional.

`plugin_order.json` is left untouched on purpose. loader.py appends plugins
that are not named there after the ones that are, and the frontend sidebar does
the same, so IEMS lands with the other unlisted plugins without reordering or
relabelling anything upstream ships.
"""

import json
import os
import sys

BACKEND = "/app/CLI/local-cli-backend"
FEATURE_CONFIG = os.path.join(BACKEND, "feature_config.json")
PLUGIN_ORDER = os.path.join(BACKEND, "plugins", "plugin_order.json")

NAME = "iems"
DESCRIPTION = ("IEMS Plugin - live microgrid dashboard, NILM disaggregation "
               "and DSS recommendations from the local IEMS engine")


def main():
    with open(FEATURE_CONFIG) as fh:
        original = fh.read()
    config = json.loads(original)
    before = json.loads(original)

    plugins = config.setdefault("plugins", {})
    plugins[NAME] = {"enabled": True, "description": DESCRIPTION}

    # Nothing else in this file may move.
    if before.get("features") != config.get("features"):
        sys.exit("enable_iems: features section changed, refusing to write")
    lost = set(before.get("plugins", {})) - set(config["plugins"])
    if lost:
        sys.exit("enable_iems: dropped plugins %s" % ", ".join(sorted(lost)))
    for key, value in before.get("plugins", {}).items():
        if config["plugins"][key] != value:
            sys.exit("enable_iems: modified existing plugin entry %r" % key)

    with open(FEATURE_CONFIG, "w") as fh:
        json.dump(config, fh, indent=2)
        fh.write("\n")

    order_before = open(PLUGIN_ORDER).read()

    print("enabled plugin '%s' in feature_config.json" % NAME)
    print("  plugins now      : %s" % ", ".join(sorted(config["plugins"])))
    print("  plugin_order.json: untouched (%d bytes, sha of first line %r)"
          % (len(order_before), order_before.split("\n")[0]))


if __name__ == "__main__":
    main()
