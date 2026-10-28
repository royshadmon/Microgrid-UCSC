# 7. Connect real hardware

[Guide home](README.md) · back [6. Demo scenarios](06_demo_scenarios.md) · next [8. Troubleshooting](08_troubleshooting.md)

The computer must be on the same network as the devices.

## Step 1, fill in `.env`

```
COMPOSE_PROFILES=live

EGAUGE_URI=https://egaugeNNNNN.egaug.es     # or http://<meter IP>
EGAUGE_USER=owner
EGAUGE_PASS=<meter password>

SA_BROKER=<Solar Assistant IP>
SA_PORT=1883
SA_USER=<MQTT user from Solar Assistant>
SA_PASS=<MQTT password>
SA_PREFIX=solar_assistant
```

The eGauge address and login are on the meter's own admin page. The Solar
Assistant values are under Configuration, MQTT in its web page. Use `live`
instead of `demo`, never both, or the demo data will mix with the real data.

## Step 2, Home Assistant (optional)

1. In Home Assistant open your profile, Security, Long lived access tokens, and
   create one.
2. Save it as a single line in `config/ha_token.txt`.
3. Set `HA_URL=http://<home assistant address>:8123` in `.env`.

## Step 3, apply

```bash
docker compose rm -sf demo-replay
./scripts/start.sh
```

(`.\scripts\start.ps1` on Windows.) Then run the status script. With a real
meter `energy_readings` receives about 1,900 rows every two minutes, because
the meter reports 16 channels every second.

## Your own house

The models in `services/iems/models/` were trained on one particular house
with three sub-panels named `Panel1 (HVAC)`, `Panel2 (H2O)` and
`Panel3 (Kitchen)`. They will run on another house only if the meter uses the
same channel names, and their appliance results only mean something for similar
appliances. Training your own is described in
[`docs/reference/04_training_pipeline.md`](../reference/04_training_pipeline.md).

Next, [8. Troubleshooting](08_troubleshooting.md).
