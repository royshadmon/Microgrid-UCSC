#!/usr/bin/env python3
"""Master training script - runs all panels in sequence."""
import subprocess, sys
from pathlib import Path
from datetime import datetime

REPO = Path(__file__).resolve().parents[3]
TRAINING = REPO / "services/iems/training"
VENV_PYTHON = REPO / ".venv-training/bin/python3"

if not VENV_PYTHON.exists():
    sys.exit(f"ERROR: {VENV_PYTHON} not found")

data_file = REPO / "data/panel1_60d.parquet"  # Will be symlinked
if not data_file.exists():
    sys.exit(f"ERROR: {data_file} not found - create symlink first")

print(f"Starting training pipeline at {datetime.now()}")
print(f"Using data: {data_file} -> {data_file.resolve()}")
print()

steps = [
    ("Panel 1 labels", "labels_panel1.py"),
    ("Panel 2 labels", "labels_panel2.py"),
    ("Panel 3 labels", "labels_panel3.py"),
    ("Panel 1 windows", "windows_panel1.py"),
    ("Panel 2 windows", "windows_panel2.py"),
    ("Panel 3 windows", "windows_panel3.py"),
    ("Panel 1 baseline", "train_panel1.py"),
    ("Panel 2 baseline", "train_panel2.py"),
    ("Panel 3 baseline", "train_panel3.py"),
    ("Panel 1 augmented", "train_panel1_aug.py"),
    ("Panel 2 augmented", "train_panel2_aug.py"),
    ("Panel 3 augmented", "train_panel3_aug.py"),
    ("Tune & evaluate", "tune_thresholds_v2.py"),
    ("Export ONNX", "export_panel1.py"),
]

failed = []
for i, (desc, script) in enumerate(steps, 1):
    print(f"[{i}/{len(steps)}] {desc}...")
    result = subprocess.run([str(VENV_PYTHON), str(TRAINING / script)],
                          cwd=str(REPO), capture_output=True, text=True)
    if result.returncode == 0:
        print(f"  ✓ Done")
    else:
        print(f"  ✗ FAILED")
        for line in result.stderr.split("\n")[-10:]:
            if line.strip():
                print(f"    {line}")
        failed.append(desc)

print("\n" + "="*60)
if not failed:
    print("✓ All steps completed!")
    print("\nModels:")
    for m in sorted((REPO / "services/iems/models").glob("nilm_panel*.pt")):
        print(f"  {m.name}")
else:
    print(f"✗ {len(failed)} failed: {', '.join(failed)}")
    sys.exit(1)
