param([switch]$Remove)
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$hooks = [System.IO.Path]::GetFullPath((Join-Path $repo '.githooks')).Replace([char]92, [char]47)
$existing = & git -C $repo config --get core.hooksPath
if ($LASTEXITCODE -notin @(0, 1)) { throw 'Cannot read Git hook configuration.' }
$existing = [string]$existing
if ($Remove) {
    if ($existing -ne $hooks) { throw 'The active hooksPath is not this managed hook; nothing changed.' }
    & git -C $repo config --local --unset core.hooksPath
    if ($LASTEXITCODE -ne 0) { throw 'Could not remove the local managed hook setting.' }
    Write-Output 'Managed handoff hook disabled; default/global hook discovery restored.'
    exit 0
}
if ($existing -and $existing -ne $hooks) { throw 'An existing hooksPath is configured; preserve it and integrate the handoff check manually.' }
if (-not $existing) {
    $defaultHooks = & git -C $repo rev-parse --git-path hooks
    if ($LASTEXITCODE -ne 0) { throw 'Cannot locate the default Git hook directory.' }
    if (-not [System.IO.Path]::IsPathRooted($defaultHooks)) { $defaultHooks = Join-Path $repo $defaultHooks }
    $active = @(Get-ChildItem -LiteralPath $defaultHooks -File -ErrorAction SilentlyContinue | Where-Object { $_.Name -notlike '*.sample' })
    if ($active.Count) { throw 'Existing Git hooks were found; preserve them and integrate the handoff check manually.' }
}
if (-not (Test-Path -LiteralPath (Join-Path $repo '.githooks/pre-commit')) -or -not (Test-Path -LiteralPath (Join-Path $repo 'tools/handoff.py'))) { throw 'The managed hook or checker is missing.' }
& git -C $repo config --local core.hooksPath $hooks
if ($LASTEXITCODE -ne 0) { throw 'Cannot enable local Git hook configuration.' }
Write-Output "Managed hooksPath enabled: $hooks"
Write-Output 'This repository-local setting is shared by its worktrees. Each commit is checked against its own index.'
