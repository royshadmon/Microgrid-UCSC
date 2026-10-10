# Microgrid Manager on the ASUS Ascent GX10

This folder moves the whole Microgrid IEMS onto one ASUS Ascent GX10 (NVIDIA GB10
Grace Blackwell, 20 Arm cores, 128 GB unified memory, DGX OS). Everything runs on
the box. The BiLSTM NILM models are trained on the GB10 GPU from real data
exported off Pat's machine, the live feed is a replay of that same data, and the
reasoning layer is NVIDIA Nemotron 3.5 Lightning served locally.

Nothing under `services/` or `streaming/` is forked for the GX10. The replay
producer emits exactly the messages the real eGauge producer emits, so Kafka, the
AnyLog operator, the inference loop and every dashboard run the production code
unchanged.

```
 ┌────────────────────── Phase A: at home, on the tailnet ──────────────────────┐
 │                                                                              │
 │  Pat's box (100.119.235.24)              GX10                                │
 │  Postgres behind AnyLog  ── export ──▶  gx10/data/export/                    │
 │  iems-inference image    ── models ──▶  services/iems/models/                │
 │                                          │                                   │
 │                                          ▼                                   │
 │                         build_dataset.py → physical_labeler_v2 →             │
 │                         train_rolling (GB10 GPU) → export_physical (ONNX)    │
 └──────────────────────────────────────────────────────────────────────────────┘

 ┌──────────────────── Phase B: at the hackathon, offline ──────────────────────┐
 │                                                                              │
 │  replay-producer ─▶ Kafka ─▶ AnyLog operator1 ─▶ Postgres                    │
 │   (Pat's real 1 s      │                    ▲                                 │
 │    data, live ts)      └─▶ anylog-consumer ─┘   energy_readings, egauge_kafka │
 │                                                                              │
 │  iems-inference (ONNX BiLSTM, 22 heads, every 30 s) ─▶ nilm_disaggregated     │
 │                                                                              │
 │  iems-backend :8009   iems-dashboard :47821   Remote GUI + MCP :3001/:8000    │
 │                     │                         │                              │
 │                     └──── Nemotron 3.5 Lightning (GB10, Ollama API :11434) ──┘│
 └──────────────────────────────────────────────────────────────────────────────┘
```

## What is in this folder

| path | purpose |
|---|---|
| `docker-compose.gx10.yaml` | the full arm64 stack, with profiles for the LLM runtime |
| `.env.example` | every setting the stack reads. Copy to `gx10/.env` |
| `replay/replay_producer.py` | the "dummy producer". Plays Pat's real data into Kafka with live timestamps, plus a control API for the demo |
| `scripts/export_pat_data.sh` | pulls data and the deployed models off Pat's box over Tailscale |
| `scripts/pat_export_remote.sh` | the half of the export that runs on Pat's box |
| `scripts/build_dataset.py` | turns the export into the parquet files the training code already reads |
| `training/Dockerfile`, `training/train_all.sh` | GPU training on the GB10 in the NGC PyTorch container |
| `llm-bridge/ollama_bridge.py` | Ollama API in front of a NIM or vLLM Nemotron, for when Nemotron is not served by Ollama |
| `scripts/bootstrap_gx10.sh`, `up.sh`, `verify.sh` | first-boot checks, ordered bring-up, end-to-end health |
| `config/operator1-gx10.env` | operator overrides (monthly partitions, same as Pat's box) |

## Services and ports

| service | port | notes |
|---|---|---|
| replay-producer | 8099 | control API: `/status`, `/speed`, `/jump`, `/inject`, `/clear` |
| kafka / kafka-ui | 9092, 9094 / 8080 | topic `egauge-energy` |
| master, operator1 (AnyLog) | 32048-32049, 32148-32149, 1883 | arm64 image `anylogco/anylog-network:local-nuitka-arm` |
| postgres1 | 5432 | `customers` database |
| iems-inference | none | writes one `nilm_disaggregated` row per head per tick |
| iems-backend | 8009 | `/iems/*` engine API and `/iems/ask` |
| iems-dashboard | 47821 | live KPIs, NILM grid, solar and battery |
| iems-app (Remote GUI 2.1.6 + IEMS plugin) | 3001 (UI), 8000 (API) | IEMS page at `/dashboard/iems`, MCP client at `/dashboard/mcpclient` |
| Nemotron 3.5 Lightning | 11434 (Ollama API) | host Ollama, `--profile ollama`, or `--profile bridge` in front of a NIM on 8010 |

Memory budget on the 128 GB pool: Nemotron 3.5 Lightning in NVFP4 is about 19 to
25 GB, the stack itself about 6 GB, and a training run a few GB on top. All three
fit at once, so you can retrain while the demo is running.

---

## Step by step

Steps 1 to 9 are done once, at home, with the GX10 on the internet and on the
tailnet. Steps 10 to 12 are what you run at the hackathon, where the box needs no
network at all.

### 1. First boot

Complete the DGX OS first-boot wizard (user account, network, time zone). Then
update and confirm the GPU and the architecture.

```bash
sudo apt update && sudo apt full-upgrade -y && sudo reboot
nvidia-smi                 # one GB10 listed, driver 580 or newer
uname -m                   # aarch64
free -g                    # ~119 GiB visible to the OS
```

### 2. Docker and the GPU runtime

DGX OS ships Docker and the NVIDIA Container Toolkit. Let your user run Docker
and confirm a container can see the GPU.

```bash
sudo usermod -aG docker $USER && newgrp docker
docker run --rm --gpus all ubuntu:24.04 nvidia-smi
docker compose version     # v2 is required
```

If the second command says the runtime is unknown, register it and restart
Docker.

```bash
sudo nvidia-ctk runtime configure --runtime=docker && sudo systemctl restart docker
```

### 3. Tailscale, so the GX10 can reach Pat's box

Pat's box is shared into your tailnet, so log the GX10 in with the same account
as your Mac.

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up                       # open the printed URL and approve
tailscale ping 100.119.235.24           # pong from pat-all-series
ssh-keygen -t ed25519                   # if the GX10 has no key yet
ssh-copy-id microgrid@100.119.235.24    # password once, then key auth
ssh microgrid@100.119.235.24 hostname   # pat-All-Series
```

### 4. Find out how Nemotron 3.5 Lightning is served

The GX10 comes with Nemotron 3.5 Lightning preloaded, but the runtime it sits in
decides how the stack talks to it. Check all three places.

```bash
ollama list 2>/dev/null | grep -i nemotron            # A: host Ollama
curl -s localhost:11434/api/tags | grep -i nemotron   # A: host Ollama, API view
docker images | grep -iE 'nim|nemotron|vllm'          # B: NIM or vLLM image
curl -s localhost:8000/v1/models                      # B: an OpenAI server already up
```

**A. Host Ollama (the simplest).** Containers reach the host through
`host.docker.internal`, which is the Docker bridge address, so Ollama must listen
on all interfaces rather than on 127.0.0.1. Keeping the model resident avoids a
reload on every question.

```bash
sudo systemctl edit ollama
#   [Service]
#   Environment="OLLAMA_HOST=0.0.0.0:11434"
#   Environment="OLLAMA_KEEP_ALIVE=-1"
sudo systemctl restart ollama
ollama list                               # note the exact tag, e.g. nemotron-3.5-lightning:latest
curl -s localhost:11434/api/chat -d '{"model":"nemotron-3.5-lightning","stream":false,
  "messages":[{"role":"user","content":"Reply with the word ready."}]}'
```

Set `LLM_MODEL` in `gx10/.env` to the tag `ollama list` printed. No compose
profile is needed.

**B. NIM or vLLM (OpenAI API).** Port 8000 belongs to the Remote GUI API, so run
the model server on 8010, and start the stack with `PROFILES=bridge`. The bridge
answers on 11434 in the Ollama dialect and forwards to the OpenAI endpoint. On the
GB10 the NIM shares unified memory with the host, so cap its share.

```bash
docker run -d --name nemotron --gpus all --restart unless-stopped \
  -e NGC_API_KEY=$NGC_API_KEY \
  -e NIM_MODEL_NAME=nvidia/nemotron-3.5-lightning-30b-a3b \
  -e NIM_SERVED_MODEL_NAME=nvidia/nemotron-3.5-lightning-30b-a3b \
  -e NIM_PASSTHROUGH_ARGS="--reasoning-parser nemotron_v3 --enable-auto-tool-choice --tool-call-parser qwen3_coder --gpu-memory-utilization 0.75" \
  -v ~/.cache/nim:/opt/nim/.cache -p 8010:8000 \
  nvcr.io/nim/nvidia/nemotron-3.5-lightning-30b-a3b:2.0.9-variant
curl -s localhost:8010/v1/models
```

NVIDIA recommends `--gpu-memory-utilization 0.75` on the GB10 to avoid a startup
OOM. That still leaves about 30 GB of the pool for the stack and a training run.
Confirm the image tag against what is already on the box (`docker images`) before
pulling anything new. `--enable-auto-tool-choice` and the `qwen3_coder` parser are
what make tool calls work, which the MCP client needs.

**C. Nothing preloaded is reachable.** Start the stack with `PROFILES=ollama` and
pull the model into the container once (about 25 GB, do it at home).

```bash
docker compose -f gx10/docker-compose.gx10.yaml --env-file gx10/.env --profile ollama up -d ollama
docker exec ollama ollama pull nemotron-3.5-lightning
```

### 5. Clone the repo on the GX10

The repo is private, so the GX10 needs a GitHub key.

```bash
cat ~/.ssh/id_ed25519.pub          # add at github.com/settings/keys
git clone -b gx10 git@github.com:royshadmon/Microgrid-UCSC.git ~/Microgrid-UCSC
cd ~/Microgrid-UCSC
```

### 6. Load the AnyLog arm64 image and set the license

The AnyLog image is not on a public registry. The arm64 build is the tar already
on your Mac, `~/microgrid-manager/AnyLog-latest-arm.tar` (tag
`anylogco/anylog-network:local-nuitka-arm`). Copy it over Tailscale or a USB drive
and load it.

```bash
# on the Mac
scp ~/microgrid-manager/AnyLog-latest-arm.tar <gx10-user>@<gx10-tailscale-ip>:~/Microgrid-UCSC/
# on the GX10
docker load -i ~/Microgrid-UCSC/AnyLog-latest-arm.tar
cp gx10/.env.example gx10/.env
```

The nodes refuse to start without a license. The key that is valid through
2026-11-01 is the `LICENSE_KEY` on the `master` service in the compose file on
Pat's box. Print it and paste it as `ANYLOG_LICENSE=` in `gx10/.env`, wrapped in
single quotes because it embeds JSON. Never commit it.

```bash
ssh microgrid@100.119.235.24 \
  "grep -m1 'LICENSE_KEY:' /home/pat/microgrid_manager/Microgrid-UCSC-dev_fin/docker-compose.yaml"
nano gx10/.env      # ANYLOG_LICENSE='<key>{"company": "Guest", ...}'
```

Then run the first-boot checks. They report and change nothing else.

```bash
bash gx10/scripts/bootstrap_gx10.sh
```

### 7. Export the real data and the deployed models from Pat's box

```bash
bash gx10/scripts/export_pat_data.sh      # asks for the sudo password on Pat's box
```

This runs `pat_export_remote.sh` on Pat's box and copies the result to
`gx10/data/export/`.

| file | content |
|---|---|
| `egauge_6s/YYYY-MM-DD.csv.gz` | every day in Postgres on the 6 s sample-and-hold grid the inference loop uses, long format `ts, channel, w` (UTC) |
| `egauge_1s/YYYY-MM-DD.csv.gz` | raw 1 s readings for the newest three days, for the replay |
| `solar.csv.gz` | all Solar Assistant rows |
| `models/` | the ONNX and norm files baked into the running `iems-inference` image |
| `MANIFEST.txt` | row counts and checksums |

Every query goes through the `ts` index, one day at a time, at low priority, and
a day already on disk is skipped, so the export is safe to re-run and to
interrupt. It takes about 30 minutes the first time. The default source table is
`egauge_kafka` (from 2026-08-18). `energy_readings` reaches back to 2026-08-01 and
fills the gap.

```bash
TABLE=energy_readings START=2026-08-01 END=2026-08-19 REPLAY_DAYS=0 \
  bash gx10/scripts/export_pat_data.sh
```

An export taken on 2026-10-10 is already on your Mac in
`~/microgrid-manager/_gx10_transfer/gx10_export.tar`. Unpack it into
`gx10/data/export/` to skip this step.

The repo already carries the deployed 18 feature models in `services/iems/models/`.
`pull_models_from_pat.sh` re-syncs them from a fresh export if Pat's box is ever
redeployed.

### 8. Build the training dataset

The NGC PyTorch image has pandas and pyarrow, so build it once and use it for the
dataset step as well. For the longest history, copy the March to August archive
from the Mac first (it is gitignored, about 145 MB).

```bash
# on the Mac
scp ~/microgrid-manager/analysis/egauge_consolidation/egauge_merged_mar_aug.parquet \
    ~/microgrid-manager/analysis/solar/solar_history.parquet \
    <gx10-user>@<gx10-tailscale-ip>:~/Microgrid-UCSC/gx10/data/
# on the GX10
docker build -t microgrid-train:gx10 -f gx10/training/Dockerfile gx10/training
docker run --rm -v $PWD:/workspace --entrypoint python3 microgrid-train:gx10 \
  gx10/scripts/build_dataset.py --export gx10/data/export \
  --archive gx10/data/egauge_merged_mar_aug.parquet \
  --solar-archive gx10/data/solar_history.parquet
```

Leave out `--archive` to train on Pat's live data alone (August to October). The
result is `gx10/data/egauge_gx10.parquet` and `gx10/data/solar_gx10.parquet`, in
exactly the shape `train_rolling.py` already reads.

### 9. Train the BiLSTM models on the GB10

```bash
# smoke test, one epoch per stage
docker run --rm --gpus all --ipc=host --ulimit memlock=-1 -e QUICK=1 \
  -v $PWD:/workspace microgrid-train:gx10
# the real run
docker run --rm --gpus all --ipc=host --ulimit memlock=-1 \
  -v $PWD:/workspace microgrid-train:gx10
```

`train_all.sh` runs the same pipeline `docs/04_training_pipeline.md` describes, now
pointed at the GPU (`train_rolling.py` picks CUDA when it is there, with the same
seed, folds and batch size, so CPU and GPU runs are comparable).

1. `physical_labeler_v2.py` labels and trust weights.
2. `train_rolling.py`, once per panel. It writes the 18 feature norm and the thresholds.
3. `export_physical.py`, the ONNX export with the output-name check.

For reference, this pipeline was run on the 70 day export on a two core CPU
machine before it was committed. Labelling took about 3 minutes and the one epoch
smoke run of Panel 1 took about 16 minutes end to end, producing an 18 feature
norm, calibrated thresholds, the per-fold report and an ONNX file whose outputs
matched the head contract. The GB10 is far faster. `BATCH=1024` (pass `-e BATCH=1024`) uses the GPU better, at the cost of
results that are no longer directly comparable with the 256 batch CPU runs.

`gen_norm_physical.py` is deliberately skipped, because it rebuilds the 14 feature
norm and would overwrite the 18 feature one. Before training, the current models
are copied to `gx10/data/model_backups/<stamp>/`. Logs land in
`gx10/data/train_logs/<stamp>/`.

Compare `services/iems/training/reports/panel{1,2,3}_rolling_unit_tests.csv` with
the deployed numbers in `docs/04_training_pipeline.md` before you keep a run. To
go back to the models that are live at the house:

```bash
git checkout -- services/iems/models/
```

Then pre-build every image while you still have internet.

```bash
bash gx10/scripts/up.sh                    # host Ollama
PROFILES=bridge bash gx10/scripts/up.sh    # NIM / vLLM
PROFILES=ollama bash gx10/scripts/up.sh    # Ollama in a container
```

### 10. Bring the stack up at the hackathon

```bash
cd ~/Microgrid-UCSC
bash gx10/scripts/up.sh            # with PROFILES=... as in step 9
```

`up.sh` builds `iems-inference` before `iems-backend` (which builds FROM it),
starts Postgres, AnyLog and Kafka first, waits for the operator's REST port, then
starts the replay, inference and apps, and runs `verify.sh`.

The replay backfills the 15 minutes before its start point, so the first
inference tick (about 30 s later) already has a full 10 minute window. With
`ALIGN=tod` the replay starts at the same local time of day as the wall clock, so
the time of day and sun position features agree with the data the model sees.

### 11. Verify

```bash
bash gx10/scripts/verify.sh
```

It checks the replay, the operator, fresh rows in `energy_readings`,
`egauge_kafka`, `solar_data` and `nilm_disaggregated`, that 22 heads are being
written, which model files `iems-inference` loaded, every app URL, and a chat
round trip to Nemotron.

| open | for |
|---|---|
| `http://<gx10>:47821` | live IEMS dashboard |
| `http://<gx10>:3001/dashboard/iems` | IEMS page in the AnyLog Remote GUI |
| `http://<gx10>:3001/dashboard/mcpclient` | MCP client, Nemotron querying AnyLog with tools |
| `http://<gx10>:8009/docs` | engine API, including `/iems/ask` |
| `http://<gx10>:8080` | Kafka UI, messages flowing on `egauge-energy` |
| `http://<gx10>:8099/status` | replay state |

### 12. Drive the demo

```bash
R=http://localhost:8099
curl -s $R/status | python3 -m json.tool
curl -s -X POST "$R/jump?to=18:30"            # evening peak (kitchen, heat pump)
curl -s -X POST "$R/inject?channel=Panel2%20(H2O)&watts=3500&seconds=300"   # water heater burst
curl -s -X POST "$R/clear"
curl -s -X POST "$R/speed?x=1"
```

An injection adds watts on top of the real trace on one channel and on
`Grid Power`, so the power gate, the water heater head and the dashboard all
react within one or two ticks. Keep `speed` at 1 while you show the model output.
The models were trained on real time 10 minute windows, so a time-lapsed window
is out of distribution. After a `jump`, give it 10 minutes (or restart the
replay, which backfills) before reading the NILM grid.

Questions that show the reasoning layer working from live data:

```bash
curl -s localhost:8009/iems/ask -H 'Content-Type: application/json' \
  -d '{"question":"Which appliances are on right now and how sure is the model?"}'
```

In the MCP client page, ask for things that need tools, for example "How many
rows did nilm_disaggregated get in the last five minutes, by appliance?".

---

## How the original Microgrid Manager maps onto the GX10

| production at Pat's house | on the GX10 |
|---|---|
| eGauge 18646, polled every second by `egauge-producer` | `replay-producer`, Pat's recorded 1 s data with live timestamps, same Kafka topic and message shape. `--profile live` restores the real producer |
| Solar Assistant over MQTT via `solar-producer` | the replay writes the recorded `solar_data` rows to the operator every 5 s |
| AnyLog 2.1.2608 amd64 on Pat's box | the same AnyLog configs on the arm64 image, monthly partitions |
| models trained on the Mac CPU, copied to Pat's box, baked into the image | trained on the GB10 GPU in the NGC container, exported to ONNX, baked into the GX10 image the same way |
| ONNX Runtime on an x86 CPU | ONNX Runtime on the Grace cores (5 to 25 ms per window, no GPU needed) |
| qwen2.5 1.5B/3B in Ollama on CPU | Nemotron 3.5 Lightning (30B MoE, 3B active) on the GB10 |
| Home Assistant thermostat controls | disabled, there is no HA instance at the hackathon |

The inference loop stays on the CPU on purpose. A 100 x 18 window through a
small BiLSTM is a few milliseconds, and keeping the GPU free leaves the whole
Blackwell for Nemotron and for training.

## Troubleshooting

| symptom | cause and fix |
|---|---|
| `master` or `operator1` restarts in a loop | `ANYLOG_LICENSE` empty or expired in `gx10/.env`. `docker logs operator1 | head -50` |
| no rows in `energy_readings` | `docker logs anylog-consumer`. The bridge waits for the operator REST port, which takes a minute on first boot |
| rows in `energy_readings` but not `egauge_kafka` | the operator's own Kafka consumer uses `reset = latest`, so it misses the backfill. It fills from the next message on |
| `nilm_disaggregated` empty | `docker logs iems-inference`. The first tick is about 30 s after start. A norm or ONNX mismatch prints the feature list it expected |
| Nemotron unreachable from containers | host Ollama is bound to 127.0.0.1. Step 4A (`OLLAMA_HOST=0.0.0.0:11434`) |
| `iems-app` port 8000 already in use | a NIM is on 8000. Restart it with `-p 8010:8000` and use `--profile bridge` |
| `iems-backend` build fails on its base image | build `iems-inference` first. `up.sh` does this |
| MCP client says the model does not support tools | NIM started without `--enable-auto-tool-choice --tool-call-parser qwen3_coder` |
| replay says `synthetic` | `gx10/data/export/egauge_1s/` is empty. Step 7 |
| GPU training warns about compute capability 12.1 | you are on a pip wheel rather than the NGC image. Use `microgrid-train:gx10` |

## Sources

NVIDIA documents the NIM run command, ports, tool calling flags and the GB10 memory note in
[Get Started with Nemotron 3.5 Lightning](https://docs.nvidia.com/nim/large-language-models/2.0.10/get-started/advanced/get-started-nemotron-3.5-lightning.html).
The Ollama tag is [nemotron-3.5-lightning](https://ollama.com/library/nemotron-3.5-lightning).
The NGC PyTorch tag for DGX Spark class machines is discussed in
[Effective PyTorch and CUDA on DGX Spark](https://forums.developer.nvidia.com/t/effective-pytorch-and-cuda/348230).
