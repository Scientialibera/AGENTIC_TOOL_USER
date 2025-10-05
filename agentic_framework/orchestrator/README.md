# Orchestrator Service

The orchestrator is the central coordination service that manages multi-agent workflows, routes requests to appropriate MCP servers, and maintains conversation state.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Orchestrator (Port 8000)                 │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────┐  ┌──────────────────┐  ┌───────────────┐ │
│  │ FastAPI     │  │ Discovery        │  │ Azure OpenAI  │ │
│  │ Server      │  │ Service          │  │ Client        │ │
│  │             │  │                  │  │               │ │
│  │ - /chat     │  │ - Load MCPs      │  │ - Planning    │ │
│  │ - /mcps     │  │ - Load Tools     │  │ - Execution   │ │
│  │ - /tools    │  │ - RBAC Filter    │  │ - Reasoning   │ │
│  │ - /healthz  │  │ - Cosmos DB      │  │               │ │
│  └─────────────┘  └──────────────────┘  └───────────────┘ │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ Unified Data Service (Cosmos DB)                     │  │
│  │ - Conversation tracking                              │  │
│  │ - Execution metadata                                 │  │
│  │ - User feedback                                      │  │
│  │ - Query caching                                      │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
              │              │              │
              ▼              ▼              ▼
        SQL MCP        Graph MCP    Interpreter MCP
```

## Key Features

### 1. **Dynamic MCP Discovery**
- Reads `MCP_ENDPOINTS` environment variable (JSON mapping)
- Validates MCP availability via health checks
- Loads tool definitions for each MCP
- Applies RBAC filtering per user

### 2. **Multi-Round Orchestration**
- Azure OpenAI function calling for tool selection
- Automatic tool chaining across multiple MCPs
- Context preservation across rounds
- Maximum 5 rounds to prevent infinite loops

### 3. **Tool Lineage Tracking**
- Records every tool call with full context
- Captures input parameters, output, and timing
- Builds execution DAG for debugging
- Frontend visualization support

### 4. **Conversation Management**
- Session-based conversation tracking
- Full message history persistence
- Turn-level granularity
- User feedback integration

### 5. **Query Caching**
- Automatic caching of MCP responses
- TTL-based expiration (5 minutes default)
- RBAC-scoped cache keys
- Reduces redundant MCP calls

## Components

### app.py

FastAPI server with REST endpoints.

**Key Endpoints:**

- `POST /chat` - Main chat interface
- `GET /mcps` - List available MCPs (RBAC-filtered)
- `GET /tools` - List available tools (RBAC-filtered)
- `GET /healthz` - Health check
- `GET /sessions` - List user's sessions
- `GET /sessions/{session_id}` - Get full conversation
- `POST /feedback` - Submit feedback for a turn

**Features:**

- Azure AD token validation
- RBAC context resolution
- Error handling and logging
- CORS configuration
- Request/response logging

### discovery_service.py

MCP discovery and tool loading service.

**Responsibilities:**

- Parse `MCP_ENDPOINTS` JSON from environment
- Load MCP definitions from Cosmos DB
- Load tool definitions from Cosmos DB
- Apply RBAC filtering
- Register tools with orchestrator agent

**RBAC Logic:**

```python
# Filter MCPs by user role
allowed_mcps = [
    mcp for mcp in all_mcps
    if user_role in mcp.allowed_roles
]

# Filter tools by user role  
allowed_tools = [
    tool for tool in all_tools
    if user_role in tool.allowed_roles
    and tool.mcp_id in allowed_mcp_ids
]
```

### orchestrator.py

Main orchestration agent using Azure OpenAI.

**Workflow:**

1. **Initialization**
   - Load tools from discovery service
   - Create Azure OpenAI client
   - Set up conversation context

2. **Query Processing**
   - Add user message to context
   - Call Azure OpenAI with function calling
   - Check for tool calls in response

3. **Tool Execution**
   - Parse tool call parameters
   - Route to appropriate MCP via HTTP
   - Capture result and timing
   - Add to tool lineage

4. **Iteration**
   - Add tool results to context
   - Call Azure OpenAI again
   - Repeat until final answer or max rounds

5. **Response Generation**
   - Extract final assistant message
   - Build execution metadata
   - Return structured response

**Key Methods:**

- `process_query()` - Main orchestration loop
- `_call_tool()` - Execute tool via MCP HTTP endpoint
- `_build_tool_lineage()` - Create execution trace
- `_apply_rbac_context()` - Inject user context into tool calls

## Configuration

### Environment Variables

```bash
# MCP Configuration (auto-generated by deploy scripts)
MCP_ENDPOINTS={"sql_mcp":"http://localhost:8001/mcp","graph_mcp":"http://localhost:8002/mcp","interpreter_mcp":"http://localhost:8003/mcp"}
LIST_OF_MCPS=sql_mcp,graph_mcp,interpreter_mcp

# Azure OpenAI
AOAI_ENDPOINT=https://your-instance.openai.azure.com
AOAI_CHAT_DEPLOYMENT=gpt-4o
AOAI_API_VERSION=2024-08-01-preview

# Framework Settings
FRAMEWORK_DEV_MODE=false
FRAMEWORK_DEBUG=true
FRAMEWORK_MAX_ROUNDS=5

# Cosmos DB
COSMOS_ENDPOINT=https://your-cosmos.documents.azure.com:443/
COSMOS_DATABASE_NAME=agentic_db

# Security
BYPASS_TOKEN_VALIDATION=false  # Set to true only for local dev
```

## API Reference

### POST /chat

Process a user query with multi-agent orchestration.

**Request:**

```json
{
  "messages": [
    {
      "role": "user",
      "content": "Get Microsoft sales and calculate revenue per employee"
    }
  ],
  "user_id": "user@example.com",
  "session_id": "optional-uuid",
  "metadata": {
    "source": "web",
    "user_agent": "Mozilla/5.0..."
  }
}
```

**Response:**

```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "response": "Microsoft has $5,000,000 in sales. With 10 employees, revenue per employee is $500,000.",
  "success": true,
  "rounds": 3,
  "mcps_used": ["sql_mcp", "interpreter_mcp"],
  "tool_lineage": [
    {
      "step": 1,
      "tool_name": "sql_query",
      "mcp_server": "sql_mcp",
      "input": {
        "query": "Get all sales for Microsoft",
        "accounts_mentioned": ["Microsoft"]
      },
      "result_summary": "Retrieved 10 rows",
      "output": {
        "success": true,
        "data": [
          {
            "opportunity_name": "Azure Enterprise Agreement",
            "amount": 5000000,
            "close_date": "2024-06-30"
          }
        ],
        "row_count": 10
      },
      "timestamp": "2025-10-05T10:15:30.123Z"
    },
    {
      "step": 2,
      "tool_name": "interpreter_agent",
      "mcp_server": "interpreter_mcp",
      "input": {
        "query": "Calculate revenue per employee: $5,000,000 / 10 employees"
      },
      "result_summary": "Success",
      "output": {
        "success": true,
        "code": "total_revenue = 5000000\nemployees = 10\nrevenue_per_employee = total_revenue / employees\nprint(f'${revenue_per_employee:,.2f}')",
        "result": "$500,000.00",
        "execution_time_ms": 3245,
        "output_type": "text"
      },
      "timestamp": "2025-10-05T10:15:35.456Z"
    }
  ],
  "metadata": {
    "turn_id": "turn_abc123",
    "execution_time_ms": 5678,
    "timestamp": "2025-10-05T10:15:36.000Z"
  }
}
```

### GET /mcps

List available MCPs for the current user.

**Query Parameters:**
- `user_id` (optional) - Filter by user ID for RBAC

**Response:**

```json
{
  "mcps": [
    {
      "id": "sql_mcp",
      "name": "SQL MCP Server",
      "description": "Natural language SQL queries",
      "endpoint": "http://localhost:8001/mcp",
      "tools": ["sql_query"],
      "enabled": true
    },
    {
      "id": "graph_mcp",
      "name": "Graph MCP Server",
      "description": "Natural language Gremlin queries",
      "endpoint": "http://localhost:8002/mcp",
      "tools": ["graph_query"],
      "enabled": true
    },
    {
      "id": "interpreter_mcp",
      "name": "Code Interpreter MCP",
      "description": "Code execution and calculations",
      "endpoint": "http://localhost:8003/mcp",
      "tools": ["interpreter_agent"],
      "enabled": true
    }
  ],
  "count": 3
}
```

### GET /tools

List available tools across all MCPs.

**Query Parameters:**
- `mcp_id` (optional) - Filter by specific MCP
- `user_id` (optional) - Filter by user for RBAC

**Response:**

```json
{
  "tools": [
    {
      "name": "sql_query",
      "description": "Execute SQL queries against Salesforce/Fabric data",
      "mcp_id": "sql_mcp",
      "parameters": {
        "type": "object",
        "properties": {
          "query": {
            "type": "string",
            "description": "Natural language query"
          },
          "accounts_mentioned": {
            "type": "array",
            "items": {"type": "string"}
          }
        },
        "required": ["query"]
      }
    },
    {
      "name": "graph_query",
      "description": "Execute Gremlin graph queries",
      "mcp_id": "graph_mcp",
      "parameters": {
        "type": "object",
        "properties": {
          "query": {
            "type": "string",
            "description": "Natural language graph query"
          }
        },
        "required": ["query"]
      }
    },
    {
      "name": "interpreter_agent",
      "description": "Execute Python code for calculations",
      "mcp_id": "interpreter_mcp",
      "parameters": {
        "type": "object",
        "properties": {
          "query": {
            "type": "string",
            "description": "Calculation or data analysis request"
          }
        },
        "required": ["query"]
      }
    }
  ],
  "count": 3
}
```

## Conversation Tracking

### Data Model

**Chat Session:**

```json
{
  "doc_type": "chat_session",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "user_id": "user@example.com",
  "created_at": "2025-10-05T10:00:00Z",
  "updated_at": "2025-10-05T10:30:00Z",
  "turns": [
    {
      "turn_id": "turn_1",
      "turn_number": 1,
      "user_message": "Get Microsoft sales",
      "assistant_response": "Microsoft has $5M in sales...",
      "timestamp": "2025-10-05T10:15:00Z",
      "execution_metadata": {
        "rounds": 2,
        "mcps_used": ["sql_mcp"],
        "execution_time_ms": 1234,
        "tool_calls": [...]
      }
    }
  ],
  "metadata": {
    "source": "web",
    "user_agent": "Mozilla/5.0..."
  }
}
```

**Feedback:**

```json
{
  "doc_type": "feedback",
  "turn_id": "turn_1",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "user_id": "user@example.com",
  "rating": 5,
  "comment": "Very helpful!",
  "timestamp": "2025-10-05T10:16:00Z"
}
```

## Error Handling

### Error Response Format

```json
{
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "response": "I encountered an error while processing your request.",
  "success": false,
  "error": {
    "type": "ToolExecutionError",
    "message": "SQL MCP returned an error",
    "details": {
      "mcp_id": "sql_mcp",
      "tool_name": "sql_query",
      "error": "Connection timeout"
    }
  },
  "tool_lineage": [...],
  "metadata": {
    "execution_time_ms": 30000,
    "timestamp": "2025-10-05T10:15:30Z"
  }
}
```

### Common Error Scenarios

1. **MCP Unreachable**
   - Retry with exponential backoff
   - Fallback to error message
   - Log for monitoring

2. **Tool Execution Failure**
   - Capture error from MCP
   - Include in tool lineage
   - Return user-friendly message

3. **Max Rounds Exceeded**
   - Stop after 5 rounds
   - Return partial results
   - Log for analysis

4. **Invalid Tool Parameters**
   - Validate before calling MCP
   - Return validation error
   - Guide user to correct format

## Monitoring & Observability

### Structured Logging

```python
logger.info(
    "Processing query",
    user_id=user_id,
    session_id=session_id,
    query_length=len(query),
    mcps_available=len(mcps)
)
```

### Metrics to Track

- Request count by endpoint
- Average execution time
- MCP call success rate
- Tool usage frequency
- Rounds per query distribution
- Cache hit rate

### Application Insights Integration

```python
from opencensus.ext.azure import metrics_exporter
from opencensus.stats import aggregation as aggregation_module
from opencensus.stats import measure as measure_module
from opencensus.stats import stats as stats_module
from opencensus.stats import view as view_module

# Track custom metrics
stats = stats_module.stats
view_manager = stats.view_manager
stats_recorder = stats.stats_recorder

# Define measures
execution_time = measure_module.MeasureFloat(
    "orchestrator/execution_time",
    "Execution time in milliseconds",
    "ms"
)

# Create views
execution_time_view = view_module.View(
    "orchestrator/execution_time_distribution",
    "Distribution of execution times",
    [],
    execution_time,
    aggregation_module.DistributionAggregation([50, 100, 200, 500, 1000, 2000, 5000])
)

view_manager.register_view(execution_time_view)
```

## Performance Optimization

### Caching Strategy

1. **MCP Response Caching**
   - Cache SQL/Graph query results
   - TTL: 5 minutes
   - Key: `{mcp_id}:{user_id}:{query_hash}`

2. **Tool Definition Caching**
   - Cache loaded tool schemas
   - TTL: 1 hour
   - Refresh on MCP update

3. **Account Resolution Caching**
   - Cache resolved account names
   - TTL: 1 hour
   - Shared across MCPs

### Concurrency

- Async/await for I/O operations
- Parallel MCP health checks on startup
- Concurrent tool calls (when independent)

### Connection Pooling

- HTTP client connection pooling
- Cosmos DB connection management
- Azure OpenAI client reuse

## Security

### Authentication & Authorization

1. **Token Validation**
   - Azure AD JWT validation
   - Audience and issuer checks
   - Expiration validation

2. **RBAC Enforcement**
   - Load user role from token claims
   - Filter MCPs by role
   - Filter tools by role
   - Inject WHERE clauses for SQL

3. **Rate Limiting**
   - Per-user request limits
   - Global orchestrator limits
   - MCP-specific limits

### Input Validation

- Sanitize user queries
- Validate tool parameters
- Check session ID format
- Limit message length

### Secrets Management

- Azure Key Vault integration
- Managed Identity for Azure services
- No secrets in environment variables (production)

## Deployment

### Local Development

```powershell
# Set environment variables
$env:MCP_ENDPOINTS='{"sql_mcp":"http://localhost:8001/mcp","graph_mcp":"http://localhost:8002/mcp","interpreter_mcp":"http://localhost:8003/mcp"}'
$env:LIST_OF_MCPS='sql_mcp,graph_mcp,interpreter_mcp'
$env:FRAMEWORK_DEV_MODE='true'

# Start orchestrator
cd agentic_framework
python -m orchestrator.app
```

### Azure Container Apps

```yaml
# Container configuration
env:
  - name: MCP_ENDPOINTS
    value: '{"sql_mcp":"http://sql-mcp:8001/mcp","graph_mcp":"http://graph-mcp:8002/mcp","interpreter_mcp":"http://interpreter-mcp:8003/mcp"}'
  - name: LIST_OF_MCPS
    value: 'sql_mcp,graph_mcp,interpreter_mcp'
  - name: AOAI_ENDPOINT
    secretRef: aoai-endpoint
  - name: COSMOS_ENDPOINT
    secretRef: cosmos-endpoint
  - name: FRAMEWORK_DEV_MODE
    value: 'false'
```

## Troubleshooting

### Issue: MCP Not Discovered

**Symptoms:** Tool not available, MCP not in `/mcps` list

**Solutions:**
1. Check `MCP_ENDPOINTS` environment variable format
2. Verify MCP is running and healthy
3. Check Cosmos DB has MCP definition
4. Verify user role has access to MCP

### Issue: Tool Execution Fails

**Symptoms:** Error in `/chat` response, tool lineage shows failure

**Solutions:**
1. Check MCP logs for errors
2. Verify tool parameters are correct
3. Test MCP endpoint directly
4. Check network connectivity

### Issue: Slow Response Times

**Symptoms:** High execution_time_ms values

**Solutions:**
1. Check MCP response times
2. Enable caching
3. Optimize tool parameters
4. Scale MCPs horizontally

### Issue: Max Rounds Exceeded

**Symptoms:** Response indicates max rounds reached

**Solutions:**
1. Review tool selection logic
2. Check for circular dependencies
3. Simplify user query
4. Increase MAX_ROUNDS (carefully)

## Development Guide

### Adding New Endpoint

```python
@app.post("/analyze")
async def analyze_conversation(
    session_id: str,
    user_id: str = Depends(get_current_user)
):
    """Analyze conversation for insights."""
    # Load session
    session = await unified_service.get_session(session_id, user_id)
    
    # Analyze with Azure OpenAI
    analysis = await orchestrator_agent.analyze(session)
    
    return {"analysis": analysis}
```

### Adding New Middleware

```python
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all requests."""
    start_time = time.time()
    
    response = await call_next(request)
    
    process_time = time.time() - start_time
    logger.info(
        "Request processed",
        path=request.url.path,
        method=request.method,
        status_code=response.status_code,
        process_time=process_time
    )
    
    return response
```

## Testing

### Unit Tests

```python
# tests/test_orchestrator.py
import pytest
from orchestrator.orchestrator import OrchestratorAgent

@pytest.mark.asyncio
async def test_tool_selection():
    """Test correct tool selection based on query."""
    agent = OrchestratorAgent()
    
    query = "Show me contacts at Microsoft"
    tools = await agent.select_tools(query)
    
    assert "sql_query" in [t.name for t in tools]
    assert "graph_query" not in [t.name for t in tools]
```

### Integration Tests

```python
# tests/test_orchestrator_integration.py
import pytest
import httpx

@pytest.mark.asyncio
async def test_chat_endpoint():
    """Test full chat flow."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:8000/chat",
            json={
                "messages": [{"role": "user", "content": "Test query"}],
                "user_id": "test@example.com"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "response" in data
        assert "tool_lineage" in data
```

## Future Enhancements

1. **Streaming Responses**: Server-Sent Events for real-time updates
2. **Tool Approval**: User confirmation before executing sensitive tools
3. **Multi-User Sessions**: Collaborative conversations
4. **Advanced Analytics**: Query pattern analysis, tool usage trends
5. **Auto-Scaling**: Dynamic MCP scaling based on load
6. **Tool Composition**: Higher-order tools that combine multiple MCPs
7. **Semantic Caching**: Similarity-based cache matching
8. **Tool Learning**: Fine-tune tool selection based on feedback

## References

- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Azure OpenAI Function Calling](https://learn.microsoft.com/en-us/azure/ai-services/openai/how-to/function-calling)
- [FastMCP Documentation](https://github.com/jlowin/fastmcp)
- [Model Context Protocol](https://modelcontextprotocol.io/)
