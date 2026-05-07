run operator where create_table=true and update_tsd_info=true and archive_json=true and master_node=host.docker.internal:32048 and policy=bcc22d1407475e2d3013e2aaf66ce2bb and threads=3

run kafka consumer where ip = host.docker.internal and port = 9094 and reset = latest and topic = (name = egauge-energy and dbms = customers and table = egauge_kafka and column.ts.timestamp = "bring [ts]" and column.dev.str = "bring [dev]" and column.nm.str = "bring [nm]" and column.tp.str = "bring [tp]" and column.w.float = "bring [w]" and column.kwh.float = "bring [kwh]")
