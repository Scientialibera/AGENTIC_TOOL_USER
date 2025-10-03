# Update MCP Definitions with Production URLs
# Run this after deploying to Azure Container Apps

param(
    [Parameter(Mandatory=$true)]
    [string]$ResourceGroup,
    
    [Parameter(Mandatory=$true)]
    [string]$SqlMcpAppName = "sql-mcp",
    
    [Parameter(Mandatory=$true)]
    [string]$GraphMcpAppName = "graph-mcp"
)

$ErrorActionPreference = "Stop"

Write-Host " Updating MCP definitions with production URLs..." -ForegroundColor Cyan

# Get FQDNs
$SqlMcpFqdn = az containerapp show --name $SqlMcpAppName --resource-group $ResourceGroup --query properties.configuration.ingress.fqdn -o tsv
$GraphMcpFqdn = az containerapp show --name $GraphMcpAppName --resource-group $ResourceGroup --query properties.configuration.ingress.fqdn -o tsv

Write-Host "SQL MCP URL: https://$SqlMcpFqdn" -ForegroundColor Yellow
Write-Host "Graph MCP URL: https://$GraphMcpFqdn" -ForegroundColor Yellow

# Create production MCP definitions
$SqlMcpDefinition = @{
    id = "sql_mcp"
    name = "SQL MCP Server"
    description = "SQL agent for querying Salesforce/Fabric data"
    endpoint = "https://$SqlMcpFqdn/mcp"
    transport = "http"
    allowed_roles = @("sales_rep", "sales_manager", "admin")
    tools = @("sql_query")
    enabled = $true
    metadata = @{
        version = "1.0.0"
        environment = "production"
        deployed_at = (Get-Date -Format "yyyy-MM-ddTHH:mm:ssZ")
    }
} | ConvertTo-Json -Depth 10

$GraphMcpDefinition = @{
    id = "graph_mcp"
    name = "Graph MCP Server"
    description = "Graph agent for querying relationship data"
    endpoint = "https://$GraphMcpFqdn/mcp"
    transport = "http"
    allowed_roles = @("sales_rep", "sales_manager", "admin")
    tools = @("graph_query")
    enabled = $true
    metadata = @{
        version = "1.0.0"
        environment = "production"
        deployed_at = (Get-Date -Format "yyyy-MM-ddTHH:mm:ssZ")
    }
} | ConvertTo-Json -Depth 10

# Save to files
$SqlMcpDefinition | Out-File -FilePath "mcp_definitions_prod_sql.json" -Encoding UTF8
$GraphMcpDefinition | Out-File -FilePath "mcp_definitions_prod_graph.json" -Encoding UTF8

Write-Host "`n Production MCP definitions created" -ForegroundColor Green
Write-Host "  - mcp_definitions_prod_sql.json" -ForegroundColor Gray
Write-Host "  - mcp_definitions_prod_graph.json" -ForegroundColor Gray

Write-Host "`n Update Cosmos DB with these definitions:" -ForegroundColor Cyan
Write-Host "  python update_mcp_endpoints.py" -ForegroundColor White

# Create Python script to update Cosmos DB
$UpdateScript = @'
"""Update MCP definitions in Cosmos DB with production URLs."""

import asyncio
import json
from shared.cosmos_client import CosmosDBClient
from shared.config import get_settings

async def update_mcp_definitions():
    settings = get_settings()
    cosmos = CosmosDBClient(settings.cosmos)
    
    # Load and upload SQL MCP definition
    with open("mcp_definitions_prod_sql.json") as f:
        sql_mcp = json.load(f)
    
    await cosmos.upsert_item(
        container_name="mcp_definitions",
        item=sql_mcp,
        partition_key="/id"
    )
    print(f" Updated: {sql_mcp['id']}")
    
    # Load and upload Graph MCP definition
    with open("mcp_definitions_prod_graph.json") as f:
        graph_mcp = json.load(f)
    
    await cosmos.upsert_item(
        container_name="mcp_definitions",
        item=graph_mcp,
        partition_key="/id"
    )
    print(f" Updated: {graph_mcp['id']}")
    
    print("\n MCP definitions updated in Cosmos DB")
    await cosmos.close()

if __name__ == "__main__":
    asyncio.run(update_mcp_definitions())
'@

$UpdateScript | Out-File -FilePath "update_mcp_endpoints.py" -Encoding UTF8

Write-Host " Update script created: update_mcp_endpoints.py" -ForegroundColor Green
