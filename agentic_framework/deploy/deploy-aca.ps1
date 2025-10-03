# Azure Container Apps Deployment Script
# Depl    # Build and push orchestrator
    Write-Host "`nBuilding Orchestrator..."
    docker build -t $OrchestratorImage -f orchestrator/Dockerfile .
    docker push $OrchestratorImage
    Write-Host " Orchestrator image pushed" -ForegroundColor Greenrchestrator and MCP servers to Azure Container Apps

param(
    [Parameter(Mandatory=$true)]
    [string]$ResourceGroup,
    
    [Parameter(Mandatory=$true)]
    [string]$Location,
    
    [Parameter(Mandatory=$true)]
    [string]$EnvironmentName,
    
    [Parameter(Mandatory=$true)]
    [string]$ContainerRegistry,
    
    [Parameter(Mandatory=$false)]
    [string]$ImageTag = "latest",
    
    [Parameter(Mandatory=$false)]
    [switch]$BuildImages
)

$ErrorActionPreference = "Stop"

Write-Host " Deploying Agentic Framework to Azure Container Apps" -ForegroundColor Cyan
Write-Host "Resource Group: $ResourceGroup" -ForegroundColor Yellow
Write-Host "Location: $Location" -ForegroundColor Yellow
Write-Host "Environment: $EnvironmentName" -ForegroundColor Yellow
Write-Host "Registry: $ContainerRegistry" -ForegroundColor Yellow

# Variables
$OrchestratorApp = "orchestrator"
$SqlMcpApp = "sql-mcp"
$GraphMcpApp = "graph-mcp"

$OrchestratorImage = "$ContainerRegistry.azurecr.io/orchestrator:$ImageTag"
$SqlMcpImage = "$ContainerRegistry.azurecr.io/sql-mcp:$ImageTag"
$GraphMcpImage = "$ContainerRegistry.azurecr.io/graph-mcp:$ImageTag"

# Step 1: Build and push images (if requested)
if ($BuildImages) {
    Write-Host "`n Building and pushing Docker images..." -ForegroundColor Cyan
    
    # Login to ACR
    Write-Host "Logging in to ACR..."
    az acr login --name $ContainerRegistry
    
    # Build and push Orchestrator
    Write-Host "`nBuilding Orchestrator..."
    docker build -t $OrchestratorImage -f Dockerfile .
    docker push $OrchestratorImage
    Write-Host " Orchestrator image pushed" -ForegroundColor Green
    
    # Build and push SQL MCP
    Write-Host "`nBuilding SQL MCP..."
    docker build -t $SqlMcpImage -f mcps/sql/Dockerfile .
    docker push $SqlMcpImage
    Write-Host " SQL MCP image pushed" -ForegroundColor Green
    
    # Build and push Graph MCP
    Write-Host "`nBuilding Graph MCP..."
    docker build -t $GraphMcpImage -f mcps/graph/Dockerfile .
    docker push $GraphMcpImage
    Write-Host " Graph MCP image pushed" -ForegroundColor Green
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

# Step 3: Create Managed Identity for each service
Write-Host "`n Creating Managed Identities..." -ForegroundColor Cyan

$OrchestratorIdentity = "${OrchestratorApp}-identity"
$SqlMcpIdentity = "${SqlMcpApp}-identity"
$GraphMcpIdentity = "${GraphMcpApp}-identity"

# Orchestrator identity
$orchIdentityId = az identity show --name $OrchestratorIdentity --resource-group $ResourceGroup --query id -o tsv 2>$null
if (-not $orchIdentityId) {
    Write-Host "Creating identity: $OrchestratorIdentity"
    az identity create --name $OrchestratorIdentity --resource-group $ResourceGroup --location $Location
}

# SQL MCP identity
$sqlIdentityId = az identity show --name $SqlMcpIdentity --resource-group $ResourceGroup --query id -o tsv 2>$null
if (-not $sqlIdentityId) {
    Write-Host "Creating identity: $SqlMcpIdentity"
    az identity create --name $SqlMcpIdentity --resource-group $ResourceGroup --location $Location
}

# Graph MCP identity
$graphIdentityId = az identity show --name $GraphMcpIdentity --resource-group $ResourceGroup --query id -o tsv 2>$null
if (-not $graphIdentityId) {
    Write-Host "Creating identity: $GraphMcpIdentity"
    az identity create --name $GraphMcpIdentity --resource-group $ResourceGroup --location $Location
}

Write-Host " Managed identities configured" -ForegroundColor Green

# Step 4: Deploy SQL MCP
Write-Host "`n Deploying SQL MCP..." -ForegroundColor Cyan

az containerapp create `
    --name $SqlMcpApp `
    --resource-group $ResourceGroup `
    --environment $EnvironmentName `
    --image $SqlMcpImage `
    --target-port 8001 `
    --ingress internal `
    --min-replicas 1 `
    --max-replicas 5 `
    --cpu 0.5 `
    --memory 1.0Gi `
    --registry-server "$ContainerRegistry.azurecr.io" `
    --user-assigned $SqlMcpIdentity `
    --env-vars `
        "APP_NAME=sql-mcp" `
        "DEV_MODE=false" `
        "DEBUG=false" 2>$null

if ($LASTEXITCODE -ne 0) {
    Write-Host "Updating existing SQL MCP app..." -ForegroundColor Yellow
    az containerapp update `
        --name $SqlMcpApp `
        --resource-group $ResourceGroup `
        --image $SqlMcpImage
}

Write-Host " SQL MCP deployed" -ForegroundColor Green

# Step 5: Deploy Graph MCP
Write-Host "`n Deploying Graph MCP..." -ForegroundColor Cyan

az containerapp create `
    --name $GraphMcpApp `
    --resource-group $ResourceGroup `
    --environment $EnvironmentName `
    --image $GraphMcpImage `
    --target-port 8002 `
    --ingress internal `
    --min-replicas 1 `
    --max-replicas 5 `
    --cpu 0.5 `
    --memory 1.0Gi `
    --registry-server "$ContainerRegistry.azurecr.io" `
    --user-assigned $GraphMcpIdentity `
    --env-vars `
        "APP_NAME=graph-mcp" `
        "DEV_MODE=false" `
        "DEBUG=false" 2>$null

if ($LASTEXITCODE -ne 0) {
    Write-Host "Updating existing Graph MCP app..." -ForegroundColor Yellow
    az containerapp update `
        --name $GraphMcpApp `
        --resource-group $ResourceGroup `
        --image $GraphMcpImage
}

Write-Host " Graph MCP deployed" -ForegroundColor Green

# Step 6: Get MCP FQDNs for orchestrator config
Write-Host "`n Getting MCP endpoints..." -ForegroundColor Cyan

$SqlMcpFqdn = az containerapp show --name $SqlMcpApp --resource-group $ResourceGroup --query properties.configuration.ingress.fqdn -o tsv
$GraphMcpFqdn = az containerapp show --name $GraphMcpApp --resource-group $ResourceGroup --query properties.configuration.ingress.fqdn -o tsv

Write-Host "SQL MCP FQDN: https://$SqlMcpFqdn" -ForegroundColor Gray
Write-Host "Graph MCP FQDN: https://$GraphMcpFqdn" -ForegroundColor Gray

# Step 7: Deploy Orchestrator
Write-Host "`n Deploying Orchestrator..." -ForegroundColor Cyan

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
    --user-assigned $OrchestratorIdentity `
    --env-vars `
        "APP_NAME=orchestrator" `
        "DEV_MODE=false" `
        "DEBUG=false" `
        MCP_ENDPOINTS={"sql_mcp": "http://localhost:8001/mcp", "graph_mcp": "http://localhost:8002/mcp"} 2>$null

if ($LASTEXITCODE -ne 0) {
    Write-Host "Updating existing Orchestrator app..." -ForegroundColor Yellow
    az containerapp update `
        --name $OrchestratorApp `
        --resource-group $ResourceGroup `
        --image $OrchestratorImage
}

Write-Host " Orchestrator deployed" -ForegroundColor Green

# Step 8: Get Orchestrator URL
Write-Host "`n Getting application URL..." -ForegroundColor Cyan

$OrchestratorFqdn = az containerapp show --name $OrchestratorApp --resource-group $ResourceGroup --query properties.configuration.ingress.fqdn -o tsv

Write-Host "`n Deployment Complete!" -ForegroundColor Green
Write-Host "`n Application URLs:" -ForegroundColor Cyan
Write-Host "  Orchestrator: https://$OrchestratorFqdn" -ForegroundColor White
Write-Host "  SQL MCP (internal): https://$SqlMcpFqdn" -ForegroundColor Gray
Write-Host "  Graph MCP (internal): https://$GraphMcpFqdn" -ForegroundColor Gray

Write-Host "`n Test the deployment:" -ForegroundColor Cyan
Write-Host "  curl https://$OrchestratorFqdn/health" -ForegroundColor White

Write-Host "`n  Next Steps:" -ForegroundColor Yellow
Write-Host "  1. Update Cosmos DB mcp_definitions with production FQDNs"
Write-Host "  2. Configure environment variables via Azure Portal or CLI"
Write-Host "  3. Assign RBAC roles for Managed Identities:"
Write-Host "     - Cosmos DB Data Contributor"
Write-Host "     - Cognitive Services OpenAI User"
Write-Host "     - Fabric Lakehouse Reader (for SQL MCP)"
Write-Host "  4. Run init_data.py to populate Cosmos DB"
Write-Host "  5. Test via POST https://$OrchestratorFqdn/chat"
