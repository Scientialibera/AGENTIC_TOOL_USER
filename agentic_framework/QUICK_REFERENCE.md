# Quick Reference: Adding a New MCP

##  Checklist

```
[ ] 1. Create MCP server file
[ ] 2. Implement tools with @mcp.tool()
[ ] 3. Create MCP definition JSON
[ ] 4. Create tool definitions JSON
[ ] 5. Upload to Cosmos DB
[ ] 6. Update LIST_OF_MCPS in .env
[ ] 7. Start MCP server
[ ] 8. Restart orchestrator
[ ] 9. Test via /chat endpoint
[ ] 10. Verify via /mcps and /tools
```

##  Quick Start

### 1. Create MCP Server (5 minutes)

```python
# mcps/your_mcp.py
from fastmcp import FastMCP
from shared.config import get_settings

settings = get_settings()
mcp = FastMCP("Your MCP Server")

@mcp.tool()
async def your_tool(
    param: str,
    rbac_context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Tool description for AI."""
    if settings.dev_mode:
        return {"success": True, "data": "dummy"}
    
    # Your implementation here
    return {"success": True, "data": "result"}

if __name__ == "__main__":
    mcp.run(transport="http", port=8XXX)  # Pick unique port
```

### 2. Create Definitions (3 minutes)

**MCP Definition:**
```json
{
  "id": "your_mcp",
  "name": "Your MCP Server",
  "description": "What this MCP does",
  "endpoint": "http://localhost:8XXX/mcp",
  "transport": "http",
  "allowed_roles": ["sales_rep", "admin"],
  "tools": ["your_tool"],
  "enabled": true
}
```

**Tool Definition:**
```json
{
  "id": "your_tool",
  "name": "your_tool",
  "description": "What this tool does",
  "mcp_id": "your_mcp",
  "parameters": {
    "type": "object",
    "properties": {
      "param": {
        "type": "string",
        "description": "Parameter description"
      }
    },
    "required": ["param"]
  },
  "allowed_roles": ["sales_rep", "admin"]
}
```

### 3. Upload to Cosmos DB (2 minutes)

```python
# upload_your_mcp.py
import asyncio
import json
from shared.cosmos_client import CosmosDBClient
from shared.config import get_settings

async def upload():
    cosmos = CosmosDBClient(get_settings().cosmos)
    
    # Upload MCP
    with open("your_mcp_def.json") as f:
        await cosmos.upsert_item("mcp_definitions", json.load(f), "/id")
    
    # Upload tools
    with open("your_tools.json") as f:
        for tool in json.load(f):
            await cosmos.upsert_item("agent_functions", tool, "/mcp_id")
    
    await cosmos.close()

asyncio.run(upload())
```

### 4. Configure & Run (2 minutes)

```bash
# Update .env
echo "LIST_OF_MCPS=sql_mcp,graph_mcp,your_mcp" >> .env

# Start your MCP
python -m mcps.your_mcp

# Restart orchestrator
python -m orchestrator.app
```

### 5. Test (1 minute)

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "Use your new tool"}],
    "user_id": "test@example.com"
  }'
```

##  File Structure

```
agentic_framework/
 mcps/
    sql_server.py          # Existing
    graph_server.py         # Existing
    your_mcp.py            #  Your new MCP
 sample_data/
    your_mcp_def.json      #  MCP definition
    your_tools.json         #  Tool definitions
 upload_your_mcp.py          #  Upload script
```

##  Key Points

### Tool Function Signature
```python
async def tool_name(
    # Your parameters
    param1: str,
    param2: Optional[int] = None,
    # Always include this
    rbac_context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Clear description for the AI."""
    pass
```

### Always Return Success/Error
```python
# Success
return {"success": True, "data": [...], "count": 10}

# Error
return {"success": False, "error": "Error message"}
```

### Dev Mode Support
```python
if settings.dev_mode:
    return {"success": True, "data": "dummy_data"}

# Real implementation
```

### RBAC Integration
```python
# Extract user info from rbac_context
if rbac_context:
    rbac = RBACContext(**rbac_context)
    user_id = rbac.user_id
    roles = rbac.roles
```

##  Common Ports

- **8000** - Orchestrator
- **8001** - SQL MCP
- **8002** - Graph MCP
- **8003+** - Your custom MCPs

##  JSON Schema Types

```json
{
  "type": "string",        // Text
  "type": "integer",       // Number
  "type": "boolean",       // true/false
  "type": "array",         // List
  "type": "object",        // Dictionary
  "type": ["string", "null"]  // Optional
}
```

##  Tool Description Best Practices

 **Bad:**
```
"description": "Searches stuff"
```

 **Good:**
```
"description": "Search user's emails using natural language. Can filter by sender, date range, and subject. Returns email ID, subject, sender, date, and preview text."
```

##  Testing Workflow

```bash
# 1. Verify MCP discovered
curl http://localhost:8000/mcps | jq '.mcps[] | select(.id=="your_mcp")'

# 2. Verify tools loaded
curl http://localhost:8000/tools | jq '.tools[] | select(.mcp_id=="your_mcp")'

# 3. Test tool via chat
curl -X POST http://localhost:8000/chat -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "test your tool"}], "user_id": "test@example.com"}'

# 4. Check execution records
# Response will include execution_records showing tool calls
```

##  Troubleshooting

### MCP not appearing in /mcps
-  Check `LIST_OF_MCPS` in .env
-  Verify MCP definition uploaded to Cosmos DB
-  Check `enabled: true` in definition
-  Restart orchestrator

### Tool not available
-  Verify tool definition has correct `mcp_id`
-  Check tool is in MCP's `tools` array
-  Verify user's role in `allowed_roles`

### Tool not called by AI
-  Improve tool description (be specific!)
-  Add examples in description
-  Check parameter descriptions
-  Verify JSON schema is valid

### Connection refused
-  Check MCP server is running
-  Verify port number in definition matches server
-  Check no other service using that port

##  Examples

### Simple Tool
```python
@mcp.tool()
async def get_weather(city: str) -> Dict[str, Any]:
    """Get current weather for a city."""
    return {"success": True, "temperature": 72, "condition": "sunny"}
```

### Tool with Multiple Parameters
```python
@mcp.tool()
async def search_data(
    query: str,
    limit: int = 10,
    include_archived: bool = False,
    rbac_context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Search data with filters."""
    return {"success": True, "results": [...], "count": 5}
```

### Tool with Array Parameters
```python
@mcp.tool()
async def batch_process(
    items: List[str],
    action: str,
    rbac_context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Process multiple items."""
    return {"success": True, "processed": len(items)}
```

##  Speed Tips

1. **Use Templates**: Copy existing MCP as starting point
2. **Test Locally**: Use dev_mode first
3. **Iterate Fast**: Start simple, add complexity
4. **Clear Descriptions**: The AI needs good docs
5. **Error Handling**: Always return success/error

##  Learn By Example

Study existing MCPs:
- `mcps/sql_server.py` - Complex with LLM query generation
- `mcps/graph_server.py` - Multi-step processing
- README example - Simple Email MCP

##  Pro Tips

1. **Tool Naming**: Use verb_noun format (`search_emails`, `send_message`)
2. **Return Structure**: Always include `success` boolean
3. **Dev Mode**: Always implement dummy data
4. **Logging**: Use structlog for context
5. **Type Hints**: Helps with validation
6. **Docstrings**: The AI reads these!

##  Full Documentation

- [README.md](README.md) - Complete Email MCP example
- [UNIFIED_SERVICE.md](UNIFIED_SERVICE.md) - History tracking
- [IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md) - Technical details

---

**Time to create new MCP:** ~15 minutes  
**Time to test and verify:** ~5 minutes  
**Total time:** ~20 minutes

Happy building! 
