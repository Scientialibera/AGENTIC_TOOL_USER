# Simple deployment wrapper script
# This script deploys the orchestrator and MCP servers to Azure Container Apps

Write-Host " Agentic Framework Deployment to Azure" -ForegroundColor Cyan
Write-Host ""

# Get the script directory and find .env file
$agenticFrameworkDir = Split-Path -Parent $PSScriptRoot
$parentDir = Split-Path -Parent $agenticFrameworkDir

# Try to find .env file (check parent directory first, then agentic_framework directory)
$envFilePath = $null
if (Test-Path (Join-Path $parentDir ".env")) {
    $envFilePath = Join-Path $parentDir ".env"
} elseif (Test-Path (Join-Path $agenticFrameworkDir ".env")) {
    $envFilePath = Join-Path $agenticFrameworkDir ".env"
}

# Check if .env file exists
if (-not $envFilePath) {
    Write-Host " Error: .env file not found" -ForegroundColor Red
    Write-Host "Looked in:" -ForegroundColor Yellow
    Write-Host "  - $(Join-Path $parentDir '.env')" -ForegroundColor Gray
    Write-Host "  - $(Join-Path $agenticFrameworkDir '.env')" -ForegroundColor Gray
    Write-Host "Please ensure .env file exists with all required configuration" -ForegroundColor Yellow
    exit 1
}

Write-Host "Using .env file: $envFilePath" -ForegroundColor Gray
Write-Host ""

# Run the deployment script with default values
Write-Host "Deploying to Azure Container Apps environment: salesforcebot-env" -ForegroundColor Yellow
Write-Host "Resource Group: salesforcebot-rg" -ForegroundColor Yellow
Write-Host "Container Registry: salesforcebotacr (will be created if it doesn't exist)" -ForegroundColor Yellow
Write-Host ""
Write-Host "Configuration:" -ForegroundColor Cyan
Write-Host "  - DEV_MODE=true (bypasses RBAC, uses dummy SQL data)" -ForegroundColor Yellow
Write-Host "  - BYPASS_TOKEN=false (JWT authentication ENABLED)" -ForegroundColor Green
Write-Host ""

$confirm = Read-Host "Do you want to build and push new Docker images? (y/N)"
$buildImages = $confirm -eq "y" -or $confirm -eq "Y"

Write-Host ""
Write-Host "Starting deployment..." -ForegroundColor Cyan

# Run the deployment
& "$PSScriptRoot\deploy-aca.ps1" `
    -ResourceGroup "salesforcebot-rg" `
    -Location "westus2" `
    -EnvironmentName "salesforcebot-env" `
    -ContainerRegistry "salesforcebotacr" `
    -ImageTag "latest" `
    -BuildImages:$buildImages `
    -EnvFile $envFilePath

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host " Deployment completed successfully!" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host " Deployment failed. Please check the errors above." -ForegroundColor Red
    exit 1
}
