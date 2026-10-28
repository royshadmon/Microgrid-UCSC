# Is everything running, and is data actually arriving? (Windows)
#   .\scripts\status.ps1
. "$PSScriptRoot\_common.ps1"
$ErrorActionPreference = "Continue"
Need-Docker

Step "Containers"
docker compose ps --format 'table {{.Name}}\t{{.State}}\t{{.Status}}'

Step "AnyLog nodes"
if ((AnyLog 32049 "get status") -match "running") { Ok "master" } else { Bad "master not answering on 32049" }
if ((AnyLog 32149 "get status") -match "running") { Ok "operator1" } else { Bad "operator1 not answering on 32149" }

Step "Rows received in the last 2 minutes"
foreach ($t in @("energy_readings", "egauge_kafka", "solar_data", "nilm_disaggregated")) {
  $n = Recent-Rows $t
  if ($n -gt 0) { Ok ("{0,-20} {1}" -f $t, $n) } else { Warn ("{0,-20} {1}" -f $t, $(if ($null -eq $n) { "no table yet" } else { $n })) }
}
Write-Host "  Expected in 2 minutes. energy_readings and egauge_kafka about 320 in demo mode or 1,900 with a"
Write-Host "  real meter, solar_data 4 to 24, nilm_disaggregated about 90 once 10 minutes of data exist."

Step "Engine and dashboard"
$bport = EnvVal "BACKEND_PORT"; if (-not $bport) { $bport = 8009 }
$dport = EnvVal "DASHBOARD_PORT"; if (-not $dport) { $dport = 47821 }
if (Http-Ok "http://127.0.0.1:$bport/") { Ok "engine on $bport" } else { Bad "engine not answering on $bport" }
try { $h = (Invoke-WebRequest -UseBasicParsing -TimeoutSec 20 "http://127.0.0.1:$bport/iems/ask/health").Content } catch { $h = "" }
if ($h -match '"model_present":\s*true') { Ok "Ask model loaded" } else { Warn "Ask model not ready (run .\scripts\start.ps1 again)" }
if (Http-Ok "http://127.0.0.1:$dport/") { Ok "dashboard on $dport" } else { Bad "dashboard not answering on $dport" }
