# 5. Check it and use it

[Guide home](README.md) · back [4. Start](04_start.md) · next [6. Demo scenarios](06_demo_scenarios.md)

## Is data flowing

macOS and Linux.

```bash
./scripts/status.sh
```

Windows.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\status.ps1
```

It lists the containers, checks both AnyLog nodes, counts the rows each table
received in the last two minutes, and checks the engine, the Ask model and the
dashboard. A healthy demo looks like this.

```
Rows received in the last 2 minutes
  [ok]   energy_readings      320
  [ok]   egauge_kafka         320
  [ok]   solar_data           4
  [ok]   nilm_disaggregated   154
```

`energy_readings` is the meter feed, `solar_data` the inverter feed and
`nilm_disaggregated` the appliance results. A container that says `running`
proves little on its own. The row counts are the real test.

## The dashboard, http://localhost:47821

| tab | what it shows |
|---|---|
| Home | one sentence about the house, battery, solar, grid and house use, what is running, indoor comfort, and a 24 hour price strip that says when heavy loads are cheapest |
| General | the live power chart for every panel and the key figures |
| Weather | outside conditions and how they relate to heating, cooling and solar |
| Appliances | appliance cards grouped by Running, Maybe and All, with the last time each was on. The raw model output is in a collapsed section underneath |
| Relay | thermostat state and controls, when Home Assistant is connected |
| Anomalies | anything unusual the rules flagged |
| Ask | type a question in plain words. Common questions are answered straight from the readings, others by the local model, and every number is checked against the readings before it is shown |

It works on a phone too. On the same Wi-Fi, open `http://<your computer's IP>:47821`.

Try these in Ask.

```
How full is the battery?
Which appliances are running?
When should I run the dryer?
Which panel is using the most power?
```

## The engine, http://localhost:8009/docs

An interactive page for every engine route. Two useful ones from a terminal.

```bash
curl http://localhost:8009/iems/health
curl -X POST http://localhost:8009/iems/ask -H "Content-Type: application/json" \
     -d '{"question":"How full is the battery?"}'
```

## AnyLog, port 32149

The operator answers plain HTTP with the command in a header.

```bash
curl -s http://localhost:32149 -H "User-Agent: AnyLog/1.23" -H "command: get status"
curl -s http://localhost:32149 -H "User-Agent: AnyLog/1.23" -H "command: get processes"
```

[`docs/reference/anylog_query_cookbook.md`](../reference/anylog_query_cookbook.md)
has every query shape that is known to work.

## Optional pages

| profile | address |
|---|---|
| `gui` | http://localhost:3001 for the AnyLog Remote GUI, with the IEMS page under Dashboard, IEMS |
| `tools` | http://localhost:8080 for Kafka UI, to watch the `egauge-energy` topic |

Next, [6. Demo scenarios](06_demo_scenarios.md).
