# MCP Agent Framework

A flexible, role-based MCP (Model Context Protocol) orchestration framework for building modular AI agents with dynamic tool routing.

## Architecture

This framework consists of three main components:

1. **Shared Module** (`shared/`): Common models (RBAC, messages) and utilities (JWT auth) used by both orchestrator and MCPs
2. **Orchestrator** (`orchestrator/`): Main API that routes user requests to appropriate MCP servers based on user roles
3. **MCP Servers** (`mcps/`): Individual MCP servers that provide domain-specific tools (e.g., Salesforce data access)

### Design Principles

- **Role-Based Access**: Users access MCPs based on their roles (admin, sales_manager, sales_rep, etc.)
- **Service Authentication**: Orchestrator uses JWT tokens to authenticate with MCP servers
- **RBAC Context Passing**: User's RBAC context is passed to MCPs as tool parameters for access control
- **MSI for Azure**: Each component uses its own Managed Service Identity to access Azure resources
- **Dev Mode**: Bypass authentication for local development and testing

## Quick Start

### Development Mode (Recommended for Testing)

1. **Copy environment templates**:
```bash
cp orchestrator/.env.template orchestrator/.env
cp mcps/salesforce_mcp/.env.template mcps/salesforce_mcp/.env
```

2. **Configure Azure credentials** (ensure you're logged in with `az login`):
```bash
az login
```

3. **Update `.env` files** with your Azure resource endpoints:
   - Azure OpenAI endpoint and deployments
   - Cosmos DB endpoint
   - Fabric Lakehouse endpoint
   - Gremlin endpoint

4. **Set DEV_MODE=true** in both `.env` files (already set in templates)

5. **Run with Docker Compose**:
```bash
docker-compose up --build
```

6. **Test the API**:
```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "What accounts do we have?"}],
    "user_id": "dev@example.com"
  }'
```

### Production Mode

1. **Configure environment variables** for production (set `DEV_MODE=false`)
2. **Set up Managed Service Identities** for each component
3. **Configure JWT secrets** for service-to-service auth
4. **Deploy to Azure Container Apps** or Kubernetes

## Project Structure

```
mcp_agent/
├── shared/                     # Shared utilities and models
│   ├── models/
│   │   ├── rbac.py            # RBAC models (RBACContext, Permission, etc.)
│   │   └── message.py         # Message models
│   └── utils/
│       └── auth_utils.py      # JWT utilities
│
├── orchestrator/               # Orchestrator service
│   ├── src/orchestrator/
│   │   ├── config/            # Settings
│   │   ├── clients/           # Azure clients + MCP client
│   │   ├── services/          # Auth, MCP loader, orchestrator logic
│   │   ├── routes/            # FastAPI routes
│   │   └── app.py             # Main FastAPI app
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .env.template
│
├── mcps/                       # MCP servers
│   └── salesforce_mcp/        # Salesforce data MCP
│       ├── src/salesforce_mcp/
│       │   ├── config/        # MCP-specific settings
│       │   ├── clients/       # Fabric, Gremlin clients
│       │   ├── services/      # SQL, Graph, Account Resolver
│       │   ├── repositories/  # SQL schema repo
│       │   ├── tools/         # FastMCP tool definitions
│       │   └── server.py      # FastMCP server
│       ├── requirements.txt
│       ├── Dockerfile
│       └── .env.template
│
└── docker-compose.yml          # Local development setup
```

## Authentication Flow

### Dev Mode (DEV_MODE=true)
- **User → Orchestrator**: No JWT required (uses default dev user with admin role)
- **Orchestrator → MCP**: Uses "dev-token" instead of real JWT
- **MCP → Azure**: Uses Azure CLI credentials (DefaultAzureCredential)

### Production Mode (DEV_MODE=false)
- **User → Orchestrator**: User JWT with roles in claims
- **Orchestrator → MCP**: Service JWT signed with shared secret
- **MCP → Azure**: Uses Managed Service Identity (MSI)

## Adding New MCPs

1. **Create MCP directory**:
```bash
mkdir -p mcps/my_new_mcp/src/my_new_mcp/{config,clients,services,tools}
```

2. **Copy template from salesforce_mcp** and adapt:
   - Settings (config/settings.py)
   - FastMCP server (server.py)
   - Tools (tools/*.py)

3. **Register in orchestrator** `.env`:
```
MCP_SERVERS={"salesforce_mcp": "http://localhost:8001", "my_new_mcp": "http://localhost:8002"}
ROLE_MCP_MAPPING={"admin": ["salesforce_mcp", "my_new_mcp"], "sales_rep": ["salesforce_mcp"]}
```

4. **Update docker-compose.yml** to include new service

## Configuration

### Role-Based Access

Configure which roles can access which MCPs in `orchestrator/.env`:

```bash
ROLE_MCP_MAPPING={
  "admin": ["salesforce_mcp", "analytics_mcp", "documents_mcp"],
  "sales_manager": ["salesforce_mcp", "analytics_mcp"],
  "sales_rep": ["salesforce_mcp"]
}
```

### MCP Endpoints

Configure MCP server endpoints in `orchestrator/.env`:

```bash
MCP_SERVERS={
  "salesforce_mcp": "http://salesforce_mcp:8001",
  "analytics_mcp": "http://analytics_mcp:8002"
}
```

## Development

### Running Locally (Without Docker)

**Terminal 1 - Salesforce MCP**:
```bash
cd mcps/salesforce_mcp
pip install -r requirements.txt
export PYTHONPATH=$PYTHONPATH:$(pwd)/../../../shared
python src/main.py
```

**Terminal 2 - Orchestrator**:
```bash
cd orchestrator
pip install -r requirements.txt
export PYTHONPATH=$PYTHONPATH:$(pwd)/../../shared
python src/main.py
```

### Testing

Test the orchestrator directly:
```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "messages": [{"role": "user", "content": "Show me recent opportunities"}],
    "user_id": "user@example.com"
  }'
```

## Troubleshooting

### Import Errors
- Ensure `PYTHONPATH` includes the shared module
- Check that all `__init__.py` files are in place

### Authentication Errors
- In dev mode: Ensure `DEV_MODE=true` in both `.env` files
- In production: Verify JWT secrets match between orchestrator and MCPs

### Azure Access Errors
- Ensure you're logged in with `az login`
- Verify your account has access to Azure resources
- Check Managed Identity permissions in production

## License

[Your License]
