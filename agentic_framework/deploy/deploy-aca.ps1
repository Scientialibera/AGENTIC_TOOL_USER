# Azure Container Apps Deployment Script
# Deploys Orchestrator and MCP servers to Azure Container Apps

param(
    [Parameter(Mandatory=$false)]
    [string]$ResourceGroup = "salesforcebot-rg",
    
    [Parameter(Mandatory=$false)]
    [string]$Location = "westus2",
    
    [Parameter(Mandatory=$false)]
    [string]$EnvironmentName = "salesforcebot-env",
    
    [Parameter(Mandatory=$false)]
    [string]$ContainerRegistry = "salesforcebotacr",
    
    [Parameter(Mandatory=$false)]
    [string]$ImageTag = "latest",
    
    [Parameter(Mandatory=$false)]
    [switch]$BuildImages,
    
    [Parameter(Mandatory=$false)]
    [string]$EnvFile = ".env"
)

$ErrorActionPreference = "Stop"

Write-Host " Deploying Agentic Framework to Azure Container Apps" -ForegroundColor Cyan
Write-Host "Resource Group: $ResourceGroup" -ForegroundColor Yellow
Write-Host "Location: $Location" -ForegroundColor Yellow
Write-Host "Environment: $EnvironmentName" -ForegroundColor Yellow
Write-Host "Registry: $ContainerRegistry" -ForegroundColor Yellow

# Variables
$OrchestratorApp = "orchestrator"
$FrontendApp = "salesforce-frontend"

$OrchestratorImage = "${ContainerRegistry}.azurecr.io/orchestrator:${ImageTag}"
$FrontendImage = "${ContainerRegistry}.azurecr.io/salesforce-frontend:${ImageTag}"

# ============================================================================
# DYNAMIC MCP DISCOVERY
# ============================================================================
Write-Host "`n Discovering MCP servers..." -ForegroundColor Cyan

# Get the agentic_framework directory
$buildDir = if ($EnvFile -match '^[^/\\]+$') { Get-Location } else { Split-Path -Parent $EnvFile }
$agenticFrameworkDir = Join-Path $buildDir "agentic_framework"
$mcpsDir = Join-Path $agenticFrameworkDir "mcps"

# Discover all MCP folders (exclude template, __pycache__, etc.)
$mcpFolders = Get-ChildItem -Path $mcpsDir -Directory | Where-Object {
    $_.Name -notmatch '^(__pycache__|TEMPLATE|\.)'
}

# Build MCP metadata array
# IMPORTANT: Each MCP must be assigned a unique sequential port starting from 8001
# The port assignment is alphabetical by folder name:
#   - graph MCP:       8001 (first alphabetically)
#   - interpreter MCP: 8002 (second alphabetically)
#   - sql MCP:         8003 (third alphabetically)
# The orchestrator always uses port 8000
$mcpServers = @()
$startPort = 8001  # MCPs start at 8001, orchestrator is 8000

foreach ($mcpFolder in $mcpFolders) {
    $mcpName = $mcpFolder.Name
    $mcpAppName = "$mcpName-mcp"
    $mcpImage = "${ContainerRegistry}.azurecr.io/${mcpAppName}:${ImageTag}"
    $mcpDockerfile = Join-Path $mcpFolder.FullName "Dockerfile"
    
    # Check if Dockerfile exists
    if (Test-Path $mcpDockerfile) {
        $mcpServers += @{
            Name = $mcpName
            AppName = $mcpAppName
            Image = $mcpImage
            Port = $startPort
            Dockerfile = "mcps/$mcpName/Dockerfile"
            FolderPath = $mcpFolder.FullName
        }
        
        Write-Host "  Found MCP: $mcpName (port $startPort)" -ForegroundColor Green
        $startPort++
    } else {
        Write-Host "  Skipping $mcpName (no Dockerfile found)" -ForegroundColor Yellow
    }
}

Write-Host " Discovered $($mcpServers.Count) MCP server(s)" -ForegroundColor Green

# Load environment variables from .env file
Write-Host "`n Loading environment variables from $EnvFile..." -ForegroundColor Cyan
if (Test-Path $EnvFile) {
    $envVars = @{}
    Get-Content $EnvFile | ForEach-Object {
        if ($_ -match '^([^#][^=]+)=(.*)$') {
            $key = $matches[1].Trim()
            $value = $matches[2].Trim()
            $envVars[$key] = $value
        }
    }
    Write-Host " Loaded $($envVars.Count) environment variables" -ForegroundColor Green
} else {
    Write-Host " Warning: $EnvFile not found, using minimal configuration" -ForegroundColor Yellow
    $envVars = @{}
}

# Step 1: Create Azure Container Registry if it doesn't exist
Write-Host "`n Checking Azure Container Registry..." -ForegroundColor Cyan
$acrExists = az acr show --name $ContainerRegistry --resource-group $ResourceGroup 2>$null
if (-not $acrExists) {
    Write-Host "Creating Azure Container Registry: $ContainerRegistry"
    az acr create --name $ContainerRegistry --resource-group $ResourceGroup --location $Location --sku Basic --admin-enabled true
    Write-Host " ACR created successfully" -ForegroundColor Green
} else {
    Write-Host "ACR already exists: $ContainerRegistry" -ForegroundColor Yellow
}

# Step 1a: Build and push images (if requested)
if ($BuildImages) {
    Write-Host "`n Building and pushing Docker images..." -ForegroundColor Cyan
    
    # Login to ACR
    Write-Host "Logging in to ACR..."
    az acr login --name $ContainerRegistry
    
    Write-Host "Build context: $agenticFrameworkDir" -ForegroundColor Gray
    
    # Build and push Orchestrator
    Write-Host "`nBuilding Orchestrator..."
    Push-Location $agenticFrameworkDir
    docker build -t $OrchestratorImage -f orchestrator/Dockerfile .
    if ($LASTEXITCODE -eq 0) {
        docker push $OrchestratorImage
        Write-Host " Orchestrator image pushed" -ForegroundColor Green
    } else {
        Write-Host " Failed to build Orchestrator image" -ForegroundColor Red
        Pop-Location
        exit 1
    }
    Pop-Location
    
    # Build and push all MCPs dynamically
    foreach ($mcp in $mcpServers) {
        Write-Host "`nBuilding $($mcp.Name) MCP..."
        Push-Location $agenticFrameworkDir
        docker build -t $mcp.Image -f $mcp.Dockerfile .
        if ($LASTEXITCODE -eq 0) {
            docker push $mcp.Image
            Write-Host " $($mcp.Name) MCP image pushed" -ForegroundColor Green
        } else {
            Write-Host " Failed to build $($mcp.Name) MCP image" -ForegroundColor Red
            Pop-Location
            exit 1
        }
        Pop-Location
    }
    
    # Build and push Frontend
    Write-Host "`nBuilding Frontend..."
    $frontendDir = Join-Path $agenticFrameworkDir "frontend"
    Push-Location $frontendDir
    docker build -t $FrontendImage -f Dockerfile .
    if ($LASTEXITCODE -eq 0) {
        docker push $FrontendImage
        Write-Host " Frontend image pushed" -ForegroundColor Green
    } else {
        Write-Host " Failed to build Frontend image" -ForegroundColor Red
        Pop-Location
        exit 1
    }
    Pop-Location
}

# Step 2: Create/Update Container Apps Environment
Write-Host "`n Setting up Container Apps Environment..." -ForegroundColor Cyan

$envExists = az containerapp env show --name $EnvironmentName --resource-group $ResourceGroup 2>$null
if (-not $envExists) {
    Write-Host "Creating new environment: $EnvironmentName"
    az containerapp env create `
        --name $EnvironmentName `
        --resource-group $ResourceGroup `
        --location $Location
} else {
    Write-Host "Environment already exists: $EnvironmentName" -ForegroundColor Yellow
}

# Step 3: Use existing Managed Identity
Write-Host "`n Using existing Managed Identity..." -ForegroundColor Cyan

$ManagedIdentityName = "salesforcebot-mi"

# Get the existing managed identity
$identityExists = az identity show --name $ManagedIdentityName --resource-group $ResourceGroup 2>$null
if (-not $identityExists) {
    Write-Host " Error: Managed identity '$ManagedIdentityName' not found in resource group '$ResourceGroup'" -ForegroundColor Red
    Write-Host "Please create the managed identity first or update the deployment script" -ForegroundColor Yellow
    exit 1
}

$managedIdentityId = az identity show --name $ManagedIdentityName --resource-group $ResourceGroup --query id -o tsv
$principalId = az identity show --name $ManagedIdentityName --resource-group $ResourceGroup --query principalId -o tsv

Write-Host "Using managed identity: $ManagedIdentityName" -ForegroundColor Green
Write-Host "  Identity ID: $managedIdentityId" -ForegroundColor Gray
Write-Host "  Principal ID: $principalId" -ForegroundColor Gray

# Step 4: Assign RBAC roles to Managed Identity (if needed)
Write-Host "`n Checking RBAC roles..." -ForegroundColor Cyan

# Get resource IDs and names
$cosmosAccountName = $(Split-Path $envVars['COSMOS_ENDPOINT'] -Leaf).Split('.')[0]
$gremlinAccountName = $(($envVars['AZURE_COSMOS_GREMLIN_ENDPOINT'] -replace 'https://|:443/','').Split('.')[0])
$openaiAccountName = $(Split-Path $envVars['AOAI_ENDPOINT'] -Leaf).Split('.')[0]

$cosmosAccountId = az cosmosdb show --name $cosmosAccountName --resource-group $ResourceGroup --query id -o tsv 2>$null
$gremlinAccountId = az cosmosdb show --name $gremlinAccountName --resource-group $ResourceGroup --query id -o tsv 2>$null
$openaiAccountId = az cognitiveservices account show --name $openaiAccountName --resource-group $ResourceGroup --query id -o tsv 2>$null

# Assign Cosmos DB Data Contributor
if ($cosmosAccountId) {
    Write-Host "Assigning Cosmos DB Data Contributor role to $ManagedIdentityName..."
    az cosmosdb sql role assignment create --account-name $cosmosAccountName --resource-group $ResourceGroup --role-definition-name "Cosmos DB Built-in Data Contributor" --principal-id $principalId --scope $cosmosAccountId 2>$null
}

# Assign Gremlin access
if ($gremlinAccountId -and ($gremlinAccountName -ne $cosmosAccountName)) {
    Write-Host "Assigning Gremlin access to $ManagedIdentityName..."
    az cosmosdb sql role assignment create --account-name $gremlinAccountName --resource-group $ResourceGroup --role-definition-name "Cosmos DB Built-in Data Contributor" --principal-id $principalId --scope $gremlinAccountId 2>$null
}

# Assign Cognitive Services OpenAI User
if ($openaiAccountId) {
    Write-Host "Assigning Cognitive Services OpenAI User role to $ManagedIdentityName..."
    az role assignment create --assignee $principalId --role "Cognitive Services OpenAI User" --scope $openaiAccountId 2>$null
}

# Assign ACR Pull permission for Container Registry
Write-Host "Assigning AcrPull role to $ManagedIdentityName for ACR..."
$acrId = az acr show --name $ContainerRegistry --resource-group $ResourceGroup --query id -o tsv
az role assignment create --assignee $principalId --role "AcrPull" --scope $acrId 2>$null

Write-Host " RBAC roles checked/assigned" -ForegroundColor Green

# ============================================================================
# Step 5: Deploy all MCPs dynamically
# ============================================================================
Write-Host "`n Deploying MCP servers..." -ForegroundColor Cyan

# Build common env vars (all MCPs need these)
$commonEnvVars = @{
    "DEV_MODE" = $envVars['DEV_MODE']
    "BYPASS_TOKEN" = $envVars['BYPASS_TOKEN']
    "DEBUG" = $envVars['DEBUG']
    "AZURE_CLIENT_ID" = "40aa2af4-4d0e-4664-97ce-15709f3fe34c"
    "AZURE_TENANT_ID" = $envVars['AZURE_TENANT_ID']
    "AOAI_ENDPOINT" = $envVars['AOAI_ENDPOINT']
    "AOAI_API_VERSION" = $envVars['AOAI_API_VERSION']
    "AOAI_CHAT_DEPLOYMENT" = $envVars['AOAI_CHAT_DEPLOYMENT']
    "AOAI_EMBEDDING_DEPLOYMENT" = $envVars['AOAI_EMBEDDING_DEPLOYMENT']
    "COSMOS_ENDPOINT" = $envVars['COSMOS_ENDPOINT']
    "COSMOS_DATABASE_NAME" = $envVars['COSMOS_DATABASE_NAME']
    "COSMOS_PROMPTS_CONTAINER" = $envVars['COSMOS_PROMPTS_CONTAINER']
    "COSMOS_SQL_SCHEMA_CONTAINER" = $envVars['COSMOS_SQL_SCHEMA_CONTAINER']
    "COSMOS_ACCOUNT_RESOLVER_CONTAINER" = $envVars['COSMOS_ACCOUNT_RESOLVER_CONTAINER']
    "COSMOS_AGENT_FUNCTIONS_CONTAINER" = $envVars['COSMOS_AGENT_FUNCTIONS_CONTAINER']
}

# MCP-specific env vars
$mcpSpecificEnvVars = @{
    "sql" = @{
        "FABRIC_SQL_ENDPOINT" = $envVars['FABRIC_SQL_ENDPOINT']
        "FABRIC_SQL_DATABASE" = $envVars['FABRIC_SQL_DATABASE']
        "FABRIC_WORKSPACE_ID" = $envVars['FABRIC_WORKSPACE_ID']
    }
    "graph" = @{
        "AZURE_COSMOS_GREMLIN_ENDPOINT" = $envVars['AZURE_COSMOS_GREMLIN_ENDPOINT']
        "AZURE_COSMOS_GREMLIN_DATABASE" = $envVars['AZURE_COSMOS_GREMLIN_DATABASE']
        "AZURE_COSMOS_GREMLIN_GRAPH" = $envVars['AZURE_COSMOS_GREMLIN_GRAPH']
        "AZURE_COSMOS_GREMLIN_PORT" = $envVars['AZURE_COSMOS_GREMLIN_PORT']
    }
    "interpreter" = @{
        # Interpreter MCP uses Assistants API, no additional vars needed
    }
}

foreach ($mcp in $mcpServers) {
    Write-Host "`n Deploying $($mcp.Name) MCP (port $($mcp.Port))..." -ForegroundColor Cyan
    
    # Build env vars array for this MCP
    $mcpEnvVarsList = @()
    $mcpEnvVarsList += "APP_NAME=$($mcp.AppName)"
    $mcpEnvVarsList += "MCP_PORT=$($mcp.Port)"  # Set the port for this MCP

    # Add common env vars
    foreach ($key in $commonEnvVars.Keys) {
        $mcpEnvVarsList += "$key=$($commonEnvVars[$key])"
    }

    # Add MCP-specific env vars if they exist
    if ($mcpSpecificEnvVars.ContainsKey($mcp.Name)) {
        foreach ($key in $mcpSpecificEnvVars[$mcp.Name].Keys) {
            $value = $mcpSpecificEnvVars[$mcp.Name][$key]
            if ($value) {
                $mcpEnvVarsList += "$key=$value"
            }
        }
    }
    
    # Check if app exists
    $mcpAppExists = az containerapp show --name $mcp.AppName --resource-group $ResourceGroup 2>$null
    if (-not $mcpAppExists) {
        Write-Host "Creating new $($mcp.Name) MCP app..." -ForegroundColor Yellow
        az containerapp create `
            --name $mcp.AppName `
            --resource-group $ResourceGroup `
            --environment $EnvironmentName `
            --image $mcp.Image `
            --target-port $mcp.Port `
            --ingress internal `
            --min-replicas 1 `
            --max-replicas 5 `
            --cpu 0.5 `
            --memory 1.0Gi `
            --registry-server "$ContainerRegistry.azurecr.io" `
            --registry-identity $managedIdentityId `
            --user-assigned $managedIdentityId `
            --env-vars $mcpEnvVarsList `
            --command "python" `
            --args "-m" "mcps.$($mcp.Name).server" "--host" "0.0.0.0" "--port" "$($mcp.Port)"
    } else {
        Write-Host "Updating existing $($mcp.Name) MCP app with new revision..." -ForegroundColor Yellow

        az containerapp update `
            --name $mcp.AppName `
            --resource-group $ResourceGroup `
            --image $mcp.Image `
            --set-env-vars $mcpEnvVarsList
        
        # Deactivate old revisions
        Write-Host "Deactivating old $($mcp.Name) MCP revisions..." -ForegroundColor Gray
        $oldRevisions = az containerapp revision list --name $mcp.AppName --resource-group $ResourceGroup --query "[?properties.active && properties.trafficWeight==``0``].name" -o tsv 2>$null
        if ($oldRevisions) {
            $oldRevisions | ForEach-Object {
                if ($_ -and $_.Trim()) {
                    az containerapp revision deactivate --name $mcp.AppName --resource-group $ResourceGroup --revision $_ 2>$null
                }
            }
        }
    }
    
    Write-Host " $($mcp.Name) MCP deployed" -ForegroundColor Green
}

# Step 6: Get MCP FQDNs for orchestrator config
Write-Host "`n Getting MCP endpoints..." -ForegroundColor Cyan

# Build MCP endpoints dynamically
$mcpEndpointsHash = @{}
foreach ($mcp in $mcpServers) {
    $fqdn = az containerapp show --name $mcp.AppName --resource-group $ResourceGroup --query properties.configuration.ingress.fqdn -o tsv
    $mcpEndpointsHash["$($mcp.Name)_mcp"] = "https://$fqdn/mcp"
    $mcp.Fqdn = $fqdn
    Write-Host "$($mcp.Name) MCP FQDN: https://$fqdn" -ForegroundColor Gray
}

# Step 7: Deploy Orchestrator with dynamically generated MCP endpoints
Write-Host "`n Deploying Orchestrator..." -ForegroundColor Cyan

# Build MCP_ENDPOINTS JSON manually to ensure proper formatting
$mcpEndpointsParts = @()
foreach ($key in $mcpEndpointsHash.Keys) {
    $mcpEndpointsParts += "`"$key`":`"$($mcpEndpointsHash[$key])`""
}
$mcpEndpointsJson = "{$($mcpEndpointsParts -join ',')}"

# Build LIST_OF_MCPS dynamically (comma-separated list of mcp names)
$listOfMcps = ($mcpServers | ForEach-Object { "$($_.Name)_mcp" }) -join ","

Write-Host "MCP_ENDPOINTS: $mcpEndpointsJson" -ForegroundColor Gray
Write-Host "LIST_OF_MCPS: $listOfMcps" -ForegroundColor Gray

# Build Orchestrator env vars
$orchestratorEnvVars = @(
    "APP_NAME=orchestrator",
    "DEV_MODE=$($envVars['DEV_MODE'])",
    "BYPASS_TOKEN=$($envVars['BYPASS_TOKEN'])",
    "DEBUG=$($envVars['DEBUG'])",
    "AZURE_CLIENT_ID=40aa2af4-4d0e-4664-97ce-15709f3fe34c",  # Managed identity client ID
    "AZURE_TENANT_ID=$($envVars['AZURE_TENANT_ID'])",
    "LIST_OF_MCPS=$listOfMcps",
    "MCP_ENDPOINTS=$mcpEndpointsJson",
    "AOAI_ENDPOINT=$($envVars['AOAI_ENDPOINT'])",
    "AOAI_API_VERSION=$($envVars['AOAI_API_VERSION'])",
    "AOAI_CHAT_DEPLOYMENT=$($envVars['AOAI_CHAT_DEPLOYMENT'])",
    "AOAI_EMBEDDING_DEPLOYMENT=$($envVars['AOAI_EMBEDDING_DEPLOYMENT'])",
    "COSMOS_ENDPOINT=$($envVars['COSMOS_ENDPOINT'])",
    "COSMOS_DATABASE_NAME=$($envVars['COSMOS_DATABASE_NAME'])",
    "COSMOS_CHAT_CONTAINER=$($envVars['COSMOS_CHAT_CONTAINER'])",
    "COSMOS_CACHE_CONTAINER=$($envVars['COSMOS_CACHE_CONTAINER'])",
    "COSMOS_FEEDBACK_CONTAINER=$($envVars['COSMOS_FEEDBACK_CONTAINER'])",
    "COSMOS_PROMPTS_CONTAINER=$($envVars['COSMOS_PROMPTS_CONTAINER'])",
    "COSMOS_AGENT_FUNCTIONS_CONTAINER=$($envVars['COSMOS_AGENT_FUNCTIONS_CONTAINER'])"
)

# Check if app exists
$orchAppExists = az containerapp show --name $OrchestratorApp --resource-group $ResourceGroup 2>$null
if (-not $orchAppExists) {
    Write-Host "Creating new Orchestrator app..." -ForegroundColor Yellow
    az containerapp create `
        --name $OrchestratorApp `
        --resource-group $ResourceGroup `
        --environment $EnvironmentName `
        --image $OrchestratorImage `
        --target-port 8000 `
        --ingress external `
        --min-replicas 2 `
        --max-replicas 10 `
        --cpu 1.0 `
        --memory 2.0Gi `
        --registry-server "$ContainerRegistry.azurecr.io" `
        --registry-identity $managedIdentityId `
        --user-assigned $managedIdentityId `
        --env-vars $orchestratorEnvVars
} else {
    Write-Host "Updating existing Orchestrator app with new revision..." -ForegroundColor Yellow
    az containerapp update `
        --name $OrchestratorApp `
        --resource-group $ResourceGroup `
        --image $OrchestratorImage `
        --set-env-vars $orchestratorEnvVars
    
    # Deactivate old revisions (keeps the latest active)
    Write-Host "Deactivating old Orchestrator revisions..." -ForegroundColor Gray
    $oldRevisions = az containerapp revision list --name $OrchestratorApp --resource-group $ResourceGroup --query "[?properties.active && properties.trafficWeight==``0``].name" -o tsv 2>$null
    if ($oldRevisions) {
        $oldRevisions | ForEach-Object {
            if ($_ -and $_.Trim()) {
                az containerapp revision deactivate --name $OrchestratorApp --resource-group $ResourceGroup --revision $_ 2>$null
            }
        }
    }
}

Write-Host " Orchestrator deployed (DEV_MODE=true, BYPASS_TOKEN=false)" -ForegroundColor Green

# Step 9: Deploy Frontend
Write-Host "`n Deploying Frontend..." -ForegroundColor Cyan

# Frontend environment variables (bcrypt hash for password "sfbot365")
$frontendEnvVars = @(
    "APP_USERNAME=demo",
    "APP_PASSWORD_HASH=`$2a`$12`$OS3NkX.f9Dar.hLxvt/LJekEj3ZDTYppldqe/xR4yUu9teURE.mGm",
    "NODE_ENV=production",
    "ORCHESTRATOR_URL=https://$OrchestratorFqdn"
)

# Check if frontend app exists
$frontendAppExists = az containerapp show --name $FrontendApp --resource-group $ResourceGroup 2>$null
if (-not $frontendAppExists) {
    Write-Host "Creating new Frontend app..." -ForegroundColor Yellow
    az containerapp create `
        --name $FrontendApp `
        --resource-group $ResourceGroup `
        --environment $EnvironmentName `
        --image $FrontendImage `
        --target-port 8080 `
        --ingress external `
        --min-replicas 1 `
        --max-replicas 5 `
        --cpu 0.5 `
        --memory 1.0Gi `
        --registry-server "$ContainerRegistry.azurecr.io" `
        --registry-identity $managedIdentityId `
        --user-assigned $managedIdentityId `
        --env-vars $frontendEnvVars
} else {
    Write-Host "Updating existing Frontend app with new revision..." -ForegroundColor Yellow
    az containerapp update `
        --name $FrontendApp `
        --resource-group $ResourceGroup `
        --image $FrontendImage `
        --set-env-vars $frontendEnvVars
    
    # Deactivate old revisions
    Write-Host "Deactivating old Frontend revisions..." -ForegroundColor Gray
    $oldRevisions = az containerapp revision list --name $FrontendApp --resource-group $ResourceGroup --query "[?properties.active && properties.trafficWeight==``0``].name" -o tsv 2>$null
    if ($oldRevisions) {
        $oldRevisions | ForEach-Object {
            if ($_ -and $_.Trim()) {
                az containerapp revision deactivate --name $FrontendApp --resource-group $ResourceGroup --revision $_ 2>$null
            }
        }
    }
}

Write-Host " Frontend deployed" -ForegroundColor Green

# Step 10: Get Application URLs
Write-Host "`n Getting application URLs..." -ForegroundColor Cyan

$OrchestratorFqdn = az containerapp show --name $OrchestratorApp --resource-group $ResourceGroup --query properties.configuration.ingress.fqdn -o tsv
$FrontendFqdn = az containerapp show --name $FrontendApp --resource-group $ResourceGroup --query properties.configuration.ingress.fqdn -o tsv

Write-Host "`n Deployment Complete!" -ForegroundColor Green
Write-Host "`n Application URLs:" -ForegroundColor Cyan
Write-Host "  Frontend: https://$FrontendFqdn" -ForegroundColor Green
Write-Host "  Orchestrator: https://$OrchestratorFqdn" -ForegroundColor White
Write-Host "`n MCP Servers (internal):" -ForegroundColor Cyan
foreach ($mcp in $mcpServers) {
    Write-Host "  $($mcp.Name) MCP: https://$($mcp.Fqdn)" -ForegroundColor Gray
}
Write-Host "`n Frontend Login Credentials:" -ForegroundColor Cyan
Write-Host "  Username: demo" -ForegroundColor White
Write-Host "  Password: sfbot365" -ForegroundColor Yellow

Write-Host "`n Configuration:" -ForegroundColor Cyan
Write-Host "  DEV_MODE=true (bypasses RBAC, uses dummy SQL data)" -ForegroundColor Yellow
Write-Host "  BYPASS_TOKEN=false (JWT authentication ENABLED)" -ForegroundColor Green

Write-Host "`n Test the deployment with authentication:" -ForegroundColor Cyan
Write-Host "  # Get Azure AD token" -ForegroundColor Gray
Write-Host '  $token = az account get-access-token --resource https://cognitiveservices.azure.com --query accessToken -o tsv' -ForegroundColor White
Write-Host "  # Test health endpoint" -ForegroundColor Gray
Write-Host "  curl -H `"Authorization: Bearer `$token`" https://$OrchestratorFqdn/health" -ForegroundColor White

Write-Host "`n  Next Steps:" -ForegroundColor Yellow
Write-Host "  1. Assign RBAC roles for Managed Identities:"
Write-Host "     - Cosmos DB Data Contributor"
Write-Host "     - Cognitive Services OpenAI User"
Write-Host "  2. When Fabric is ready, update DEV_MODE=false and configure:"
Write-Host "     - Fabric Lakehouse Reader (for SQL MCP)"
Write-Host "     - Update FABRIC_SQL_ENDPOINT, FABRIC_SQL_DATABASE, FABRIC_WORKSPACE_ID"
Write-Host "  3. Test chat endpoint with authentication:"
Write-Host "     curl -X POST -H `"Authorization: Bearer `$token`" -H `"Content-Type: application/json`" \" -ForegroundColor White
Write-Host "       -d '{`"query`": `"Show me opportunities`"}' https://$OrchestratorFqdn/chat" -ForegroundColor White
