# Configure Environment Variables for Azure Container Apps
# Sets all required environment variables for production deployment

param(
    [Parameter(Mandatory=$true)]
    [string]$ResourceGroup,
    
    [Parameter(Mandatory=$true)]
    [string]$CosmosAccountName,
    
    [Parameter(Mandatory=$true)]
    [string]$OpenAIAccountName,
    
    [Parameter(Mandatory=$true)]
    [string]$GremlinAccountName,
    
    [Parameter(Mandatory=$false)]
    [string]$FabricSqlEndpoint,
    
    [Parameter(Mandatory=$false)]
    [string]$FabricDatabase
)

$ErrorActionPreference = "Stop"

Write-Host "  Configuring environment variables for Container Apps..." -ForegroundColor Cyan

# Get resource endpoints
$CosmosEndpoint = az cosmosdb show --name $CosmosAccountName --resource-group $ResourceGroup --query documentEndpoint -o tsv
$GremlinEndpoint = "wss://$GremlinAccountName.gremlin.cosmos.azure.com:443/"
$OpenAIEndpoint = az cognitiveservices account show --name $OpenAIAccountName --resource-group $ResourceGroup --query properties.endpoint -o tsv

Write-Host "`n Detected endpoints:" -ForegroundColor Yellow
Write-Host "  Cosmos DB: $CosmosEndpoint" -ForegroundColor Gray
Write-Host "  Gremlin: $GremlinEndpoint" -ForegroundColor Gray
Write-Host "  OpenAI: $OpenAIEndpoint" -ForegroundColor Gray

# Common environment variables
$CommonEnvVars = @(
    "COSMOS_ENDPOINT=$CosmosEndpoint",
    "COSMOS_DATABASE_NAME=appdb",
    "AOAI_ENDPOINT=$OpenAIEndpoint",
    "AOAI_API_VERSION=2024-06-01",
    "AOAI_CHAT_DEPLOYMENT=gpt-4",
    "DEV_MODE=false",
    "DEBUG=false"
)

# Orchestrator-specific variables
$OrchestratorEnvVars = $CommonEnvVars + @(
    "APP_NAME=orchestrator",
    MCP_ENDPOINTS={"sql_mcp": "http://localhost:8001/mcp", "graph_mcp": "http://localhost:8002/mcp"},
    "COSMOS_MCP_DEFINITIONS_CONTAINER=mcp_definitions",
    "COSMOS_AGENT_FUNCTIONS_CONTAINER=agent_functions",
    "COSMOS_PROMPTS_CONTAINER=prompts",
    "COSMOS_RBAC_CONFIG_CONTAINER=rbac_config",
    "COSMOS_CHAT_CONTAINER=unified_data",
    "AOAI_EMBEDDING_DEPLOYMENT=text-embedding-3-small"
)

# SQL MCP-specific variables
$SqlMcpEnvVars = $CommonEnvVars + @(
    "APP_NAME=sql-mcp",
    "COSMOS_CHAT_CONTAINER=unified_data"
)

if ($FabricSqlEndpoint -and $FabricDatabase) {
    $SqlMcpEnvVars += "FABRIC_SQL_ENDPOINT=$FabricSqlEndpoint"
    $SqlMcpEnvVars += "FABRIC_SQL_DATABASE=$FabricDatabase"
}

# Graph MCP-specific variables
$GraphMcpEnvVars = $CommonEnvVars + @(
    "APP_NAME=graph-mcp",
    "COSMOS_CHAT_CONTAINER=unified_data",
    "AZURE_COSMOS_GREMLIN_ENDPOINT=$GremlinEndpoint",
    "AZURE_COSMOS_GREMLIN_PORT=443",
    "AZURE_COSMOS_GREMLIN_DATABASE=graphdb",
    "AZURE_COSMOS_GREMLIN_GRAPH=account_graph"
)

# Update Orchestrator
Write-Host "`n Updating Orchestrator environment..." -ForegroundColor Cyan
az containerapp update `
    --name orchestrator `
    --resource-group $ResourceGroup `
    --set-env-vars $OrchestratorEnvVars

Write-Host " Orchestrator configured" -ForegroundColor Green

# Update SQL MCP
Write-Host "`n Updating SQL MCP environment..." -ForegroundColor Cyan
az containerapp update `
    --name sql-mcp `
    --resource-group $ResourceGroup `
    --set-env-vars $SqlMcpEnvVars

Write-Host " SQL MCP configured" -ForegroundColor Green

# Update Graph MCP
Write-Host "`n Updating Graph MCP environment..." -ForegroundColor Cyan
az containerapp update `
    --name graph-mcp `
    --resource-group $ResourceGroup `
    --set-env-vars $GraphMcpEnvVars

Write-Host " Graph MCP configured" -ForegroundColor Green

Write-Host "`n All environment variables configured!" -ForegroundColor Green
Write-Host "`n  Don't forget to:" -ForegroundColor Yellow
Write-Host "  1. Assign RBAC roles to Managed Identities"
Write-Host "  2. Verify connections with health checks"
Write-Host "  3. Update MCP definitions in Cosmos DB"
