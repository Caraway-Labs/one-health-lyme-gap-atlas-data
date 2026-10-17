param(
    [Parameter(Mandatory)][ValidateSet('prepare', 'calculate')][string]$Mode,
    [Parameter(Mandatory)][string]$Inputs,
    [string]$Capture,
    [string]$Output,
    [string]$Counties = '',
    [ValidateRange(1, 128)][int]$MaximumCounties = 16,
    [ValidateRange(60, 1800)][int]$Seconds = 900
)
# Existing cached laptop runtime. No pull, cloud calls, credentials or database.
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$repository = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$inputsPath = (Resolve-Path -LiteralPath $Inputs).Path
$name = 'atlas-nlcd-local-' + [Guid]::NewGuid().ToString()
$image = 'sha256:a1a2939b969fd2ec8ca78a973f921b95486f97a71b7ddfc4c4be4be1a6c3b6d7'
& docker image inspect $image --format '{{.Id}}' | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Reviewed cached runtime unavailable; do not pull' }
$revision = (& git -c "safe.directory=$($repository.Replace('\', '/'))" -C $repository rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $revision -notmatch '^[a-f0-9]{40}$') { throw 'Exact Git revision required' }
$changes = & git -c "safe.directory=$($repository.Replace('\', '/'))" -C $repository status --porcelain
if ($LASTEXITCODE -ne 0 -or $changes) { throw 'Commit calculation code before execution' }
$active = & docker ps --filter label=atlas.nlcd.local.owner --format '{{.Names}}'
if ($LASTEXITCODE -ne 0 -or $active) { throw 'Another owned local calculation is active' }
$arguments = @(
    'run', '--rm', '--name', $name, '--label', "atlas.nlcd.local.owner=$name",
    '--cpus=0.5', '--memory=2g', '--pids-limit=64', '--network=none',
    '--read-only', '--tmpfs', '/tmp:rw,noexec,nosuid,size=64m',
    '--cap-drop=ALL', '--security-opt=no-new-privileges',
    '--env', 'PYTHONPATH=/proof/src', '--env', 'OPENBLAS_NUM_THREADS=1',
    '--env', 'OMP_NUM_THREADS=1', '--env', 'PROJ_NETWORK=OFF',
    '--mount', "type=bind,src=$repository/src,dst=/proof/src,readonly",
    '--mount', "type=bind,src=$repository/config,dst=/proof/config,readonly"
)
$command = @(
    '--entrypoint', 'timeout', $image, '--signal=TERM', '--kill-after=10s', "$Seconds",
    '/app/.venv/bin/python', '-m', 'lyme_gap_atlas_data.ingestion.annual_nlcd_mosaic', $Mode,
    '--extracted', '/inputs', '--seconds', "$Seconds"
)
if ($Mode -eq 'prepare') {
    if (-not $Capture) { throw 'Retained capture directory required' }
    $capturePath = (Resolve-Path -LiteralPath $Capture).Path
    $arguments += @('--mount', "type=bind,src=$capturePath,dst=/capture,readonly")
    $arguments += @('--mount', "type=bind,src=$inputsPath,dst=/inputs")
    $command += @('--capture', '/capture', '--manifest', '/proof/config/annual-nlcd-2025-mrlc-staging-manifest.json')
} else {
    if (-not $Output) { throw 'Existing owned result directory required' }
    $outputPath = (Resolve-Path -LiteralPath $Output).Path
    if ($outputPath -eq $inputsPath -or $outputPath -eq $repository) { throw 'Separate result directory required' }
    $arguments += @('--mount', "type=bind,src=$inputsPath,dst=/inputs,readonly")
    $arguments += @('--mount', "type=bind,src=$outputPath,dst=/results")
    $command += @('--tiger', '/inputs/tl_2025_us_county.zip', '--output', '/results',
                  '--maximum-counties', "$MaximumCounties", '--code-revision', $revision)
    if ($Counties) { $command += @('--counties', $Counties) }
}
try {
    & docker @arguments @command
    $status = $LASTEXITCODE
} finally {
    $label = & docker inspect --format '{{ index .Config.Labels "atlas.nlcd.local.owner" }}' $name 2>$null
    if ($label -eq $name) { & docker kill $name 2>$null | Out-Null }
}
exit $status
