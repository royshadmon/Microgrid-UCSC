#!/usr/bin/env bash
# Copy the ONNX + norm files the running iems-inference container on Pat's box
# actually loaded into services/iems/models/, so the GX10 starts on the same
# 18 feature model set that is live at the house. Uses the export folder when
# it already holds them.
set -euo pipefail
cd "$(dirname "$0")/../.."
SRC="${SRC:-gx10/data/export/models}"
if [ ! -s "$SRC/nilm_panel3.onnx" ]; then
  echo "no $SRC yet; run gx10/scripts/export_pat_data.sh first"; exit 1
fi
cp "$SRC"/nilm_panel?.onnx "$SRC"/panel?_norm_bilstm.json services/iems/models/
python3 - <<'PY'
import json
for p in (1, 2, 3):
    d = json.load(open(f"services/iems/models/panel{p}_norm_bilstm.json"))
    print(f"panel{p}: {len(d['features'])} features, {len(d['heads'])} heads")
PY
md5sum services/iems/models/nilm_panel?.onnx
