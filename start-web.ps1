param([int]$Port = 8000, [switch]$SkipBuild)
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    if (-not $SkipBuild) {
        Push-Location (Join-Path $PSScriptRoot 'frontend')
        try {
            if (-not (Test-Path 'node_modules')) {
                & npm.cmd ci
                if ($LASTEXITCODE -ne 0) { throw 'npm ci failed' }
            }
            & npm.cmd run build
            if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' }
        } finally { Pop-Location }
    }
    if (-not (Test-Path 'frontend/dist/index.html')) { throw 'Build the frontend first.' }
    $env:STILL_ALLOWED_ORIGINS = "http://127.0.0.1:$Port,http://localhost:$Port,http://127.0.0.1:5173,http://localhost:5173"
    Write-Host "Still Journal: http://127.0.0.1:$Port"
    $python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $python)) {
        $python = Join-Path (Split-Path $PSScriptRoot -Parent) '.venv\Scripts\python.exe'
    }
    if (-not (Test-Path -LiteralPath $python)) { $python = 'python' }
    & $python -m uvicorn backend.main:create_app --factory --host 127.0.0.1 --port $Port --no-access-log
    if ($LASTEXITCODE -ne 0) { throw 'Backend startup failed' }
} finally { Pop-Location }
