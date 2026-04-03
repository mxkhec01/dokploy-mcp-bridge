# ====================================================
# inicia.ps1 — Start the MCP bridge for local dev/testing
# Connects to the control-pui stack's postgres
# ====================================================
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)

# Kill any existing bridge on port 8000
$processes = Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique
foreach ($pid in $processes) {
    Write-Host "Killing process $pid on port 8000"
    Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
}

# Set environment for local testing against control-pui
$env:DATABASE_URI = "postgresql://pui_admin:pui_s3cur3_p4ss@localhost:5432/pui_db"
$env:ACCESS_MODE = "admin"

Write-Host "`n=== Starting Dokploy MCP Bridge (local dev) ===" -ForegroundColor Cyan
Write-Host "  DB: $env:DATABASE_URI"
Write-Host "  Mode: $env:ACCESS_MODE"
Write-Host ""

Set-Location $ProjectRoot
& python -m src.server --transport=streamable-http --access-mode=admin
