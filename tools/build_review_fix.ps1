$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)
& powershell -NoProfile -ExecutionPolicy Bypass -File tools/setup_review_env.ps1
if ($LASTEXITCODE -ne 0) { throw 'Environment setup failed' }
New-Item -ItemType Directory -Path '.runtime-local/dist', '.runtime-local/build' -Force | Out-Null
& .venv-review/Scripts/python.exe -m PyInstaller --noconfirm --distpath .runtime-local/dist --workpath .runtime-local/build 'PM Stack V1.10.2.spec'
if ($LASTEXITCODE -ne 0) { throw 'Build failed' }
Copy-Item -LiteralPath 'browser-extension' -Destination '.runtime-local/dist' -Recurse -Force
Write-Output 'Built: .runtime-local/dist/PM Stack.exe'
