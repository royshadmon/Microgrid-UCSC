#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# pat_export_remote.sh  (runs ON Pat's box, invoked by export_pat_data.sh)
#
# Dumps the real house data out of the production Postgres behind AnyLog so
# the GX10 can train and replay it with no live link to the house.
#
#   egauge_6s/YYYY-MM-DD.csv.gz    6 s sample-and-hold grid, long format
#                                  (ts, channel, w). Same grid and the same
#                                  "last value at or before the grid point"
#                                  rule feature_builder._resample_uniform uses
#                                  at inference, so training sees what the
#                                  runtime sees.
#   egauge_1s/YYYY-MM-DD.csv.gz    raw 1 s readings for the newest REPLAY_DAYS
#                                  days, used by the replay producer.
#   solar.csv.gz                   Solar Assistant rows (5 s), all of them.
#   models/                        the ONNX + norm files baked into the
#                                  running iems-inference image.
#   MANIFEST.txt                   row counts and checksums.
#
# Per-day files make the export resumable: a day already on disk is skipped.
# All queries go through the ts index, about 20 s per day on Pat's box.
#
# Env: START (YYYY-MM-DD, default first day with data), END (exclusive,
#      default today UTC), REPLAY_DAYS (default 3), OUT (default
#      ~/gx10_export), TABLE (egauge_kafka | energy_readings),
#      SUDO_PASS (only if sudo needs a password for docker).
# ---------------------------------------------------------------------------
set -euo pipefail

OUT="${OUT:-$HOME/gx10_export}"
TABLE="${TABLE:-egauge_kafka}"
REPLAY_DAYS="${REPLAY_DAYS:-3}"
PG_CONTAINER="${PG_CONTAINER:-postgres1}"
mkdir -p "$OUT/egauge_6s" "$OUT/egauge_1s" "$OUT/models"

if [ -n "${SUDO_PASS:-}" ]; then
  D() { printf '%s\n' "$SUDO_PASS" | sudo -S -p "" docker "$@"; }
elif docker ps >/dev/null 2>&1; then
  D() { docker "$@"; }
else
  D() { sudo -n docker "$@"; }
fi

psql_q() {  # $1 = SQL, output to stdout
  D exec "$PG_CONTAINER" sh -c \
    "PGPASSWORD=\$POSTGRES_PASSWORD psql -U \$POSTGRES_USER -d customers -q -t -A -c \"$1\""
}

# AnyLog writes one physical partition per month: par_<table>_YYYY_MM_m01_insert_timestamp
parts() {
  psql_q "select tablename from pg_tables where tablename like 'par_${1}_%' order by tablename;"
}

# Map a day to the partition(s) that can hold it (rows near midnight on the
# 1st can land in the previous month's partition, so check both).
day_parts() {
  local day="$1" base="$2" ym prev
  ym=$(date -u -d "$day" +%Y_%m)
  prev=$(date -u -d "$day -1 day" +%Y_%m)
  for p in $(parts "$base"); do
    case "$p" in *"_${ym}_"*|*"_${prev}_"*) echo "$p";; esac
  done | sort -u
}

union_sql() {  # $1 = base table, $2 = day, $3 = select list
  local day="$2" next first=1 sql=""
  next=$(date -u -d "$day +1 day" +%F)
  for p in $(day_parts "$day" "$1"); do
    [ $first -eq 1 ] || sql="$sql UNION ALL "
    sql="$sql SELECT $3 FROM $p WHERE ts >= '$day' AND ts < '$next'"
    first=0
  done
  echo "$sql"
}

ALL_PARTS=$(parts "$TABLE")
[ -n "$ALL_PARTS" ] || { echo "no partitions for $TABLE" >&2; exit 1; }
if [ -z "${START:-}" ]; then
  START=$(psql_q "select to_char(min(ts),'YYYY-MM-DD') from $(echo "$ALL_PARTS" | head -1);")
fi
END="${END:-$(date -u +%F)}"
echo "[export] table=$TABLE start=$START end=$END (exclusive) out=$OUT"

# -- 6 s training grid ------------------------------------------------------
day="$START"
while [[ "$day" < "$END" ]]; do
  f="$OUT/egauge_6s/$day.csv.gz"
  if [ -s "$f" ]; then day=$(date -u -d "$day +1 day" +%F); continue; fi
  inner=$(union_sql "$TABLE" "$day" "date_bin('6 seconds', ts, timestamp '2026-01-01') AS b, ts, nm, w")
  if [ -z "$inner" ]; then day=$(date -u -d "$day +1 day" +%F); continue; fi
  q="COPY (SELECT DISTINCT ON (b, nm) to_char(b,'YYYY-MM-DD HH24:MI:SS') AS ts, nm AS channel, w FROM ($inner) s ORDER BY b, nm, ts DESC) TO STDOUT WITH CSV HEADER"
  t0=$(date +%s)
  D exec "$PG_CONTAINER" sh -c \
    "PGPASSWORD=\$POSTGRES_PASSWORD psql -U \$POSTGRES_USER -d customers -q -c \"$q\"" \
    | gzip > "$f.part"
  mv "$f.part" "$f"
  echo "  6s  $day  $(zcat "$f" | tail -n +2 | wc -l) rows  $(( $(date +%s) - t0 ))s"
  day=$(date -u -d "$day +1 day" +%F)
done

# -- 1 s replay days (newest complete days) ---------------------------------
for i in $(seq "$REPLAY_DAYS" -1 1); do
  day=$(date -u -d "$END -$i day" +%F)
  f="$OUT/egauge_1s/$day.csv.gz"
  [ -s "$f" ] && continue
  inner=$(union_sql "$TABLE" "$day" "ts, nm, w")
  [ -n "$inner" ] || continue
  q="COPY (SELECT to_char(ts,'YYYY-MM-DD HH24:MI:SS') AS ts, nm AS channel, w FROM ($inner) s ORDER BY ts, nm) TO STDOUT WITH CSV HEADER"
  D exec "$PG_CONTAINER" sh -c \
    "PGPASSWORD=\$POSTGRES_PASSWORD psql -U \$POSTGRES_USER -d customers -q -c \"$q\"" \
    | gzip > "$f.part"
  mv "$f.part" "$f"
  echo "  1s  $day  $(zcat "$f" | tail -n +2 | wc -l) rows"
done

# -- Solar Assistant --------------------------------------------------------
sol=""
for p in $(parts solar_data); do
  [ -n "$sol" ] && sol="$sol UNION ALL "
  sol="$sol SELECT ts, pv_power, battery_power, battery_soc, grid_power, load_power, device_mode FROM $p"
done
if [ -n "$sol" ]; then
  q="COPY (SELECT to_char(ts,'YYYY-MM-DD HH24:MI:SS') AS ts, pv_power, battery_power, battery_soc, grid_power, load_power, device_mode FROM ($sol) s ORDER BY ts) TO STDOUT WITH CSV HEADER"
  D exec "$PG_CONTAINER" sh -c \
    "PGPASSWORD=\$POSTGRES_PASSWORD psql -U \$POSTGRES_USER -d customers -q -c \"$q\"" \
    | gzip > "$OUT/solar.csv.gz"
  echo "  solar  $(zcat "$OUT/solar.csv.gz" | tail -n +2 | wc -l) rows"
fi

# -- Deployed models (what iems-inference actually loaded) ------------------
for f in nilm_panel1.onnx nilm_panel2.onnx nilm_panel3.onnx \
         panel1_norm_bilstm.json panel2_norm_bilstm.json panel3_norm_bilstm.json; do
  D exec iems-inference cat "/app/services/iems/models/$f" > "$OUT/models/$f"
done
echo "  models  $(ls "$OUT/models" | wc -l) files"

{
  echo "exported_at_utc $(date -u +%FT%TZ)"
  echo "host $(hostname) table $TABLE start $START end $END"
  echo "egauge_6s_days $(ls "$OUT/egauge_6s" | wc -l)"
  echo "egauge_1s_days $(ls "$OUT/egauge_1s" | wc -l)"
  (cd "$OUT" && find . -type f ! -name MANIFEST.txt -printf '%P\n' | sort | xargs md5sum)
} > "$OUT/MANIFEST.txt"
echo "[export] done -> $OUT"
