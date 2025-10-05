# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This is an **agentic framework** built on **FastMCP** for orchestrating multi-agent workflows with Azure services. The system consists of:

- **Orchestrator Agent**: Central coordinator that discovers MCPs from configured endpoints, routes requests, and aggregates responses using Azure OpenAI
- **MCP Servers**: Specialized Model Context Protocol servers (SQL, Graph) that execute domain-specific queries
- **RBAC System**: Role-based access control with row-level security via Cosmos DB configuration
- **Account Resolution**: Fuzzy matching service for handling typos and abbreviations in account names

The framework supports both production and dev mode operation.

## Architecture

```
User Request → Orchestrator (Port 8000)
                     ↓
         ┌───────────┴───────────┐
         ↓                       ↓
    SQL MCP (8001)         Graph MCP (8002)
         ↓                       ↓
    Fabric SQL              Gremlin/Cosmos
```

### Key Components

1. **Orchestrator** ([orchestrator/orchestrator.py](agentic_framework/orchestrator/orchestrator.py))
   - Discovers MCPs from endpoints configured via `MCP_ENDPOINTS` environment variable
   - Calls MCP servers directly via HTTP to fetch their tool definitions
   - Multi-round planning loop using Azure OpenAI function calling
   - Routes tool calls to appropriate MCP servers using FastMCP client

2. **MCP Servers** ([mcps/sql/server.py](agentic_framework/mcps/sql/server.py), [mcps/graph/server.py](agentic_framework/mcps/graph/server.py))
   - Use internal LLMs to convert natural language → SQL/Gremlin
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
- `MCP_ENDPOINTS={"sql_mcp": "http://localhost:8001/mcp", "graph_mcp": "http://localhost:8002/mcp"}` - JSON dictionary mapping MCP IDs to endpoints

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
```bash
# Set dev mode in .env
echo "DEV_MODE=true" >> .env
echo "BYPASS_TOKEN=true" >> .env

# Start MCP servers (in separate terminals, from repository root)
cd agentic_framework
python -m mcps.sql.server    # Terminal 1, port 8001
python -m mcps.graph.server  # Terminal 2, port 8002

# Start orchestrator
python -m orchestrator.app   # Terminal 3, port 8000
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
python tests/test_orchestrator.py
```

## Adding New MCPs

1. **Create MCP Server** using FastMCP pattern in `agentic_framework/mcps/`:
   ```python
   from fastmcp import FastMCP
   from shared.auth_provider import create_auth_provider

   auth_provider = create_auth_provider()
   mcp = FastMCP("Custom MCP", auth=auth_provider)

   @mcp.tool()
   async def custom_tool(query: str, rbac_context: Optional[Dict] = None):
       return {"success": True, "data": []}

   if __name__ == "__main__":
       mcp.run(transport="http", port=8003)
   ```

2. **Upload Tool Definitions**: Upload tool schemas to `agent_functions` container in Cosmos DB

3. **Update Environment**: Add MCP endpoint to `MCP_ENDPOINTS` JSON in `.env`:
   ```bash
   MCP_ENDPOINTS={"sql_mcp": "http://localhost:8001/mcp", "graph_mcp": "http://localhost:8002/mcp", "custom_mcp": "http://localhost:8003/mcp"}
   ```

4. **Restart Orchestrator**: Auto-discovers new MCP from configured endpoint

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

### Deployment Script

The main deployment script is `agentic_framework/deploy/deploy-aca.ps1`. Run it from the repository root:

```powershell
# Deploy without rebuilding images (faster)
.\agentic_framework\deploy\deploy-aca.ps1 -EnvFile .env

# Deploy with image rebuild (after code changes)
.\agentic_framework\deploy\deploy-aca.ps1 -EnvFile .env -BuildImages
```

### Deployment Process

1. **Build Docker Images** (if `-BuildImages` flag is used):
   - Builds orchestrator, all MCPs, and frontend
   - Pushes images to Azure Container Registry

2. **Configure Infrastructure**:
   - Creates/updates Container Apps Environment
   - Sets up Managed Identity with RBAC roles

3. **Deploy MCPs**:
   - Deploys each MCP with correct port assignment
   - Sets all required environment variables
   - Configures internal ingress

4. **Deploy Orchestrator**:
   - Builds `MCP_ENDPOINTS` JSON from discovered MCPs
   - Configures external ingress on port 8000

### Deployment Troubleshooting

**MCP Starting on Wrong Port:**
- Check that `MCP_PORT` environment variable is set in Container App
- Verify MCP server code passes `port` parameter to `mcp.run()`:
  ```python
  mcp.run(transport=TRANSPORT, host=HOST, port=MCP_SERVER_PORT)
  ```
- Check logs: `az containerapp logs show --name <mcp-name> --resource-group <rg> --tail 10`

**Orchestrator Can't Discover MCPs:**
- Verify `MCP_ENDPOINTS` JSON format (no backticks, proper quotes)
- Check MCP internal URLs match the format: `https://<mcp-name>.internal.<env-domain>/mcp`
- Ensure all MCPs are running: `az containerapp list --resource-group <rg> --query "[].{Name:name, Status:properties.runningStatus}"`

**Image Not Updating:**
- Azure Container Apps caches images by tag
- Force update with digest: `az containerapp update --image <registry>/<image>@sha256:<digest>`
- Or use versioned tags (v1, v2, etc.) instead of `latest`

### Other Deployment Scripts
- `configure-env.ps1` - Configure environment variables for deployment
- `update-mcp-urls.ps1` - Update MCP endpoints after deployment