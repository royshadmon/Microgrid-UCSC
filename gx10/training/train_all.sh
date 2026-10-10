#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# train_all.sh  (runs inside microgrid-train:gx10 with the repo at /workspace)
#
# The same pipeline docs/04_training_pipeline.md describes for the Mac, aimed
# at the GB10 GPU and at the data exported from Pat's box.
#
#   1. physical_labeler_v2.py   labels + trust weights from the physics rules
#   2. train_rolling.py         rolling walk-forward BiLSTM, once per panel
#                               (writes the 18 feature norm + thresholds)
#   3. export_physical.py       ONNX export + output-name verification
#
# gen_norm_physical.py is deliberately NOT run. It rebuilds the 14 feature
# norm of train_all_physical.py and would overwrite the 18 feature norm that
# train_rolling.py has just written, which is exactly the silent mismatch the
# training doc warns about.
#
# Env
#   EGAUGE_PARQUET  default gx10/data/egauge_gx10.parquet
#   SOLAR_PARQUET   default gx10/data/solar_gx10.parquet
#   PANELS          default "1 2 3"
#   SKIP_LABELS=1   reuse labels from a previous run
#   QUICK=1         one epoch per stage, for a smoke test
#   EPOCHS_FIRST / EPOCHS_ROLL / BATCH / DEVICE pass straight through
# ---------------------------------------------------------------------------
set -euo pipefail
cd /workspace

export EGAUGE_PARQUET="${EGAUGE_PARQUET:-gx10/data/egauge_gx10.parquet}"
export SOLAR_PARQUET="${SOLAR_PARQUET:-gx10/data/solar_gx10.parquet}"
PANELS="${PANELS:-1 2 3}"
if [ "${QUICK:-0}" = "1" ]; then
  export EPOCHS_FIRST=1 EPOCHS_ROLL=1
fi

[ -f "$EGAUGE_PARQUET" ] || { echo "missing $EGAUGE_PARQUET, run gx10/scripts/build_dataset.py first" >&2; exit 1; }
mkdir -p services/iems/training/data services/iems/training/models services/iems/training/reports

stamp=$(date +%Y%m%d_%H%M%S)
log_dir="gx10/data/train_logs/$stamp"
mkdir -p "$log_dir"
echo "[train] logs -> $log_dir"

python3 - <<'PY'
import torch
ok = torch.cuda.is_available()
print("[train] torch", torch.__version__, "cuda", ok,
      torch.cuda.get_device_name(0) if ok else "(CPU only)")
PY

# Keep what is deployed now, so a bad run is one copy away from undone.
bak="gx10/data/model_backups/$stamp"
mkdir -p "$bak"
cp services/iems/models/nilm_panel?.onnx services/iems/models/panel?_norm_bilstm.json "$bak"/ 2>/dev/null || true
echo "[train] incumbent models backed up -> $bak"

if [ "${SKIP_LABELS:-0}" != "1" ]; then
  echo "[train] 1/3 physical labels"
  python3 services/iems/training/physical_labeler_v2.py 2>&1 | tee "$log_dir/labels.log"
fi

for P in $PANELS; do
  echo "[train] 2/3 rolling walk-forward, panel $P"
  t0=$(date +%s)
  PANEL=$P python3 services/iems/training/train_rolling.py 2>&1 | tee "$log_dir/panel$P.log"
  echo "[train]     panel $P took $(( $(date +%s) - t0 ))s"
done

echo "[train] 3/3 ONNX export + verify"
for P in $PANELS; do
  python3 services/iems/training/export_physical.py --panel "$P" 2>&1 | tee -a "$log_dir/export.log"
done

python3 - <<'PY'
import json
for p in (1, 2, 3):
    d = json.load(open(f"services/iems/models/panel{p}_norm_bilstm.json"))
    print(f"[train] panel{p}: {len(d['features'])} features, {len(d['heads'])} heads, source={d.get('_source')}")
PY
echo "[train] reports: services/iems/training/reports/panel{1,2,3}_rolling_unit_tests.csv"
echo "[train] next: docker compose -f gx10/docker-compose.gx10.yaml build iems-inference iems-backend && ... up -d --no-deps iems-inference iems-backend"
