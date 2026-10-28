# local_script.al, IEMS operator startup additions
# Called at the END of the config policy script array.
#
# Under AnyLog 2.1.2608 node_policy.al can abort the policy script array before
# the operator is declared (see docs/reference/07_streaming_storage.md, the
# node-policy trap). So the operator is declared here as well, from this node's
# own policy looked up by company and name. 'on error ignore' turns each line
# into a no-op if the policy path already did the same thing.

on error ignore
operator_id = blockchain get operator where company = !company_name and name = !node_name bring [operator][id]
set buffer threshold where time = 2 seconds and volume = 10000 and write_immediate = true
run streamer
partition customers * using insert_timestamp by month
run operator where policy = !operator_id and create_table = true and update_tsd_info = true and compress_json = true and master_node = !ledger_conn

run kafka consumer where ip = host.docker.internal and port = 9094 and reset = latest and topic = (name = egauge-energy and dbms = customers and table = egauge_kafka and column.ts.timestamp = "bring [ts]" and column.dev.str = "bring [dev]" and column.nm.str = "bring [nm]" and column.tp.str = "bring [tp]" and column.w.float = "bring [w]" and column.kwh.float = "bring [kwh]")

# ── Solar Assistant via AnyLog's own MQTT broker ─────────────────────────────
# Pattern: "AnyLog as the broker" (06- Networking & Security / 05- MQTT Message
# Broker.md, Case 4). The broker itself is already up on ANYLOG_BROKER_PORT=1883
# via base_configs.env; this is the missing subscriber half.
#
# Explicit column mapping, NOT dynamic = true. Two reasons:
#   1. Naming precedence: with dynamic = true and no table setting, the table is
#      the LAST TOPIC SEGMENT -> topic "solar" would create table "solar", not
#      solar_data. Setting `table` explicitly overrides that.
#   2. Schema freeze: under dynamic = true the first message's JSON defines the
#      column types for good. `ts` would land as a str and break every time-range
#      query. Declaring column.ts.timestamp pins it correctly up front.
run msg client where broker = local and log = false and topic = (name = solar and dbms = customers and table = solar_data and column.ts.timestamp = "bring [ts]" and column.pv_power.float = "bring [pv_power]" and column.battery_power.float = "bring [battery_power]" and column.battery_soc.float = "bring [battery_soc]" and column.grid_power.float = "bring [grid_power]" and column.load_power.float = "bring [load_power]" and column.device_mode.str = "bring [device_mode]")
