#Requires -Version 7.0
<#
.SYNOPSIS
    Configure RBAC permissions for the Agentic Framework Managed Identity

.DESCRIPTION
    This script assigns all necessary RBAC roles to the managed identity created
    by the infrastructure deployment. It handles:
    - Azure OpenAI permissions (Cognitive Services OpenAI User)
    - Cosmos DB data plane permissions (Cosmos DB Data Contributor)
    - Cosmos DB Gremlin permissions
    - Container Registry permissions (AcrPull)
    - Resource Group contributor access

.PARAMETER ResourceGroup
    The name of the resource group containing the deployed resources

.PARAMETER ManagedIdentityName
    The name of the managed identity to configure (default: <baseName>-identity)

.PARAMETER WaitForPropagation
    Wait for role assignments to propagate (default: $true)

.EXAMPLE
    .\configure-rbac.ps1 -ResourceGroup "agentic-rg" -ManagedIdentityName "agentic-identity"
#>

param(
    [Parameter(Mandatory=$true)]
    [string]$ResourceGroup,

    [Parameter(Mandatory=$false)]
    [string]$ManagedIdentityName,

    [Parameter(Mandatory=$false)]
    [bool]$WaitForPropagation = $true
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

function Ensure-RoleAssignment {
    param(
        [string]$PrincipalId,
        [string]$Scope,
        [string]$RoleDefinitionId,
        [string]$RoleName,
        [string]$PrincipalType = "ServicePrincipal"
    )

    if (-not $Scope) {
        Write-Warning "Scope is empty, skipping role assignment for $RoleName"
        return
    }

    Write-Info "Checking role: $RoleName"

    # Check if assignment already exists
    $existing = az role assignment list `
        --assignee $PrincipalId `
        --scope $Scope `
        --role $RoleDefinitionId `
        --query "[0].id" `
        -o tsv 2>$null

    if ($existing) {
        Write-Info "  Already assigned"
        return
    }

    # Create role assignment
    Write-Info "  Assigning..."
    az role assignment create `
        --assignee-object-id $PrincipalId `
        --assignee-principal-type $PrincipalType `
        --role $RoleDefinitionId `
        --scope $Scope `
        -o none

    Write-Success "  Assigned $RoleName"
}

# =============================================================================
# MAIN SCRIPT
# =============================================================================

Write-Step "Validating Azure CLI authentication"
$context = az account show -o json 2>$null | ConvertFrom-Json
if (-not $context) {
    throw "Not logged in to Azure. Please run 'az login' first."
}

$subscriptionId = $context.id
$tenantId = $context.tenantId
Write-Info "Subscription: $($context.name)"
Write-Info "Tenant: $tenantId"

# =============================================================================
# DISCOVER RESOURCES
# =============================================================================

Write-Step "Discovering resources in resource group: $ResourceGroup"

# Get resource group
$rg = az group show -n $ResourceGroup -o json 2>$null | ConvertFrom-Json
if (-not $rg) {
    throw "Resource group '$ResourceGroup' not found"
}
$rgId = $rg.id
Write-Success "Found resource group"

# Get managed identity
if (-not $ManagedIdentityName) {
    Write-Info "Auto-discovering managed identity..."
    $identities = az identity list -g $ResourceGroup --query "[].name" -o tsv
    if ($identities -is [array]) {
        $ManagedIdentityName = $identities[0]
    } else {
        $ManagedIdentityName = $identities
    }
    if (-not $ManagedIdentityName) {
        throw "No managed identity found in resource group. Please specify -ManagedIdentityName"
    }
}

$identity = az identity show -g $ResourceGroup -n $ManagedIdentityName -o json 2>$null | ConvertFrom-Json
if (-not $identity) {
    throw "Managed identity '$ManagedIdentityName' not found in resource group '$ResourceGroup'"
}

$principalId = $identity.principalId
$clientId = $identity.clientId
Write-Success "Found managed identity: $ManagedIdentityName"
Write-Info "Principal ID: $principalId"
Write-Info "Client ID: $clientId"

# Get Azure OpenAI account
Write-Info "Discovering Azure OpenAI account..."
$openAiAccount = az cognitiveservices account list -g $ResourceGroup --query "[?kind=='OpenAI'] | [0]" -o json 2>$null | ConvertFrom-Json
if ($openAiAccount) {
    $openAiId = $openAiAccount.id
    Write-Success "Found OpenAI account: $($openAiAccount.name)"
} else {
    Write-Warning "No Azure OpenAI account found"
    $openAiId = $null
}

# Get Cosmos DB accounts
Write-Info "Discovering Cosmos DB accounts..."
$cosmosAccounts = az cosmosdb list -g $ResourceGroup -o json 2>$null | ConvertFrom-Json
if ($cosmosAccounts) {
    Write-Success "Found $($cosmosAccounts.Count) Cosmos DB account(s)"
} else {
    Write-Warning "No Cosmos DB accounts found"
}

# Get Container Registry
Write-Info "Discovering Azure Container Registry..."
$acr = az acr list -g $ResourceGroup --query "[0]" -o json 2>$null | ConvertFrom-Json
if ($acr) {
    $acrId = $acr.id
    Write-Success "Found ACR: $($acr.name)"
} else {
    Write-Warning "No Azure Container Registry found"
    $acrId = $null
}

# =============================================================================
# ASSIGN RBAC ROLES
# =============================================================================

Write-Step "Configuring RBAC permissions"

# 1. Azure OpenAI - Cognitive Services OpenAI User
if ($openAiId) {
    Ensure-RoleAssignment `
        -PrincipalId $principalId `
        -Scope $openAiId `
        -RoleDefinitionId "5e0bd9bd-7b93-4f28-af87-19fc36ad61bd" `
        -RoleName "Cognitive Services OpenAI User"
}

# 2. Cosmos DB - Built-in Data Contributor (for each account)
foreach ($cosmosAccount in $cosmosAccounts) {
    $accountName = $cosmosAccount.name
    Write-Info "Configuring Cosmos DB: $accountName"

    # Cosmos DB uses custom RBAC, not Azure RBAC for data plane
    # We need to use the Cosmos DB specific role assignment API
    $cosmosId = $cosmosAccount.id

    # Check if this is a SQL API or Gremlin API account
    $capabilities = $cosmosAccount.capabilities
    $isGremlin = $capabilities | Where-Object { $_.name -eq "EnableGremlin" }

    if ($isGremlin) {
        # For Gremlin, we still need service-level access
        Ensure-RoleAssignment `
            -PrincipalId $principalId `
            -Scope $cosmosId `
            -RoleDefinitionId "00000000-0000-0000-0000-000000000001" `
            -RoleName "Cosmos DB Account Reader Role"
    }

    # Assign built-in data contributor role (works for both SQL and Gremlin)
    # Role definition ID for "Cosmos DB Built-in Data Contributor"
    $roleDefinitionId = "00000000-0000-0000-0000-000000000002"

    # Create Cosmos DB RBAC assignment using REST API
    Write-Info "  Assigning Cosmos DB data plane permissions..."
    $roleAssignmentId = [guid]::NewGuid().ToString()
    $roleAssignmentPath = "$cosmosId/sqlRoleAssignments/$roleAssignmentId"

    # Check if assignment exists
    $existingAssignments = az cosmosdb sql role assignment list `
        --account-name $accountName `
        --resource-group $ResourceGroup `
        -o json 2>$null | ConvertFrom-Json

    $exists = $existingAssignments | Where-Object {
        $_.principalId -eq $principalId -and $_.roleDefinitionId -like "*$roleDefinitionId"
    }

    if (-not $exists) {
        az cosmosdb sql role assignment create `
            --account-name $accountName `
            --resource-group $ResourceGroup `
            --role-definition-id "$cosmosId/sqlRoleDefinitions/$roleDefinitionId" `
            --principal-id $principalId `
            --scope $cosmosId `
            -o none 2>$null

        Write-Success "  Assigned Cosmos DB data contributor"
    } else {
        Write-Info "  Already assigned"
    }
}

# 3. Azure Container Registry - AcrPull
if ($acrId) {
    Ensure-RoleAssignment `
        -PrincipalId $principalId `
        -Scope $acrId `
        -RoleDefinitionId "7f951dda-4ed3-4680-a7ca-43fe172d538d" `
        -RoleName "AcrPull"
}

# 4. Resource Group - Contributor (for creating resources during deployment)
Ensure-RoleAssignment `
    -PrincipalId $principalId `
    -Scope $rgId `
    -RoleDefinitionId "b24988ac-6180-42a0-ab88-20f7382dd24c" `
    -RoleName "Contributor"

# =============================================================================
# WAIT FOR PROPAGATION
# =============================================================================

if ($WaitForPropagation) {
    Write-Step "Waiting for role assignments to propagate (60 seconds)"
    Start-Sleep -Seconds 60
    Write-Success "Propagation complete"
}

# =============================================================================
# OUTPUT SUMMARY
# =============================================================================

Write-Step "RBAC Configuration Complete"
Write-Host ""
Write-Host "Managed Identity Details:" -ForegroundColor Yellow
Write-Host "  Name:         $ManagedIdentityName"
Write-Host "  Principal ID: $principalId"
Write-Host "  Client ID:    $clientId"
Write-Host "  Tenant ID:    $tenantId"
Write-Host ""
Write-Host "Permissions Configured:" -ForegroundColor Yellow
if ($openAiId) { Write-Host "  ✓ Azure OpenAI (Cognitive Services OpenAI User)" }
Write-Host "  ✓ Cosmos DB ($($cosmosAccounts.Count) account(s), Data Contributor)"
if ($acrId) { Write-Host "  ✓ Azure Container Registry (AcrPull)" }
Write-Host "  ✓ Resource Group (Contributor)"
Write-Host ""
Write-Host "Next Steps:" -ForegroundColor Yellow
Write-Host "  1. Add these values to your .env file:"
Write-Host "     AZURE_CLIENT_ID=$clientId"
Write-Host "     AZURE_TENANT_ID=$tenantId"
Write-Host ""
Write-Host "  2. Run data initialization:"
Write-Host "     python deploy/data/init-cosmos-data.py"
Write-Host ""
