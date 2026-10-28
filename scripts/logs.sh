#!/usr/bin/env bash
# Follow the logs of one service, or of all of them.
#   ./scripts/logs.sh                 everything
#   ./scripts/logs.sh iems-inference  one service
set -euo pipefail
source "$(dirname "$0")/_common.sh"
need_docker
compose logs -f --tail 100 "$@"
