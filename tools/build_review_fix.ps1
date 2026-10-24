$ErrorActionPreference = 'Stop'
# Keep unrelated document-tool SSL binaries out of this build process.
$env:PATH = (($env:PATH -split ';') | Where-Object { $_ -notlike '*codex-primary-runtime*poppler*' -and $_ -notlike '*codex-primary-runtime*libheif*' -and $_ -notlike '*codex-primary-runtime*jxrlib*' }) -join ';'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
& powershell -NoProfile -ExecutionPolicy Bypass -File tools/setup_review_env.ps1
if ($LASTEXITCODE -ne 0) { throw 'Environment setup failed' }
New-Item -ItemType Directory -Path 'dist', 'build' -Force | Out-Null
& .venv-review/Scripts/python.exe -m PyInstaller --noconfirm --distpath dist --workpath build 'PM Stack v1.11.5.spec'
if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
Copy-Item -LiteralPath 'browser-extension' -Destination 'dist' -Recurse -Force
Write-Output 'Built: dist/PM Stack.exe'
