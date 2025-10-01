# Complete deployment preparation script
# This script prepares your app for offline deployment by copying cache files and building Docker images

Write-Host "`n=== GridStats Deployment Preparation ===" -ForegroundColor Cyan
Write-Host "This script will:" -ForegroundColor Yellow
Write-Host "  1. Copy backend cache files to frontend assets" -ForegroundColor Gray
Write-Host "  2. Commit changes to git" -ForegroundColor Gray
Write-Host "  3. Build and tag Docker images" -ForegroundColor Gray
Write-Host "  4. (Optional) Push to Docker Hub`n" -ForegroundColor Gray

# Step 1: Copy cache files
Write-Host "[Step 1/4] Copying cache files to frontend..." -ForegroundColor Cyan
& .\copy-cache-to-frontend.ps1

if ($LASTEXITCODE -ne 0) {
    Write-Host "Failed to copy cache files!" -ForegroundColor Red
    exit 1
}

# Step 2: Git operations
Write-Host "`n[Step 2/4] Committing changes to git..." -ForegroundColor Cyan
git add copy-cache-to-frontend.ps1
git add frontend/public/assets/
git add README.md
git add backend/app/routers/track.py
git add docker-compose.portainer.yml
git add DEPLOYMENT_FIX.md
git add prepare-deployment.ps1

$commitMsg = "Add offline track cache to frontend for production deployment"
git commit -m $commitMsg

if ($LASTEXITCODE -eq 0) {
    Write-Host "  ✓ Changes committed" -ForegroundColor Green
} else {
    Write-Host "  ! No changes to commit or commit failed" -ForegroundColor Yellow
}

# Step 3: Build Docker images
Write-Host "`n[Step 3/4] Building Docker images..." -ForegroundColor Cyan
docker-compose build

if ($LASTEXITCODE -ne 0) {
    Write-Host "Failed to build Docker images!" -ForegroundColor Red
    exit 1
}

Write-Host "  ✓ Docker images built successfully" -ForegroundColor Green

# Step 4: Tag and push (optional)
Write-Host "`n[Step 4/4] Docker Hub operations (optional)" -ForegroundColor Cyan
$pushToHub = Read-Host "Do you want to push images to Docker Hub? (y/n)"

if ($pushToHub -eq "y" -or $pushToHub -eq "Y") {
    $username = Read-Host "Enter your Docker Hub username (default: claudio08092002)"
    if ([string]::IsNullOrWhiteSpace($username)) {
        $username = "claudio08092002"
    }
    
    Write-Host "  Tagging images..." -ForegroundColor Gray
    docker tag gridstats-backend:latest "${username}/gridstats-backend:latest"
    docker tag gridstats-frontend:latest "${username}/gridstats-frontend:latest"
    
    Write-Host "  Pushing to Docker Hub..." -ForegroundColor Gray
    docker push "${username}/gridstats-backend:latest"
    docker push "${username}/gridstats-frontend:latest"
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "  ✓ Images pushed to Docker Hub" -ForegroundColor Green
    } else {
        Write-Host "  ! Failed to push images" -ForegroundColor Red
    }
} else {
    Write-Host "  Skipped Docker Hub push" -ForegroundColor Yellow
}

Write-Host "`n=== Deployment Preparation Complete ===" -ForegroundColor Green
Write-Host "`nNext steps:" -ForegroundColor Cyan
Write-Host "  1. Push git changes: git push origin main" -ForegroundColor Gray
Write-Host "  2. Update your Portainer stack to pull new images" -ForegroundColor Gray
Write-Host "  3. Verify tracks load without HTTP requests`n" -ForegroundColor Gray
