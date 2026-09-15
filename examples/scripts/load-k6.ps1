# Generate sustained realistic traffic with k6 (grafana/k6 in Docker, no local install).
# Targets the examples only: insurance-direct (:8083 -> ubix) + retail-collector (:8084 -> digiflow).
# Usage: .\examples\scripts\load-k6.ps1 [-DurationMin 5] [-Vus 10] [-Chaos off|latency|rejects]
param(
  [int]$DurationMin = 5,
  [int]$Vus = 10,
  [ValidateSet("off", "latency", "rejects")]
  [string]$Chaos = "off",
  [switch]$h,
  [switch]$Help
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSCommandPath))
$PlatformCompose = Join-Path $Root "compose.local.yml"
$InsCompose = Join-Path $Root "examples\insurance-direct\docker-compose.yml"
$RetailCompose = Join-Path $Root "examples\retail-collector\docker-compose.yml"
$LoadDir = Join-Path $Root "examples\load"

if ($h -or $Help) {
  @'
Usage: .\examples\scripts\load-k6.ps1 [-DurationMin 5] [-Vus 10] [-Chaos off|latency|rejects]

  -DurationMin  steady-load minutes (default 5; ramp adds +2m, or +1m when <= 2)
  -Vus          virtual users per scenario (default 10; insurance + retail run together)
  -Chaos        off | latency | rejects (default off)
                latency: CHAOS_LATENCY_MS=2500 on risk-service (trips 2s timeout)
                         + CHAOS_LATENCY_MS=2500 on retail-api (processing delay)
                rejects: CHAOS_REJECT_RATE=0.3 on risk-service (reject storm)
                         + CHAOS_FAIL_RATE=0.3 on retail-api (500 storm)

Examples:
  .\examples\scripts\load-k6.ps1 -DurationMin 1 -Vus 2
  .\examples\scripts\load-k6.ps1 -DurationMin 5 -Vus 10 -Chaos latency

Notes:
  k6 runs in Docker (grafana/k6) on the default bridge network via
  http://host.docker.internal:8083|:8084 (Docker Desktop resolves it).
  Start everything first: .\examples\scripts\up.ps1
'@
  exit 0
}

if ($DurationMin -lt 1) { throw "-DurationMin must be >= 1." }
if ($Vus -lt 1) { throw "-Vus must be >= 1." }

$RampMin = 2
if ($DurationMin -le 2) { $RampMin = 1 }

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw "docker not found in PATH." }
if (-not (Test-Path -LiteralPath (Join-Path $LoadDir "examples-load.js"))) {
  throw "examples/load/examples-load.js not found. Run from the repo root."
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

# Single source of truth (mirrors up.ps1): chaos `compose up -d` recreates
# risk-service and retail-api, so the platform tokens must be exported.
$RootEnv = Join-Path $Root ".env"
$env:UBIX_OTEL_TOKEN = Get-EnvValue $RootEnv "UBIX_OTEL_TOKEN"
$env:DIGIFLOW_OTEL_TOKEN = Get-EnvValue $RootEnv "DIGIFLOW_OTEL_TOKEN"
if ([string]::IsNullOrWhiteSpace($env:UBIX_OTEL_TOKEN) -or [string]::IsNullOrWhiteSpace($env:DIGIFLOW_OTEL_TOKEN)) {
  throw "UBIX_OTEL_TOKEN / DIGIFLOW_OTEL_TOKEN missing in $RootEnv. Copy .env.example to .env and set both tokens."
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

function Set-Chaos($Latency, $Rate) {
  Write-Host "== chaos CHAOS_LATENCY_MS=$Latency CHAOS_REJECT/FAIL_RATE=$Rate =="
  $env:CHAOS_LATENCY_MS = $Latency
  $env:CHAOS_REJECT_RATE = $Rate
  try {
    $b = @("compose", "-f", $InsCompose, "up", "-d", "risk-service"); & docker @b
    $env:CHAOS_FAIL_RATE = $Rate
    $c = @("compose", "-f", $RetailCompose, "up", "-d", "retail-api"); & docker @c
  } finally {
    Remove-Item Env:\CHAOS_LATENCY_MS -ErrorAction SilentlyContinue
    Remove-Item Env:\CHAOS_REJECT_RATE -ErrorAction SilentlyContinue
    Remove-Item Env:\CHAOS_FAIL_RATE -ErrorAction SilentlyContinue
  }
}

Write-Host "== insurance (direct -> ubix) =="
if (Wait-Tcp 8083 5) { Write-Host "ok 127.0.0.1:8083 (insurance-api)" }
else { Write-Warning "127.0.0.1:8083 not reachable - start the stack first: .\examples\scripts\up.ps1" }
Write-Host "== retail (collector -> digiflow) =="
if (Wait-Tcp 8084 5) { Write-Host "ok 127.0.0.1:8084 (retail-api)" }
else { Write-Warning "127.0.0.1:8084 not reachable - start the stack first: .\examples\scripts\up.ps1" }
Write-Host "== pipeline =="
$platform = & docker compose -f $PlatformCompose ps --status running otel-gateway otel-collector 2>$null
if ($LASTEXITCODE -eq 0) { Write-Host "ok platform gateway + collector are running (OTLP/HTTP :4318)" }
else { Write-Warning "platform services are not all running (see docker compose logs)" }

if ($Chaos -eq "latency") { Set-Chaos "2500" "0" }
elseif ($Chaos -eq "rejects") { Set-Chaos "0" "0.3" }

$K6Exit = 0
try {
  Write-Host "== k6 (insurance + retail, Vus=$Vus steady=${DurationMin}m ramp=${RampMin}m chaos=$Chaos) =="
  $k6Args = @(
    "run", "--rm", "-i",
    "--network", "bridge",
    "-e", "INSURANCE_URL=http://host.docker.internal:8083",
    "-e", "RETAIL_URL=http://host.docker.internal:8084",
    "-e", "VUS=$Vus",
    "-e", "RAMP_MIN=$RampMin",
    "-e", "STEADY_MIN=$DurationMin",
    "-e", "CHAOS_MODE=$Chaos",
    "-v", "${LoadDir}:/scripts:ro",
    "grafana/k6", "run", "/scripts/examples-load.js"
  )
  & docker @k6Args
  $K6Exit = $LASTEXITCODE
} finally {
  if ($Chaos -ne "off") {
    Write-Host "== chaos restore (0/0) =="
    Set-Chaos "0" "0"
  }
}

Write-Host ""
Write-Host "Endpoints: Insurance API http://localhost:8083, Retail API http://localhost:8084,"
Write-Host "  Gateway http://localhost:4318/healthz, Grafana http://localhost:3000."
exit $K6Exit
