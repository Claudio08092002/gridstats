# Copy backend track cache files to frontend assets for offline deployment

$backendCache = "backend\app\tracks_cache"
$frontendAssets = "frontend\public\assets\tracks_cache"

Write-Host "Copying track cache files from backend to frontend..." -ForegroundColor Cyan

# Ensure destination directory exists
if (-not (Test-Path $frontendAssets)) {
    New-Item -Path $frontendAssets -ItemType Directory -Force | Out-Null
}

# Copy all JSON files
$files = Get-ChildItem -Path $backendCache -Filter "*.json"
foreach ($file in $files) {
    Copy-Item -Path $file.FullName -Destination $frontendAssets -Force
    Write-Host "  Copied: $($file.Name)" -ForegroundColor Green
}

Write-Host "`nTotal files copied: $($files.Count)" -ForegroundColor Yellow
Write-Host "Frontend assets are now ready for offline deployment!" -ForegroundColor Green
