# ====================================================
# build.ps1 — Build and optionally push the bridge image
# Usage:
#   .\scripts\build.ps1             # build only
#   .\scripts\build.ps1 -Push       # build + push to GHCR
# ====================================================
param(
    [switch]$Push,
    [string]$Tag = "latest"
)

$ErrorActionPreference = "Stop"
$ImageName = "ghcr.io/mxkhec01/dokploy-mcp-bridge"
$FullTag = "${ImageName}:${Tag}"

Write-Host "`n=== Building $FullTag ===`n" -ForegroundColor Cyan
docker build -t $FullTag .

if ($LASTEXITCODE -ne 0) {
    Write-Host "Build failed!" -ForegroundColor Red
    exit 1
}

Write-Host "`nBuild successful: $FullTag" -ForegroundColor Green

if ($Push) {
    Write-Host "`n=== Pushing to GHCR ===`n" -ForegroundColor Cyan
    docker push $FullTag
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Push failed! Did you run 'echo $TOKEN | docker login ghcr.io -u mxkhec01 --password-stdin' ?" -ForegroundColor Red
        exit 1
    }
    Write-Host "Pushed successfully: $FullTag" -ForegroundColor Green
}
