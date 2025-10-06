#Requires -Version 7.0
<#
.SYNOPSIS
    Deploy Container Apps for the Agentic Framework

.DESCRIPTION
    Deploys all Container Apps (Orchestrator, MCPs) to Azure Container Apps Environment.
    Requires Docker images to be built and pushed to ACR first.

.PARAMETER ResourceGroup
    The name of the resource group

.PARAMETER EnvironmentName
    The name of the Container Apps Environment

.PARAMETER ContainerRegistryName
    The name of the Azure Container Registry

.PARAMETER ManagedIdentityName
    The name of the managed identity to use

.PARAMETER ImageTag
    Docker image tag to deploy (default: latest)

.PARAMETER SkipBuild
    Skip building Docker images (use existing images)

.EXAMPLE
    .\deploy-container-apps.ps1 -ResourceGroup "agentic-rg" -EnvironmentName "agentic-aca-env"
#>

param(
    [Parameter(Mandatory=$true)]
    [string]$ResourceGroup,

    [Parameter(Mandatory=$false)]
    [string]$EnvironmentName,

    [Parameter(Mandatory=$false)]
    [string]$ContainerRegistryName,

    [Parameter(Mandatory=$false)]
    [string]$ManagedIdentityName,

    [Parameter(Mandatory=$false)]
    [string]$ImageTag = "latest",

    [Parameter(Mandatory=$false)]
    [switch]$SkipBuild
)

$ErrorActionPreference = 'Stop'

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

function Write-Step {
    param([string]$Message)
    Write-Host "`n>>> $Message" -ForegroundColor Cyan
}

function Write-Success {
    param([string]$Message)
    Write-Host "✓ $Message" -ForegroundColor Green
}

function Write-Info {
    param([string]$Message)
    Write-Host "  $Message" -ForegroundColor Gray
}

# =============================================================================
# DISCOVER RESOURCES
# =============================================================================

Write-Step "Discovering Azure resources"

# Get Container Apps Environment
if (-not $EnvironmentName) {
    $envs = az containerapp env list -g $ResourceGroup --query "[].name" -o tsv
    if ($envs -is [array]) {
        $EnvironmentName = $envs[0]
    } else {
        $EnvironmentName = $envs
    }
}

if (-not $EnvironmentName) {
    throw "No Container Apps Environment found. Please specify -EnvironmentName"
}

$env = az containerapp env show -n $EnvironmentName -g $ResourceGroup -o json | ConvertFrom-Json
$envId = $env.id
$envDomain = $env.properties.defaultDomain
Write-Success "Found Container Apps Environment: $EnvironmentName"

# Get Container Registry
if (-not $ContainerRegistryName) {
    $acrs = az acr list -g $ResourceGroup --query "[].name" -o tsv
    if ($acrs -is [array]) {
        $ContainerRegistryName = $acrs[0]
    } else {
        $ContainerRegistryName = $acrs
    }
}

if (-not $ContainerRegistryName) {
    throw "No Azure Container Registry found. Please specify -ContainerRegistryName"
}

$acrLoginServer = az acr show -n $ContainerRegistryName --query loginServer -o tsv
Write-Success "Found ACR: $acrLoginServer"

# Get Managed Identity
if (-not $ManagedIdentityName) {
    $identities = az identity list -g $ResourceGroup --query "[].name" -o tsv
    if ($identities -is [array]) {
        $ManagedIdentityName = $identities[0]
    } else {
        $ManagedIdentityName = $identities
    }
}

if (-not $ManagedIdentityName) {
    throw "No managed identity found. Please specify -ManagedIdentityName"
}

$identity = az identity show -g $ResourceGroup -n $ManagedIdentityName -o json | ConvertFrom-Json
$identityId = $identity.id
Write-Success "Found Managed Identity: $ManagedIdentityName"

# Read environment variables from .env file
Write-Step "Loading environment variables from .env"
$envVars = @()
$envFile = Join-Path $PSScriptRoot "..\..\. env"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^([^=]+)=(.*)$') {
            $key = $matches[1].Trim()
            $value = $matches[2].Trim()
            if ($key -and -not $key.StartsWith('#')) {
                $envVars += @{name=$key; value=$value}
            }
        }
    }
    Write-Success "Loaded $($envVars.Count) environment variables"
} else {
    Write-Warning ".env file not found at $envFile"
}

# =============================================================================
# BUILD AND PUSH DOCKER IMAGES
# =============================================================================

if (-not $SkipBuild) {
    Write-Step "Building and pushing Docker images"

    # Login to ACR
    az acr login --name $ContainerRegistryName

    $projectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent

    # Build and push orchestrator
    Write-Info "Building orchestrator..."
    docker build -t "$acrLoginServer/orchestrator:$ImageTag" `
        -f "$projectRoot/agentic_framework/orchestrator/Dockerfile" `
        "$projectRoot/agentic_framework"
    docker push "$acrLoginServer/orchestrator:$ImageTag"

    # Build and push MCPs (alphabetically ordered)
    $mcpDirs = Get-ChildItem "$projectRoot/agentic_framework/mcps" -Directory | Where-Object { $_.Name -ne "__pycache__" }
    foreach ($mcpDir in $mcpDirs) {
        $mcpName = $mcpDir.Name
        Write-Info "Building $mcpName MCP..."
        docker build -t "$acrLoginServer/$mcpName-mcp:$ImageTag" `
            -f "$mcpDir/Dockerfile" `
            "$projectRoot/agentic_framework"
        docker push "$acrLoginServer/$mcpName-mcp:$ImageTag"
    }

    Write-Success "Docker images built and pushed"
}

# =============================================================================
# DEPLOY MCPS
# =============================================================================

Write-Step "Deploying MCP Container Apps"

# Get MCP directories (alphabetically sorted)
$projectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$mcpDirs = Get-ChildItem "$projectRoot/agentic_framework/mcps" -Directory |
    Where-Object { $_.Name -ne "__pycache__" } |
    Sort-Object Name

# Assign ports starting from 8001 (alphabetically)
$mcpPort = 8001
$mcpEndpoints = @{}

foreach ($mcpDir in $mcpDirs) {
    $mcpName = $mcpDir.Name
    $appName = "$mcpName-mcp"
    $imageName = "$acrLoginServer/$mcpName-mcp:$ImageTag"

    Write-Info "Deploying $appName on port $mcpPort..."

    # MCP-specific environment variables
    $mcpEnvVars = $envVars + @(
        @{name="MCP_PORT"; value="$mcpPort"}
    )

    # Deploy container app
    az containerapp create `
        --name $appName `
        --resource-group $ResourceGroup `
        --environment $EnvironmentName `
        --image $imageName `
        --user-assigned $identityId `
        --registry-server $acrLoginServer `
        --registry-identity $identityId `
        --target-port $mcpPort `
        --ingress internal `
        --min-replicas 1 `
        --max-replicas 3 `
        --cpu 0.5 `
        --memory 1.0Gi `
        --env-vars ($mcpEnvVars | ForEach-Object { "$($_.name)=$($_.value)" }) `
        -o none 2>$null

    # Get FQDN
    $fqdn = az containerapp show -n $appName -g $ResourceGroup --query "properties.configuration.ingress.fqdn" -o tsv
    $mcpEndpoints[$mcpName] = "https://$fqdn/mcp"

    Write-Success "Deployed $appName at https://$fqdn"
    $mcpPort++
}

# =============================================================================
# DEPLOY ORCHESTRATOR
# =============================================================================

Write-Step "Deploying Orchestrator Container App"

# Build MCP_ENDPOINTS JSON
$mcpEndpointsJson = ($mcpEndpoints | ConvertTo-Json -Compress) -replace '"', '\"'

# Orchestrator environment variables
$orchEnvVars = $envVars + @(
    @{name="MCP_ENDPOINTS"; value=$mcpEndpointsJson}
)

az containerapp create `
    --name orchestrator `
    --resource-group $ResourceGroup `
    --environment $EnvironmentName `
    --image "$acrLoginServer/orchestrator:$ImageTag" `
    --user-assigned $identityId `
    --registry-server $acrLoginServer `
    --registry-identity $identityId `
    --target-port 8000 `
    --ingress external `
    --min-replicas 1 `
    --max-replicas 5 `
    --cpu 1.0 `
    --memory 2.0Gi `
    --env-vars ($orchEnvVars | ForEach-Object { "$($_.name)=$($_.value)" }) `
    -o none

# Get orchestrator FQDN
$orchFqdn = az containerapp show -n orchestrator -g $ResourceGroup --query "properties.configuration.ingress.fqdn" -o tsv

Write-Success "Deployed orchestrator at https://$orchFqdn"

# =============================================================================
# OUTPUT SUMMARY
# =============================================================================

Write-Step "Deployment Complete"
Write-Host ""
Write-Host "Orchestrator URL:" -ForegroundColor Yellow
Write-Host "  https://$orchFqdn"
Write-Host ""
Write-Host "MCP Endpoints:" -ForegroundColor Yellow
foreach ($mcp in $mcpEndpoints.Keys) {
    Write-Host "  $mcp : $($mcpEndpoints[$mcp])"
}
Write-Host ""
Write-Host "Test the deployment:" -ForegroundColor Yellow
Write-Host "  curl https://$orchFqdn/health"
Write-Host "  curl https://$orchFqdn/mcps"
Write-Host ""
