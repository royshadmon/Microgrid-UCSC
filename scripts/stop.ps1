# Stop the stack on Windows.
#   .\scripts\stop.ps1         stop, keep all data
#   .\scripts\stop.ps1 -Wipe   stop and delete all data
param([switch]$Wipe)
. "$PSScriptRoot\_common.ps1"
Need-Docker
if ($Wipe) {
  $ans = Read-Host "  This deletes every stored reading and the downloaded language model. Type yes to continue"
  if ($ans -ne "yes") { Write-Host "  nothing deleted"; exit 0 }
  docker compose --profile '*' down -v --remove-orphans
  Ok "stopped and wiped"
} else {
  docker compose --profile '*' down --remove-orphans
  Ok "stopped. Your data is kept, start again with .\scripts\start.ps1"
}
