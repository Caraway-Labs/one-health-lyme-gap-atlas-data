param(
  [Parameter(Mandatory = $true)][string]$AppId,
  [Parameter(Mandatory = $true)][string]$VpcUuid
)

$ErrorActionPreference = 'Stop'
if (-not (Get-Command doctl -ErrorAction SilentlyContinue)) {
  throw 'doctl is required to attach an App Platform app to a VPC.'
}

$temporarySpec = New-TemporaryFile
try {
  $app = @(& doctl apps get $AppId --output json | ConvertFrom-Json)[0]
  if (-not $app -or -not $app.spec) {
    throw "DigitalOcean did not return an app specification for $AppId."
  }

  $app.spec | Add-Member -NotePropertyName vpc -NotePropertyValue ([pscustomobject]@{ id = $VpcUuid }) -Force
  $app.spec | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $temporarySpec.FullName -Encoding utf8
  & doctl apps update $AppId --spec $temporarySpec.FullName --wait | Out-Null
  if ($LASTEXITCODE -ne 0) {
    throw "Failed to attach App Platform app $AppId to VPC $VpcUuid."
  }

  $updated = @(& doctl apps get $AppId --output json | ConvertFrom-Json)[0]
  if ($updated.spec.vpc.id -ne $VpcUuid) {
    throw "App Platform app $AppId did not retain VPC $VpcUuid."
  }
  [pscustomobject]@{ app = $updated.spec.name; vpc_id = $updated.spec.vpc.id } | ConvertTo-Json
} finally {
  Remove-Item -LiteralPath $temporarySpec.FullName -Force -ErrorAction SilentlyContinue
}
