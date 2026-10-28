# Follow the logs of one service, or of all of them (Windows).
#   .\scripts\logs.ps1                 everything
#   .\scripts\logs.ps1 iems-inference  one service
. "$PSScriptRoot\_common.ps1"
Need-Docker
docker compose logs -f --tail 100 @args
