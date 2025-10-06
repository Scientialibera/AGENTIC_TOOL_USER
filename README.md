# Agentic Framework

Multi-agent orchestration framework built on FastMCP for Azure-based AI workflows with role-based access control and graph-powered insights.

## Overview

This is a production-grade agentic framework that orchestrates specialized Model Context Protocol (MCP) servers to answer complex questions using multiple data sources. The system uses Azure OpenAI for LLM operations, Cosmos DB for configuration and graph relationships, and Microsoft Fabric for SQL queries.

**Key Features:**
- 🤖 **Multi-Agent Orchestration** - Central orchestrator coordinates specialized MCP servers
- 🔐 **Role-Based Access Control** - Row-level security with user roles and permissions
- 📊 **Graph-Powered Insights** - Relationship discovery using Cosmos DB Gremlin
- 🔄 **FastMCP Integration** - Built on FastMCP for rapid MCP server development
- 🚀 **Azure Native** - Runs on Azure Container Apps with Managed Identity
- 🎯 **Development & Production Modes** - Dev mode with dummy data, production with full Azure integration

## Architecture

```
User Request → Orchestrator (Port 8000)
                     ↓
         ┌───────────┴───────────┐
         ↓                       ↓
    SQL MCP (8003)         Graph MCP (8001)    Interpreter MCP (8002)
         ↓                       ↓                      ↓
    Fabric SQL            Gremlin/Cosmos         Code Execution
```

### Components

1. **Orchestrator** - Central coordinator that:
   - Discovers MCPs from configured endpoints
   - Plans multi-step workflows using Azure OpenAI function calling
   - Routes tool calls to appropriate MCP servers
   - Aggregates and returns results

2. **MCP Servers** - Specialized servers for domain-specific tasks:
   - **SQL MCP** - Natural language → SQL queries on Fabric lakehouse
   - **Graph MCP** - Relationship discovery using Gremlin/Cosmos DB
   - **Interpreter MCP** - Code execution and data analysis

3. **Frontend** - Web interface for chatbot interactions

4. **Shared Services**:
   - Azure OpenAI client (chat & embeddings)
   - Cosmos DB client (configuration & state)
   - Fabric SQL client (lakehouse queries)
   - Gremlin client (graph traversals)
   - Account resolver (fuzzy matching)
   - Auth provider (JWT validation or bypass)

## Quick Start

### Prerequisites

- Azure subscription
- Azure CLI (`az`) installed and authenticated (`az login`)
- Docker Desktop (for local development)
- Python 3.11+ (for local development)
- PowerShell 7+ (for deployment scripts)

### 1. Deploy Infrastructure

```powershell
# Provision Azure resources (Cosmos DB, OpenAI, etc.)
.\scripts\infra\deploy.ps1 -BaseName "mybot" -Location "westus2"
```

### 2. Configure Environment

```powershell
# Auto-discover endpoints and create .env
.\scripts\test_env\set_env.ps1 -ResourceGroup "mybot-rg"
```

### 3. Initialize Data

```powershell
# Create containers and upload seed data
python .\scripts\test_env\init_data.py
```

### 4. Run Locally (Development)

```powershell
cd agentic_framework

# Terminal 1 - Graph MCP
python -m mcps.graph.server

# Terminal 2 - Interpreter MCP
python -m mcps.interpreter.server

# Terminal 3 - SQL MCP
python -m mcps.sql.server

# Terminal 4 - Orchestrator
python -m orchestrator.app

# Terminal 5 - Frontend (optional)
cd frontend
npm install
npm run dev
```

Access:
- Orchestrator API: http://localhost:8000
- Frontend: http://localhost:3000

### 5. Deploy to Azure (Production)

```powershell
# Deploy to Azure Container Apps
.\agentic_framework\deploy\deploy-aca.ps1 -EnvFile .env -BuildImages
```

## Project Structure

```
.
├── agentic_framework/           # Core framework code
│   ├── orchestrator/           # Central orchestrator
│   │   ├── app.py             # FastAPI application
│   │   ├── orchestrator.py    # Multi-round planning logic
│   │   └── Dockerfile
│   ├── mcps/                  # MCP servers
│   │   ├── graph/             # Graph/relationship MCP
│   │   ├── interpreter/       # Code execution MCP
│   │   ├── sql/               # SQL query MCP
│   │   └── TEMPLATE/          # Template for new MCPs
│   ├── shared/                # Shared clients and utilities
│   │   ├── aoai_client.py     # Azure OpenAI wrapper
│   │   ├── cosmos_client.py   # Cosmos DB client
│   │   ├── fabric_client.py   # Fabric SQL client
│   │   ├── gremlin_client.py  # Gremlin graph client
│   │   ├── auth_provider.py   # JWT auth or bypass
│   │   ├── config.py          # Pydantic settings
│   │   └── models.py          # Shared data models
│   ├── frontend/              # Web interface
│   │   ├── app.js             # Express server
│   │   ├── public/            # Static assets
│   │   └── Dockerfile
│   └── deploy/                # Container Apps deployment
│       ├── deploy-aca.ps1     # Main deployment script
│       ├── configure-env.ps1  # Environment updates
│       └── update-mcp-urls.ps1
├── scripts/
│   ├── infra/
│   │   └── deploy.ps1         # Azure infrastructure provisioning
│   ├── test_env/
│   │   ├── set_env.ps1        # Environment configuration
│   │   └── init_data.py       # Data initialization
│   └── assets/                # Seed data
│       ├── prompts/           # System prompts (markdown)
│       ├── functions/         # Tool/agent definitions (JSON)
│       └── schema/            # SQL schema metadata (JSON)
├── .env.example               # Environment variable template
├── CLAUDE.md                  # Architecture & development guide
├── DEPLOYMENT.md              # Deployment guide
└── README.md                  # This file
```

## Configuration

All configuration is managed via environment variables in `.env`:

### Development Mode
```bash
DEV_MODE=true
BYPASS_TOKEN=true
DEBUG=true
```

### Production Mode
```bash
DEV_MODE=false
BYPASS_TOKEN=false
AZURE_TENANT_ID=your-tenant-id
```

See [.env.example](.env.example) for complete configuration options.

## Usage Examples

### Query with SQL MCP
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "Show me all opportunities at Microsoft"}],
    "user_id": "sales@example.com"
  }'
```

### Graph Relationship Discovery
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "What technologies does Salesforce use?"}],
    "user_id": "sales@example.com"
  }'
```

### Code Execution
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "Calculate the average deal size"}],
    "user_id": "analyst@example.com"
  }'
```

## Development

### Adding a New MCP Server

1. Create folder in `agentic_framework/mcps/`:
```powershell
mkdir agentic_framework/mcps/custom
```

2. Add `server.py` using FastMCP:
```python
from fastmcp import FastMCP
from shared.auth_provider import create_auth_provider

auth_provider = create_auth_provider()
mcp = FastMCP("Custom MCP", auth=auth_provider)

@mcp.tool()
async def custom_tool(query: str, rbac_context: dict = None):
    return {"success": True, "data": []}

if __name__ == "__main__":
    import os
    MCP_PORT = int(os.getenv("MCP_PORT", "8004"))
    mcp.run(transport="http", host="0.0.0.0", port=MCP_PORT)
```

3. Add Dockerfile

4. Upload tool definition to Cosmos:
```json
{
  "id": "custom_tool",
  "mcp_id": "custom_mcp",
  "name": "custom_tool",
  "description": "Execute custom operations",
  "parameters": {
    "type": "object",
    "properties": {
      "query": {"type": "string"}
    }
  },
  "allowed_roles": ["admin"]
}
```

5. Update `.env`:
```bash
MCP_ENDPOINTS={"sql_mcp": "http://localhost:8003/mcp", "graph_mcp": "http://localhost:8001/mcp", "custom_mcp": "http://localhost:8004/mcp"}
```

6. Redeploy:
```powershell
.\agentic_framework\deploy\deploy-aca.ps1 -BuildImages
```

### Running Tests

```powershell
cd agentic_framework

# Test individual MCPs
python tests/test_sql_mcp.py
python tests/test_graph_mcp.py

# Test orchestrator
python tests/test_orchestrator.py
```

## RBAC Implementation

The framework enforces access control at two levels:

### 1. MCP/Tool Access
User roles determine which MCPs and tools are visible:
```json
{
  "role_name": "sales_rep",
  "allowed_mcps": ["sql_mcp", "graph_mcp"],
  "allowed_tools": ["sql_query", "graph_query"]
}
```

### 2. Row-Level Security
RBAC context is passed to MCP tools to filter data:
```python
@mcp.tool()
async def sql_query(query: str, rbac_context: dict = None):
    # Inject WHERE clause based on rbac_context
    filtered_query = apply_rbac_filter(query, rbac_context)
    return execute_sql(filtered_query)
```

In dev mode (`DEV_MODE=true`), all users get admin access.

## Authentication

### Development (No Auth)
```bash
DEV_MODE=true
BYPASS_TOKEN=true
```

### Testing (Azure Services, No JWT)
```bash
DEV_MODE=false
BYPASS_TOKEN=true
```

### Production (Full Auth)
```bash
DEV_MODE=false
BYPASS_TOKEN=false
AZURE_TENANT_ID=your-tenant-id
```

All Azure services use `DefaultAzureCredential`:
- Local: `az login`
- Production: Managed Identity

## Deployment

See [DEPLOYMENT.md](DEPLOYMENT.md) for complete deployment guide.

**Quick deploy:**
```powershell
# 1. Infrastructure
.\scripts\infra\deploy.ps1 -BaseName "mybot" -Location "westus2"

# 2. Configure
.\scripts\test_env\set_env.ps1 -ResourceGroup "mybot-rg"

# 3. Initialize
python .\scripts\test_env\init_data.py

# 4. Deploy apps
.\agentic_framework\deploy\deploy-aca.ps1 -BuildImages
```

## Monitoring

### View Logs
```powershell
# Orchestrator logs
az containerapp logs show -n orchestrator -g mybot-rg --tail 50

# MCP logs
az containerapp logs show -n sql-mcp -g mybot-rg --tail 50
```

### Health Checks
```bash
# Orchestrator health
curl https://<orchestrator-fqdn>/health

# List MCPs
curl https://<orchestrator-fqdn>/mcps

# List tools
curl https://<orchestrator-fqdn>/tools
```

## Troubleshooting

### Common Issues

**MCPs not discovered:**
- Check `MCP_ENDPOINTS` JSON format in orchestrator environment
- Verify MCP servers are running and accessible
- Test MCP endpoint: `curl http://<mcp-fqdn>/mcp`

**Authentication errors:**
- Run `az login` for local development
- Verify Managed Identity has required RBAC roles
- Check `AZURE_TENANT_ID` is set for production

**Tool not available:**
- Verify tool definition exists in `agent_functions` container
- Check `mcp_id` matches MCP endpoint key
- Ensure user role has access to tool

**Container Apps deployment fails:**
- Check image tag exists in ACR
- Verify environment variables are set correctly
- Review logs: `az containerapp logs show`

See [DEPLOYMENT.md](DEPLOYMENT.md) for detailed troubleshooting.

## Architecture Details

See [CLAUDE.md](CLAUDE.md) for detailed architecture documentation including:
- Component design patterns
- MCP discovery mechanism
- Multi-round planning loop
- RBAC implementation
- Session-centric tracking
- Development vs production modes

## Technology Stack

- **Framework**: FastMCP, FastAPI, asyncio
- **LLM**: Azure OpenAI (GPT-4.1, text-embedding-3-small)
- **Data Storage**: Cosmos DB (NoSQL + Gremlin)
- **SQL**: Microsoft Fabric Lakehouse
- **Compute**: Azure Container Apps
- **Auth**: Azure AD, Managed Identity
- **Frontend**: Node.js, Express, vanilla JS
- **Infrastructure**: Azure CLI, PowerShell

## Contributing

1. Create new MCP in `agentic_framework/mcps/`
2. Follow FastMCP patterns (see TEMPLATE/)
3. Add tool definitions to `scripts/assets/functions/`
4. Update documentation
5. Test locally before deploying

## License

This project is proprietary. All rights reserved.

## Support

For issues and questions:
1. Check [DEPLOYMENT.md](DEPLOYMENT.md) troubleshooting
2. Review [CLAUDE.md](CLAUDE.md) architecture guide
3. Check Azure service health
4. Review Container Apps logs

## Roadmap

- [ ] Add more MCP servers (email, calendar, etc.)
- [ ] Implement streaming responses
- [ ] Add conversation memory across sessions
- [ ] Enhanced graph visualization in frontend
- [ ] Multi-tenant support
- [ ] Advanced RBAC with attribute-based access control
- [ ] Performance monitoring and tracing
- [ ] Automated testing pipeline

---

**Version:** 1.0.0
**Last Updated:** 2025-10-05
