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
$env:UBIX_OTEL_TOKEN = Get-EnvValue $RootEnv "UBIX_OTEL_TOKEN"
$env:DIGIFLOW_OTEL_TOKEN = Get-EnvValue $RootEnv "DIGIFLOW_OTEL_TOKEN"
$env:KEYCLOAK_GRAFANA_CLIENT_SECRET = Get-EnvValue $RootEnv "KEYCLOAK_GRAFANA_CLIENT_SECRET"
if ([string]::IsNullOrWhiteSpace($env:UBIX_OTEL_TOKEN)) { $env:UBIX_OTEL_TOKEN = "placeholder-for-down" }
if ([string]::IsNullOrWhiteSpace($env:DIGIFLOW_OTEL_TOKEN)) { $env:DIGIFLOW_OTEL_TOKEN = "placeholder-for-down" }
if ([string]::IsNullOrWhiteSpace($env:KEYCLOAK_GRAFANA_CLIENT_SECRET)) { $env:KEYCLOAK_GRAFANA_CLIENT_SECRET = "placeholder-for-down" }

function Invoke-ComposeDown($ComposeFile) {
  $composeArgs = @("compose", "-f", $ComposeFile, "down")
  if ($Volumes) { $composeArgs += "-v" }
  & docker @composeArgs
}

Invoke-ComposeDown (Join-Path $RetailDir "docker-compose.yml")
Invoke-ComposeDown (Join-Path $InsDir "docker-compose.yml")
Invoke-ComposeDown $Platform

Write-Host "All stacks stopped."
