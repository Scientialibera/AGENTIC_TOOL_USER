## Overview

This is an **agentic framework** built on **FastMCP** for orchestrating multi-agent workflows with Azure services. The system consists of:

- **Orchestrator Agent**: Central coordinator that discovers MCPs from configured endpoints, routes requests, and aggregates responses using Azure OpenAI
- **MCP Servers**: Specialized Model Context Protocol servers (SQL, Graph, Interpreter) that execute domain-specific queries
- **RBAC System**: Role-based access control with row-level security via Cosmos DB configuration
- **Account Resolution**: Fuzzy matching service for handling typos and abbreviations in account names

The framework supports both production and dev mode operation.

## Architecture

```
User Request → Orchestrator (Port 8000)
                     ↓
         ┌───────────┴───────────────────┐
         ↓                   ↓            ↓
    Graph MCP (8001)   Interpreter   SQL MCP (8003)
         ↓              MCP (8002)        ↓
    Gremlin/Cosmos         ↓         Fabric SQL
                     Code Execution
```

### Key Components

1. **Orchestrator** ([orchestrator/orchestrator.py](agentic_framework/orchestrator/orchestrator.py))
   - Discovers MCPs from endpoints configured via `MCP_ENDPOINTS` environment variable
   - Calls MCP servers directly via HTTP to fetch their tool definitions
   - Multi-round planning loop using Azure OpenAI function calling
   - Routes tool calls to appropriate MCP servers using FastMCP client

2. **MCP Servers** ([mcps/sql/server.py](agentic_framework/mcps/sql/server.py), [mcps/graph/server.py](agentic_framework/mcps/graph/server.py), [mcps/interpreter/server.py](agentic_framework/mcps/interpreter/server.py))
   - **SQL MCP**: Uses internal LLM to convert natural language → SQL queries on Fabric lakehouse
   - **Graph MCP**: Uses internal LLM to convert natural language → Gremlin queries for relationship discovery
   - **Interpreter MCP**: Uses Azure OpenAI Assistants API for code execution (math, graphs, data analysis)
   - Apply RBAC filtering via WHERE clause injection (SQL) or vertex filtering (Graph)
   - Support JWT authentication in production mode (bypassed in dev mode)
   - Return structured results to orchestrator

3. **Shared Clients** ([shared/](agentic_framework/shared/))
   - `aoai_client.py`: Azure OpenAI wrapper with DefaultAzureCredential
   - `cosmos_client.py`: Cosmos DB NoSQL client for configuration/state
   - `fabric_client.py`: Fabric lakehouse SQL client
   - `gremlin_client.py`: Cosmos DB Gremlin client
   - `account_resolver.py`: Fuzzy account matching with Levenshtein distance
   - `unified_service.py`: Conversation tracking and caching service
   - `auth_provider.py`: JWT token validation (production) or bypass (dev mode)

## Environment Configuration

The framework uses `.env` in the **repository root** for configuration. Key settings:

### Framework Settings
- `DEV_MODE=true` - Bypasses RBAC and authentication, returns dummy data (no Azure connections needed)
- `BYPASS_TOKEN=true` - Bypasses JWT token validation for API endpoints (for testing)
- `DEBUG=true` - Enables verbose logging
- `MCP_ENDPOINTS={"graph_mcp": "http://localhost:8001/mcp", "interpreter_mcp": "http://localhost:8002/mcp", "sql_mcp": "http://localhost:8003/mcp"}` - JSON dictionary mapping MCP IDs to endpoints

### Azure Services (Production)
- **Azure OpenAI**: `AOAI_ENDPOINT`, `AOAI_CHAT_DEPLOYMENT`, `AOAI_EMBEDDING_DEPLOYMENT`
- **Cosmos DB**: `COSMOS_ENDPOINT`, `COSMOS_DATABASE_NAME`, container names for various data types
- **Fabric SQL**: `FABRIC_SQL_ENDPOINT`, `FABRIC_SQL_DATABASE`
- **Gremlin**: `AZURE_COSMOS_GREMLIN_ENDPOINT`, `AZURE_COSMOS_GREMLIN_DATABASE`

### Authentication (Production)
- `AZURE_TENANT_ID` - Azure AD tenant ID for JWT validation (required)
- `AZURE_AUDIENCE` - Expected audience in JWT tokens (optional, leave unset to skip audience validation and only validate issuer/tenant)

All Azure services use **DefaultAzureCredential** from `azure.identity`. For local dev, use `az login`. For production, configure Managed Identity with proper RBAC roles.

## Running the Framework

### Development Mode (No Azure Resources)

**Option 1: Using the helper script (PowerShell)**
```powershell
# Starts all MCPs and orchestrator in separate windows
.\agentic_framework\deploy\start-local.ps1
```

**Option 2: Manual startup (separate terminals)**
```bash
# Set dev mode in .env
echo "DEV_MODE=true" >> .env
echo "BYPASS_TOKEN=true" >> .env

# Start MCP servers (in separate terminals, from repository root)
cd agentic_framework
python -m mcps.graph.server       # Terminal 1, port 8001
python -m mcps.interpreter.server # Terminal 2, port 8002
python -m mcps.sql.server         # Terminal 3, port 8003

# Start orchestrator
python -m orchestrator.app        # Terminal 4, port 8000
# OR
uvicorn orchestrator.app:app --reload --port 8000
```

### Production Mode
1. Ensure Azure authentication is configured (`az login` or Managed Identity)
2. Set `DEV_MODE=false` and `BYPASS_TOKEN=false` in `.env`
3. Configure `AZURE_TENANT_ID` for JWT validation (AZURE_AUDIENCE is optional)
4. Initialize Cosmos DB containers (see [Cosmos DB Setup](#cosmos-db-setup))
5. Upload artifacts: `python scripts/test_env/init_data.py`
6. Start servers as above

## Development Scripts

Located in `scripts/test_env/`:

- **`set_env.ps1`** - Merges `.env.example` into `.env`, optionally auto-discovers Azure endpoints from resource group
  ```powershell
  .\scripts\test_env\set_env.ps1 -ResourceGroup <your-rg>
  ```
- **`init_data.py`** - Initializes Cosmos DB containers and uploads prompts/functions from `scripts/assets/`
  ```bash
  python .\scripts\test_env\init_data.py
  ```

Typical workflow:
```powershell
# From repository root
.\scripts\test_env\set_env.ps1 -ResourceGroup <your-rg>
python .\scripts\test_env\init_data.py
```

## Cosmos DB Setup

The framework expects these containers in `COSMOS_DATABASE_NAME`:

- **mcp_definitions** (partition key: `/id`) - MCP server registrations (optional, discovery now uses HTTP endpoints)
- **agent_functions** (partition key: `/mcp_id`) - Tool/function schemas
- **prompts** (partition key: `/id`) - System prompts for agents
- **rbac_config** (partition key: `/role_name`) - Role permissions
- **unified_data** (partition key: `/session_id`) - Chat history/cache
- **sql_schema** (partition key: `/id`) - SQL schema metadata

### Sample Data Structure

**Tool Definition** (`agent_functions` container):
```json
{
  "id": "sql_query",
  "mcp_id": "sql_mcp",
  "name": "sql_query",
  "description": "Execute SQL queries",
  "parameters": {
    "type": "object",
    "properties": {
      "query": {"type": "string"},
      "accounts_mentioned": {"type": "array"}
    }
  },
  "allowed_roles": ["sales_rep", "admin"]
}
```

## Port Configuration

**CRITICAL**: Each MCP server must use a unique port number. Ports are assigned sequentially starting from 8001, in alphabetical order by MCP folder name:

- **Orchestrator**: Port 8000 (always)
- **Graph MCP**: Port 8001 (alphabetically first)
- **Interpreter MCP**: Port 8002 (alphabetically second)
- **SQL MCP**: Port 8003 (alphabetically third)

### How Port Assignment Works

1. Each MCP server reads its port from the `MCP_PORT` environment variable
2. The deployment script automatically assigns ports based on alphabetical folder order
3. MCP servers **must** pass the port explicitly to `mcp.run()`:
   ```python
   mcp.run(transport=TRANSPORT, host=HOST, port=MCP_SERVER_PORT)
   ```
4. The port constant should read from environment:
   ```python
   MCP_SERVER_PORT = int(os.getenv("MCP_PORT", "8001"))  # Default for first MCP
   ```

**Important**: When adding new MCPs, they will automatically be assigned the next sequential port based on their alphabetical position.

## Testing

### Test Orchestrator
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "Show contacts at Microsoft"}],
    "user_id": "test@example.com"
  }'
```

### List MCPs and Tools
```bash
curl http://localhost:8000/mcps
curl http://localhost:8000/tools
```

### Run Test Scripts
```bash
cd agentic_framework
python tests/test_sql_mcp.py
python tests/test_graph_mcp.py
python tests/test_interpreter_mcp.py
python tests/test_orchestrator.py
python tests/test_orchestrator_multitool.py
```

## Adding New MCPs

Adding a new MCP requires code changes, configuration updates, and optionally infrastructure changes for additional Azure services.

### Step 1: Create MCP Server Code

**1.1. Create MCP Directory and Server**

Using the template in [mcps/TEMPLATE_MCP.py](agentic_framework/mcps/TEMPLATE_MCP.py):

```bash
# Create new MCP directory (name determines port assignment - alphabetical order)
mkdir agentic_framework/mcps/custom
cp agentic_framework/mcps/TEMPLATE_MCP.py agentic_framework/mcps/custom/server.py
```

**1.2. Implement MCP Logic**

Edit `agentic_framework/mcps/custom/server.py`:

```python
from fastmcp import FastMCP
from shared.auth_provider import create_auth_provider
from shared.config import get_settings
from shared.aoai_client import AzureOpenAIClient
import os

# Configuration
MCP_SERVER_NAME = "Custom MCP Server"
AGENT_TYPE = "custom"
PROMPT_ID = "custom_agent_system"
MCP_SERVER_PORT = int(os.getenv("MCP_PORT", "8004"))  # Adjust default based on alphabetical position

settings = get_settings()
auth_provider = create_auth_provider()
mcp = FastMCP(MCP_SERVER_NAME, auth=auth_provider)

# Global clients
aoai_client = None

async def initialize_clients():
    global aoai_client
    if aoai_client is None:
        aoai_client = AzureOpenAIClient(settings.aoai)

@mcp.tool()
async def custom_tool(query: str, rbac_context: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Execute custom operations.

    Args:
        query: Natural language query
        rbac_context: RBAC context for filtering (injected by orchestrator)
    """
    await initialize_clients()

    # Your custom logic here
    # Use aoai_client, apply RBAC filtering, etc.

    return {
        "success": True,
        "data": [],
        "source": "custom_mcp"
    }

if __name__ == "__main__":
    mcp.run(transport="http", host="0.0.0.0", port=MCP_SERVER_PORT)
```

**1.3. Create Dockerfile**

Create `agentic_framework/mcps/custom/Dockerfile`:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Copy shared dependencies and MCP code
COPY shared/ ./shared/
COPY mcps/custom/ ./mcps/custom/
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Run the MCP server
CMD ["python", "-m", "mcps.custom.server"]
```

### Step 2: Create Tool Definitions

**2.1. Create Tool Schema**

Create `scripts/assets/functions/tools/custom_tool.json`:

```json
{
  "id": "custom_tool",
  "mcp_id": "custom_mcp",
  "name": "custom_tool",
  "description": "Execute custom operations based on natural language query",
  "parameters": {
    "type": "object",
    "properties": {
      "query": {
        "type": "string",
        "description": "Natural language description of the operation to perform"
      }
    },
    "required": ["query"]
  },
  "allowed_roles": ["admin", "power_user"]
}
```

**2.2. Create System Prompt (Optional)**

Create `scripts/assets/prompts/custom_agent_system.md`:

```markdown
You are a custom operations agent that executes specialized tasks.

Your capabilities:
- Custom operation 1
- Custom operation 2

Always return structured data in the expected format.
```

### Step 3: Configure Infrastructure (If New Azure Services Needed)

**3.1. Add Bicep Module (if needed)**

If your MCP needs a new Azure service (e.g., Azure Storage, Key Vault):

Create `deploy/infrastructure/modules/storage.bicep`:

```bicep
param name string
param location string
param tags object = {}

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: name
  location: location
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  properties: {
    accessTier: 'Hot'
  }
  tags: tags
}

output storageAccountId string = storageAccount.id
output storageAccountName string = storageAccount.name
```

**3.2. Update Main Bicep Template**

Edit `deploy/infrastructure/main.bicep`:

```bicep
// Add to variables section
var storageAccountName = '${baseName}storage${uniqueSuffix}'

// Add module import
module storage 'modules/storage.bicep' = {
  name: 'deploy-storage'
  params: {
    name: storageAccountName
    location: location
    tags: tags
  }
}

// Add RBAC assignment
resource storageRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(storage.outputs.storageAccountId, identity.outputs.principalId, 'StorageBlobDataContributor')
  scope: resourceGroup()
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', 'ba92f5b4-2d11-453d-a403-e96b0029c9fe')
    principalId: identity.outputs.principalId
    principalType: 'ServicePrincipal'
  }
}

// Add to outputs section
output storageAccountName string = storage.outputs.storageAccountName
```

**3.3. Update generate-env.ps1**

Edit `deploy/utils/generate-env.ps1` to discover the new service:

```powershell
# Add after other resource discovery
$storage = az storage account list -g $ResourceGroup --query "[0]" -o json | ConvertFrom-Json
if ($storage) {
    $storageName = $storage.name
    Write-Host "  ✓ Azure Storage: $storageName" -ForegroundColor Green
}

# Add to .env generation
STORAGE_ACCOUNT_NAME=$storageName
```

### Step 4: Local Development Setup

**4.1. Update Local .env**

Add MCP endpoint to `MCP_ENDPOINTS`:

```bash
MCP_ENDPOINTS={"graph_mcp": "http://localhost:8001/mcp", "interpreter_mcp": "http://localhost:8002/mcp", "sql_mcp": "http://localhost:8003/mcp", "custom_mcp": "http://localhost:8004/mcp"}
```

Add any new service configuration:

```bash
STORAGE_ACCOUNT_NAME=your-storage-account
```

**4.2. Upload Tool Definitions**

```bash
python deploy/data/init-cosmos-data.py
```

**4.3. Test Locally**

```bash
# Terminal 1-3: Existing MCPs
python -m mcps.graph.server       # Port 8001
python -m mcps.interpreter.server # Port 8002
python -m mcps.sql.server         # Port 8003

# Terminal 4: New MCP
python -m mcps.custom.server      # Port 8004

# Terminal 5: Orchestrator
python -m orchestrator.app        # Port 8000
```

### Step 5: Deploy to Azure

**5.1. Infrastructure Update (if needed)**

```powershell
# Redeploy infrastructure with new resources
az deployment group create `
    --resource-group "mybot-rg" `
    --template-file "deploy/infrastructure/main.bicep" `
    --parameters "deploy/infrastructure/parameters/prod.parameters.json"
```

**5.2. Deploy Container Apps**

The deployment script automatically discovers all MCPs in `mcps/` directory:

```powershell
# Deploy all apps (including new MCP)
.\deploy\apps\deploy-container-apps.ps1 -ResourceGroup "mybot-rg"
```

The script will:
1. Discover `custom` MCP folder
2. Assign port 8004 (based on alphabetical order: graph=8001, interpreter=8002, sql=8003, custom=8004)
3. Build Docker image
4. Push to ACR
5. Deploy Container App with correct port
6. Update orchestrator with new MCP endpoint

**5.3. Verify Deployment**

```bash
# Check MCP is running
az containerapp list -g mybot-rg --query "[].{Name:name, Status:properties.runningStatus}" -o table

# Get orchestrator URL
$orchUrl = az containerapp show -n orchestrator -g mybot-rg --query "properties.configuration.ingress.fqdn" -o tsv

# Verify MCP is discovered
curl "https://$orchUrl/mcps"

# Test new tool
curl -X POST "https://$orchUrl/chat" `
    -H "Content-Type: application/json" `
    -d '{
        "messages": [{"role": "user", "content": "Use custom tool to..."}],
        "user_id": "test@example.com"
    }'
```

### Important Notes

**Port Assignment**:
- Ports are assigned alphabetically by MCP folder name
- Example: `aardvark_mcp` gets port 8001, `zebra_mcp` gets last port
- New MCPs inserted alphabetically will shift port numbers
- **Recommendation**: Use prefixes to control order (e.g., `01_graph`, `02_sql`, `03_custom`)

**Deployment Script Auto-Discovery**:
- `deploy/apps/deploy-container-apps.ps1` automatically discovers MCPs in `agentic_framework/mcps/`
- No hardcoded MCP lists to maintain
- New MCPs are automatically included in builds

**RBAC for New MCPs**:
- If your MCP needs access to new Azure services, add RBAC assignments to `deploy/infrastructure/main.bicep`
- Or manually run: `az role assignment create --assignee <managed-identity-id> --role <role> --scope <resource-id>`

**Tool Visibility**:
- Tools are filtered by `allowed_roles` in tool definition
- Update `rbac_config` container in Cosmos DB to control which roles can access your MCP

## RBAC Implementation

The framework enforces RBAC at two levels:

1. **MCP/Tool Access**: User roles determine which MCPs and tools are visible
2. **Row-Level Security**: RBAC context is passed to MCP tools to filter data (SQL WHERE clauses, Gremlin vertex filters)

In **dev mode** (`DEV_MODE=true`), RBAC is bypassed and all users get admin access.

## Configuration Files

- **Settings**: [shared/config.py](agentic_framework/shared/config.py) - Pydantic settings with env var validation
  - `.env` file should be in **repository root**, not in `agentic_framework/`
  - Config automatically searches for `.env` in parent directory
- **Models**: [shared/models.py](agentic_framework/shared/models.py) - RBACContext, MCPDefinition, AccessScope
- **Prompts**: `scripts/assets/prompts/*.md` - System prompts for agents
- **Functions**: `scripts/assets/functions/tools/*.json` - Tool schemas for OpenAI function calling

## Common Issues

### MCP Not Discovered
- Verify `MCP_ENDPOINTS` includes the MCP endpoint in JSON format
- Check that MCP server is running on the specified port
- Verify MCP server is accessible via HTTP (test with curl)

### Tool Not Available
- Verify tool definition in `agent_functions` container in Cosmos DB
- Check `mcp_id` matches MCP endpoint key in `MCP_ENDPOINTS`
- Verify user's role has access to tool (or enable dev mode)

### Authentication Errors (Production Mode)
- Run `az login` for local development
- Verify Managed Identity has Cosmos DB Data Contributor role
- Check endpoint URLs don't have trailing slashes
- For API authentication, ensure `AZURE_TENANT_ID` is set (validates issuer/tenant only)
- For testing, use `BYPASS_TOKEN=true` to skip JWT validation

### .env Not Found
- Ensure `.env` is in **repository root**, not in `agentic_framework/`
- Use `scripts/test_env/set_env.ps1` to generate `.env` from `.env.example`

## Key Design Patterns

1. **MCP Discovery via HTTP**: Orchestrator calls MCP servers directly to fetch tool definitions, not from Cosmos DB
2. **RBAC Context Passing**: All MCP tools receive `rbac_context` dict for filtering
3. **Dev Mode**: Clients return dummy data when `DEV_MODE=true` to avoid Azure dependencies
4. **Token Bypass**: `BYPASS_TOKEN=true` disables JWT validation for easier local testing
5. **LLM-Powered Tools**: MCP servers use internal LLMs to generate SQL/Gremlin from natural language
6. **Multi-Round Planning**: Orchestrator uses function calling loop with configurable max rounds
7. **Shared Clients**: Common Azure clients in `shared/` imported by all components
8. **Session-Centric Tracking**: Conversation history stored in `unified_data` container with turn-level metadata

## Authentication Modes

The framework supports three authentication modes controlled by environment variables:

### Development Mode (`DEV_MODE=true`)
- No Azure connections required
- Returns dummy data for all queries
- RBAC bypassed (all users have admin access)
- No JWT token validation

### Testing Mode (`DEV_MODE=false`, `BYPASS_TOKEN=true`)
- Uses real Azure services
- JWT token validation bypassed for easier testing
- RBAC still enforced based on user_id in request

### Production Mode (`DEV_MODE=false`, `BYPASS_TOKEN=false`)
- All Azure services active
- Full JWT token validation using Azure AD
- Requires `AZURE_TENANT_ID` (validates issuer/tenant)
- `AZURE_AUDIENCE` is optional (leave unset to skip audience validation)
- MCP servers validate tokens using same configuration

## Deployment

The framework uses an enterprise-grade deployment structure in the `deploy/` directory with modular Bicep templates, automated RBAC configuration, and orchestrated deployment scripts.

### Quick Start - New Client Deployment

For complete zero-to-production deployment:

```powershell
# Complete automated deployment
.\deploy\main.ps1 -BaseName "clientbot" -Location "eastus" -Environment "prod"
```

This orchestrates:
1. **Infrastructure** - Deploys all Azure resources using Bicep
2. **Security** - Configures managed identity with all required RBAC permissions
3. **Configuration** - Auto-generates `.env` from deployed resources
4. **Data** - Initializes Cosmos DB with prompts, functions, and demo data
5. **Applications** - Builds and deploys all Container Apps

### Modular Deployment

Deploy or update individual components:

```powershell
# Infrastructure only (Bicep)
az deployment group create `
    --resource-group "mybot-rg" `
    --template-file ".\deploy\infrastructure\main.bicep" `
    --parameters ".\deploy\infrastructure\parameters\prod.parameters.json"

# Security/RBAC only
.\deploy\security\configure-rbac.ps1 -ResourceGroup "mybot-rg"

# Generate .env from existing resources
.\deploy\utils\generate-env.ps1 -ResourceGroup "mybot-rg"

# Initialize Cosmos DB data
python .\deploy\data\init-cosmos-data.py

# Deploy Container Apps
.\deploy\apps\deploy-container-apps.ps1 -ResourceGroup "mybot-rg"
```

### Deployment Structure

```
deploy/
├── main.ps1                      # Master orchestrator
├── infrastructure/               # Bicep IaC
│   ├── main.bicep                # Main template
│   ├── modules/                  # Modular components
│   └── parameters/               # Environment configs
├── security/                     # RBAC automation
├── data/                         # Data initialization
├── apps/                         # Container Apps deployment
└── utils/                        # Helper scripts
```

See [deploy/README.md](deploy/README.md) for complete deployment documentation.

### Legacy Deployment Scripts

Previous deployment scripts in `agentic_framework/deploy/` and `scripts/` are deprecated in favor of the new `deploy/` structure. For compatibility:
- Old: `.\agentic_framework\deploy\deploy-aca.ps1`
- New: `.\deploy\main.ps1` (recommended)

## Useful Development Commands

### Local Development Workflow
```powershell
# 1. Configure environment (one time)
.\scripts\test_env\set_env.ps1 -ResourceGroup <your-rg>

# 2. Initialize data (one time or when updating prompts/functions)
python .\scripts\test_env\init_data.py

# 3. Start all services locally (each development session)
.\agentic_framework\deploy\start-local.ps1

# 4. Test the orchestrator
curl -X POST http://localhost:8000/chat -H "Content-Type: application/json" -d '{...}'
```

### Working with Individual MCPs
```bash
# Test a single MCP in isolation
cd agentic_framework
python -m mcps.sql.server  # Start SQL MCP only

# Run MCP-specific tests
python tests/test_sql_mcp.py
```

### Updating Prompts and Functions
```bash
# After modifying files in scripts/assets/prompts/ or scripts/assets/functions/
python .\scripts\test_env\init_data.py  # Re-upload to Cosmos DB
```