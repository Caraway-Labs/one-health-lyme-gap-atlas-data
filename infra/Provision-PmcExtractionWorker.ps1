param(
  [Parameter(Mandatory = $true)][string]$VpcUuid,
  [Parameter(Mandatory = $true)][string]$SshKeyFingerprint,
  [Parameter(Mandatory = $true)][string]$SshAllowedCidr,
  [Parameter(Mandatory = $true)][string]$ImageDigest,
  [Parameter(Mandatory = $true)][string]$RuntimeEnvFile,
  [Parameter(Mandatory = $true)][string]$Neo4jPrivateIp,
  [switch]$Confirm
)
$ErrorActionPreference = 'Stop'
if (-not $Confirm) { throw 'Pass --Confirm after reviewing the DEV-only target.' }
if ($ImageDigest -notmatch '^sha256:[0-9a-f]{64}$') { throw 'ImageDigest must be immutable.' }
if (-not (Test-Path -LiteralPath $RuntimeEnvFile)) { throw 'Protected runtime environment file is missing.' }
$name = 'oh-lyme-dev-pmc-extraction'
$existing = @(& doctl compute droplet list --tag-name $name --output json | ConvertFrom-Json)
if ($existing.Count -gt 0) { throw 'DEV PMC worker already exists; refusing duplicate provisioning.' }
$root = Split-Path -Parent $PSScriptRoot
$droplet = (& doctl compute droplet create $name --region sfo3 --size s-1vcpu-1gb --image ubuntu-24-04-x64 --vpc-uuid $VpcUuid --ssh-keys $SshKeyFingerprint --tag-names $name --user-data-file (Join-Path $PSScriptRoot 'pmc-worker-cloud-init.yml') --wait --output json | ConvertFrom-Json)[0]
$vpc = (& doctl vpcs get $VpcUuid --output json | ConvertFrom-Json)[0]
& doctl compute firewall create --name "$name-private" --inbound-rules "protocol:tcp,ports:22,address:$SshAllowedCidr" --outbound-rules 'protocol:tcp,ports:1-65535,address:0.0.0.0/0 protocol:udp,ports:1-65535,address:0.0.0.0/0' --tag-names $name | Out-Null
$publicIp = @($droplet.networks.v4 | Where-Object {$_.type -eq 'public'})[0].ip_address
& (Join-Path $PSScriptRoot 'Configure-PmcExtractionWorker.ps1') -SshHost $publicIp -ImageDigest $ImageDigest -RuntimeEnvFile $RuntimeEnvFile -Neo4jPrivateIp $Neo4jPrivateIp -Confirm
[pscustomobject]@{ droplet_id=$droplet.id; private_bolt=$true; public_application_ingress=$false } | ConvertTo-Json
