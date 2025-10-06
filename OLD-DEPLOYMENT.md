# Deployment Guide

Complete guide for deploying the Agentic Framework to Azure.

## Overview

This repository contains multiple deployment scripts organized by purpose:

```
├── scripts/
│   ├── infra/
│   │   └── deploy.ps1              # Azure infrastructure provisioning
│   └── test_env/
│       ├── set_env.ps1             # Environment variable configuration
│       └── init_data.py            # Data initialization and seeding
└── agentic_framework/
    └── deploy/
        ├── deploy-aca.ps1          # Container Apps deployment
        ├── configure-env.ps1       # Environment variable updates
        └── update-mcp-urls.ps1     # MCP endpoint configuration
```

---

## Quick Start (New Deployment)

For a fresh deployment to Azure, follow these steps in order:

### 1. Deploy Infrastructure
```powershell
# Deploy core Azure resources (Cosmos DB, Azure OpenAI, etc.)
.\scripts\infra\deploy.ps1 `
  -BaseName "salesforcebot" `
  -Location "westus2" `
  -Mode "Core"
```

**What it does:**
- Creates resource group
- Provisions Azure OpenAI (eastus2 for quota)
- Deploys GPT-4.1 and text-embedding-3-small models
- Creates Cosmos DB NoSQL account (for config/data)
- Creates Cosmos DB Gremlin account (for graph data)
- Sets up Managed Identity with RBAC roles
- Optionally creates Container Apps Environment

**Output:** Core Azure resources with endpoints

---

### 2. Configure Environment Variables
```powershell
# Auto-discover endpoints and configure .env
.\scripts\test_env\set_env.ps1 -ResourceGroup "salesforcebot-rg"
```

**What it does:**
- Merges `.env.example` into `.env`
- Auto-discovers Azure resource endpoints
- Detects Azure OpenAI deployments
- Configures Cosmos DB connection strings
- Sets up Gremlin endpoints
- Forces `DEV_MODE=true` for local development

**Output:** Configured `.env` file in repository root

---

### 3. Initialize Data
```powershell
# Create containers and upload seed data
python .\scripts\test_env\init_data.py
```

**What it does:**
- Creates required Cosmos DB containers via Azure CLI
- Uploads system prompts from `scripts/assets/prompts/`
- Uploads tool/agent definitions from `scripts/assets/functions/`
- Uploads SQL schema from `scripts/assets/schema/`
- Seeds dummy graph data (accounts, SOWs, offerings, tech stack)
- Assigns data-plane RBAC roles

**Requirements:**
- Azure CLI (`az`) installed and authenticated (`az login`)
- Permissions to create Cosmos DB resources

**Output:** Cosmos DB containers with seed data

---

### 4. Deploy Container Apps
```powershell
# Deploy orchestrator, MCPs, and frontend to Azure Container Apps
.\agentic_framework\deploy\deploy-aca.ps1 `
  -EnvFile .env `
  -BuildImages
```

**What it does:**
- Builds Docker images for orchestrator, all MCPs, and frontend
- Pushes images to Azure Container Registry
- Creates/updates Container Apps Environment
- Deploys MCP servers with unique ports (8001, 8002, 8003...)
- Deploys orchestrator with dynamic MCP endpoint discovery
- Deploys frontend with orchestrator URL
- Configures ingress (internal for MCPs, external for orchestrator/frontend)

**Flags:**
- `-BuildImages`: Rebuild and push Docker images (use after code changes)
- Omit `-BuildImages` to redeploy without rebuilding (faster)

**Output:** Running Container Apps with public URLs

---

## Script Details

### Infrastructure Scripts

#### `scripts/infra/deploy.ps1`
**Purpose:** Provision Azure infrastructure
**When to use:** First-time setup or adding new Azure resources

**Parameters:**
- `-BaseName` (required): Base name for resources (e.g., "salesforcebot")
- `-Location` (required): Azure region (e.g., "westus2")
- `-Mode`: "Core" or "Full" (default: "Core")
  - Core: Cosmos DB, OpenAI, Managed Identity
  - Full: Adds API Management and Azure Front Door

**Example:**
```powershell
.\scripts\infra\deploy.ps1 `
  -BaseName "mybot" `
  -Location "eastus" `
  -Mode "Full"
```

**Resources created:**
- Resource Group: `{BaseName}-rg`
- Azure OpenAI: `{BaseName}-aoai-eastus2` (uses eastus2 for quota)
- Cosmos NoSQL: `{BaseName}-cosmos-sql`
- Cosmos Gremlin: `{BaseName}-cosmos-graph`
- Managed Identity: `{BaseName}-mi`
- Container Apps Environment: `{BaseName}-env` (optional)

---

### Environment Configuration

#### `scripts/test_env/set_env.ps1`
**Purpose:** Auto-discover Azure endpoints and configure `.env`
**When to use:** After infrastructure deployment, or when endpoints change

**Parameters:**
- `-ResourceGroup` (optional): Azure resource group name (auto-detects if omitted)

**Example:**
```powershell
.\scripts\test_env\set_env.ps1 -ResourceGroup "salesforcebot-rg"
```

**What it configures:**
- `AOAI_ENDPOINT` - Azure OpenAI endpoint
- `AOAI_CHAT_DEPLOYMENT` - Chat model deployment (prefers gpt-4.1 > gpt-4o > gpt-4)
- `AOAI_EMBEDDING_DEPLOYMENT` - Embedding model deployment
- `COSMOS_ENDPOINT` - Cosmos NoSQL endpoint
- `AZURE_COSMOS_GREMLIN_ENDPOINT` - Gremlin endpoint
- `CONTAINER_APP_RESOURCE_GROUP` - Resource group for deployments
- `AZURE_TENANT_ID` - Azure AD tenant ID

**Output:** `.env` file in repository root and `chatbot/.env`

---

### Data Initialization

#### `scripts/test_env/init_data.py`
**Purpose:** Create Cosmos containers and seed data
**When to use:** After infrastructure deployment, before first run

**Usage:**
```powershell
python .\scripts\test_env\init_data.py
```

**What it does:**
1. **Provisioning** (via Azure CLI):
   - Creates Cosmos SQL database (`appdb`)
   - Creates containers: `chat_history`, `prompts`, `agent_functions`, `sql_schema`
   - Creates Gremlin database (`graphdb`) and graph (`account_graph`)
   - Assigns data-plane RBAC roles to current user

2. **Data Upload**:
   - Prompts: `scripts/assets/prompts/*.md` → `prompts` container
   - Functions: `scripts/assets/functions/tools/*.json` → `agent_functions` container
   - Schema: `scripts/assets/schema/*.json` → `sql_schema` container
   - Graph: Demo accounts, SOWs, offerings, tech stack → Gremlin graph

**Requirements:**
- Azure CLI installed (`az`)
- Authenticated (`az login`)
- Permissions: Cosmos DB Data Contributor, DocumentDB Account Contributor

**Environment variables:**
- `INIT_DATA_CLEAR_GRAPH=true` - Clear existing graph data before upload (default: true)

---

### Container Apps Deployment

#### `agentic_framework/deploy/deploy-aca.ps1`
**Purpose:** Deploy orchestrator, MCPs, and frontend to Azure Container Apps
**When to use:** Initial deployment or code updates

**Parameters:**
- `-EnvFile` (default: `.env`): Path to environment file
- `-BuildImages`: Rebuild Docker images before deployment
- `-ResourceGroup` (default: "salesforcebot-rg"): Azure resource group
- `-Location` (default: "westus2"): Azure region
- `-EnvironmentName` (default: "salesforcebot-env"): Container Apps environment
- `-ContainerRegistry` (default: "salesforcebotacr"): Azure Container Registry
- `-ImageTag` (default: "latest"): Docker image tag

**Usage:**
```powershell
# Deploy with image rebuild (after code changes)
.\agentic_framework\deploy\deploy-aca.ps1 -EnvFile .env -BuildImages

# Deploy without rebuild (faster, uses existing images)
.\agentic_framework\deploy\deploy-aca.ps1 -EnvFile .env
```

**Deployment process:**

1. **Discovery**: Finds all MCP servers in `agentic_framework/mcps/`
2. **Port Assignment**: Assigns sequential ports alphabetically:
   - Orchestrator: 8000 (always)
   - graph-mcp: 8001
   - interpreter-mcp: 8002
   - sql-mcp: 8003
3. **Image Build** (if `-BuildImages`):
   - Builds orchestrator, all MCPs, frontend
   - Pushes to Azure Container Registry
4. **MCP Deployment**:
   - Deploys each MCP with internal ingress
   - Sets `MCP_PORT` environment variable
5. **Orchestrator Deployment**:
   - Builds `MCP_ENDPOINTS` JSON from MCP FQDNs
   - Deploys with external ingress on port 8000
6. **Frontend Deployment**:
   - Sets `ORCHESTRATOR_URL` to orchestrator FQDN
   - Deploys with external ingress on port 8080

**Environment modes:**
- `DEV_MODE=true` - Uses dummy data, bypasses Azure services
- `BYPASS_TOKEN=true` - Skips JWT token validation
- Production: Set both to `false`

---

#### `agentic_framework/deploy/configure-env.ps1`
**Purpose:** Update Container App environment variables after deployment
**When to use:** To change configuration without redeployment

**Parameters:**
- `-ResourceGroup` (required): Azure resource group
- `-CosmosAccountName` (required): Cosmos DB account name
- `-OpenAIAccountName` (required): Azure OpenAI account name
- `-GremlinAccountName` (required): Gremlin account name
- `-FabricSqlEndpoint` (optional): Fabric SQL endpoint
- `-FabricDatabase` (optional): Fabric database name

**Example:**
```powershell
.\agentic_framework\deploy\configure-env.ps1 `
  -ResourceGroup "salesforcebot-rg" `
  -CosmosAccountName "salesforcebot-cosmos-sql" `
  -OpenAIAccountName "salesforcebot-aoai-eastus2" `
  -GremlinAccountName "salesforcebot-cosmos-graph"
```

---

## Deployment Scenarios

### Scenario 1: Fresh Production Deployment
```powershell
# 1. Deploy infrastructure
.\scripts\infra\deploy.ps1 -BaseName "mybot" -Location "eastus"

# 2. Configure environment
.\scripts\test_env\set_env.ps1 -ResourceGroup "mybot-rg"

# 3. Set production mode in .env
# Edit .env: DEV_MODE=false, BYPASS_TOKEN=false

# 4. Initialize data
python .\scripts\test_env\init_data.py

# 5. Deploy apps
.\agentic_framework\deploy\deploy-aca.ps1 -BuildImages
```

---

### Scenario 2: Local Development Setup
```powershell
# 1. Deploy infrastructure (if needed)
.\scripts\infra\deploy.ps1 -BaseName "dev" -Location "westus2"

# 2. Configure environment (sets DEV_MODE=true)
.\scripts\test_env\set_env.ps1 -ResourceGroup "dev-rg"

# 3. Initialize data
python .\scripts\test_env\init_data.py

# 4. Run locally (no Container Apps deployment)
cd agentic_framework
python -m mcps.sql.server      # Terminal 1
python -m mcps.graph.server    # Terminal 2
python -m orchestrator.app     # Terminal 3
```

---

### Scenario 3: Update Code in Production
```powershell
# 1. Make code changes
# Edit files in agentic_framework/...

# 2. Rebuild and redeploy
.\agentic_framework\deploy\deploy-aca.ps1 -BuildImages
```

---

### Scenario 4: Update Configuration Only
```powershell
# Update environment variables without rebuilding images
.\agentic_framework\deploy\configure-env.ps1 `
  -ResourceGroup "salesforcebot-rg" `
  -CosmosAccountName "salesforcebot-cosmos-sql" `
  -OpenAIAccountName "salesforcebot-aoai-eastus2" `
  -GremlinAccountName "salesforcebot-cosmos-graph"
```

---

### Scenario 5: Add New MCP Server
```powershell
# 1. Create new MCP folder
mkdir agentic_framework/mcps/custom

# 2. Add Dockerfile and server.py
# See agentic_framework/mcps/TEMPLATE/ for example

# 3. Upload tool definitions to Cosmos
# Add JSON files to scripts/assets/functions/tools/

# 4. Run init_data to upload new tools
python .\scripts\test_env\init_data.py

# 5. Rebuild and redeploy (auto-discovers new MCP)
.\agentic_framework\deploy\deploy-aca.ps1 -BuildImages
```

---

## Troubleshooting

### Infrastructure Deployment Issues

**Error: Quota exceeded for Azure OpenAI**
- Script automatically uses eastus2 region for better quota availability
- If still failing, request quota increase or use existing account

**Error: Container Apps environment creation failed**
- Regional quota may be exceeded
- Script will attempt to reuse existing environment
- Or deploy to different region

**Error: Cannot create Cosmos DB**
- Check Azure subscription limits
- Ensure proper permissions (Contributor role)
- Verify resource name is globally unique

---

### Environment Configuration Issues

**Error: Resource group not found**
- Provide explicit `-ResourceGroup` parameter
- Verify resource group name matches infrastructure deployment

**Error: No deployment found**
- Azure OpenAI deployments take time to propagate
- Wait a few minutes and re-run `set_env.ps1`
- Or manually set `AOAI_CHAT_DEPLOYMENT` in `.env`

**Error: BOM detected in .env file**
- Script automatically removes UTF-8 BOM
- If persists, manually re-save `.env` without BOM

---

### Data Initialization Issues

**Error: Azure CLI not found**
- Install Azure CLI: https://aka.ms/installazurecli
- Run `az login` to authenticate
- Verify `az` is in PATH

**Error: Permission denied creating containers**
- Current user needs "Cosmos DB Data Contributor" role
- Or run `az role assignment` commands manually (script prints them)
- Or use Managed Identity with proper roles

**Error: Gremlin graph not found**
- Script attempts to create `graphdb` database and `account_graph` graph
- Verify Gremlin account has EnableGremlin capability
- Check resource group and account names in environment

**Error: DefaultAzureCredential failed**
- Ensure `az login` is successful
- Check that AAD token hasn't expired
- For Managed Identity, verify RBAC assignments

---

### Container Apps Deployment Issues

**Error: MCP starting on wrong port**
- Verify `MCP_PORT` environment variable is set correctly
- Check MCP server code uses `port` parameter in `mcp.run()`
- View logs: `az containerapp logs show --name <mcp-name> -g <rg> --tail 50`

**Error: Orchestrator can't discover MCPs**
- Check `MCP_ENDPOINTS` JSON format (no backticks, proper quotes)
- Verify MCP internal URLs: `https://<mcp-name>.internal.<env-domain>/mcp`
- Ensure all MCPs are running: `az containerapp list -g <rg>`

**Error: Frontend shows old code**
- Check that `ORCHESTRATOR_URL` is set in frontend environment variables
- Verify traffic is routed to latest revision
- Deactivate old revisions manually if needed

**Error: Image not updating**
- Azure Container Apps caches images by tag
- Use versioned tags (v1, v2) instead of `latest`
- Or force update with image digest

---

## Environment Variables Reference

### Core Settings
- `DEV_MODE` - Bypass Azure services, use dummy data (true/false)
- `BYPASS_TOKEN` - Skip JWT validation (true/false)
- `DEBUG` - Enable verbose logging (true/false)

### Azure OpenAI
- `AOAI_ENDPOINT` - Azure OpenAI endpoint
- `AOAI_CHAT_DEPLOYMENT` - Chat model deployment name
- `AOAI_EMBEDDING_DEPLOYMENT` - Embedding model deployment name
- `AOAI_API_VERSION` - API version (default: 2024-06-01)

### Cosmos DB (NoSQL)
- `COSMOS_ENDPOINT` - Cosmos NoSQL endpoint
- `COSMOS_DATABASE_NAME` - Database name (default: appdb)
- `COSMOS_CHAT_CONTAINER` - Unified chat/message/feedback container
- `COSMOS_PROMPTS_CONTAINER` - System prompts container
- `COSMOS_AGENT_FUNCTIONS_CONTAINER` - Tool/agent definitions container

### Gremlin (Graph)
- `AZURE_COSMOS_GREMLIN_ENDPOINT` - Gremlin endpoint
- `AZURE_COSMOS_GREMLIN_DATABASE` - Gremlin database name
- `AZURE_COSMOS_GREMLIN_GRAPH` - Graph/collection name
- `AZURE_COSMOS_GREMLIN_PORT` - Port (default: 443)

### Authentication
- `AZURE_TENANT_ID` - Azure AD tenant ID (required for JWT validation)
- `AZURE_AUDIENCE` - JWT audience (optional, leave unset to skip audience check)

### MCP Configuration
- `MCP_ENDPOINTS` - JSON dict mapping MCP IDs to endpoints
- `MCP_PORT` - Port for MCP server (set by deployment script)

### Fabric SQL (Optional)
- `FABRIC_SQL_ENDPOINT` - Fabric lakehouse endpoint
- `FABRIC_SQL_DATABASE` - Fabric database name
- `FABRIC_WORKSPACE_ID` - Fabric workspace ID

---

## Port Assignments

**Important:** Each MCP must use a unique port. Ports are assigned alphabetically by folder name.

- **Orchestrator**: 8000 (always)
- **graph-mcp**: 8001 (first alphabetically)
- **interpreter-mcp**: 8002 (second alphabetically)
- **sql-mcp**: 8003 (third alphabetically)

When adding new MCPs, they automatically receive the next sequential port based on alphabetical order.

---

## Authentication Modes

### Development Mode
```
DEV_MODE=true
BYPASS_TOKEN=true
```
- No Azure connections
- Returns dummy data
- No authentication required

### Testing Mode
```
DEV_MODE=false
BYPASS_TOKEN=true
```
- Uses real Azure services
- Skips JWT validation
- RBAC still enforced based on user_id

### Production Mode
```
DEV_MODE=false
BYPASS_TOKEN=false
```
- Full Azure integration
- JWT token validation via Azure AD
- Requires `AZURE_TENANT_ID`
- Optional `AZURE_AUDIENCE` check

---

## Getting Application URLs

After deployment, get public URLs:

```powershell
# Frontend URL
az containerapp show -n salesforce-frontend -g salesforcebot-rg --query "properties.configuration.ingress.fqdn" -o tsv

# Orchestrator URL
az containerapp show -n orchestrator -g salesforcebot-rg --query "properties.configuration.ingress.fqdn" -o tsv

# MCP URLs (internal only)
az containerapp show -n sql-mcp -g salesforcebot-rg --query "properties.configuration.ingress.fqdn" -o tsv
```

---

## Testing Deployment

### Test Orchestrator Health
```bash
curl https://<orchestrator-fqdn>/health
```

### Test Orchestrator Chat
```bash
curl -X POST https://<orchestrator-fqdn>/chat \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Show contacts at Microsoft"}], "user_id": "test@example.com"}'
```

### List Available MCPs
```bash
curl https://<orchestrator-fqdn>/mcps
```

### List Available Tools
```bash
curl https://<orchestrator-fqdn>/tools
```

---

## Additional Resources

- [CLAUDE.md](CLAUDE.md) - Architecture and development guide
- [README.md](README.md) - Project overview
- Azure OpenAI: https://learn.microsoft.com/azure/ai-services/openai/
- Azure Cosmos DB: https://learn.microsoft.com/azure/cosmos-db/
- Azure Container Apps: https://learn.microsoft.com/azure/container-apps/
