# Stop the local demo (reverse order of up.ps1).
# Usage: .\examples\scripts\down.ps1 [-Volumes]   # also removes named volumes
param(
  [switch]$Volumes
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSCommandPath))
$Platform = Join-Path $Root "compose.local.yml"
$InsDir = Join-Path $Root "examples\insurance-direct"
$RetailDir = Join-Path $Root "examples\retail-collector"

function Get-EnvValue($File, $Key) {
  $line = Select-String -LiteralPath $File -Pattern "^\s*(export\s+)?$Key=" -ErrorAction SilentlyContinue |
    Select-Object -Last 1
  if ($null -eq $line) { return "" }
  $val = $line.Line -replace "^\s*(export\s+)?$Key=", ""
  $val = $val.Trim().Trim("'", '"')
  $val = ($val -split '\s#', 2)[0].Trim().Trim("'", '"')
  return $val
}

# down only needs interpolation to succeed, not real secrets.
$RootEnv = Join-Path $Root ".env"
$env:KEVE_UBIX_OTEL_TOKEN = Get-EnvValue $RootEnv "KEVE_UBIX_OTEL_TOKEN"
$env:KEVE_DIGIFLOW_OTEL_TOKEN = Get-EnvValue $RootEnv "KEVE_DIGIFLOW_OTEL_TOKEN"
$env:BCI_UBIX_OTEL_TOKEN = Get-EnvValue $RootEnv "BCI_UBIX_OTEL_TOKEN"
$env:BCI_DIGIFLOW_OTEL_TOKEN = Get-EnvValue $RootEnv "BCI_DIGIFLOW_OTEL_TOKEN"
$env:KEYCLOAK_GRAFANA_CLIENT_SECRET = Get-EnvValue $RootEnv "KEYCLOAK_GRAFANA_CLIENT_SECRET"
if ([string]::IsNullOrWhiteSpace($env:KEVE_UBIX_OTEL_TOKEN)) { $env:KEVE_UBIX_OTEL_TOKEN = "placeholder-for-down" }
if ([string]::IsNullOrWhiteSpace($env:KEVE_DIGIFLOW_OTEL_TOKEN)) { $env:KEVE_DIGIFLOW_OTEL_TOKEN = "placeholder-for-down" }
if ([string]::IsNullOrWhiteSpace($env:BCI_UBIX_OTEL_TOKEN)) { $env:BCI_UBIX_OTEL_TOKEN = "placeholder-for-down" }
if ([string]::IsNullOrWhiteSpace($env:BCI_DIGIFLOW_OTEL_TOKEN)) { $env:BCI_DIGIFLOW_OTEL_TOKEN = "placeholder-for-down" }
if ([string]::IsNullOrWhiteSpace($env:KEYCLOAK_GRAFANA_CLIENT_SECRET)) { $env:KEYCLOAK_GRAFANA_CLIENT_SECRET = "placeholder-for-down" }

function Invoke-ComposeDown($ComposeFile, $EnvFile = $null) {
  $composeArgs = @("compose", "-f", $ComposeFile)
  if ($EnvFile) { $composeArgs += @("--env-file", $EnvFile) }
  $composeArgs += @("down")
  if ($Volumes) { $composeArgs += "-v" }
  # docker compose writes progress to stderr, which PowerShell surfaces as
  # ErrorRecords; run with 'Continue' so informational lines can't abort the
  # script under $ErrorActionPreference='Stop'. Real failures use the exit code.
  $prevPref = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  try {
    & docker @composeArgs 2>&1 | ForEach-Object { "$_" }
    $code = $LASTEXITCODE
  } finally { $ErrorActionPreference = $prevPref }
  if ($code -ne 0) { throw "docker compose down failed for $ComposeFile (exit $code)." }
}

Invoke-ComposeDown (Join-Path $RetailDir "docker-compose.bci.yml") (Join-Path $RetailDir ".env.bci")
Invoke-ComposeDown (Join-Path $RetailDir "docker-compose.yml")
Invoke-ComposeDown (Join-Path $InsDir "docker-compose.bci.yml") (Join-Path $InsDir ".env.bci")
Invoke-ComposeDown (Join-Path $InsDir "docker-compose.yml")
Invoke-ComposeDown $Platform

Write-Host "All stacks stopped."
