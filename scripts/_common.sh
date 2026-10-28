# Shared helpers for the IEMS scripts. Sourced, not run.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [ -t 1 ]; then G=$'\033[32m'; Y=$'\033[33m'; R=$'\033[31m'; B=$'\033[1m'; N=$'\033[0m'; else G=; Y=; R=; B=; N=; fi
ok()   { printf '  %s[ok]%s   %s\n' "$G" "$N" "$*"; }
warn() { printf '  %s[warn]%s %s\n' "$Y" "$N" "$*"; }
bad()  { printf '  %s[fail]%s %s\n' "$R" "$N" "$*"; }
step() { printf '\n%s%s%s\n' "$B" "$*" "$N"; }
die()  { bad "$*"; exit 1; }

# Read one value from .env without sourcing it (values may contain { } and quotes).
envval() {
  [ -f .env ] || return 0
  grep -E "^$1=" .env | tail -1 | cut -d= -f2- | sed -e 's/^"//' -e 's/"$//' -e "s/^'//" -e "s/'$//"
}

compose() { docker compose "$@"; }

need_docker() {
  command -v docker >/dev/null 2>&1 || die "Docker is not installed. See docs/guide/01_requirements.md"
  docker info >/dev/null 2>&1 || die "Docker is installed but not running. Start Docker Desktop (or the docker service) and try again"
  docker compose version >/dev/null 2>&1 || die "Docker Compose v2 is missing. Update Docker Desktop, or install the docker-compose-plugin package"
  local v; v=$(docker compose version --short 2>/dev/null | sed 's/^v//')
  local major minor; major=${v%%.*}; minor=$(echo "$v" | cut -d. -f2)
  if [ "${major:-0}" -lt 2 ] || { [ "${major:-0}" -eq 2 ] && [ "${minor:-0}" -lt 24 ]; }; then
    die "Docker Compose $v is too old, 2.24 or newer is needed. Update Docker Desktop or the compose plugin"
  fi
}

port_busy() {
  local p=$1
  if command -v lsof >/dev/null 2>&1; then lsof -nP -iTCP:"$p" -sTCP:LISTEN >/dev/null 2>&1 && return 0
  elif command -v ss >/dev/null 2>&1; then ss -ltn "( sport = :$p )" 2>/dev/null | grep -q LISTEN && return 0
  elif command -v nc >/dev/null 2>&1; then nc -z 127.0.0.1 "$p" >/dev/null 2>&1 && return 0
  fi
  return 1
}

anylog() {  # anylog <port> <command>
  curl -s --max-time 8 "http://127.0.0.1:$1" -H "User-Agent: AnyLog/1.23" -H "command: $2"
}
recent_rows() {  # recent_rows <table>, rows inserted in the last 2 minutes, read from Postgres
  local u db pw part
  u=$(envval POSTGRES_USER); u=${u:-admin}; db=$(envval POSTGRES_DB); db=${db:-customers}
  pw=$(envval POSTGRES_PASSWORD); pw=${pw:-passwd}
  part=$(compose exec -T -e PGPASSWORD="$pw" postgres psql -U "$u" -d "$db" -tAc \
    "select tablename from pg_tables where tablename like 'par\\_$1\\_%' order by tablename desc limit 1" </dev/null 2>/dev/null | tr -d '[:space:]')
  [ -n "$part" ] || return 0
  compose exec -T -e PGPASSWORD="$pw" postgres psql -U "$u" -d "$db" -tAc \
    "select count(*) from $part where insert_timestamp >= now() at time zone 'utc' - interval '2 minutes'" </dev/null 2>/dev/null | tr -d '[:space:]'
}
