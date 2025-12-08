# Text-to-SQL Agent with Automatic Value Matching

Production-ready SQL query agent that automatically handles value matching for low-cardinality columns. Built on Azure SQL, Azure OpenAI, and FastMCP.

## Key Features

✅ **Automatic Value Matching** - MCP corrects casing automatically (e.g., 'closed won' → 'Closed Won')
✅ **Simple API** - Just send SQL queries, MCP handles the rest
✅ **Azure AD Authentication** - JWT token validation with optional role-based access control
✅ **Comprehensive Logging** - Full visibility into MCP operations and tool usage
✅ **Config-Driven** - All settings from `config.toml`, no hardcoded values

## Architecture

```
User Query → Orchestrator (optional) → SQL MCP → Azure SQL Database
                                         ↓
                                   Value Matching
                                   (automatic from
                                    Cosmos DB cache)
```

### Components

1. **SQL MCP Server** (port 8003) - Executes T-SQL queries with automatic value matching
   - Tools: `sql_query`, `list_tables`, `list_columns`, `get_schema`
   - Automatically corrects values for low-cardinality columns
   - No LLM inside MCP - orchestrator handles query generation

2. **Orchestrator** (port 8000, optional) - Routes requests and discovers MCP tools
   - Generates SQL using Azure OpenAI
   - Discovers available tools from SQL MCP
   - Orchestrates multi-step workflows

3. **Shared Services**
   - Cosmos DB: Schema metadata, value mappings, function definitions
   - Azure SQL: Primary database for queries
   - Azure OpenAI: Embeddings for table discovery (optional)

## Quick Start

### 1. Prerequisites

- Azure SQL Database
- Azure Cosmos DB (SQL API)
- Azure OpenAI (for embeddings, optional)
- Python 3.11+

### 2. Configuration

Copy `config.toml.example` to `config.toml` and fill in your Azure resources:

```toml
[framework]
dev_mode = false  # true for local dev without Azure
bypass_token = false  # true to skip JWT validation

[azure.auth]
tenant_id = "your-tenant-id"

[azure.sql]
enabled = true
server = "your-server.database.windows.net"
database = "your-database"

[azure.cosmos]
endpoint = "https://your-cosmos.documents.azure.com:443/"
database = "appdb"

[mcp.endpoints]
sql_mcp = "http://localhost:8003/mcp"

[text_to_sql]
enable_value_matching = true  # Automatic value correction
enable_table_discovery = true  # Use embeddings for table discovery
```

### 3. Install Dependencies

```bash
cd agentic_framework
pip install -r requirements.txt
```

### 4. Run

```bash
# Start SQL MCP
python -m agentic_framework.mcps.sql.server

# Optional: Start orchestrator
python -m agentic_framework.orchestrator.app
```

### 5. Test

```bash
# Test MCP directly
python scripts/test_mcp.py

# Test orchestrator end-to-end
python scripts/test_agent.py
```

## How Value Matching Works

The SQL MCP automatically corrects value casing using cached mappings from Cosmos DB:

**Example:**
```python
# User sends (via orchestrator):
query = "SELECT * FROM Opportunity WHERE StageName = 'closed won'"

# MCP automatically corrects to:
query = "SELECT * FROM Opportunity WHERE StageName = 'Closed Won'"

# Then executes against Azure SQL
```

The MCP loads value mappings from Cosmos DB on startup and uses them to auto-correct:
- Lowercase values → Exact database values
- Mixed case → Exact database values
- Multi-word values (e.g., "in progress" → "In Progress")

## Authentication & RBAC

### JWT Authentication
When `bypass_token = false`, the MCP validates JWT tokens from Azure AD:
- Validates signature using JWKS
- Checks issuer matches tenant ID
- Optionally checks user roles

### Role-Based Access Control
```toml
[rbac]
enabled = true
check_role = true  # Enforce role checking
required_role = "mcp:READ"  # Required role from JWT
enforcement_mode = "hard"  # hard = block, soft = log only
```

The MCP extracts `roles` from JWT and validates against `required_role`.

## Logging

The MCP logs comprehensive information on startup:
```
================================================================================
SQL MCP SERVER STARTING
================================================================================
Server Configuration: host=0.0.0.0 port=8003 transport=http
Authentication: auth_enabled=True tenant_id=da48a11d-...
RBAC Configuration: rbac_enabled=True check_role=False
Text-to-SQL Features: auto_value_matching=True table_discovery=True
Available Tools: tool_count=4 tools=['sql_query', 'list_tables', ...]
Database Connection: azure_sql_enabled=True server=your-server.database.windows.net
================================================================================
```

## Development

### Dev Mode
Set `dev_mode = true` in config.toml to use mock data without Azure resources.

### Testing
- `scripts/test_mcp.py` - Test MCP directly (tools, queries)
- `scripts/test_agent.py` - Test orchestrator end-to-end

### Project Structure
```
agentic_framework/
├── mcps/sql/           # SQL MCP server
├── orchestrator/       # Orchestrator service
├── shared/             # Shared utilities (auth, config, clients)
└── tests/              # Unit tests

scripts/
├── test_mcp.py         # MCP test
├── test_agent.py       # Orchestrator test
└── test_env/           # Test data and utilities
```

## Deployment

See `biceps/` for Azure infrastructure deployment (Container Apps, App Service, etc.)

## License

MIT

## Contributing

PRs welcome! Please ensure:
1. All config from `config.toml`, no hardcoded values
2. Comprehensive logging for debugging
3. Tests pass (`test_mcp.py`, `test_agent.py`)
