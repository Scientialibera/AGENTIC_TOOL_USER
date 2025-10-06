#Requires -Version 7.0
<#
.SYNOPSIS
    Grant developer/admin user the same Azure RBAC permissions as the managed identity

.DESCRIPTION
    This script assigns the same RBAC roles to a user or service principal that the
    managed identity has, allowing developers to run the framework locally with the
    same permissions as production.

    Grants access to:
    - Azure OpenAI (Cognitive Services OpenAI User)
    - Cosmos DB NoSQL (Cosmos DB Built-in Data Contributor)
    - Cosmos DB Gremlin (Cosmos DB Built-in Data Contributor)
    - Azure Container Registry (AcrPull) - optional
    - Resource Group (Reader)

.PARAMETER ResourceGroup
    The name of the resource group containing the deployed resources

.PARAMETER UserEmail
    Email address of the user to grant access to (e.g., admin@contoso.com)

.PARAMETER UserObjectId
    Object ID of the user (alternative to UserEmail)

.PARAMETER ServicePrincipalId
    Object ID of a service principal (for CI/CD scenarios)

.PARAMETER IncludeContributor
    Also grant Contributor role on the resource group (allows creating/modifying resources)

.EXAMPLE
    .\grant-developer-access.ps1 -ResourceGroup "mybot-rg" -UserEmail "dev@contoso.com"

.EXAMPLE
    .\grant-developer-access.ps1 -ResourceGroup "mybot-rg" -UserObjectId "12345678-1234-1234-1234-123456789012"

.EXAMPLE
    .\grant-developer-access.ps1 -ResourceGroup "mybot-rg" -UserEmail "admin@contoso.com" -IncludeContributor
#>

param(
    [Parameter(Mandatory=$true)]
    [string]$ResourceGroup,

    [Parameter(Mandatory=$false)]
    [string]$UserEmail,

    [Parameter(Mandatory=$false)]
    [string]$UserObjectId,

    [Parameter(Mandatory=$false)]
    [string]$ServicePrincipalId,

    [Parameter(Mandatory=$false)]
    [switch]$IncludeContributor
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
        [string]$PrincipalType = "User"
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

    try {
        az role assignment create `
            --assignee-object-id $PrincipalId `
            --assignee-principal-type $PrincipalType `
            --role $RoleDefinitionId `
            --scope $Scope `
            -o none 2>$null

        if ($LASTEXITCODE -eq 0) {
            Write-Success "  Assigned $RoleName"
        } else {
            Write-Warning "  Failed to assign $RoleName (may not have permission)"
        }
    } catch {
        Write-Warning "  Failed to assign $RoleName : $_"
    }
}

# =============================================================================
# VALIDATE INPUTS
# =============================================================================

Write-Step "Validating inputs"

# Ensure at least one principal identifier is provided
if (-not $UserEmail -and -not $UserObjectId -and -not $ServicePrincipalId) {
    throw "Must provide either -UserEmail, -UserObjectId, or -ServicePrincipalId"
}

# Get Azure context
$context = az account show -o json 2>$null | ConvertFrom-Json
if (-not $context) {
    throw "Not logged in to Azure. Please run 'az login' first."
}

$tenantId = $context.tenantId
$subscriptionId = $context.id
Write-Info "Subscription: $($context.name)"
Write-Info "Tenant: $tenantId"

# =============================================================================
# RESOLVE PRINCIPAL
# =============================================================================

Write-Step "Resolving principal identity"

$principalId = $null
$principalType = "User"
$principalDisplayName = $null

if ($ServicePrincipalId) {
    # Service principal provided directly
    $principalId = $ServicePrincipalId
    $principalType = "ServicePrincipal"

    $sp = az ad sp show --id $principalId -o json 2>$null | ConvertFrom-Json
    if ($sp) {
        $principalDisplayName = $sp.displayName
    } else {
        $principalDisplayName = "Service Principal"
    }

    Write-Success "Using Service Principal: $principalDisplayName"
    Write-Info "Principal ID: $principalId"
}
elseif ($UserObjectId) {
    # Object ID provided directly
    $principalId = $UserObjectId
    $principalType = "User"

    $user = az ad user show --id $principalId -o json 2>$null | ConvertFrom-Json
    if ($user) {
        $principalDisplayName = $user.userPrincipalName
    } else {
        $principalDisplayName = "User"
    }

    Write-Success "Using User (Object ID): $principalDisplayName"
    Write-Info "Principal ID: $principalId"
}
else {
    # Email provided - lookup object ID
    Write-Info "Looking up user by email: $UserEmail"

    $user = az ad user show --id $UserEmail -o json 2>$null | ConvertFrom-Json
    if (-not $user) {
        throw "User not found: $UserEmail. Ensure the email is correct and the user exists in Azure AD."
    }

    $principalId = $user.id
    $principalType = "User"
    $principalDisplayName = $user.userPrincipalName

    Write-Success "Found user: $principalDisplayName"
    Write-Info "Principal ID: $principalId"
}

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
# ASSIGN RBAC ROLES (Same as Managed Identity)
# =============================================================================

Write-Step "Granting RBAC permissions (matching managed identity)"

# 1. Azure OpenAI - Cognitive Services OpenAI User
if ($openAiId) {
    Ensure-RoleAssignment `
        -PrincipalId $principalId `
        -Scope $openAiId `
        -RoleDefinitionId "5e0bd9bd-7b93-4f28-af87-19fc36ad61bd" `
        -RoleName "Cognitive Services OpenAI User" `
        -PrincipalType $principalType
}

# 2. Cosmos DB - Built-in Data Contributor (for each account)
foreach ($cosmosAccount in $cosmosAccounts) {
    $accountName = $cosmosAccount.name
    Write-Info "Configuring Cosmos DB: $accountName"

    $cosmosId = $cosmosAccount.id

    # Check if this is a Gremlin account
    $capabilities = $cosmosAccount.capabilities
    $isGremlin = $capabilities | Where-Object { $_.name -eq "EnableGremlin" }

    # Cosmos DB uses custom RBAC for data plane
    # Role definition ID for "Cosmos DB Built-in Data Contributor"
    $roleDefinitionId = "00000000-0000-0000-0000-000000000002"

    Write-Info "  Assigning Cosmos DB data plane permissions..."
    $roleAssignmentId = [guid]::NewGuid().ToString()

    # Check if assignment exists
    $existingAssignments = az cosmosdb sql role assignment list `
        --account-name $accountName `
        --resource-group $ResourceGroup `
        -o json 2>$null | ConvertFrom-Json

    $exists = $existingAssignments | Where-Object {
        $_.principalId -eq $principalId -and $_.roleDefinitionId -like "*$roleDefinitionId"
    }

    if (-not $exists) {
        try {
            az cosmosdb sql role assignment create `
                --account-name $accountName `
                --resource-group $ResourceGroup `
                --role-definition-id "$cosmosId/sqlRoleDefinitions/$roleDefinitionId" `
                --principal-id $principalId `
                --scope $cosmosId `
                -o none 2>$null

            if ($LASTEXITCODE -eq 0) {
                Write-Success "  Assigned Cosmos DB data contributor"
            } else {
                Write-Warning "  Failed to assign Cosmos DB data contributor (may not have permission)"
            }
        } catch {
            Write-Warning "  Failed to assign Cosmos DB permissions: $_"
        }
    } else {
        Write-Info "  Already assigned"
    }

    # For Gremlin accounts, also assign Account Reader Role
    if ($isGremlin) {
        Ensure-RoleAssignment `
            -PrincipalId $principalId `
            -Scope $cosmosId `
            -RoleDefinitionId "00000000-0000-0000-0000-000000000001" `
            -RoleName "Cosmos DB Account Reader Role" `
            -PrincipalType $principalType
    }
}

# 3. Azure Container Registry - AcrPull (optional, for pulling images)
if ($acrId) {
    Ensure-RoleAssignment `
        -PrincipalId $principalId `
        -Scope $acrId `
        -RoleDefinitionId "7f951dda-4ed3-4680-a7ca-43fe172d538d" `
        -RoleName "AcrPull" `
        -PrincipalType $principalType
}

# 4. Resource Group - Reader (for listing resources)
Ensure-RoleAssignment `
    -PrincipalId $principalId `
    -Scope $rgId `
    -RoleDefinitionId "acdd72a7-3385-48ef-bd42-f606fba81ae7" `
    -RoleName "Reader" `
    -PrincipalType $principalType

# 5. Resource Group - Contributor (optional, for creating/modifying resources)
if ($IncludeContributor) {
    Write-Info "Including Contributor role (creates/modifies resources)"
    Ensure-RoleAssignment `
        -PrincipalId $principalId `
        -Scope $rgId `
        -RoleDefinitionId "b24988ac-6180-42a0-ab88-20f7382dd24c" `
        -RoleName "Contributor" `
        -PrincipalType $principalType
}

# =============================================================================
# WAIT FOR PROPAGATION
# =============================================================================

Write-Step "Waiting for role assignments to propagate (60 seconds)"
Start-Sleep -Seconds 60
Write-Success "Propagation complete"

# =============================================================================
# OUTPUT SUMMARY
# =============================================================================

Write-Step "Developer Access Configuration Complete"
Write-Host ""
Write-Host "Principal Details:" -ForegroundColor Yellow
Write-Host "  Display Name: $principalDisplayName"
Write-Host "  Principal ID: $principalId"
Write-Host "  Type:         $principalType"
Write-Host ""
Write-Host "Permissions Granted:" -ForegroundColor Yellow
if ($openAiId) { Write-Host "  ✓ Azure OpenAI (Cognitive Services OpenAI User)" }
Write-Host "  ✓ Cosmos DB ($($cosmosAccounts.Count) account(s), Data Contributor)"
if ($acrId) { Write-Host "  ✓ Azure Container Registry (AcrPull)" }
Write-Host "  ✓ Resource Group (Reader)"
if ($IncludeContributor) { Write-Host "  ✓ Resource Group (Contributor)" }
Write-Host ""
Write-Host "Next Steps for Local Development:" -ForegroundColor Yellow
Write-Host "  1. Ensure you're logged in with this account:"
Write-Host "     az login $(if ($UserEmail) { "--user $UserEmail" })"
Write-Host ""
Write-Host "  2. Set the subscription:"
Write-Host "     az account set --subscription $subscriptionId"
Write-Host ""
Write-Host "  3. Generate/update .env file:"
Write-Host "     .\deploy\utils\generate-env.ps1 -ResourceGroup $ResourceGroup"
Write-Host ""
Write-Host "  4. Start local development:"
Write-Host "     cd agentic_framework"
Write-Host "     python -m mcps.graph.server       # Terminal 1"
Write-Host "     python -m mcps.interpreter.server # Terminal 2"
Write-Host "     python -m mcps.sql.server         # Terminal 3"
Write-Host "     python -m orchestrator.app        # Terminal 4"
Write-Host ""
Write-Host "Authentication Mode:" -ForegroundColor Yellow
Write-Host "  Your local development will use DefaultAzureCredential with the"
Write-Host "  permissions granted above. No keys or connection strings needed!"
Write-Host ""
