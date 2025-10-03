# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This is an **agentic framework** built on **FastMCP** for orchestrating multi-agent workflows with Azure services. The system consists of:

- **Orchestrator Agent**: Central coordinator that discovers MCPs, routes requests, and aggregates responses using Azure OpenAI
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
   - Discovers MCPs from Cosmos DB based on `MCP_ENDPOINTS` env var
   - Loads tool definitions with RBAC filtering
   - Multi-round planning loop using Azure OpenAI function calling
   - Routes tool calls to appropriate MCP servers

2. **MCP Servers** ([mcps/sql/server.py](agentic_framework/mcps/sql/server.py), [mcps/graph/server.py](agentic_framework/mcps/graph/server.py))
   - Use internal LLMs to convert natural language → SQL/Gremlin
   - Apply RBAC filtering via WHERE clause injection (SQL) or vertex filtering (Graph)
   - Return structured results to orchestrator

3. **Shared Clients** ([shared/](agentic_framework/shared/))
   - `aoai_client.py`: Azure OpenAI wrapper with DefaultAzureCredential
   - `cosmos_client.py`: Cosmos DB NoSQL client for configuration/state
   - `fabric_client.py`: Fabric lakehouse SQL client
   - `gremlin_client.py`: Cosmos DB Gremlin client
   - `account_resolver.py`: Fuzzy account matching with Levenshtein distance
   - `unified_service.py`: Conversation tracking and caching service

## Environment Configuration

The framework uses `.env` for configuration. Key settings:

### Framework Settings
- `DEV_MODE=true` - Bypasses RBAC and returns dummy data (no Azure connections needed)
- `DEBUG=true` - Enables verbose logging
- `MCP_ENDPOINTS={"sql_mcp": "http://localhost:8001/mcp", "graph_mcp": "http://localhost:8002/mcp"}` - JSON dictionary mapping MCP IDs to endpoints

### Azure Services (Production)
- **Azure OpenAI**: `AOAI_ENDPOINT`, `AOAI_CHAT_DEPLOYMENT`, `AOAI_EMBEDDING_DEPLOYMENT`
- **Cosmos DB**: `COSMOS_ENDPOINT`, `COSMOS_DATABASE_NAME`, container names for various data types
- **Fabric SQL**: `FABRIC_SQL_ENDPOINT`, `FABRIC_SQL_DATABASE`
- **Gremlin**: `AZURE_COSMOS_GREMLIN_ENDPOINT`, `AZURE_COSMOS_GREMLIN_DATABASE`

All Azure services use **DefaultAzureCredential** (Managed Identity/az login). No client secrets in `.env`.

## Running the Framework

### Development Mode (No Azure Resources)
```bash
# Set dev mode in .env
echo "DEV_MODE=true" >> .env

# Start MCP servers (in separate terminals)
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
2. Set `DEV_MODE=false` in `.env`
3. Initialize Cosmos DB containers (see [Cosmos DB Setup](#cosmos-db-setup))
4. Upload artifacts: `python scripts/test_env/init_data.py`
5. Start servers as above

## Development Scripts

Located in `scripts/test_env/`:

- **`set_env.ps1`** - Merges `.env.example` into `.env`, optionally auto-discovers Azure endpoints from resource group
- **`init_data.py`** - Initializes Cosmos DB containers and uploads prompts/functions from `scripts/assets/`

Typical workflow:
```powershell
# From repository root
.\scripts\test_env\set_env.ps1 -ResourceGroup <your-rg>
python .\scripts\test_env\init_data.py
```

## Cosmos DB Setup

The framework expects these containers in `COSMOS_DATABASE_NAME`:

- **mcp_definitions** (partition key: `/id`) - MCP server registrations
- **agent_functions** (partition key: `/mcp_id`) - Tool/function schemas
- **prompts** (partition key: `/id`) - System prompts for agents
- **rbac_config** (partition key: `/role_name`) - Role permissions
- **unified_data** (partition key: `/session_id`) - Chat history/cache

### Sample Data Structure

**MCP Definition** (`mcp_definitions` container):
```json
{
  "id": "sql_mcp",
  "name": "SQL MCP Server",
  "endpoint": "http://localhost:8001/mcp",
  "allowed_roles": ["sales_rep", "admin"],
  "tools": ["sql_query"],
  "enabled": true
}
```

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

   mcp = FastMCP("Custom MCP")

   @mcp.tool()
   async def custom_tool(query: str, rbac_context: Optional[Dict] = None):
       return {"success": True, "data": []}

   if __name__ == "__main__":
       mcp.run(transport="http", port=8003)
   ```

2. **Register in Cosmos DB**: Upload MCP definition and tool schemas to respective containers

3. **Update Environment**: Add MCP endpoint to `MCP_ENDPOINTS` JSON in `.env`

4. **Restart Orchestrator**: Auto-discovers new MCP on startup

## RBAC Implementation

The framework enforces RBAC at two levels:

1. **MCP/Tool Access**: User roles determine which MCPs and tools are visible
2. **Row-Level Security**: RBAC context is passed to MCP tools to filter data (SQL WHERE clauses, Gremlin vertex filters)

In **dev mode** (`DEV_MODE=true`), RBAC is bypassed and all users get admin access.

## Configuration Files

- **Settings**: [shared/config.py](agentic_framework/shared/config.py) - Pydantic settings with env var validation
- **Models**: [shared/models.py](agentic_framework/shared/models.py) - RBACContext, MCPDefinition, AccessScope
- **Prompts**: `scripts/assets/prompts/*.md` - System prompts for agents
- **Functions**: `scripts/assets/functions/tools/*.json` - Tool schemas for OpenAI function calling

## Common Issues

### MCP Not Discovered
- Verify `MCP_ENDPOINTS` includes the MCP endpoint in JSON format
- Check MCP definition exists in `mcp_definitions` container
- Ensure RBAC allows user's role (or enable dev mode)

### Authentication Errors
- Run `az login` for local development
- Verify Managed Identity has Cosmos DB Data Contributor role
- Check endpoint URLs don't have trailing slashes

### Tool Execution Fails
- Verify tool's `mcp_id` matches MCP definition
- Check tool schema in `agent_functions` container
- Review logs for RBAC filtering issues

## Key Design Patterns

1. **MCP Discovery**: Orchestrator loads MCP configs from Cosmos DB at startup, not hardcoded
2. **RBAC Context Passing**: All MCP tools receive `rbac_context` dict for filtering
3. **Dev Mode**: Clients return dummy data when `DEV_MODE=true` to avoid Azure dependencies
4. **LLM-Powered Tools**: MCP servers use internal LLMs to generate SQL/Gremlin from natural language
5. **Multi-Round Planning**: Orchestrator uses function calling loop with configurable max rounds
6. **Shared Clients**: Common Azure clients in `shared/` imported by all components

## Authentication

All Azure service calls use **DefaultAzureCredential** from `azure.identity`. For local dev, use `az login`. For production, configure Managed Identity with proper RBAC roles on Cosmos DB, Fabric, and Azure OpenAI.