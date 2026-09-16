# Start the local demo: platform (compose.local.yml) + insurance-direct A/B + retail-collector A/B.
# Fresh-clone safe: bootstraps missing .env files and exports the platform
# tokens so all examples always agree with the gateway.
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

function Wait-Grafana($Tries = 30) {
  for ($i = 1; $i -le $Tries; $i++) {
    try {
      $response = Invoke-WebRequest -Uri "http://127.0.0.1:3000/api/health" -UseBasicParsing -TimeoutSec 3
      if ($response.StatusCode -eq 200) { return $true }
    } catch { }
    Start-Sleep -Seconds 2
  }
  return $false
}

function Get-KeycloakAdminToken($Tries = 30) {
  for ($i = 1; $i -le $Tries; $i++) {
    try {
      $response = Invoke-RestMethod `
        -Uri "http://127.0.0.1:8090/realms/master/protocol/openid-connect/token" `
        -Method Post `
        -ContentType "application/x-www-form-urlencoded" `
        -Body @{ client_id = "admin-cli"; username = "admin"; password = "admin"; grant_type = "password" }
      if ($response.access_token) { return $response.access_token }
    } catch { }
    Start-Sleep -Seconds 2
  }
  return $null
}

function Sync-KeycloakGrafanaClient {
  $token = Get-KeycloakAdminToken
  if ([string]::IsNullOrWhiteSpace($token)) {
    throw "Keycloak did not become ready for administration. Check: docker compose -f compose.local.yml logs keycloak"
  }

  $headers = @{ Authorization = "Bearer $token" }
  $clients = Invoke-RestMethod `
    -Uri "http://127.0.0.1:8090/admin/realms/observability/clients?clientId=grafana" `
    -Headers $headers -Method Get
  $client = @($clients) | Where-Object { $_.clientId -eq "grafana" } | Select-Object -First 1
  if ($null -eq $client) { throw "Keycloak client 'grafana' was not found in realm 'observability'." }

  $client.secret = $env:KEYCLOAK_GRAFANA_CLIENT_SECRET
  $body = $client | ConvertTo-Json -Depth 20 -Compress
  Invoke-RestMethod `
    -Uri "http://127.0.0.1:8090/admin/realms/observability/clients/$($client.id)" `
    -Headers $headers -Method Put -ContentType "application/json" -Body $body | Out-Null
  Write-Host "synchronized Keycloak client 'grafana' with KEYCLOAK_GRAFANA_CLIENT_SECRET"
}

# 1. Bootstrap .env files (variant A reads .env; variant B uses --env-file .env.bci).
Copy-IfMissing (Join-Path $Root ".env.example") (Join-Path $Root ".env")
Copy-IfMissing (Join-Path $InsDir ".env.example") (Join-Path $InsDir ".env")
Copy-IfMissing (Join-Path $InsDir ".env.example") (Join-Path $InsDir ".env.keve")
Copy-IfMissing (Join-Path $RetailDir ".env.example") (Join-Path $RetailDir ".env")
Copy-IfMissing (Join-Path $RetailDir ".env.example") (Join-Path $RetailDir ".env.keve")
if (-not (Test-Path -LiteralPath (Join-Path $InsDir ".env.bci"))) { Copy-IfMissing (Join-Path $InsDir ".env.example") (Join-Path $InsDir ".env.bci") }
if (-not (Test-Path -LiteralPath (Join-Path $RetailDir ".env.bci"))) { Copy-IfMissing (Join-Path $RetailDir ".env.example") (Join-Path $RetailDir ".env.bci") }

# 2. Single source of truth: tokens come from the PLATFORM .env and are exported
#    so `docker compose` interpolation in the example stacks cannot drift.
$RootEnv = Join-Path $Root ".env"
$env:KEVE_UBIX_OTEL_TOKEN = Get-EnvValue $RootEnv "KEVE_UBIX_OTEL_TOKEN"
$env:KEVE_DIGIFLOW_OTEL_TOKEN = Get-EnvValue $RootEnv "KEVE_DIGIFLOW_OTEL_TOKEN"
$env:BCI_UBIX_OTEL_TOKEN = Get-EnvValue $RootEnv "BCI_UBIX_OTEL_TOKEN"
$env:BCI_DIGIFLOW_OTEL_TOKEN = Get-EnvValue $RootEnv "BCI_DIGIFLOW_OTEL_TOKEN"
if ([string]::IsNullOrWhiteSpace($env:KEVE_UBIX_OTEL_TOKEN) -or [string]::IsNullOrWhiteSpace($env:KEVE_DIGIFLOW_OTEL_TOKEN) -or [string]::IsNullOrWhiteSpace($env:BCI_UBIX_OTEL_TOKEN) -or [string]::IsNullOrWhiteSpace($env:BCI_DIGIFLOW_OTEL_TOKEN)) {
  throw "KEVE_UBIX / KEVE_DIGIFLOW / BCI_UBIX / BCI_DIGIFLOW tokens missing in $RootEnv. Copy .env.example to .env and set all four tokens."
}
$env:KEYCLOAK_GRAFANA_CLIENT_SECRET = Get-EnvValue $RootEnv "KEYCLOAK_GRAFANA_CLIENT_SECRET"
if ([string]::IsNullOrWhiteSpace($env:KEYCLOAK_GRAFANA_CLIENT_SECRET)) {
  throw "KEYCLOAK_GRAFANA_CLIENT_SECRET missing in $RootEnv. Set it before starting."
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { throw "docker not found in PATH." }

function Invoke-ComposeUp($ComposeFile, $EnvFile = $null, $Service = $null, [switch]$BootstrapProfile) {
  $composeArgs = @("compose", "-f", $ComposeFile)
  if ($BootstrapProfile) { $composeArgs += @("--profile", "bootstrap") }
  if ($EnvFile) { $composeArgs += @("--env-file", $EnvFile) }
  $composeArgs += @("up", "-d")
  if (-not $NoBuild) { $composeArgs += "--build" }
  if ($Service) { $composeArgs += $Service }
  # docker compose writes progress to stderr, which PowerShell surfaces as
  # ErrorRecords; run with 'Continue' so informational lines can't abort the
  # script under $ErrorActionPreference='Stop'. Real failures use the exit code.
  $prevPref = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  try {
    & docker @composeArgs 2>&1 | ForEach-Object { "$_" }
    $code = $LASTEXITCODE
  } finally { $ErrorActionPreference = $prevPref }
  if ($code -ne 0) { throw "docker compose up failed for $ComposeFile (exit $code)." }
}

function Invoke-ComposeGrafanaContainer {
  $composeArgs = @("compose", "-f", $Platform, "rm", "-sf", "grafana")
  $prevPref = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  try {
    & docker @composeArgs 2>&1 | ForEach-Object { "$_" }
    $code = $LASTEXITCODE
  } finally { $ErrorActionPreference = $prevPref }
  if ($code -ne 0) { throw "docker compose rm grafana failed (exit $code)." }
}

function Invoke-ComposeGrafanaBootstrapContainer {
  $composeArgs = @("compose", "-f", $Platform, "--profile", "bootstrap", "rm", "-sf", "grafana-bootstrap")
  $prevPref = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  try {
    & docker @composeArgs 2>&1 | ForEach-Object { "$_" }
    $code = $LASTEXITCODE
  } finally { $ErrorActionPreference = $prevPref }
  if ($code -ne 0) { throw "docker compose rm grafana-bootstrap failed (exit $code)." }
}

function Get-GrafanaHeaders {
  $raw = "admin:admin"
  $encoded = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes($raw))
  return @{ Authorization = "Basic $encoded" }
}

function Ensure-GrafanaOrg($Name, $ExpectedId) {
  $headers = Get-GrafanaHeaders
  $orgs = Invoke-RestMethod -Uri "http://127.0.0.1:3000/api/orgs?perpage=100" -Headers $headers -Method Get
  $org = @($orgs) | Where-Object { $_.name -eq $Name } | Select-Object -First 1
  if ($null -eq $org) {
    $body = @{ name = $Name } | ConvertTo-Json -Compress
    try {
      $org = Invoke-RestMethod -Uri "http://127.0.0.1:3000/api/orgs" -Headers $headers -Method Post -ContentType "application/json" -Body $body
      Write-Host "created Grafana organization '$Name' (id $($org.orgId))"
      $org | Add-Member -NotePropertyName id -NotePropertyValue $org.orgId -Force
    } catch {
      if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 409) {
        $orgs = Invoke-RestMethod -Uri "http://127.0.0.1:3000/api/orgs?perpage=100" -Headers $headers -Method Get
        $org = @($orgs) | Where-Object { $_.name -eq $Name } | Select-Object -First 1
      }
      if ($null -eq $org) { throw "Unable to create Grafana organization '$Name': $($_.Exception.Message)" }
    }
  }

  if ([int]$org.id -ne $ExpectedId) {
    throw "Grafana organization '$Name' has id $($org.id), expected $ExpectedId. Existing Grafana state uses a different organization layout. Back up and reset only the grafana-data volume, then rerun up.ps1."
  }
  Write-Host "verified Grafana organization '$Name' (id $($org.id))"
}

function Ensure-GrafanaOrganizations {
  if (-not (Wait-Grafana)) {
    throw "Grafana bootstrap did not become healthy. Check: docker compose -f compose.local.yml logs grafana"
  }
  Ensure-GrafanaOrg "Main Org." 2
  Ensure-GrafanaOrg "keve" 3
  Ensure-GrafanaOrg "bci" 4
}

# 3. Start in dependency order: platform first, examples second.
Write-Host "== platform bootstrap (compose.local.yml) =="
Invoke-ComposeUp $Platform $null "grafana-bootstrap" -BootstrapProfile
Write-Host "== Keycloak/Grafana client secret =="
Sync-KeycloakGrafanaClient
Write-Host "== Grafana organizations =="
Ensure-GrafanaOrganizations
Write-Host "== platform (normal provisioning) =="
Invoke-ComposeGrafanaBootstrapContainer
Invoke-ComposeGrafanaContainer "rm -sf"
Invoke-ComposeUp $Platform
Write-Host "== insurance-direct A (keve_ubix, direct OTLP) =="
Invoke-ComposeUp (Join-Path $InsDir "docker-compose.yml")
Write-Host "== insurance-direct B (bci_ubix, direct OTLP) =="
Invoke-ComposeUp (Join-Path $InsDir "docker-compose.bci.yml") (Join-Path $InsDir ".env.bci")
Write-Host "== retail-collector A (keve_digiflow, local collector) =="
Invoke-ComposeUp (Join-Path $RetailDir "docker-compose.yml")
Write-Host "== retail-collector B (bci_digiflow, local collector) =="
Invoke-ComposeUp (Join-Path $RetailDir "docker-compose.bci.yml") (Join-Path $RetailDir ".env.bci")

# 4. Poll the public surface from the host.
foreach ($p in 4318, 3000, 8083, 8082, 8093, 8092, 8084, 8094) {
  if ($p -eq 3000) {
    if (Wait-Grafana) { Write-Host "ok Grafana http://127.0.0.1:3000/api/health" }
    else { throw "Grafana is not healthy after startup. Check: docker compose -f compose.local.yml logs grafana" }
  } elseif (Wait-Tcp $p) { Write-Host "ok 127.0.0.1:$p" }
  else { Write-Warning "127.0.0.1:$p not reachable yet (see docker compose ps/logs)" }
}

@'

All stacks started:
  Gateway       http://localhost:4318/healthz (OTLP/HTTP + Bearer)
  Grafana       http://localhost:3000 (admin/admin local demo)
  Insurance A   http://localhost:8083  (container :8080, direct -> keve_ubix)
  Risk A        http://localhost:8082
  Insurance B   http://localhost:8093  (container :8080, direct -> bci_ubix)
  Risk B        http://localhost:8092
  Retail A      http://localhost:8084  (container :8080, via retail-collector -> keve_digiflow)
  Retail B      http://localhost:8094  (container :8080, via retail-collector -> bci_digiflow)

Useful:
  .\examples\scripts\down.ps1                # stop everything
  .\examples\scripts\load-k6.ps1 -DurationMin 1 -Vus 2   # smoke traffic
'@
