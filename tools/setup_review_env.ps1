$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$reviewRuntime = Join-Path $projectRoot '.runtime-local'
$reviewUv = Join-Path $reviewRuntime 'bootstrap\bin\uv.exe'
if (-not (Test-Path -LiteralPath $reviewUv)) {
    python -m pip --isolated install --disable-pip-version-check --no-cache-dir --only-binary=:all: --target (Join-Path $reviewRuntime 'bootstrap') uv==0.12.10
    if ($LASTEXITCODE -ne 0) { throw 'Unable to install local uv bootstrap' }
}
$env:UV_CACHE_DIR = Join-Path $reviewRuntime 'uv-cache'
$env:UV_PYTHON_INSTALL_DIR = Join-Path $reviewRuntime 'python'
$env:UV_PYTHON_BIN_DIR = Join-Path $reviewRuntime 'bin'
$env:UV_PYTHON_INSTALL_REGISTRY = 'false'
$env:UV_PYTHON_NO_REGISTRY = 'true'
$env:UV_PYTHON_INSTALL_BIN = 'false'
if (-not (Test-Path -LiteralPath '.venv-review\Scripts\python.exe')) {
    $reviewPythonVersion = '3.12'
    & $reviewUv --no-config venv --managed-python --python $reviewPythonVersion .venv-review
    if ($LASTEXITCODE -ne 0) { throw 'Unable to create the project Python environment' }
}
$reviewInstallArgs = @('--no-config', 'pip', 'install', '--python', '.venv-review\Scripts\python.exe', '-r', 'requirements.txt')
if (Test-Path -LiteralPath 'requirements-review.lock.txt') {
    $reviewInstallArgs += @('-c', 'requirements-review.lock.txt')
}
& $reviewUv @reviewInstallArgs
if ($LASTEXITCODE -ne 0) { throw 'Unable to install project dependencies' }
& $reviewUv --no-config pip check --python '.venv-review\Scripts\python.exe'
if ($LASTEXITCODE -ne 0) { throw 'Dependency check failed' }
Write-Output 'Environment ready. Run start-pm-stack.bat.'

