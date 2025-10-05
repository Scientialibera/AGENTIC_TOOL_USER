# Agentic Framework with FastMCP

A production-ready, RBAC-enabled multi-agent framework using FastMCP for orchestration. The framework features dynamic MCP discovery, automated deployment, and specialized agents for SQL, Graph, and Code Interpreter operations.

## Architecture

```
                    Orchestrator Agent (Port 8000)               
  ┌──────────────────────────────────────────────────────────────┐
  │ - Dynamic MCP discovery from environment config              │
  │ - Loads tool definitions with RBAC filtering                 │
  │ - Uses Azure OpenAI for planning and execution               │
  │ - Multi-round conversations with tool chaining               │
  │ - Full conversation tracking and caching                     │
  └──────────────────────────────────────────────────────────────┘
                              │
           ┌──────────────────┼──────────────────┬──────────────────┐
           │                  │                  │                  │
     SQL MCP Server     Graph MCP Server   Interpreter MCP    (Extensible)
     (Port 8001)        (Port 8002)        (Port 8003)        
     ┌──────────┐       ┌──────────┐       ┌──────────┐
     │ SQL      │       │ Graph    │       │ Code     │
     │ Queries  │       │ Queries  │       │ Exec     │
     │ Fabric   │       │ Gremlin  │       │ Azure    │
     │ Account  │       │ Account  │       │ Asst     │
     │ Resolver │       │ Resolver │       │ Math     │
     └──────────┘       └──────────┘       └──────────┘
```

## Key Features

### 1. **Dynamic MCP Discovery & Deployment**
- **Automatic Discovery**: Scans `mcps/` folder for any subfolder with `Dockerfile` or `server.py`
- **Port Auto-Assignment**: Sequential port allocation (8001, 8002, 8003, etc.)
- **Zero Configuration**: Add new MCP by creating folder - deployment scripts handle the rest
- **Environment Generation**: Automatically builds `MCP_ENDPOINTS` JSON and `LIST_OF_MCPS` CSV

### 2. **Three Specialized MCP Servers**

#### SQL MCP (Port 8001)
- Natural language → SQL query generation
- Microsoft Fabric SQL endpoint integration
- Salesforce data querying
- Account name resolution with fuzzy matching
- Dev mode with realistic sample data

#### Graph MCP (Port 8002)
- Natural language → Gremlin query generation  
- Azure Cosmos DB Gremlin API integration
- Relationship traversal and pattern matching
- Account context resolution
- Dev mode with sample graph data

#### Interpreter MCP (Port 8003)
- Code execution via Azure OpenAI Assistants API
- Sandboxed Python environment
- Mathematical calculations and data analysis
- Statistics, CAGR, financial formulas
- Result formatting with execution time tracking

### 3. **Multi-Tool Orchestration**
- **Tool Chaining**: Single query triggers multiple MCPs
- **Example Queries**:
  - "Get Microsoft sales and calculate revenue per employee" → SQL + Interpreter
  - "Get AI chatbot SOWs and calculate average revenue" → Graph + Interpreter
  - "Top 3 accounts and their percentage of total" → SQL + Interpreter (multi-step)
- **Tool Lineage Tracking**: Full execution trace for debugging
- **Automatic Routing**: LLM determines which MCP to call based on intent

### 4. **Role-Based Access Control (RBAC)**
- User-specific tool and MCP filtering
- Row-level security via SQL WHERE clause injection
- Graph query scoping by user context
- RBAC config stored in Cosmos DB
- Dev mode bypasses RBAC for testing

### 5. **Account Resolution**
- **Fuzzy Matching**: Levenshtein distance algorithm
- **Handles Variations**: "MSFT" → "Microsoft Corporation", "Google" → "Google LLC"
- **Shared Service**: Used by both SQL and Graph MCPs
- **Dev Mode Data**: 5 predefined accounts (Microsoft, Salesforce, Google, AWS, SAP)

### 6. **Conversation Tracking & Caching**
- **Full History**: All user messages and assistant responses
- **Execution Metadata**: Tool calls, arguments, results, timing
- **User Feedback**: Star ratings and comments per turn
- **Query Caching**: Automatic caching of SQL/Graph results with TTL
- **Storage**: Cosmos DB `unified_data` container

### 7. **Dev Mode**
- **Realistic Dummy Data**: Complete sample datasets for all MCPs
- **No Dependencies**: Runs without Fabric, Gremlin, or Assistants API
- **Perfect for Testing**: Local development, CI/CD, demos
- **Enable**: Set `FRAMEWORK_DEV_MODE=true`

### 8. **Automated Deployment**
- **Azure Container Apps**: One-command deployment with `deploy.ps1`
- **Local Development**: `start-local.ps1` with port conflict detection
- **Docker Automation**: Image building and ACR push
- **Dynamic Configuration**: MCP endpoints auto-configured

### 9. **Modern React Frontend**
- **Chat Interface**: Clean, responsive UI
- **Tool Lineage Visualization**: Expandable cards showing MCP calls
- **Code Interpreter Display**: Syntax-highlighted Python code with execution results
- **MCP-Specific Badges**: Color-coded badges for SQL (blue), Graph (orange), Interpreter (green)
- **Execution Metrics**: Round count, MCPs used, execution time

## Project Structure

```
agentic_framework/
├─ orchestrator/
│   ├─ app.py                    # FastAPI server with /chat, /mcps, /tools endpoints
│   ├─ discovery_service.py      # Dynamic MCP discovery from environment
│   └─ orchestrator.py           # Main orchestration agent with Azure OpenAI
├─ mcps/
│   ├─ sql/
│   │   ├─ server.py            # SQL MCP: Natural language → SQL
│   │   ├─ Dockerfile           # Containerization
│   │   └─ README.md            # SQL MCP documentation
│   ├─ graph/
│   │   ├─ server.py            # Graph MCP: Natural language → Gremlin
│   │   ├─ Dockerfile
│   │   └─ README.md            # Graph MCP documentation
│   └─ interpreter/
│       ├─ server.py            # Interpreter MCP: Code execution via Assistants
│       ├─ Dockerfile
│       └─ README.md            # Interpreter MCP documentation
├─ shared/
│   ├─ config.py                # Settings from environment variables
│   ├─ models.py                # Pydantic models for API contracts
│   ├─ aoai_client.py           # Azure OpenAI client wrapper
│   ├─ cosmos_client.py         # Cosmos DB client
│   ├─ fabric_client.py         # Microsoft Fabric SQL client
│   ├─ gremlin_client.py        # Gremlin/Cosmos DB graph client
│   └─ account_resolver.py      # Fuzzy account name matching
├─ deploy/
│   ├─ deploy.ps1               # Main deployment wrapper
│   ├─ deploy-aca.ps1           # Azure Container Apps deployment (dynamic MCP discovery)
│   ├─ start-local.ps1          # Automated local startup with port management
│   ├─ show-local-commands.ps1  # Display manual startup commands
│   └─ README_DEPLOYMENT.md     # Deployment documentation
├─ frontend/
│   ├─ src/
│   │   ├─ App.js               # React chat interface with lineage visualization
│   │   └─ App.css              # Styles with code interpreter support
│   ├─ server.js                # Express server for login/proxy
│   ├─ Dockerfile               # Frontend containerization
│   └─ package.json
├─ tests/
│   ├─ test_orchestrator.py              # Basic SQL/Graph tests
│   ├─ test_orchestrator_interpreter.py  # Code interpreter tests (4 tests)
│   └─ test_orchestrator_multitool.py    # Multi-MCP chain tests (4 tests)
└─ requirements.txt              # Python dependencies
```

## Quick Start

### Prerequisites
- Python 3.10+
- Node.js 18+ (for frontend)
- Azure subscription
- Azure OpenAI deployment
- (Optional) Microsoft Fabric workspace
- (Optional) Cosmos DB with Gremlin API

### 1. Install Dependencies

```powershell
cd agentic_framework
pip install -r requirements.txt
```

### 2. Configure Environment

Copy `.env.example` to `.env` and configure:

```bash
# Framework Settings
FRAMEWORK_DEV_MODE=true          # Use dummy data for testing
FRAMEWORK_DEBUG=true
LIST_OF_MCPS=sql_mcp,graph_mcp,interpreter_mcp  # Auto-generated by deploy scripts

# Azure OpenAI
AOAI_ENDPOINT=https://your-instance.openai.azure.com
AOAI_API_KEY=your-key-or-use-managed-identity
AOAI_CHAT_DEPLOYMENT=gpt-4o
AOAI_EMBEDDING_DEPLOYMENT=text-embedding-ada-002

# Azure OpenAI Assistants (for Interpreter MCP)
AZURE_OPENAI_ASSISTANTS_ENDPOINT=https://your-instance.openai.azure.com
AZURE_OPENAI_ASSISTANTS_API_KEY=your-key
AZURE_OPENAI_ASSISTANTS_DEPLOYMENT=gpt-4o
AZURE_OPENAI_ASSISTANTS_API_VERSION=2024-05-01-preview

# Cosmos DB (optional in dev mode)
COSMOS_ENDPOINT=https://your-cosmos.documents.azure.com:443/
COSMOS_DATABASE_NAME=agentic_db

# Fabric SQL (optional in dev mode)
FABRIC_SQL_ENDPOINT=your-endpoint.datawarehouse.fabric.microsoft.com
FABRIC_DATABASE=your_lakehouse

# Gremlin (optional in dev mode)
AZURE_COSMOS_GREMLIN_ENDPOINT=wss://your-cosmos.gremlin.cosmos.azure.com:443/
```

### 3. Start All Services Locally

**Option A: Automated Startup (Recommended)**
```powershell
cd deploy
.\start-local.ps1
```

This will:
- Discover all MCPs in `mcps/` folder
- Check for port conflicts
- Start each MCP in separate PowerShell window
- Start orchestrator with auto-configured endpoints
- Display service URLs and test commands

**Option B: Manual Startup**
```powershell
# Terminal 1: SQL MCP
cd agentic_framework
python -c "import os; os.environ['FASTMCP_HOST']='0.0.0.0'; os.environ['FASTMCP_PORT']='8001'; exec(open('mcps/sql/server.py').read())"

# Terminal 2: Graph MCP
python -c "import os; os.environ['FASTMCP_HOST']='0.0.0.0'; os.environ['FASTMCP_PORT']='8002'; exec(open('mcps/graph/server.py').read())"

# Terminal 3: Interpreter MCP
python -c "import os; os.environ['FASTMCP_HOST']='0.0.0.0'; os.environ['FASTMCP_PORT']='8003'; exec(open('mcps/interpreter/server.py').read())"

# Terminal 4: Orchestrator
$env:MCP_ENDPOINTS='{"sql_mcp": "http://localhost:8001/mcp", "graph_mcp": "http://localhost:8002/mcp", "interpreter_mcp": "http://localhost:8003/mcp"}'
$env:LIST_OF_MCPS='sql_mcp,graph_mcp,interpreter_mcp'
python -m orchestrator.app
```

### 4. Test the Framework

```powershell
# Health check
Invoke-RestMethod http://localhost:8000/healthz

# List available MCPs
Invoke-RestMethod http://localhost:8000/mcps

# List available tools
Invoke-RestMethod http://localhost:8000/tools

# Run comprehensive tests
python tests\test_orchestrator_interpreter.py      # Code interpreter tests
python tests\test_orchestrator_multitool.py        # Multi-tool orchestration tests
```

### 5. Start Frontend (Optional)

```powershell
cd frontend
npm install
npm start
```

Visit http://localhost:3000 to access the chat interface.

## Example Queries

### Single-Tool Queries

**SQL MCP:**
```
"Show me all contacts at Microsoft"
"Find opportunities over $100,000"
"List accounts in the technology sector"
```

**Graph MCP:**
```
"Show me relationships for Salesforce account"
"Find companies connected to Microsoft"
"What are the related accounts for Google?"
```

**Interpreter MCP:**
```
"Calculate 157 * 234 + 891"
"What's the CAGR from $100K to $250K over 5 years?"
"Calculate monthly revenue statistics for [45000, 52000, 61000, 58000, 63000, 77000]"
```

### Multi-Tool Queries (Requires Multiple MCPs)

**SQL + Interpreter:**
```
"Get all sales to Microsoft and calculate revenue per employee if we have 10 employees"
"Show top 3 accounts by revenue and calculate what percentage each represents"
"Find opportunities for Google and if we closed $1M in 2020 growing to $3M by 2025, what's the CAGR?"
```

**Graph + Interpreter:**
```
"Get all SOWs for ai_chatbot and calculate average revenue per SOW"
"Find connected accounts for Microsoft and calculate total relationship value"
```

## API Endpoints

### Orchestrator (Port 8000)

#### `POST /chat`
Process user query with orchestrator.

**Request:**
```json
{
  "messages": [
    {"role": "user", "content": "Get Microsoft sales and calculate revenue per employee"}
  ],
  "user_id": "user@example.com",
  "session_id": "optional-session-id",
  "metadata": {}
}
```

**Response:**
```json
{
  "session_id": "abc-123",
  "response": "Microsoft has $5M in sales. With 10 employees, that's $500K per employee.",
  "success": true,
  "rounds": 3,
  "mcps_used": ["sql_mcp", "interpreter_mcp"],
  "tool_lineage": [
    {
      "step": 1,
      "tool_name": "sql_query",
      "mcp_server": "sql_mcp",
      "input": {"query": "Get sales for Microsoft"},
      "result_summary": "Retrieved 10 rows",
      "output": {"success": true, "data": [...]},
      "timestamp": "2025-10-05T10:00:00Z"
    },
    {
      "step": 2,
      "tool_name": "interpreter_agent",
      "mcp_server": "interpreter_mcp",
      "input": {"query": "Calculate $5M / 10 employees"},
      "result_summary": "Success",
      "output": {
        "success": true,
        "code": "total = 5000000\nemployees = 10\nrevenue_per_employee = total / employees",
        "result": "500000.0",
        "execution_time_ms": 3245
      },
      "timestamp": "2025-10-05T10:00:15Z"
    }
  ],
  "metadata": {
    "execution_time_ms": 18500,
    "timestamp": "2025-10-05T10:00:18Z"
  }
}
```

#### `GET /mcps`
List all available MCPs for the current user (RBAC-filtered).

#### `GET /tools`
List all available tools, optionally filtered by `mcp_id` query parameter.

#### `GET /healthz`
Health check endpoint.

#### `GET /sessions`
List all chat sessions for user.

#### `GET /sessions/{session_id}`
Get full conversation history for a session.

#### `POST /feedback`
Submit feedback for a conversation turn.

## Deployment to Azure

### Deploy All Services

```powershell
cd deploy
.\deploy.ps1
```

This will:
1. Discover all MCPs by scanning `mcps/` folder
2. Build Docker images for each MCP + orchestrator + frontend
3. Push images to Azure Container Registry
4. Deploy to Azure Container Apps with auto-configured networking
5. Set up environment variables and secrets
6. Display service URLs

### What Gets Deployed

- **Orchestrator**: Main API endpoint
- **SQL MCP**: Containerized on unique internal port
- **Graph MCP**: Containerized on unique internal port
- **Interpreter MCP**: Containerized on unique internal port
- **Frontend**: React chat interface
- **Networking**: MCPs communicate via internal Azure Container Apps network

### Environment Configuration

The deployment script automatically:
- Assigns sequential ports (8001, 8002, 8003)
- Generates `MCP_ENDPOINTS` JSON mapping
- Creates `LIST_OF_MCPS` comma-separated list
- Configures orchestrator environment variables
- Sets up MCP-to-MCP communication

## Adding a New MCP

Adding a new MCP is simple - the framework automatically discovers and deploys it!

### Step 1: Create MCP Folder

```powershell
cd agentic_framework/mcps
mkdir weather
cd weather
```

### Step 2: Create server.py

```python
"""
Weather MCP Server - Provides weather data and forecasts.
"""
from typing import Dict, Any, Optional
from fastmcp import FastMCP
import structlog

from shared.config import get_settings

logger = structlog.get_logger(__name__)
settings = get_settings()

MCP_SERVER_NAME = "weather_mcp"
MCP_SERVER_PORT = 8004  # Port assigned by deployment script
HOST = "0.0.0.0"
TRANSPORT = "http"

mcp = FastMCP(MCP_SERVER_NAME)


@mcp.tool()
async def get_weather(
    location: str,
    units: str = "fahrenheit",
    rbac_context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Get current weather for a location.
    
    Args:
        location: City name or coordinates
        units: Temperature units (fahrenheit/celsius)
        rbac_context: User RBAC context
        
    Returns:
        Weather data including temperature, conditions, etc.
    """
    try:
        logger.info("Getting weather", location=location)
        
        if settings.dev_mode:
            return {
                "success": True,
                "location": location,
                "temperature": 72,
                "conditions": "Partly Cloudy",
                "humidity": 65,
                "wind_speed": 8
            }
        
        # Production: Call weather API
        # weather_client = WeatherClient(settings.weather_api_key)
        # data = await weather_client.get_current(location, units)
        
        return {"success": True, "location": location, "temperature": 72}
        
    except Exception as e:
        logger.error("Weather fetch failed", error=str(e))
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    import os
    logger.info(f"Starting {MCP_SERVER_NAME} on {HOST}:{MCP_SERVER_PORT}")
    os.environ["FASTMCP_HOST"] = HOST
    os.environ["FASTMCP_PORT"] = str(MCP_SERVER_PORT)
    mcp.run(transport=TRANSPORT)
```

### Step 3: Create Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Copy shared dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared modules
COPY shared/ ./shared/

# Copy this MCP
COPY mcps/weather/ ./mcps/weather/

# Set Python path
ENV PYTHONPATH=/app

CMD ["python", "mcps/weather/server.py"]
```

### Step 4: Deploy!

That's it! The deployment scripts will automatically:

```powershell
# Local testing
cd deploy
.\start-local.ps1  # Discovers weather/ folder, assigns port 8004

# Azure deployment
.\deploy.ps1  # Builds weather MCP image, deploys to ACA
```

No configuration changes needed! The scripts:
- Find `weather/` folder with `server.py`
- Assign it port 8004
- Add `weather_mcp:http://localhost:8004/mcp` to `MCP_ENDPOINTS`
- Add `weather_mcp` to `LIST_OF_MCPS`
- Build and deploy Docker image

### Testing New MCP

```powershell
# Test directly
Invoke-RestMethod -Uri http://localhost:8004/mcp -Method POST -Body '{"method":"tools/list"}' -ContentType 'application/json'

# Test via orchestrator
$body = @{
    messages = @(@{ role = "user"; content = "What's the weather in Seattle?" })
    user_id = "test@example.com"
} | ConvertTo-Json

Invoke-RestMethod -Uri http://localhost:8000/chat -Method POST -Body $body -ContentType 'application/json'
```

## MCP Development Guidelines

### Tool Definition Best Practices

```python
@mcp.tool()
async def my_tool(
    required_param: str,
    optional_param: Optional[int] = 10,
    rbac_context: Optional[Dict[str, Any]] = None  # Always include for RBAC
) -> Dict[str, Any]:
    """
    Clear description of what the tool does.
    
    Args:
        required_param: Description of required parameter
        optional_param: Description of optional parameter with default
        rbac_context: User RBAC context (automatically injected)
        
    Returns:
        Dictionary with 'success' boolean and result data
    """
    try:
        # Check dev mode
        if settings.dev_mode:
            return {"success": True, "data": "dummy data"}
        
        # Production logic
        result = await do_something(required_param, optional_param)
        
        return {"success": True, "data": result}
        
    except Exception as e:
        logger.error("Tool execution failed", error=str(e))
        return {"success": False, "error": str(e)}
```

### Key Requirements

1. **RBAC Context**: Always include `rbac_context` parameter
2. **Dev Mode Support**: Provide dummy data when `settings.dev_mode=true`
3. **Error Handling**: Return `{"success": false, "error": "..."}` on failure
4. **Type Hints**: Use proper type annotations for all parameters
5. **Docstrings**: Clear descriptions for LLM to understand tool purpose
6. **Logging**: Use structlog for structured logging

## Testing

### Run All Tests

```powershell
# Code interpreter tests (4 tests)
python tests\test_orchestrator_interpreter.py

# Multi-tool orchestration tests (4 tests)
python tests\test_orchestrator_multitool.py

# Basic orchestrator tests
python tests\test_orchestrator.py
```

### Test Coverage

**Interpreter Tests:**
- Simple math calculation
- Revenue per employee calculation
- Monthly revenue statistics
- CAGR calculation

**Multi-Tool Tests:**
- Microsoft sales + revenue per employee (SQL + Interpreter)
- AI chatbot SOWs + average revenue (Graph + Interpreter)
- Google opportunities + CAGR (SQL + Interpreter)
- Top 3 accounts + percentages (SQL + multiple Interpreter calls)

### Manual Testing

```powershell
# Test SQL MCP
$body = @{ messages = @(@{ role = "user"; content = "Show contacts at Microsoft" }) } | ConvertTo-Json
Invoke-RestMethod -Uri http://localhost:8000/chat -Method POST -Body $body -ContentType 'application/json'

# Test Graph MCP
$body = @{ messages = @(@{ role = "user"; content = "Show relationships for Salesforce" }) } | ConvertTo-Json
Invoke-RestMethod -Uri http://localhost:8000/chat -Method POST -Body $body -ContentType 'application/json'

# Test Interpreter MCP
$body = @{ messages = @(@{ role = "user"; content = "Calculate 157 * 234 + 891" }) } | ConvertTo-Json
Invoke-RestMethod -Uri http://localhost:8000/chat -Method POST -Body $body -ContentType 'application/json'

# Test multi-tool
$body = @{ messages = @(@{ role = "user"; content = "Get Microsoft sales and calculate revenue per employee with 10 employees" }) } | ConvertTo-Json
Invoke-RestMethod -Uri http://localhost:8000/chat -Method POST -Body $body -ContentType 'application/json'
```

## Troubleshooting

### Port Conflicts

```powershell
# Check what's using ports
Get-NetTCPConnection -State Listen | Where-Object LocalPort -In 8000,8001,8002,8003

# Kill Python processes
Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force

# Use automated startup (handles conflicts)
cd deploy
.\start-local.ps1
```

### MCP Not Discovered

1. Check folder has `Dockerfile` or `server.py`
2. Folder must be in `mcps/` directory
3. Folder name should not start with `__` or `.`
4. Restart orchestrator to reload MCP list

### Authentication Errors

```powershell
# Login to Azure
az login

# Check token
az account get-access-token --resource https://cognitiveservices.azure.com

# Set explicit credentials in .env
AOAI_API_KEY=your-key-here
```

### Code Interpreter Not Working

1. Check Assistants API is enabled in your Azure OpenAI resource
2. Verify API version is `2024-05-01-preview` or later
3. Ensure `code_interpreter` tool is enabled in your deployment
4. Check `AZURE_OPENAI_ASSISTANTS_ENDPOINT` environment variable

### Dev Mode Issues

```bash
# Force dev mode
export FRAMEWORK_DEV_MODE=true

# Windows PowerShell
$env:FRAMEWORK_DEV_MODE='true'

# Verify in logs
# Should see: "Dev mode enabled - using dummy data"
```

## Architecture Decisions

### Why FastMCP?
- **Simplicity**: Decorator-based tool definition
- **Type Safety**: Full Pydantic integration
- **Flexibility**: HTTP and stdio transports
- **Standards**: MCP protocol compliance

### Why Separate MCP Servers?
- **Isolation**: Each MCP has dedicated resources
- **Scalability**: Independent scaling per MCP
- **Reliability**: Failure in one MCP doesn't affect others
- **Development**: Teams can work on MCPs independently

### Why Dynamic Discovery?
- **Extensibility**: Add MCPs without code changes
- **Deployment**: Automated deployment with zero config
- **Maintainability**: No hard-coded MCP lists
- **Developer Experience**: Simple folder-based structure

### Why Azure OpenAI Assistants for Interpreter?
- **Sandboxed**: Safe code execution environment
- **Pre-built**: Code interpreter tool included
- **File Support**: Can handle CSV, images, etc.
- **Reliable**: Microsoft-managed infrastructure

## Security Considerations

### Production Checklist

- [ ] Enable Managed Identity for all Azure services
- [ ] Remove API keys from `.env`, use Azure Key Vault
- [ ] Set `FRAMEWORK_DEV_MODE=false`
- [ ] Configure RBAC roles in Cosmos DB
- [ ] Enable Azure Container Apps authentication
- [ ] Set up Azure Front Door with WAF
- [ ] Enable Azure Monitor and Application Insights
- [ ] Configure network restrictions (VNET integration)
- [ ] Implement rate limiting on orchestrator
- [ ] Enable audit logging for all MCP calls

### RBAC Implementation

```json
// Cosmos DB: rbac_config container
{
  "id": "sales_rep",
  "role_name": "sales_rep",
  "mcp_access": ["sql_mcp", "graph_mcp"],  // No interpreter access
  "tool_access": ["sql_query", "graph_query"],
  "sql_restrictions": {
    "where_clause": "owner_email = @user_email"  // Row-level security
  }
}
```

## Performance Optimization

### Caching Strategy

The framework automatically caches:
- SQL query results (TTL: 5 minutes)
- Graph query results (TTL: 5 minutes)
- Account resolution (TTL: 1 hour)
- Embeddings (TTL: 24 hours)

### Scaling Recommendations

- **Orchestrator**: Scale horizontally (stateless)
- **SQL MCP**: Vertical scaling for compute-heavy queries
- **Graph MCP**: Horizontal scaling for high throughput
- **Interpreter MCP**: Isolated instances per tenant (long-running code)

## Contributing

### Adding New Features

1. Create feature branch
2. Add tests in `tests/`
3. Update relevant READMEs
4. Test locally with `start-local.ps1`
5. Test Azure deployment with `deploy.ps1`
6. Submit pull request

### Code Style

- Python: Black formatter, isort, flake8
- JavaScript: Prettier, ESLint
- Commit messages: Conventional Commits format

## License

MIT License - see LICENSE file for details.

## Support

- **Documentation**: See individual MCP READMEs in `mcps/*/README.md`
- **Deployment Guide**: `deploy/README_DEPLOYMENT.md`
- **Issues**: GitHub Issues
- **Questions**: GitHub Discussions

## Acknowledgments

- Built with [FastMCP](https://github.com/jlowin/fastmcp)
- Powered by [Azure OpenAI](https://azure.microsoft.com/products/ai-services/openai-service)
- Deployed on [Azure Container Apps](https://azure.microsoft.com/products/container-apps)
