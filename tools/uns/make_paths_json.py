#!/usr/bin/env python3
"""
Collapse the UNS graph into ONE file for /uns/draft-paths/save.

That endpoint takes a list of root-to-leaf paths and generates BOTH the object
policies and the namespace policies from them, so a single upload builds the
whole tree and the whole graph. Shared prefixes are deduplicated by the plugin:
`losgatos/electrical` appears at the head of six paths and is published once.

Reads the two-file payloads this repo already produces and re-expresses them,
so the two forms cannot drift.

Usage: make_paths_json.py <objects.json> <assignments.json> <out.json>
"""

import json
import sys


def main():
    obj_path, asg_path, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
    objects = {o["id"]: o for o in json.load(open(obj_path))["objects"]}
    payload = json.load(open(asg_path))
    assignments = payload["assignments"]

    by_ns = {a["namespace"]: a for a in assignments}
    parents = set(a["parent_namespace"] for a in assignments if a["parent_namespace"])
    leaves = [a["namespace"] for a in assignments if a["namespace"] not in parents]

    def segment(namespace):
        a = by_ns[namespace]
        o = objects[a["object_id"]]
        seg = {
            "name": a["name"],
            "path_segment": a["path_segment"],
            "object_type": "object",
            "uns_level": a["uns_level"],
            "description": a.get("description", ""),
            "metadata": a.get("metadata", {}),
        }
        # dbms/table make it a data-bearing tag. Columns are deliberately left
        # out: the plugin expands a column list into an extra object and uns
        # node per column, which would grow the tree past what is published.
        if o.get("dbms") and o.get("table"):
            seg["dbms"] = o["dbms"]
            seg["table"] = o["table"]
            if o.get("where_conditions"):
                seg["where_conditions"] = o["where_conditions"]
        return seg

    paths = []
    for leaf in sorted(leaves):
        parts = leaf.split("/")
        chain = ["/".join(parts[:i + 1]) for i in range(len(parts))]
        paths.append({
            "name": leaf.replace("/", " / "),
            "root_namespace": parts[0],
            "segments": [segment(ns) for ns in chain],
        })

    out = {
        "conn": payload.get("conn", "host.docker.internal:32149"),
        "source_node": assignments[0].get("source_node", ""),
        "publish": True,
        "paths": paths,
    }
    with open(out_path, "w") as fh:
        json.dump(out, fh, indent=2)

    distinct = set()
    for p in paths:
        segs = p["segments"]
        for i in range(len(segs)):
            distinct.add(tuple(s["path_segment"] for s in segs[:i + 1]))
    print("paths            : %d root-to-leaf chains" % len(paths))
    print("distinct nodes   : %d (what the tree will contain)" % len(distinct))
    print("total segments   : %d (before the plugin deduplicates prefixes)"
          % sum(len(p["segments"]) for p in paths))
    print("wrote            : %s" % out_path)


if __name__ == "__main__":
    main()
