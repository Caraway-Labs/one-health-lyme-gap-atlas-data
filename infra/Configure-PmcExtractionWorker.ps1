param(
  [Parameter(Mandatory = $true)][string]$SshHost,
  [Parameter(Mandatory = $true)][string]$ImageDigest,
  [Parameter(Mandatory = $true)][string]$RuntimeEnvFile,
  [Parameter(Mandatory = $true)][string]$Neo4jPrivateIp,
  [switch]$Confirm
)
$ErrorActionPreference = 'Stop'
if (-not $Confirm) { throw 'Pass --Confirm after reviewing the DEV-only target.' }
if ($ImageDigest -notmatch '^sha256:[0-9a-f]{64}$') { throw 'ImageDigest must be immutable.' }
if ($Neo4jPrivateIp -notmatch '^((25[0-5]|2[0-4][0-9]|1?[0-9][0-9]?)\.){3}(25[0-5]|2[0-4][0-9]|1?[0-9][0-9]?)$') { throw 'Neo4jPrivateIp must be an IPv4 address.' }
if (-not (Test-Path -LiteralPath $RuntimeEnvFile)) { throw 'Protected runtime environment file is missing.' }

$ready = $false
for ($attempt = 1; $attempt -le 30; $attempt++) {
  & ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new "root@$SshHost" 'true' 2>$null
  if ($LASTEXITCODE -eq 0) { $ready = $true; break }
  Start-Sleep -Seconds 5
}
if (-not $ready) { throw 'Worker SSH did not become ready; secret transfer was not attempted.' }

$envFile = New-TemporaryFile
$dockerFile = New-TemporaryFile
try {
  $managedNames = @('TOPX_ENV', 'PAPERS_REQUIRE_HUMAN_REVIEW', 'KG_CHAT_ENABLED', 'NEO4J_URI')
  $lines = Get-Content -LiteralPath $RuntimeEnvFile |
    Where-Object { $_ -match '^[A-Za-z_][A-Za-z0-9_]*=' } |
    Where-Object { $managedNames -notcontains ($_.Split('=', 2)[0]) }
  $lines += 'TOPX_ENV=dev'
  $lines += 'PAPERS_REQUIRE_HUMAN_REVIEW=true'
  $lines += 'KG_CHAT_ENABLED=false'
  $lines += "NEO4J_URI=bolt://$Neo4jPrivateIp:7687"
  Set-Content -LiteralPath $envFile -Value ($lines -join "`n") -Encoding utf8 -NoNewline
  & doctl registry docker-config oh-lyme-data --expiry-seconds 3600 | Set-Content -LiteralPath $dockerFile -Encoding utf8 -NoNewline
  if ($LASTEXITCODE -ne 0) { throw 'Unable to obtain a short-lived read-only registry credential.' }
  & scp -q (Join-Path $PSScriptRoot 'install-pmc-worker.sh') "root@${SshHost}:/tmp/install-pmc-worker.sh"
  if ($LASTEXITCODE -ne 0) { throw 'Worker installer transfer failed.' }
  & scp -q $envFile "root@${SshHost}:/tmp/pmc-runtime.env"
  if ($LASTEXITCODE -ne 0) { throw 'Protected runtime environment transfer failed.' }
  & scp -q $dockerFile "root@${SshHost}:/tmp/docker-config.json"
  if ($LASTEXITCODE -ne 0) { throw 'Registry credential transfer failed.' }
  & ssh -o BatchMode=yes "root@$SshHost" "set -e; chmod 0700 /tmp/install-pmc-worker.sh; IMAGE_DIGEST='$ImageDigest' /tmp/install-pmc-worker.sh"
  if ($LASTEXITCODE -ne 0) { throw 'Worker installation failed.' }
} finally {
  Remove-Item $envFile, $dockerFile -Force -ErrorAction SilentlyContinue
}
[pscustomobject]@{ configured=$true; private_bolt=$true; public_application_ingress=$false } | ConvertTo-Json
