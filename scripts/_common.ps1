# Shared helpers for the IEMS PowerShell scripts. Dot sourced, not run.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

function Ok($m)   { Write-Host "  [ok]   $m" -ForegroundColor Green }
function Warn($m) { Write-Host "  [warn] $m" -ForegroundColor Yellow }
function Bad($m)  { Write-Host "  [fail] $m" -ForegroundColor Red }
function Step($m) { Write-Host ""; Write-Host $m -ForegroundColor White }
function Die($m)  { Bad $m; exit 1 }

function EnvVal($name) {
  if (-not (Test-Path .env)) { return "" }
  $line = Get-Content .env | Where-Object { $_ -match "^$name=" } | Select-Object -Last 1
  if (-not $line) { return "" }
  $v = $line.Substring($name.Length + 1).Trim()
  if ($v.Length -ge 2 -and (($v.StartsWith("'") -and $v.EndsWith("'")) -or ($v.StartsWith('"') -and $v.EndsWith('"')))) { $v = $v.Substring(1, $v.Length - 2) }
  return $v
}

function Need-Docker {
  if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { Die "Docker is not installed. See docs/guide/01_requirements.md" }
  docker info *> $null
  if ($LASTEXITCODE -ne 0) { Die "Docker is installed but not running. Start Docker Desktop and try again" }
  $v = (docker compose version --short) -replace '^v',''
  if ($LASTEXITCODE -ne 0) { Die "Docker Compose v2 is missing. Update Docker Desktop" }
  $p = $v.Split('.')
  if ([int]$p[0] -lt 2 -or ([int]$p[0] -eq 2 -and [int]$p[1] -lt 24)) { Die "Docker Compose $v is too old, 2.24 or newer is needed. Update Docker Desktop" }
}

function Port-Busy($port) {
  try { return [bool](Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction Stop) } catch { return $false }
}

function AnyLog($port, $cmd) {
  try { return (Invoke-WebRequest -UseBasicParsing -TimeoutSec 8 -Uri "http://127.0.0.1:$port" -Headers @{ "User-Agent" = "AnyLog/1.23"; "command" = $cmd }).Content } catch { return "" }
}

function Recent-Rows($table) {
  $u = EnvVal "POSTGRES_USER"; if (-not $u) { $u = "admin" }
  $db = EnvVal "POSTGRES_DB"; if (-not $db) { $db = "customers" }
  $pw = EnvVal "POSTGRES_PASSWORD"; if (-not $pw) { $pw = "passwd" }
  $part = (docker compose exec -T -e PGPASSWORD=$pw postgres psql -U $u -d $db -tAc "select tablename from pg_tables where tablename like 'par\_$table\_%' order by tablename desc limit 1" 2>$null | Out-String).Trim()
  if (-not $part) { return $null }
  $n = (docker compose exec -T -e PGPASSWORD=$pw postgres psql -U $u -d $db -tAc "select count(*) from $part where insert_timestamp >= now() at time zone 'utc' - interval '2 minutes'" 2>$null | Out-String).Trim()
  if ($n -match '^\d+$') { return [int]$n } else { return $null }
}

function Http-Ok($url) {
  try { return ((Invoke-WebRequest -UseBasicParsing -TimeoutSec 10 -Uri $url).StatusCode -eq 200) } catch { return $false }
}
