# eGauge to AnyLog Streaming Script

## Requirements
```
pip install egauge-python paho-mqtt crcmod
```

## Configuration

Edit the top of `egauge_to_anylog.py` and fill in `EGAUGE_URI`, `EGAUGE_USER`, `EGAUGE_PASS`, and `MQTT_BROKER`.

## Functions

| Function | Description |
|---|---|
| `connect_egauge()` | Authenticates with eGauge via JWT. Returns a device handle. |
| `fetch(dev)` | Calls `GET /register?rate` for instantaneous watts. Maps raw register names to short names via `NAME_MAP`. Returns list of JSON payloads. |
| `publish(payloads)` | Publishes each payload as JSON to AnyLog's MQTT broker which is just a database name for Anylog from previous testing. |
| `main()` | Poll loop — fetches and publishes every `POLL_INTERVAL` seconds. Auto-reconnects on failure. |

## AnyLog Operator Setup
```
set buffer threshold where time = 60 seconds and volume = 10KB
run streamer
run msg client where broker = local and port = 1883 and log = false and topic = (name = egauge/energy and dbms = customers and table = egd and column.tstamp.timestamp = "bring [ts]" and column.dvc.str = "bring [dev]" and column.reg.str = "bring [nm]" and column.rtyp.str = "bring [tp]" and column.watt.float = "bring [w]" and column.kwhr.float = "bring [kwh]")
```

