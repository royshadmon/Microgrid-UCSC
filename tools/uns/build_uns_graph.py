#!/usr/bin/env python3
"""
Build the UNS knowledge graph for the Los Gatos microgrid and upload it through
the remote-gui UNS plugin.

Every asset in the deployment becomes an `object` policy carrying a stable id
and, where it maps to real data, its linking fields (dbms, table, column, and a
where clause). Every node in the namespace tree becomes a `uns` policy carrying
that object_id plus its parent, which is what the UNS and UNS Knowledge Graph
pages traverse.

The inventory is read live from the IEMS engine rather than hard-coded, so the
graph reflects what the models and the meter actually expose today.

Usage:
  build_uns_graph.py --dry-run          write the JSON, publish nothing
  build_uns_graph.py                    write the JSON and upload it
"""

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request

GUI = os.environ.get("GUI_URL", "http://localhost:8000")
IEMS = os.environ.get("IEMS_URL", "http://localhost:8009")
CONN = os.environ.get("UNS_CONN", "host.docker.internal:32149")
SOURCE_NODE = os.environ.get("UNS_SOURCE_NODE", "operator1-bkup")
OUT_DIR = os.environ.get("OUT_DIR", os.path.expanduser("~/uns-graph"))

DBMS = "customers"
T_ENERGY = "energy_readings"
T_SOLAR = "solar_data"
T_NILM = "nilm_disaggregated"
T_ANOM = "anomalies"
T_KAFKA = "egauge_kafka"

ROOT = "losgatos"

# The six channels that are real power feeds; everything else the meter reports
# is instrumentation (volts, amps, frequency).
POWER_CHANNELS = [
    ("Panel1 (HVAC)", "panel1_hvac", "HVAC sub-panel, heat pump and pool/solar pumps"),
    ("Panel2 (H2O)", "panel2_h2o", "Water sub-panel, water heater, sprinklers, bath"),
    ("Panel3 (Kitchen)", "panel3_kitchen", "Kitchen sub-panel, refrigeration and small appliances"),
    ("Shop", "shop", "Shop feed, dryer, washer and pressure pump"),
    ("Grid Power", "grid_power", "Utility tie, negative when exporting"),
    ("Generac Power", "generac_power", "Standby generator feed"),
]

SOLAR_COLUMNS = [
    ("pv_power", "PV production, watts"),
    ("battery_power", "Battery flow, positive charging"),
    ("battery_soc", "Battery state of charge, percent"),
    ("grid_power", "Grid flow as the inverter sees it"),
    ("load_power", "House load as the inverter sees it"),
    ("device_mode", "Inverter operating mode"),
]

NODES = [
    ("master", "master", "AnyLog metadata node, holds the ledger", "32048/32049"),
    ("operator1", "operator1", "AnyLog operator, Kafka consumer and Postgres writer", "32148/32149"),
]

SOURCES = [
    ("eGauge 18646", "egauge18646", "Revenue-grade meter, 16 channels, one second cadence",
     DBMS, T_KAFKA, []),
    ("Solar Assistant", "solar_assistant", "Raspberry Pi bridge, inverter and battery over MQTT",
     DBMS, T_SOLAR, []),
    ("Home Assistant", "home_assistant", "Sensi thermostat, the only control path in the system",
     None, None, []),
]


def oid(namespace):
    return hashlib.md5(("iems-object::" + namespace).encode()).hexdigest()


def fetch(url):
    with urllib.request.urlopen(url, timeout=90) as resp:
        return json.loads(resp.read())


def post(url, payload, timeout=900):
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


class Graph(object):
    """Collects objects and namespace assignments in parent-before-child order."""

    def __init__(self):
        self.objects = []
        self.assignments = []
        self.seen = set()

    def add(self, namespace, display, description, level,
            dbms=None, table=None, columns=None, where=None, metadata=None):
        if namespace in self.seen:
            return oid(namespace)
        self.seen.add(namespace)

        object_id = oid(namespace)
        segments = namespace.split("/")
        parent_namespace = "/".join(segments[:-1])
        path_segment = segments[-1]

        obj = {
            "id": object_id,
            "name": display,
            "description": description,
            "object_type": "object",
            "uns_level": level,
            "metadata": dict(metadata or {}),
        }
        if dbms and table:
            obj["dbms"] = dbms
            obj["table"] = table
            if columns:
                obj["columns"] = list(columns)
            if where:
                obj["where_conditions"] = where
        self.objects.append(obj)

        self.assignments.append({
            "object_id": object_id,
            "name": display,
            "path_segment": path_segment,
            "namespace": namespace,
            "parent_namespace": parent_namespace,
            "description": description,
            "uns_level": level,
            "source_node": SOURCE_NODE,
            "metadata": dict(metadata or {}),
        })
        return object_id


def eq(column, value):
    return [{"column": column, "operator": "=", "value": value,
             "value_type": "character varying", "joiner": "AND"}]


def build():
    channels = fetch(IEMS + "/iems/channels").get("channels", [])
    models = fetch(IEMS + "/iems/onnx/models").get("models", [])
    catalog = fetch(IEMS + "/iems/appliances").get("appliances", {})

    power_names = set(name for name, _, _ in POWER_CHANNELS)
    instrumentation = [c for c in channels if c not in power_names]

    g = Graph()

    g.add(ROOT, "Los Gatos Microgrid",
          "Residential microgrid, eGauge and solar telemetry into AnyLog with local NILM",
          "group", metadata={"site": "Los Gatos, CA", "tz": "America/Los_Angeles",
                             "lat": 37.2358, "lon": -121.9624})

    # ── electrical ──────────────────────────────────────────────────────────
    g.add(ROOT + "/electrical", "Electrical",
          "Metered feeds from the eGauge 18646", "group",
          metadata={"meter": "eGauge18646", "channels": len(channels)})

    for name, slug, desc in POWER_CHANNELS:
        g.add("%s/electrical/%s" % (ROOT, slug), name, desc, "tag",
              dbms=DBMS, table=T_ENERGY, columns=["ts", "w", "kwh"],
              where=eq("nm", name),
              metadata={"channel": name, "asset_class": "power_feed", "unit": "W"})

    g.add(ROOT + "/electrical/instrumentation", "Instrumentation",
          "Voltage, current and frequency channels", "group",
          metadata={"asset_class": "instrumentation"})
    for name in instrumentation:
        slug = name.lower().replace(" ", "_")
        g.add("%s/electrical/instrumentation/%s" % (ROOT, slug), name,
              "eGauge instrumentation channel %s" % name, "tag",
              dbms=DBMS, table=T_ENERGY, columns=["ts", "w"],
              where=eq("nm", name),
              metadata={"channel": name, "asset_class": "instrumentation"})

    # ── solar and storage ───────────────────────────────────────────────────
    g.add(ROOT + "/solar", "Solar and Storage",
          "Inverter and battery telemetry from Solar Assistant over MQTT", "group",
          metadata={"source": "Solar Assistant", "capacity_kwh": 13.5, "soc_floor_pct": 10})
    for column, desc in SOLAR_COLUMNS:
        g.add("%s/solar/%s" % (ROOT, column), column, desc, "tag",
              dbms=DBMS, table=T_SOLAR, columns=["ts", column],
              metadata={"asset_class": "solar", "column": column})

    # ── appliances, grouped by the panel they are inferred from ─────────────
    g.add(ROOT + "/appliances", "Appliances",
          "Loads inferred from panel-level power by the local ONNX NILM models", "group",
          metadata={"method": "NILM", "engine": "onnxruntime"})

    slug_by_panel = dict((name, slug) for name, slug, _ in POWER_CHANNELS)
    for model in models:
        panel = model.get("panel")
        slug = slug_by_panel.get(panel, str(panel).lower().replace(" ", "_"))
        base = "%s/appliances/%s" % (ROOT, slug)
        g.add(base, panel, "Appliances disaggregated from %s" % panel, "group",
              metadata={"panel": panel, "model": model.get("model"),
                        "heads": len(model.get("heads", []))})
        thresholds = model.get("thresholds", {})
        for head in model.get("heads", []):
            meta = {"appliance": head, "panel": panel, "model": model.get("model"),
                    "asset_class": "appliance",
                    "threshold": thresholds.get(head)}
            known = catalog.get(head) or catalog.get(head.replace("_", "")) or {}
            if isinstance(known, dict):
                for key in ("laxity", "shed_priority", "on_threshold_w",
                            "avg_on_duration_min", "typical_cycle_min",
                            "user_visible_label", "deferrable", "critical",
                            "weather_coupled", "anomaly_target", "mobile"):
                    if known.get(key) is not None:
                        meta[key] = known[key]
                rng = known.get("power_range_w")
                if isinstance(rng, list) and len(rng) == 2:
                    meta["power_min_w"], meta["power_max_w"] = rng[0], rng[1]
            label = meta.get("user_visible_label") or head.replace("_", " ").title()
            g.add("%s/%s" % (base, head), label,
                  "%s inferred from %s" % (label, panel), "tag",
                  dbms=DBMS, table=T_NILM,
                  columns=["ts", "state", "confidence", "avg_w"],
                  where=eq("circuit", panel) + [
                      {"column": "appliance", "operator": "=", "value": head,
                       "value_type": "character varying", "joiner": "AND"}],
                  metadata=dict((k, v) for k, v in meta.items() if v is not None))

    # ── models ──────────────────────────────────────────────────────────────
    g.add(ROOT + "/models", "NILM Models",
          "ONNX disaggregation models running locally in the inference container", "group",
          metadata={"count": len(models), "runtime": "onnxruntime"})
    for model in models:
        g.add("%s/models/%s" % (ROOT, model.get("model")), model.get("model"),
              "Disaggregates %s into %d appliances"
              % (model.get("panel"), len(model.get("heads", []))), "tag",
              dbms=DBMS, table=T_NILM, columns=["ts", "appliance", "state", "confidence"],
              where=eq("circuit", model.get("panel")),
              metadata={"panel": model.get("panel"), "window": model.get("window"),
                        "n_features": len(model.get("features", [])),
                        "n_outputs": model.get("n_outputs"),
                        "asset_class": "model"})

    # ── anomalies ───────────────────────────────────────────────────────────
    g.add(ROOT + "/anomalies", "Anomalies",
          "Detector output, one row per sustained condition", "tag",
          dbms=DBMS, table=T_ANOM,
          columns=["ts", "atype", "severity", "entity", "value", "status"],
          metadata={"asset_class": "event_stream"})

    # ── data sources ────────────────────────────────────────────────────────
    g.add(ROOT + "/sources", "Data Sources",
          "Where the telemetry enters the system", "group")
    for name, slug, desc, dbms, table, cols in SOURCES:
        g.add("%s/sources/%s" % (ROOT, slug), name, desc, "tag",
              dbms=dbms, table=table, columns=cols,
              metadata={"asset_class": "data_source"})

    # ── infrastructure ──────────────────────────────────────────────────────
    g.add(ROOT + "/infrastructure", "Infrastructure",
          "AnyLog nodes serving this site", "group")
    for name, slug, desc, ports in NODES:
        g.add("%s/infrastructure/%s" % (ROOT, slug), name, desc, "tag",
              metadata={"asset_class": "anylog_node", "ports": ports})

    return g


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    g = build()

    if not os.path.isdir(OUT_DIR):
        os.makedirs(OUT_DIR)

    objects_payload = {"conn": CONN, "publish": True, "objects": g.objects}
    assignments_payload = {"conn": CONN, "publish": True, "assignments": g.assignments}

    with open(os.path.join(OUT_DIR, "uns_objects.json"), "w") as fh:
        json.dump(objects_payload, fh, indent=2)
    with open(os.path.join(OUT_DIR, "uns_assignments.json"), "w") as fh:
        json.dump(assignments_payload, fh, indent=2)

    print("built %d objects and %d namespace assignments"
          % (len(g.objects), len(g.assignments)))
    print("  %s/uns_objects.json" % OUT_DIR)
    print("  %s/uns_assignments.json" % OUT_DIR)
    depths = {}
    for a in g.assignments:
        depths[a["namespace"].count("/")] = depths.get(a["namespace"].count("/"), 0) + 1
    print("  depth histogram: %s" % sorted(depths.items()))

    if args.dry_run:
        print("\ndry run, nothing published")
        return

    print("\nPOST %s/uns/draft-objects/save" % GUI)
    status, body = post(GUI + "/uns/draft-objects/save", objects_payload)
    results = body.get("publish_results", []) if isinstance(body, dict) else []
    failed = [r for r in results if not r.get("success")]
    skipped = [r for r in results if r.get("skipped")]
    print("  HTTP %s  success=%s  published=%d  skipped=%d  failed=%d"
          % (status, body.get("success"), len(results) - len(skipped) - len(failed),
             len(skipped), len(failed)))
    for r in failed[:10]:
        print("    FAILED %s: %s" % (r.get("name"), r.get("error")))
    if failed:
        print("  aborting before assignments; objects must exist first")
        sys.exit(1)

    # One request per depth level, shallowest first.
    #
    # save_draft_path_assignments caches the id of each policy it publishes and
    # reuses it as the parent for deeper nodes in the SAME request.  It reads
    # that id out of the blockchain-insert acknowledgement, which on this build
    # is the string "true" -- so every child in a mixed-depth request inherits
    # parent="true" and is rejected.  Batching by depth means a parent is never
    # in the same request as its children, so the code falls through to its
    # ledger lookup, which resolves correctly.
    print("\nPOST %s/uns/draft-path-assignments/save  (batched by depth)" % GUI)
    by_depth = {}
    for a in g.assignments:
        by_depth.setdefault(a["namespace"].count("/"), []).append(a)

    total_failed = 0
    for depth in sorted(by_depth):
        batch = by_depth[depth]
        status, body = post(GUI + "/uns/draft-path-assignments/save",
                            {"conn": CONN, "publish": True, "assignments": batch})
        results = body.get("publish_results", []) if isinstance(body, dict) else []
        failed = [r for r in results if not r.get("success")]
        skipped = [r for r in results if r.get("skipped")]
        total_failed += len(failed)
        print("  depth %d: %2d nodes  HTTP %s  published=%d skipped=%d failed=%d"
              % (depth, len(batch), status,
                 len(results) - len(skipped) - len(failed), len(skipped), len(failed)))
        for r in failed[:8]:
            print("      FAILED %s (%s): %s"
                  % (r.get("name"), r.get("namespace"), r.get("error")))
        if not results:
            print("      unexpected response: %s" % str(body)[:300])

    print("\n%d assignment failures overall" % total_failed)


if __name__ == "__main__":
    main()
