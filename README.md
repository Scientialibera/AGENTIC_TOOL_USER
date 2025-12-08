## Text-to-SQL Agentic Framework (SQL-only)

This repo now serves a single SQL MCP plus an optional orchestrator. All graph/interpreter/front-end content has been removed.

### Current Architecture
- **SQL MCP (8003)**: Executes caller-provided T-SQL only (no internal SQL agent/LLM). Tools: `sql_query`, `list_tables`, `list_columns`, `get_schema`.
- **Orchestrator (8000)**: Optional router/planner that discovers the SQL tools via MCP HTTP.
- **Shared services**: Cosmos DB (schema + tool defs + embeddings), Azure SQL (primary), optional Fabric SQL, Azure OpenAI for embeddings only, account resolver/value matching services.

### Azure Resources
- Cosmos DB SQL API containers: `prompts`, `agent_functions`, `sql_schema`, `table_metadata`, `value_mappings` (Gremlin not required).
- Azure SQL Database (token auth via DefaultAzureCredential).
- Azure OpenAI (embeddings deployment; chat not used by SQL MCP).

### Configuration (single `config.toml`)
Key sections that matter now:
```toml
[framework]
dev_mode = false
bypass_token = true

[azure.sql]
enabled = true
server = "<server>.database.windows.net"
database = "<database>"
authentication = "azure_ad"
token_scope = "https://database.windows.net/.default"

[text_to_sql]
enable_embeddings = true
enable_table_discovery = true
enable_value_matching = true
max_tables_per_query = 5

[mcp.endpoints]
sql_mcp = "http://localhost:8003/mcp"
```
Secrets stay in environment/Managed Identity; no `.env` is required.

### Run
```pwsh
cd agentic_framework
pip install -r requirements.txt
python mcps/sql/server.py          # SQL MCP on 8003
# optional
# python orchestrator/app.py      # Orchestrator on 8000
```
Dev mode: set `[framework].dev_mode = true` to return dummy SQL rows without Azure.

### SQL MCP Behavior (no internal LLM)
- `sql_query` executes caller-supplied SELECT T-SQL; if no `TOP` and a limit is provided, it injects `TOP <limit>`.
- Safety: rejects non-SELECT statements.
- Embedding warmup: loads table/value metadata from Cosmos and backfills embeddings using Azure OpenAI when enabled.
- Account resolver/value matching: cached services from Cosmos metadata; metadata only (no query rewriting by LLM).
- RBAC context can be passed through `rbac_context` but no automatic clause generation occurs.

### Tool Definitions (Cosmos-synced)
Stored at `scripts/assets/functions/tools/` and uploaded with `python scripts/test_env/upload_artifacts.py`:
- `sql_query_function.json`
- `list_tables_function.json`
- `list_columns_function.json`
- `get_schema_function.json`
No other tool or agent JSON remains.

### Schema and Embeddings
- Schema seed JSON: `scripts/assets/schema/salesforce_schema.json` (Account/Contact/Opportunity/Case/Lead tables).
- Embedding caches: `table_metadata` and `value_mappings` containers; `_ensure_*_embeddings` runs on startup when embeddings are enabled.

### Quick Smoke Checks
```pwsh
# List tools via MCP client
python agentic_framework/mcp_test.py

# Direct sql_query (T-SQL only)
python - <<'PY'
import asyncio
from fastmcp import Client

async def main():
    client = Client('http://localhost:8003/mcp')
    async with client:
        res = await client.call_tool('sql_query', {'query': 'SELECT TOP 1 name FROM sys.tables'})
        print(res)

asyncio.run(main())
PY
```

### Cosmos Resync
Use the lightweight uploader (no Gremlin dependency):
```pwsh
python scripts/test_env/upload_artifacts.py
```
Uploads prompts, function JSONs, and schema JSON to the configured Cosmos containers.

### Troubleshooting
- If `sql_query` fails but `sys.tables` works, check table/column names and Azure SQL permissions; errors now surface tenacity root causes.
- Port in use on restart: `Get-NetTCPConnection -LocalPort 8003 | Select OwningProcess` then `Stop-Process -Id <pid>`.
- ODBC token issues: ensure `az login` or Managed Identity; install `ODBC Driver 18 for SQL Server`.

### Repository Pointers
- `agentic_framework/mcps/sql/server.py` — SQL MCP (caller-provided SQL only)
- `agentic_framework/shared/azure_sql_client.py` — Azure SQL access token wiring
- `scripts/assets/functions/tools/` — tool schemas (exactly four)
- `scripts/assets/schema/` — seed schema data
- `scripts/test_env/upload_artifacts.py` — Cosmos sync helper

```toml
[framework]
dev_mode = false
bypass_token = true
debug = true
environment = "development"
app_name = "Text-to-SQL Agent"

[azure.openai]
endpoint = "https://<your-aoai>.openai.azure.com/"
chat_deployment = "gpt-4o"
embedding_deployment = "text-embedding-ada-002"
api_version = "2024-06-01"

[azure.cosmos]
endpoint = "https://<your-cosmos>.documents.azure.com:443/"
database = "appdb"

[azure.fabric]
sql_endpoint = "<workspace>.datawarehouse.fabric.microsoft.com"
database = "<lakehouse>"
token_scope = "https://analysis.windows.net/powerbi/api/.default"

[azure.sql]
enabled = true
server = "<server>.database.windows.net"
database = "<database>"
authentication = "azure_ad"
token_scope = "https://database.windows.net/.default"

[rbac]
enabled = true
enforcement_mode = "soft"
row_level_security = true

[text_to_sql]
enable_embeddings = true
enable_table_discovery = true
enable_value_matching = true
similarity_threshold = 0.75
max_tables_per_query = 5
value_match_threshold = 0.80
max_unique_values_for_low_cardinality = 50
enable_self_healing = true
max_retry_attempts = 3

[mcp.endpoints]
sql_mcp = "http://localhost:8003/mcp"
graph_mcp = "http://localhost:8001/mcp"
interpreter_mcp = "http://localhost:8002/mcp"
```

### Setup
1) **Authenticate**: `az login` (DefaultAzureCredential everywhere; prefer Managed Identity in prod).
2) **Install** (Python 3.11+):
```pwsh
cd agentic_framework
pip install -r requirements.txt
```
3) **Configure**: Edit the single `config.toml` with your endpoints and toggles. No `.env` files.

### Run
- **Dev mode (no cloud calls)**: set `[framework].dev_mode = true`, `[framework].bypass_token = true` then run all services locally:
```pwsh
cd agentic_framework
python -m mcps.graph.server       # 8001
python -m mcps.interpreter.server # 8002
python -m mcps.sql.server         # 8003
python -m orchestrator.app        # 8000
```
- **Production mode**: set `dev_mode = false`, `bypass_token = false`, ensure Cosmos containers exist, and start the same entrypoints (Container Apps/AKS recommended). Port assignments stay fixed.

### Key Features
- Embedding-based table discovery for large schemas
- Low-cardinality value normalization and fuzzy matching
- Dual Fabric SQL and Azure SQL with correct token scopes
- RBAC-aware SQL generation (row and column filtering)
- Self-healing retries on SQL errors

### Testing
Run pytest from repository root:
```pwsh
python -m pytest tests
```
Expect real Azure endpoints unless `dev_mode` is true. Use Managed Identity or `az login` before running integration tests.

### Troubleshooting
- **Auth issues**: `az login`; verify managed identity roles (Cosmos DB Data Contributor/Reader, Fabric/Azure SQL data reader, Azure OpenAI user).
- **Table not found**: confirm database names and schema metadata in `sql_schema`/`table_metadata` containers.
- **Value not matching**: ensure `max_unique_values_for_low_cardinality` is not exceeded and value_mappings container is populated.
- **RBAC blocks**: start with `[rbac].enforcement_mode = "soft"` to log violations without blocking.

### Repository Layout (essentials)
- `config.toml` — single config source (required)
- `agentic_framework/orchestrator/` — orchestrator FastMCP app
- `agentic_framework/mcps/` — SQL/Graph/Interpreter MCP servers
- `agentic_framework/shared/` — shared clients (Azure OpenAI, Cosmos, Fabric/Azure SQL, RBAC, discovery)
- `scripts/` — utilities, test data loaders
- `deploy/` — infra and deployment helpers

### Quick Validation Calls
```pwsh
curl http://localhost:8000/mcps
curl http://localhost:8000/tools
curl -X POST http://localhost:8000/chat -H "Content-Type: application/json" -d '{"messages":[{"role":"user","content":"Show closed deals for Contoso"}],"user_id":"test@example.com"}'
```

### Notes
- All services use HTTP transport; ports remain 8000–8003.
- Secrets should be injected via environment or Managed Identity, not checked into `config.toml`.
- Cosmos vector search is used when available for table embeddings; otherwise the service falls back to in-memory similarity.
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