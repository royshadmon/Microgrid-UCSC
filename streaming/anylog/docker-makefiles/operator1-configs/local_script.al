# local_script.al — IEMS operator startup additions
# Called at the END of the config policy script array.
# Do NOT duplicate commands already in the policy script array
# (set buffer threshold, run streamer, run operator — those run before this file).

run kafka consumer where ip = host.docker.internal and port = 9094 and reset = latest and topic = (name = egauge-energy and dbms = customers and table = egauge_kafka and column.ts.timestamp = "bring [ts]" and column.dev.str = "bring [dev]" and column.nm.str = "bring [nm]" and column.tp.str = "bring [tp]" and column.w.float = "bring [w]" and column.kwh.float = "bring [kwh]")
