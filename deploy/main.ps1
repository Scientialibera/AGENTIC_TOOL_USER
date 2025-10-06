#Requires -Version 7.0
<#
.SYNOPSIS
    Main deployment script for Agentic Framework

.DESCRIPTION
    Orchestrates the complete deployment process:
    1. Deploy Azure infrastructure (Bicep)
    2. Configure RBAC permissions
    3. Generate .env file
    4. Initialize Cosmos DB data
    5. Deploy Container Apps

.PARAMETER BaseName
    Base name for all resources (3-15 characters, alphanumeric)

.PARAMETER Location
    Azure region for deployment (default: eastus)

.PARAMETER ResourceGroup
    Resource group name (default: <baseName>-rg)

.PARAMETER Environment
    Environment name: dev, staging, or prod (default: dev)

.PARAMETER SkipInfrastructure
    Skip infrastructure deployment (use existing resources)

.PARAMETER SkipData
    Skip data initialization

.PARAMETER SkipApps
    Skip Container Apps deployment

.EXAMPLE
    .\main.ps1 -BaseName "mybot" -Location "eastus" -Environment "dev"

.EXAMPLE
    .\main.ps1 -BaseName "mybot" -SkipInfrastructure -SkipData
    # Only deploys Container Apps to existing infrastructure
#>

param(
    [Parameter(Mandatory=$false)]
    [ValidateLength(3, 15)]
    [ValidatePattern('^[a-z0-9]+$')]
    [string]$BaseName,

    [Parameter(Mandatory=$false)]
    [string]$Location = "eastus",

    [Parameter(Mandatory=$false)]
    [string]$ResourceGroup,

    [Parameter(Mandatory=$false)]
    [ValidateSet('dev', 'staging', 'prod')]
    [string]$Environment = "dev",

    [Parameter(Mandatory=$false)]
    [switch]$SkipInfrastructure,

    [Parameter(Mandatory=$false)]
    [switch]$SkipData,

    [Parameter(Mandatory=$false)]
    [switch]$SkipApps
)

$ErrorActionPreference = 'Stop'

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

function Write-Step {
    param([string]$Message)
    Write-Host "`n========================================" -ForegroundColor Cyan
    Write-Host ">>> $Message" -ForegroundColor Cyan
    Write-Host "========================================`n" -ForegroundColor Cyan
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
# INITIALIZATION
# =============================================================================

Write-Host @"

╔═══════════════════════════════════════════════════════════╗
║                                                             ║
║         AGENTIC FRAMEWORK - DEPLOYMENT ORCHESTRATOR        ║
║                                                             ║
╚═══════════════════════════════════════════════════════════╝

"@ -ForegroundColor Cyan

# Validate Azure CLI
Write-Info "Checking Azure CLI..."
$azVersion = az version --query '\"azure-cli\"' -o tsv 2>$null
if (-not $azVersion) {
    throw "Azure CLI not found. Please install: https://aka.ms/azure-cli"
}
Write-Success "Azure CLI version: $azVersion"

# Validate login
$account = az account show -o json 2>$null | ConvertFrom-Json
if (-not $account) {
    throw "Not logged into Azure. Run 'az login' first."
}
Write-Success "Logged in as: $($account.user.name)"
Write-Info "Subscription: $($account.name)"
Write-Info "Tenant: $($account.tenantId)"

# Set defaults
if (-not $BaseName) {
    $BaseName = Read-Host "Enter base name for resources (3-15 characters, lowercase)"
    if ($BaseName.Length -lt 3 -or $BaseName.Length -gt 15) {
        throw "Base name must be 3-15 characters"
    }
}

if (-not $ResourceGroup) {
    $ResourceGroup = "$BaseName-rg"
}

Write-Info "Base Name: $BaseName"
Write-Info "Resource Group: $ResourceGroup"
Write-Info "Location: $Location"
Write-Info "Environment: $Environment"

# =============================================================================
# STEP 1: DEPLOY INFRASTRUCTURE
# =============================================================================

if (-not $SkipInfrastructure) {
    Write-Step "STEP 1: Deploying Azure Infrastructure (Bicep)"

    # Ensure resource group exists
    $rgExists = az group exists -n $ResourceGroup
    if ($rgExists -eq "false") {
        Write-Info "Creating resource group..."
        az group create -n $ResourceGroup -l $Location -o none
        Write-Success "Resource group created"
    } else {
        Write-Info "Resource group already exists"
    }

    # Deploy Bicep template
    $bicepPath = Join-Path $PSScriptRoot "infrastructure\main.bicep"
    $paramsPath = Join-Path $PSScriptRoot "infrastructure\parameters\$Environment.parameters.json"

    if (-not (Test-Path $bicepPath)) {
        throw "Bicep template not found: $bicepPath"
    }

    Write-Info "Deploying Bicep template..."
    Write-Info "  Template: $bicepPath"
    Write-Info "  Parameters: $paramsPath"

    $deploymentName = "agentic-$Environment-$(Get-Date -Format 'yyyyMMddHHmmss')"

    if (Test-Path $paramsPath) {
        az deployment group create `
            --name $deploymentName `
            --resource-group $ResourceGroup `
            --template-file $bicepPath `
            --parameters $paramsPath `
            --parameters baseName=$BaseName location=$Location `
            -o none
    } else {
        az deployment group create `
            --name $deploymentName `
            --resource-group $ResourceGroup `
            --template-file $bicepPath `
            --parameters baseName=$BaseName location=$Location environment=$Environment `
            -o none
    }

    Write-Success "Infrastructure deployment completed"

    # Wait for resources to be ready
    Write-Info "Waiting for resources to propagate (30 seconds)..."
    Start-Sleep -Seconds 30
} else {
    Write-Step "STEP 1: Skipping Infrastructure Deployment"
}

# =============================================================================
# STEP 2: CONFIGURE RBAC
# =============================================================================

Write-Step "STEP 2: Configuring RBAC Permissions"

$rbacScript = Join-Path $PSScriptRoot "security\configure-rbac.ps1"
if (Test-Path $rbacScript) {
    & $rbacScript -ResourceGroup $ResourceGroup -WaitForPropagation $true
    Write-Success "RBAC configuration completed"
} else {
    Write-Warning "RBAC script not found: $rbacScript"
}

# =============================================================================
# STEP 3: GENERATE .ENV FILE
# =============================================================================

Write-Step "STEP 3: Generating .env File"

$envScript = Join-Path $PSScriptRoot "utils\generate-env.ps1"
if (Test-Path $envScript) {
    & $envScript -ResourceGroup $ResourceGroup
    Write-Success ".env file generated"
} else {
    Write-Warning "generate-env script not found: $envScript"
}

# =============================================================================
# STEP 4: INITIALIZE DATA
# =============================================================================

if (-not $SkipData) {
    Write-Step "STEP 4: Initializing Cosmos DB Data"

    $dataScript = Join-Path $PSScriptRoot "data\init-cosmos-data.py"
    if (Test-Path $dataScript) {
        python $dataScript
        Write-Success "Data initialization completed"
    } else {
        Write-Warning "Data initialization script not found: $dataScript"
    }
} else {
    Write-Step "STEP 4: Skipping Data Initialization"
}

# =============================================================================
# STEP 5: DEPLOY CONTAINER APPS
# =============================================================================

if (-not $SkipApps) {
    Write-Step "STEP 5: Deploying Container Apps"

    $appsScript = Join-Path $PSScriptRoot "apps\deploy-container-apps.ps1"
    if (Test-Path $appsScript) {
        & $appsScript -ResourceGroup $ResourceGroup
        Write-Success "Container Apps deployment completed"
    } else {
        Write-Warning "Container Apps deployment script not found: $appsScript"
    }
} else {
    Write-Step "STEP 5: Skipping Container Apps Deployment"
}

# =============================================================================
# DEPLOYMENT COMPLETE
# =============================================================================

Write-Host @"

╔═══════════════════════════════════════════════════════════╗
║                                                             ║
║              DEPLOYMENT COMPLETED SUCCESSFULLY!            ║
║                                                             ║
╚═══════════════════════════════════════════════════════════╝

"@ -ForegroundColor Green

Write-Host "Resource Group: $ResourceGroup" -ForegroundColor Yellow
Write-Host "Location: $Location" -ForegroundColor Yellow
Write-Host ""
Write-Host "Next Steps:" -ForegroundColor Yellow
Write-Host "  1. Review the .env file in the repository root"
Write-Host "  2. Test the orchestrator endpoint"
Write-Host "  3. Configure frontend deployment (optional)"
Write-Host ""
Write-Host "View Resources:" -ForegroundColor Yellow
Write-Host "  az resource list -g $ResourceGroup -o table"
Write-Host ""
Write-Host "View Logs:" -ForegroundColor Yellow
Write-Host "  az containerapp logs show -n orchestrator -g $ResourceGroup --tail 50"
Write-Host ""
