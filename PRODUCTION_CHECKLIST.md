# Production Readiness Checklist

## Status: In Progress

### ✅ Completed Items

1. **Config File Protection**
   - `config.toml` is in `.gitignore`
   - Created `config.toml.example` template without sensitive data
   - All Azure resource names, tenant IDs, endpoints are template values

2. **Value Matching Location**
   - ✅ Value matching logic IS inside MCP server (`agentic_framework/mcps/sql/server.py` lines 720-749)
   - ✅ Orchestrator only passes `value_mappings` array to MCP
   - ✅ MCP performs string replacement before query execution
   - ✅ Supports multi-word values, quoted/unquoted variants

3. **Config-Driven Architecture**
   - All settings come from `config.toml`
   - Falls back to environment variables
   - Uses `get_nested_config()` helper for TOML access
   - Added `rbac.check_role` and `rbac.required_role` to config

### 🔄 In Progress

4. **Authentication & Role Checking**
   - Current state:
     - JWT token validation exists (`auth_provider.py`)
     - Validates tenant ID from Azure AD
     - Validates token signature using JWKS
     - `bypass_token` flag for dev mode
   - **TODO**: Add role checking
     - Extract roles from JWT token claims (`roles` array)
     - Check if required role is present
     - Log access denied if role missing
     - Respect `rbac.enforcement_mode` (soft=log, hard=block)

5. **Better Logging**
   - Current MCP logging:
     - `logger.info("SQL TOOL START")` - logs query, accounts, value_mappings
     - `logger.info("Applying value mappings")` - logs each mapping applied
     - `logger.info("EXECUTING SQL QUERY")` - logs attempt number
     - `logger.info("SQL QUERY COMPLETE")` - logs duration, row count
   - **TODO**: Add to MCP startup
     - Log available tools with descriptions
     - Log server configuration (port, auth mode, RBAC settings)
     - Log connection to Azure SQL/Cosmos
   - **TODO**: Add to Orchestrator
     - Log discovered MCPs and their endpoints
     - Log available tools from each MCP
     - Log tool selection and routing decisions

### ⏳ Pending

6. **Simplify Test Suite**
   - **Current tests** (too many):
     - `test_value_mappings_mcp.py`
     - `test_value_mappings_curl.py`
     - `test_real_schema.py`
     - `test_complex_value_mappings.py`
     - `test_orchestrator_end_to_end.py`
     - `test_azure_connectivity.py`
     - Plus old deprecated tests
   - **Target: 2 essential tests**:
     1. `test_mcp.py` - Test MCP directly (list tools, execute sql_query, verify value_mappings)
     2. `test_agent.py` - Test orchestrator end-to-end (discover tools, execute 2-3 queries)
   - **Action**: Delete all others, create simple focused tests

7. **Remove Hardcoded Values**
   - **Audit needed** for:
     - Port numbers (use `mcp.base_port` from config)
     - URLs (use `mcp.endpoints` from config)
     - Deployment names (use `azure.openai.*` from config)
     - Database names (use `azure.sql.*` or `azure.fabric.*` from config)
     - Container names (use `azure.cosmos.containers.*` from config)
     - Magic numbers (e.g., max_unique_values_for_low_cardinality = 50 from config)
   - **Current hardcoded values found**:
     - `MCP_SERVER_PORT = int(os.getenv("MCP_PORT", "8003"))` - should use config
     - `DEFAULT_QUERY_LIMIT = 100` - OK (reasonable default)
     - `MAX_RETRY_ATTEMPTS = int(os.getenv("MCP_MAX_RETRIES", "3"))` - should use config

8. **Update Infrastructure Files**
   - **TODO**: Review `biceps/` deployment files
   - **TODO**: Remove graph MCP references from infra
   - **TODO**: Remove interpreter MCP references from infra
     - Add SQL MCP deployment (Container App or App Service)
     - Add orchestrator deployment
     - Ensure proper networking, environment variables
   - **TODO**: Add deployment documentation

9. **Update READMEs**
   - **Main README.md**: Update with:
     - Text-to-SQL focus (remove graph/interpreter)
     - value_mappings feature highlight
     - Architecture diagram (Orchestrator -> SQL MCP -> Azure SQL)
     - Quick start guide
     - Configuration guide
     - Deployment guide
   - **agentic_framework/mcps/sql/README.md**: Update with:
     - value_mappings parameter documentation
     - Tool descriptions (sql_query, list_tables, list_columns, get_schema)
     - Examples
   - **scripts/README.md**: Update test documentation

10. **Create New Repository**
    - **Name**: `text-to-sql`
    - **TODO**: Initialize new repo on GitHub/Azure DevOps
    - **TODO**: Push clean codebase
    - **TODO**: Set up branch protection
    - **TODO**: Add CI/CD pipelines

## Critical Fixes Needed

### 1. Authentication Flow
```python
# In auth_provider.py - add role checking function
async def check_user_role(payload: dict, required_role: str) -> bool:
    """Check if user has required role in JWT token."""
    settings = get_settings()

    if not settings.rbac.check_role:
        logger.info("Role checking disabled - allowing access")
        return True

    roles = payload.get('roles', [])
    if required_role in roles:
        logger.info("Role check passed", required_role=required_role, user_roles=roles)
        return True

    logger.warning("Role check failed", required_role=required_role, user_roles=roles)

    if settings.rbac.enforcement_mode == 'hard':
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Missing required role: {required_role}"
        )

    return False  # soft mode - log but allow
```

### 2. MCP Server Startup Logging
```python
# In server.py - add to startup
@mcp.on_startup()
async def on_startup():
    logger.info("=== SQL MCP SERVER STARTING ===")
    logger.info("Server configuration",
                port=MCP_SERVER_PORT,
                auth_enabled=not settings.bypass_token,
                rbac_enabled=settings.rbac.enabled,
                role_checking=settings.rbac.check_role)

    # Initialize clients
    await initialize_clients()

    # Log available tools
    tools = [
        {"name": "sql_query", "description": "Execute T-SQL queries with value mappings"},
        {"name": "list_tables", "description": "List available database tables"},
        {"name": "list_columns", "description": "List columns for a table"},
        {"name": "get_schema", "description": "Get detailed schema information"}
    ]
    logger.info("Available MCP tools", tool_count=len(tools), tools=[t["name"] for t in tools])

    logger.info("=== SQL MCP SERVER READY ===")
```

### 3. Orchestrator Logging
```python
# In orchestrator.py - enhance tool discovery logging
async def discover_tools(self):
    logger.info("=== DISCOVERING MCP TOOLS ===")
    logger.info("Configured MCPs", endpoints=list(self.settings.mcp_endpoints_dict.keys()))

    for mcp_name, endpoint in self.settings.mcp_endpoints_dict.items():
        logger.info(f"Discovering tools from {mcp_name}", endpoint=endpoint)
        tools = await self._fetch_tools(endpoint)
        logger.info(f"Discovered tools from {mcp_name}",
                   tool_count=len(tools),
                   tool_names=[t.name for t in tools])

    logger.info("=== TOOL DISCOVERY COMPLETE ===",
               total_tools=len(self.all_tools))
```

## Next Actions

1. Add role checking to auth_provider.py
2. Enhance MCP startup logging
3. Enhance orchestrator tool discovery logging
4. Create 2 simple test files (test_mcp.py, test_agent.py)
5. Delete redundant test files
6. Audit and remove hardcoded values
7. Update all READMEs
8. Review and update infrastructure files
9. Create new text-to-sql repository
10. Final testing and deployment
