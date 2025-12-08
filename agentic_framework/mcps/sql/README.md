# SQL MCP Server - Automatic Value Matching

FastMCP server that executes T-SQL queries against Azure SQL with automatic value matching for low-cardinality columns.

## Features

- **4 Tools**: `sql_query`, `list_tables`, `list_columns`, `get_schema`
- **Automatic Value Matching**: Corrects casing automatically using Cosmos DB cache
- **Safety**: SELECT-only queries, automatic TOP injection
- **Auth**: Optional JWT validation with Azure AD
- **RBAC**: Optional role-based access control
- **Logging**: Comprehensive startup and query logging

## How It Works

### Automatic Value Matching

The MCP loads value mappings from Cosmos DB on startup and automatically corrects values in queries:

```python
# Input query (from orchestrator):
SELECT * FROM Opportunity WHERE StageName = 'closed won'

# MCP auto-corrects to:
SELECT * FROM Opportunity WHERE StageName = 'Closed Won'

# Then executes against Azure SQL
```

The value matching cache (`_value_mappings_cache`) contains exact database values for low-cardinality columns. The MCP tries multiple variants (lowercase, title case) and replaces them with exact matches.

## API

### sql_query

Execute T-SQL SELECT query with automatic value matching.

**Parameters:**
- `query` (required): T-SQL SELECT statement
- `limit` (optional): Max rows to return (default: 100)

**Returns:**
```json
{
  "success": true,
  "query": "SELECT TOP 5 ...",
  "row_count": 5,
  "data": [...],
  "source": "azure_sql"
}
```

### list_tables

List all available tables from schema cache.

**Returns:**
```json
{
  "success": true,
  "tables": ["Account", "Opportunity", "Contact", ...]
}
```

### list_columns

List columns for a specific table.

**Parameters:**
- `table` (required): Table name

**Returns:**
```json
{
  "success": true,
  "table": "Opportunity",
  "columns": [
    {"name": "Id", "type": "uniqueidentifier"},
    {"name": "Name", "type": "nvarchar"},
    ...
  ]
}
```

### get_schema

Get complete schema information for all tables.

**Returns:**
```json
{
  "success": true,
  "schema": "Table: Account...",
  "tables": {
    "Account": [...],
    "Opportunity": [...]
  }
}
```

## Configuration

All settings from `config.toml`:

```toml
[mcp]
base_port = 8000  # SQL MCP will use base_port + 3 = 8003

[text_to_sql]
enable_value_matching = true  # Enable automatic value correction
max_retry_attempts = 3  # Retry failed queries

[azure.sql]
enabled = true
server = "your-server.database.windows.net"
database = "your-database"
authentication = "azure_ad"

[rbac]
check_role = false  # Set true to enforce role checking
required_role = "mcp:READ"  # Required role if check_role = true
enforcement_mode = "soft"  # soft = log only, hard = block
```

## Running

```bash
python -m agentic_framework.mcps.sql.server
```

**Startup logs:**
```
================================================================================
SQL MCP SERVER STARTING
================================================================================
Server Configuration: host=0.0.0.0 port=8003 transport=http
Authentication: auth_enabled=True tenant_id=...
RBAC Configuration: rbac_enabled=True check_role=False
Text-to-SQL Features: auto_value_matching=True
Available Tools: tool_count=4 tools=['sql_query', 'list_tables', ...]
Database Connection: azure_sql_enabled=True server=...
================================================================================
```

## Testing

```bash
# Test MCP directly
python scripts/test_mcp.py
```

## Cosmos DB Dependencies

Required containers:
- `sql_schema`: Table/column metadata
- `value_mappings`: Low-cardinality value mappings
- `table_metadata`: Table descriptions with embeddings (optional)
- `agent_functions`: Tool definitions
- `prompts`: System prompts

Upload to Cosmos:
```bash
python scripts/test_env/upload_artifacts.py
```

## Authentication

When `bypass_token = false`:
1. Validates JWT from `Authorization: Bearer <token>` header
2. Checks token signature using Azure AD JWKS
3. Validates issuer matches tenant ID
4. Optionally checks user roles (if `rbac.check_role = true`)

## Troubleshooting

**Port already in use:**
```powershell
Get-NetTCPConnection -LocalPort 8003 | Select OwningProcess
Stop-Process -Id <pid>
```

**Query fails:**
- Check Azure SQL permissions
- Verify table/column names match schema
- Check logs for exact error message

**Value matching not working:**
- Verify `text_to_sql.enable_value_matching = true`
- Check `value_mappings` container in Cosmos DB has data
- Review MCP startup logs for cache loading
