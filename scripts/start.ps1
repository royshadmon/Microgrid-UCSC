# Build and start the stack on Windows, wait for it, and print the addresses.
#   powershell -ExecutionPolicy Bypass -File .\scripts\start.ps1
#   add -NoBuild to skip rebuilding the local images
param([switch]$NoBuild)
. "$PSScriptRoot\_common.ps1"
Need-Docker
if (-not (Test-Path .env)) { Die "no .env yet. Run .\scripts\setup.ps1 first" }
if (-not (EnvVal "ANYLOG_LICENSE")) { Die "ANYLOG_LICENSE is empty in .env. See docs/guide/03_configure.md" }

if (-not $NoBuild) {
  Step "1. Building the local images (5 to 15 minutes the first time, seconds after that)"
  docker compose build --quiet
  if ($LASTEXITCODE -ne 0) { Die "a build failed, see the messages above" }
  Ok "images built"
}
Step ("2. Starting containers (profiles: " + (EnvVal "COMPOSE_PROFILES") + ")")
docker compose up -d --quiet-pull
if ($LASTEXITCODE -ne 0) {
  Bad "docker compose up failed"
  Write-Host "  If the message mentions anylogco/anylog-network and 'pull access denied', log in to"
  Write-Host "  Docker Hub with the account the AnyLog team gave you:  docker login"
  exit 1
}

Step "3. Waiting for the AnyLog operator"
$up = $false
for ($i = 0; $i -lt 60; $i++) { if ((AnyLog 32149 "get status") -match "running") { $up = $true; break }; Start-Sleep 5 }
if ($up) { Ok "operator answers on 32149" } else { Die "operator did not answer within 5 minutes. Look at .\scripts\logs.ps1 operator1" }
if ((AnyLog 32049 "get status") -match "running") { Ok "master answers on 32049" } else { Warn "master is not answering yet" }
# On a brand new install the operator policy is created during the first boot,
# after the step that declares the operator has already run. One restart fixes it.
function Op-Running { return ((AnyLog 32149 "get processes") -match "Operator +\|Running") }
Start-Sleep 10
if (Op-Running) { Ok "operator process is running" }
else {
  Write-Host "  first start, restarting operator1 once so it picks up its new policy"
  docker compose restart operator1 | Out-Null
  for ($i = 0; $i -lt 30; $i++) { Start-Sleep 5; if (Op-Running) { break } }
  if (Op-Running) { Ok "operator process is running" } else { Warn "operator process is not running yet, see .\scripts\logs.ps1 operator1" }
}

Step "4. Language model for Ask"
$model = EnvVal "OLLAMA_MODEL"; if (-not $model) { $model = "qwen2.5:1.5b-instruct" }
if ((docker compose exec -T ollama ollama list) -match [regex]::Escape($model)) { Ok "$model is present" }
else { Write-Host "  downloading $model (about 1 GB for the 1.5b model, once)"; docker compose exec -T ollama ollama pull $model; Ok "$model downloaded" }

Step "5. Dashboard"
$dport = EnvVal "DASHBOARD_PORT"; if (-not $dport) { $dport = 47821 }
for ($i = 0; $i -lt 30; $i++) { if (Http-Ok "http://127.0.0.1:$dport/") { Ok "dashboard is up"; break }; Start-Sleep 3 }

$bport = EnvVal "BACKEND_PORT"; if (-not $bport) { $bport = 8009 }
$profiles = "," + (EnvVal "COMPOSE_PROFILES") + ","
Step "Ready"
Write-Host "  Dashboard       http://localhost:$dport"
Write-Host "  Engine API      http://localhost:$bport/docs"
Write-Host "  AnyLog REST     http://localhost:32149"
if ($profiles -like "*,gui,*")   { Write-Host ("  Remote GUI      http://localhost:" + (EnvVal "GUI_PORT")) }
if ($profiles -like "*,tools,*") { Write-Host ("  Kafka UI        http://localhost:" + (EnvVal "KAFKA_UI_PORT")) }
Write-Host ""
Write-Host "  Appliance results need about 10 minutes of data before the first ones appear."
Write-Host "  Check progress with  .\scripts\status.ps1"
