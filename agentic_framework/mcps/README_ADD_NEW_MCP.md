# How to Add a New MCP (Model Context Protocol Server)

This guide shows you how to add a new MCP to the framework in **5 simple steps**. The orchestrator automatically discovers and uses your MCP - no code changes needed!

## 🚀 Quick Start (5 Steps)

### Step 1: Create MCP from Template
```bash
# From agentic_framework/mcps/
cp TEMPLATE_MCP.py <your_mcp_name>/server.py
```

### Step 2: Customize the MCP
Open `<your_mcp_name>/server.py` and update:

```python
# 1. Update constants (lines 20-24)
MCP_SERVER_NAME = "Weather MCP Server"  # Human-readable name
AGENT_TYPE = "weather"                  # Prefix for Cosmos DB lookups
PROMPT_ID = "weather_agent_system"      # System prompt ID
DEFAULT_QUERY_LIMIT = 50                # Default result limit
PORT = 8003                             # Unique port number

# 2. Add any custom clients (line 60)
weather_client: Optional[WeatherClient] = None

# 3. Initialize custom clients (line 75)
if weather_client is None:
    weather_client = WeatherClient(settings.weather_api_key)

# 4. Implement your tool logic (lines 185-280)
@mcp.tool()
async def weather_query(query: str, ...):
    # Your implementation here
    pass

# 5. Add dummy data for dev mode (line 282)
def _get_dummy_data(query: str, limit: int = 100):
    return [{"location": "Seattle", "temp": 72, "conditions": "Sunny"}]
```

### Step 3: Upload Cosmos DB Artifacts

Create and upload to Cosmos DB:

**A. System Prompt** (`scripts/assets/prompts/weather_agent_system.md`):
```markdown
# Weather Query Agent

You are a weather data assistant. Generate weather API queries based on user requests.

## Available Tools
- get_weather: Fetch current weather conditions

## Instructions
1. Parse the user's location and time requirements
2. Call get_weather with appropriate parameters
3. Format results clearly for the user
```

**B. Tool Definition** (`scripts/assets/functions/tools/weather_query_function.json`):
```json
{
  "id": "weather_query_function",
  "mcp_id": "weather_mcp",
  "name": "get_weather",
  "description": "Get current weather conditions for a location",
  "parameters": {
    "type": "object",
    "properties": {
      "location": {
        "type": "string",
        "description": "City name or coordinates"
      },
      "units": {
        "type": "string",
        "enum": ["celsius", "fahrenheit"],
        "description": "Temperature units"
      }
    },
    "required": ["location"]
  },
  "allowed_roles": ["sales_rep", "admin"]
}
```

**Upload to Cosmos DB:**
```bash
# From agentic_framework/
python scripts/test_env/init_data.py
```

### Step 4: Add MCP Endpoint to Environment

Update `.env` in repository root:
```bash
MCP_ENDPOINTS={"sql_mcp": "http://localhost:8001/mcp", "graph_mcp": "http://localhost:8002/mcp", "weather_mcp": "http://localhost:8003/mcp"}
```

**Format:** JSON dictionary mapping MCP ID to endpoint URL

### Step 5: Start Your MCP Server

```bash
# From agentic_framework/
python -m mcps.weather.server
```

**That's it!** The orchestrator automatically:
- Discovers your MCP from `MCP_ENDPOINTS`
- Loads tool definitions from Cosmos DB
- Routes requests to your MCP
- Aggregates results

---

## 📋 Checklist

- [ ] Created `mcps/<name>/server.py` from template
- [ ] Updated MCP constants (name, agent_type, prompt_id, port)
- [ ] Implemented tool logic and dummy data
- [ ] Created system prompt in `scripts/assets/prompts/<agent_type>_agent_system.md`
- [ ] Created tool definition in `scripts/assets/functions/tools/<agent_type>_*_function.json`
- [ ] Uploaded artifacts: `python scripts/test_env/init_data.py`
- [ ] Added MCP endpoint to `.env` MCP_ENDPOINTS
- [ ] Started MCP server: `python -m mcps.<name>.server`
- [ ] Tested: `curl http://localhost:<port>/mcp/tools`

---

## 🔍 How It Works

### Discovery Flow
```
1. Orchestrator reads MCP_ENDPOINTS from .env
2. On startup, orchestrator calls /mcp/tools for each endpoint
3. Tools are cached in memory
4. User query → Orchestrator plans → Routes to MCP → Executes
```

### File Structure
```
mcps/
├── TEMPLATE_MCP.py          # Copy this to create new MCP
├── README_ADD_NEW_MCP.md    # This guide
├── sql/
│   └── server.py            # SQL MCP example
├── graph/
│   └── server.py            # Graph MCP example
└── weather/                 # Your new MCP
    └── server.py            # Created from template
```

### Cosmos DB Schema
```
prompts container:
  - id: "<agent_type>_agent_system"
  - content: "System prompt markdown..."

agent_functions container:
  - id: "<agent_type>_query_function"
  - mcp_id: "<agent_type>_mcp"
  - name: "tool_name"
  - description: "..."
  - parameters: {...}
  - allowed_roles: [...]
```

---

## 🎯 Zero Orchestrator Changes

**The orchestrator is 100% generic!** It:
- ✅ Reads MCPs from environment variable
- ✅ Discovers tools via HTTP `/mcp/tools` endpoint
- ✅ Caches everything on startup
- ✅ Routes based on tool name → MCP mapping
- ✅ No hardcoded MCP references

**You only need to:**
1. Create MCP from template
2. Upload artifacts to Cosmos DB
3. Add endpoint to `.env`

---

## 🛠️ Advanced Customization

### Add Custom Client
```python
# In your MCP server.py
from my_package import MyCustomClient

# Add to globals (line 60)
my_client: Optional[MyCustomClient] = None

# Initialize in initialize_clients() (line 75)
if my_client is None:
    my_client = MyCustomClient(settings.my_api_key)

# Use in your tool
async def my_tool(...):
    await initialize_clients()
    result = await my_client.query(...)
```

### Add Schema/Config Cache
```python
# Add to globals
_my_schema_cache: Optional[str] = None

# Create loader function
async def get_my_schema() -> str:
    global _my_schema_cache
    if _my_schema_cache is None:
        # Load from Cosmos or API
        _my_schema_cache = await load_schema()
    return _my_schema_cache

# Use in your tool
schema = await get_my_schema()
```

### Multiple Tools per MCP
```python
@mcp.tool()
async def tool_one(...):
    # Implementation
    pass

@mcp.tool()
async def tool_two(...):
    # Implementation
    pass
```

Upload multiple tool definitions with same `mcp_id`:
- `weather_current_function.json` → mcp_id: "weather_mcp"
- `weather_forecast_function.json` → mcp_id: "weather_mcp"

---

## 🧪 Testing Your MCP

### 1. Test MCP Directly
```bash
# Check tools endpoint
curl http://localhost:8003/mcp/tools

# Test tool call
curl -X POST http://localhost:8003/mcp \
  -H "Content-Type: application/json" \
  -d '{"method": "tools/call", "params": {"name": "weather_query", "arguments": {"query": "weather in Seattle"}}}'
```

### 2. Test via Orchestrator
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "What is the weather in Seattle?"}],
    "user_id": "test@example.com"
  }'
```

### 3. Check Logs
Look for:
- `✅ MCPs discovered and cached` (orchestrator startup)
- `✅ All tools loaded and cached` (orchestrator startup)
- `⚙️ CALLING MCP TOOL` (orchestrator → MCP)
- `📊 <YOUR_TYPE> TOOL START` (your MCP)
- `✅ <YOUR_TYPE> TOOL COMPLETE` (your MCP)

---

## 💡 Tips

1. **Start with template** - Don't write from scratch
2. **Use dev mode** - Test with dummy data first (`DEV_MODE=true`)
3. **Follow naming convention** - `<type>_agent_system` for prompts, `<type>_*_function` for tools
4. **Test incrementally** - Test MCP alone, then via orchestrator
5. **Check caching** - Look for "cache miss" vs "cached" in logs
6. **Port numbers** - Use sequential ports: 8001, 8002, 8003, etc.

---

## 📚 Examples

See existing MCPs for reference:
- **SQL MCP**: `mcps/sql/server.py` - Database queries with LLM-generated SQL
- **Graph MCP**: `mcps/graph/server.py` - Graph traversal with Gremlin

Both follow the exact same template pattern!
