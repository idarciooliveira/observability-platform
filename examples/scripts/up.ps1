# Start the local demo: platform (compose.local.yml) + insurance-direct + retail-collector.
# Fresh-clone safe: bootstraps missing .env files from .env.example and
# exports the platform tokens so both examples always agree with the gateway.
# Usage: .\examples\scripts\up.ps1 [-NoBuild]
param(
  [switch]$NoBuild
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSCommandPath))
$Platform = Join-Path $Root "compose.local.yml"
$InsDir = Join-Path $Root "examples\insurance-direct"
$RetailDir = Join-Path $Root "examples\retail-collector"

function Copy-IfMissing($Example, $Target) {
  if (-not (Test-Path -LiteralPath $Target)) {
    if (Test-Path -LiteralPath $Example) {
      Copy-Item -LiteralPath $Example -Destination $Target
      Write-Host "created $Target from example (edit it for real secrets)"
    } else {
      Write-Warning "neither $Target nor $Example exists, continuing with compose defaults"
    }
  }
}

function Get-EnvValue($File, $Key) {
  $line = Select-String -LiteralPath $File -Pattern "^\s*(export\s+)?$Key=" -ErrorAction SilentlyContinue |
    Select-Object -Last 1
  if ($null -eq $line) { return "" }
  $val = $line.Line -replace "^\s*(export\s+)?$Key=", ""
  $val = $val.Trim().Trim("'", '"')
  $val = ($val -split '\s#', 2)[0].Trim().Trim("'", '"')
  return $val
}

function Wait-Tcp($Port, $Tries = 30) {
  for ($i = 1; $i -le $Tries; $i++) {
    try {
      $c = New-Object Net.Sockets.TcpClient
      $iar = $c.BeginConnect("127.0.0.1", $Port, $null, $null)
      if ($iar.AsyncWaitHandle.WaitOne(2000) -and $c.Connected) { $c.Close(); return $true }
      $c.Close()
    } catch { }
    Start-Sleep -Seconds 2
  }
  return $false
}

# 1. Bootstrap .env files (all gitignored, only *.example is committed).
Copy-IfMissing (Join-Path $Root ".env.example") (Join-Path $Root ".env")
Copy-IfMissing (Join-Path $InsDir ".env.example") (Join-Path $InsDir ".env")
Copy-IfMissing (Join-Path $RetailDir ".env.example") (Join-Path $RetailDir ".env")

# 2. Single source of truth: tokens come from the PLATFORM .env and are exported
#    so `docker compose` interpolation in the example stacks cannot drift.
$RootEnv = Join-Path $Root ".env"
$env:UBIX_OTEL_TOKEN = Get-EnvValue $RootEnv "UBIX_OTEL_TOKEN"
$env:DIGIFLOW_OTEL_TOKEN = Get-EnvValue $RootEnv "DIGIFLOW_OTEL_TOKEN"
if ([string]::IsNullOrWhiteSpace($env:UBIX_OTEL_TOKEN) -or [string]::IsNullOrWhiteSpace($env:DIGIFLOW_OTEL_TOKEN)) {
  throw "UBIX_OTEL_TOKEN / DIGIFLOW_OTEL_TOKEN missing in $RootEnv. Copy .env.example to .env and set both tokens."
}
$env:KEYCLOAK_GRAFANA_CLIENT_SECRET = Get-EnvValue $RootEnv "KEYCLOAK_GRAFANA_CLIENT_SECRET"
if ([string]::IsNullOrWhiteSpace($env:KEYCLOAK_GRAFANA_CLIENT_SECRET)) {
  throw "KEYCLOAK_GRAFANA_CLIENT_SECRET missing in $RootEnv. Set it before starting."
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw "docker not found in PATH." }

function Invoke-ComposeUp($ComposeFile) {
  $composeArgs = @("compose", "-f", $ComposeFile, "up", "-d")
  if (-not $NoBuild) { $composeArgs += "--build" }
  & docker @composeArgs
}

# 3. Start in dependency order: platform first, examples second.
Write-Host "== platform (compose.local.yml) =="
Invoke-ComposeUp $Platform
Write-Host "== insurance-direct (ubix, direct OTLP) =="
Invoke-ComposeUp (Join-Path $InsDir "docker-compose.yml")
Write-Host "== retail-collector (digiflow, local collector) =="
Invoke-ComposeUp (Join-Path $RetailDir "docker-compose.yml")

# 4. Poll the public surface from the host.
foreach ($p in 4318, 3000, 8083, 8082, 8084) {
  if (Wait-Tcp $p) { Write-Host "ok 127.0.0.1:$p" }
  else { Write-Warning "127.0.0.1:$p not reachable yet (see docker compose ps/logs)" }
}

@'

All stacks started:
  Gateway       http://localhost:4318/healthz (OTLP/HTTP + Bearer)
  Grafana       http://localhost:3000 (admin/admin local demo)
  Insurance API http://localhost:8083  (container :8080, direct -> ubix)
  Risk svc      http://localhost:8082
  Retail API    http://localhost:8084  (container :8080, via retail-collector -> digiflow)

Useful:
  .\examples\scripts\down.ps1                # stop everything
  .\examples\scripts\load-k6.ps1 -DurationMin 1 -Vus 2   # smoke traffic
'@
