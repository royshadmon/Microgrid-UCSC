# First time setup on Windows. Safe to run again at any time.
#   powershell -ExecutionPolicy Bypass -File .\scripts\setup.ps1
. "$PSScriptRoot\_common.ps1"

Step "1. Docker"
Need-Docker
Ok ("Docker " + (docker version --format '{{.Server.Version}}') + " with Compose " + (docker compose version --short))
$mem = [int64](docker info --format '{{.MemTotal}}')
$gb = [math]::Floor($mem / 1GB)
if ($gb -lt 6) { Warn "Docker has $gb GB of memory. 8 GB or more is recommended (Docker Desktop, Settings, Resources, or .wslconfig)" } else { Ok "Docker has $gb GB of memory" }

Step "2. Settings file"
if (Test-Path .env) { Ok ".env already exists, leaving it as it is" } else { Copy-Item .env.example .env; Ok "created .env from .env.example" }
if (-not (EnvVal "ANYLOG_LICENSE")) {
  Write-Host ""
  Write-Host "  The AnyLog nodes need a license key (see docs/guide/03_configure.md)."
  $lic = Read-Host "  Paste it now and press Enter, or just press Enter to add it to .env later"
  if ($lic) {
    $lic = $lic.Replace("'", "")
    $lines = Get-Content .env | ForEach-Object { if ($_ -match '^ANYLOG_LICENSE=') { "ANYLOG_LICENSE='$lic'" } else { $_ } }
    Set-Content -Path .env -Value $lines -Encoding ascii
    Ok "license saved to .env"
  } else { Warn "no license yet. Add ANYLOG_LICENSE to .env before .\scripts\start.ps1" }
} else { Ok "ANYLOG_LICENSE is set" }
Ok ("profiles to run: " + (EnvVal "COMPOSE_PROFILES"))

Step "3. Ports"
$busy = $false
foreach ($p in @(5432, 9092, 9094, 32048, 32049, 32148, 32149, 1883, (EnvVal "DASHBOARD_PORT"), (EnvVal "BACKEND_PORT"), (EnvVal "OLLAMA_PORT"))) {
  if (-not $p) { continue }
  if (Port-Busy ([int]$p)) {
    if ((docker ps --format '{{.Ports}}') -match ":$p->") { Warn "port $p is used by a container that is already running (fine if it is this stack)" }
    else { Bad "port $p is already in use by another program"; $busy = $true }
  }
}
if (-not $busy) { Ok "ports look free" } else { Warn "free the ports above, or change the movable ones in section 7 of .env" }

Step "4. Download images (this takes a while the first time)"
$out = docker compose pull --ignore-buildable --quiet 2>&1 | Out-String
if ($LASTEXITCODE -eq 0) { Ok "images ready" }
elseif ($out -match "access denied") {
  docker image inspect (EnvVal "ANYLOG_IMAGE") *> $null
  if ($LASTEXITCODE -eq 0) { Ok "AnyLog image already on this computer" }
  else { Bad "Docker Hub refused the AnyLog image. Run  docker login  with the account the AnyLog team gave you, then run setup again" }
} else { Write-Host $out; Warn "some images could not be pulled now, start will retry" }

Step "Done"
Write-Host "  Next run  powershell -ExecutionPolicy Bypass -File .\scripts\start.ps1"
