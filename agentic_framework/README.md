# Agentic Framework with FastMCP

A flexible, RBAC-enabled agentic framework using FastMCP for orchestration and specialized MCP servers for SQL and Graph operations.

## Architecture

```

                    Orchestrator Agent (Client)               
  - Discovers MCPs from Cosmos DB                            
  - Loads tool definitions with RBAC filtering               
  - Uses Azure OpenAI for planning and execution             

                                     
           
           SQL MCP Server    Graph MCP Server
           (Port 8001)        (Port 8002)    
                                             
          - SQL queries      - Graph queries 
          - Fabric           - Gremlin       
          - Account res.     - Account res.  
           
```

## Features

### 1. **Dynamic MCP Discovery**
- MCPs configured via `LIST_OF_MCPS` environment variable
- Definitions loaded from Cosmos DB
- Tools dynamically registered based on RBAC

### 2. **Role-Based Access Control (RBAC)**
- User-specific tool and MCP filtering
- Row-level security via WHERE clause injection
- Dev mode bypasses RBAC for testing

### 3. **Intelligent Agents**
- SQL MCP: Natural language  SQL queries
- Graph MCP: Natural language  Gremlin queries
- Both use internal LLMs for query generation

### 4. **Account Resolution**
- Fuzzy matching using Levenshtein distance
- Handles typos and abbreviations
- Dev mode provides dummy accounts

### 5. **Dev Mode**
- Returns dummy data without database connections
- Useful for local development and testing
- Enabled via `FRAMEWORK_DEV_MODE=true`

## Project Structure

```
agentic_framework/
 orchestrator/
    __init__.py
    app.py                    # FastAPI orchestrator
    discovery_service.py      # MCP discovery logic
    orchestrator.py           # Main orchestrator agent
 mcps/
    __init__.py
    sql_server.py            # SQL MCP server
    graph_server.py          # Graph MCP server
 shared/
    __init__.py
    config.py                # Configuration
    models.py                # Pydantic models
    aoai_client.py           # Azure OpenAI client
    cosmos_client.py         # Cosmos DB client
    fabric_client.py         # Fabric SQL client
    gremlin_client.py        # Gremlin client
    account_resolver.py      # Account resolution
 requirements.txt
```

## Setup

### 1. Install Dependencies

```bash
cd agentic_framework
pip install -r requirements.txt
```

### 2. Environment Variables

Create a `.env` file in the `agentic_framework` directory:

```bash
# Framework Settings
FRAMEWORK_DEV_MODE=true
FRAMEWORK_DEBUG=true
FRAMEWORK_LIST_OF_MCPS=sql_mcp,graph_mcp

# Azure OpenAI
AOAI_ENDPOINT=https://your-instance.openai.azure.com
AOAI_CHAT_DEPLOYMENT=gpt-4
AOAI_EMBEDDING_DEPLOYMENT=text-embedding-ada-002

# Cosmos DB
COSMOS_ENDPOINT=https://your-cosmos.documents.azure.com:443/
COSMOS_DATABASE_NAME=agentic_db

# Gremlin (optional)
AZURE_COSMOS_GREMLIN_ENDPOINT=wss://your-cosmos.gremlin.cosmos.azure.com:443/

# Fabric (optional)
FABRIC_SQL_ENDPOINT=your-fabric-endpoint.datawarehouse.fabric.microsoft.com
FABRIC_DATABASE=your_lakehouse
```

### 3. Initialize Cosmos DB

Load sample MCP definitions and tool schemas into Cosmos DB:

```bash
# Create containers
az cosmosdb sql container create \
  --account-name <account-name> \
  --database-name agentic_db \
  --name mcp_definitions \
  --partition-key-path "/id"

az cosmosdb sql container create \
  --account-name <account-name> \
  --database-name agentic_db \
  --name agent_functions \
  --partition-key-path "/mcp_id"

az cosmosdb sql container create \
  --account-name <account-name> \
  --database-name agentic_db \
  --name rbac_config \
  --partition-key-path "/role_name"
```

Upload sample data (see `sample_data/` directory).

## Running the Framework

### Start MCP Servers

```bash
# Terminal 1: SQL MCP Server
python -m mcps.sql_server

# Terminal 2: Graph MCP Server
python -m mcps.graph_server
```

### Start Orchestrator

```bash
# Terminal 3: Orchestrator
python -m orchestrator.app
```

Or use uvicorn:

```bash
uvicorn orchestrator.app:app --reload --port 8000
```

## API Endpoints

### Orchestrator (Port 8000)

#### POST `/chat`
Process a chat request using the orchestrator.

```json
{
  "messages": [
    {"role": "user", "content": "Show me contacts at Microsoft"}
  ],
  "user_id": "user@example.com",
  "session_id": "optional-session-id"
}
```

Response:
```json
{
  "session_id": "abc-123",
  "response": "Here are the contacts at Microsoft...",
  "success": true,
  "rounds": 2,
  "mcps_used": ["sql_mcp"],
  "execution_records": [...]
}
```

#### GET `/mcps`
List available MCPs for the current user.

#### GET `/tools`
List available tools, optionally filtered by MCP.

#### GET `/health`
Health check endpoint.

#### GET `/sessions`
List all chat sessions for the current user.

#### GET `/sessions/{session_id}`
Get full conversation history for a specific session.

#### POST `/feedback`
Submit feedback for a conversation turn.

```json
{
  "turn_id": "turn_abc123",
  "rating": 5,
  "comment": "Very helpful!"
}
```

## Conversation Tracking

The framework uses **UnifiedDataService** for comprehensive conversation tracking:

### What Gets Tracked

1. **Full Conversation History**
   - User messages and assistant responses
   - Turn numbers and timestamps
   - Citations (if applicable)

2. **Execution Metadata**
   - Tool calls made by each MCP
   - Arguments and results for each call
   - Execution times and success/failure status
   - Number of planning rounds

3. **User Feedback**
   - Rating (1-5 stars) for each turn
   - Optional comments
   - Feedback timestamps

4. **Query Caching**
   - Automatic caching of SQL/Graph query results
   - TTL-based expiration
   - RBAC-scoped cache keys

### Data Persistence

All data stored in Cosmos DB `unified_data` container:

- `doc_type: chat_session` - Full conversation history
- `doc_type: feedback` - User feedback
- `doc_type: cache` - Query result cache
- `doc_type: embedding` - Text embedding cache

See [UNIFIED_SERVICE.md](UNIFIED_SERVICE.md) for complete documentation.

#### GET `/health`
Health check endpoint.

## Sample Cosmos DB Data

### MCP Definition (mcp_definitions container)

```json
{
  "id": "sql_mcp",
  "name": "SQL MCP Server",
  "description": "SQL agent for querying Salesforce/Fabric data",
  "endpoint": "http://localhost:8001/mcp",
  "transport": "http",
  "allowed_roles": ["sales_rep", "admin"],
  "tools": ["sql_query"],
  "enabled": true
}
```

### Tool Definition (agent_functions container)

```json
{
  "id": "sql_query",
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
        "items": {"type": "string"},
        "description": "List of account names mentioned"
      },
      "limit": {
        "type": "integer",
        "description": "Maximum rows to return",
        "default": 100
      }
    },
    "required": ["query"]
  },
  "allowed_roles": ["sales_rep", "admin"]
}
```

### RBAC Configuration (rbac_config container)

```json
{
  "id": "sales_rep",
  "role_name": "sales_rep",
  "mcp_access": ["sql_mcp", "graph_mcp"],
  "tool_access": ["sql_query", "graph_query"]
}
```

## Dev Mode

When `FRAMEWORK_DEV_MODE=true`:

- **RBAC is bypassed** - all MCPs and tools are available
- **Dummy data returned** - no database connections needed
- **Account resolver** returns 5 predefined accounts
- **SQL queries** return sample contact/opportunity data
- **Graph queries** return sample relationship data

This is perfect for:
- Local development without Azure resources
- Testing the orchestration logic
- Debugging MCP communication

## Testing

```bash
# Test orchestrator
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "Show me contacts at Microsoft"}],
    "user_id": "test@example.com"
  }'

# List available MCPs
curl http://localhost:8000/mcps

# List available tools
curl http://localhost:8000/tools
```

## Adding New MCPs - Complete Example

Let's walk through adding a new **Email MCP** that can search and send emails.

### Step 1: Create the MCP Server

Create `mcps/email_server.py`:

```python
"""
Email MCP Server.

Provides tools for searching and sending emails via Microsoft Graph API.
"""

from typing import Dict, Any, Optional, List
from fastmcp import FastMCP
import structlog

from shared.config import get_settings
from shared.models import RBACContext
from shared.aoai_client import AzureOpenAIClient

logger = structlog.get_logger(__name__)
settings = get_settings()

mcp = FastMCP("Email MCP Server")

@mcp.tool()
async def search_emails(
    query: str,
    sender: Optional[str] = None,
    date_from: Optional[str] = None,
    limit: int = 10,
    rbac_context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Search user's emails using natural language query.
    
    Args:
        query: Natural language search query
        sender: Filter by sender email
        date_from: Filter by date (ISO format)
        limit: Maximum results to return
        rbac_context: User RBAC context
    
    Returns:
        Dictionary with success status and email results
    """
    try:
        logger.info("Searching emails", query=query, sender=sender)
        
        if settings.dev_mode:
            return _get_dummy_emails(query, sender, limit)
        
        # In production, use Microsoft Graph API
        # graph_client = GraphClient(settings.graph)
        # results = await graph_client.search_emails(query, sender, date_from, limit)
        
        return {
            "success": True,
            "emails": [
                {
                    "id": "email-1",
                    "subject": "Q4 Planning Meeting",
                    "from": "manager@contoso.com",
                    "date": "2025-10-01T14:30:00Z",
                    "preview": "Let's discuss Q4 objectives..."
                }
            ],
            "count": 1
        }
        
    except Exception as e:
        logger.error("Email search failed", error=str(e))
        return {"success": False, "error": str(e)}


@mcp.tool()
async def send_email(
    to: List[str],
    subject: str,
    body: str,
    cc: Optional[List[str]] = None,
    rbac_context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Send an email to recipients.
    
    Args:
        to: List of recipient email addresses
        subject: Email subject
        body: Email body (HTML or plain text)
        cc: Optional CC recipients
        rbac_context: User RBAC context
    
    Returns:
        Dictionary with success status and message ID
    """
    try:
        logger.info("Sending email", to=to, subject=subject)
        
        if settings.dev_mode:
            return {
                "success": True,
                "message_id": "msg-dummy-123",
                "sent_at": "2025-10-02T10:00:00Z"
            }
        
        # In production, use Microsoft Graph API
        # graph_client = GraphClient(settings.graph)
        # result = await graph_client.send_email(to, subject, body, cc)
        
        return {
            "success": True,
            "message_id": "msg-123",
            "sent_at": "2025-10-02T10:00:00Z"
        }
        
    except Exception as e:
        logger.error("Email send failed", error=str(e))
        return {"success": False, "error": str(e)}


def _get_dummy_emails(query: str, sender: Optional[str], limit: int) -> Dict[str, Any]:
    """Return dummy email data for dev mode."""
    dummy_emails = [
        {
            "id": "email-1",
            "subject": "Q4 Planning Meeting",
            "from": "manager@contoso.com",
            "date": "2025-10-01T14:30:00Z",
            "preview": "Let's discuss Q4 objectives and goals..."
        },
        {
            "id": "email-2",
            "subject": "Customer Feedback - Fabrikam",
            "from": "customer@fabrikam.com",
            "date": "2025-10-01T09:15:00Z",
            "preview": "We really appreciate your service..."
        },
        {
            "id": "email-3",
            "subject": "Contract Renewal Discussion",
            "from": "sales@wingtip.com",
            "date": "2025-09-30T16:45:00Z",
            "preview": "I wanted to follow up on our contract..."
        }
    ]
    
    if sender:
        dummy_emails = [e for e in dummy_emails if sender.lower() in e["from"].lower()]
    
    return {
        "success": True,
        "emails": dummy_emails[:limit],
        "count": len(dummy_emails[:limit])
    }


if __name__ == "__main__":
    import asyncio
    
    logger.info("Starting Email MCP Server", port=8003, dev_mode=settings.dev_mode)
    mcp.run(transport="http", port=8003)
```

### Step 2: Create MCP Definition

Create `sample_data/email_mcp_definition.json`:

```json
{
  "id": "email_mcp",
  "name": "Email MCP Server",
  "description": "Search and send emails via Microsoft Graph API",
  "endpoint": "http://localhost:8003/mcp",
  "transport": "http",
  "allowed_roles": ["sales_rep", "sales_manager", "admin"],
  "tools": ["search_emails", "send_email"],
  "enabled": true,
  "metadata": {
    "version": "1.0.0",
    "capabilities": ["email_search", "email_send"],
    "requires_graph_api": true
  }
}
```

### Step 3: Create Tool Definitions

Create `sample_data/email_tools.json`:

```json
[
  {
    "id": "search_emails",
    "name": "search_emails",
    "description": "Search user's emails using natural language. Can filter by sender and date.",
    "mcp_id": "email_mcp",
    "parameters": {
      "type": "object",
      "properties": {
        "query": {
          "type": "string",
          "description": "Natural language search query (e.g., 'emails from manager about Q4')"
        },
        "sender": {
          "type": "string",
          "description": "Filter by sender email address (optional)"
        },
        "date_from": {
          "type": "string",
          "description": "Filter emails after this date in ISO format (optional)"
        },
        "limit": {
          "type": "integer",
          "description": "Maximum number of emails to return",
          "default": 10
        }
      },
      "required": ["query"]
    },
    "allowed_roles": ["sales_rep", "sales_manager", "admin"],
    "metadata": {
      "category": "email",
      "requires_permission": "Mail.Read"
    }
  },
  {
    "id": "send_email",
    "name": "send_email",
    "description": "Send an email to one or more recipients with optional CC",
    "mcp_id": "email_mcp",
    "parameters": {
      "type": "object",
      "properties": {
        "to": {
          "type": "array",
          "items": {"type": "string"},
          "description": "List of recipient email addresses"
        },
        "subject": {
          "type": "string",
          "description": "Email subject line"
        },
        "body": {
          "type": "string",
          "description": "Email body content (plain text or HTML)"
        },
        "cc": {
          "type": "array",
          "items": {"type": "string"},
          "description": "Optional CC recipients"
        }
      },
      "required": ["to", "subject", "body"]
    },
    "allowed_roles": ["sales_rep", "sales_manager", "admin"],
    "metadata": {
      "category": "email",
      "requires_permission": "Mail.Send"
    }
  }
]
```

### Step 4: Upload to Cosmos DB

Create `upload_email_mcp.py`:

```python
"""Upload Email MCP configuration to Cosmos DB."""

import asyncio
import json
from shared.cosmos_client import CosmosDBClient
from shared.config import get_settings

async def upload_email_mcp():
    settings = get_settings()
    cosmos = CosmosDBClient(settings.cosmos)
    
    # Upload MCP definition
    with open("sample_data/email_mcp_definition.json") as f:
        mcp_def = json.load(f)
    
    await cosmos.upsert_item(
        container_name="mcp_definitions",
        item=mcp_def,
        partition_key="/id"
    )
    print(f" Uploaded MCP definition: {mcp_def['id']}")
    
    # Upload tool definitions
    with open("sample_data/email_tools.json") as f:
        tools = json.load(f)
    
    for tool in tools:
        await cosmos.upsert_item(
            container_name="agent_functions",
            item=tool,
            partition_key="/mcp_id"
        )
        print(f" Uploaded tool: {tool['name']}")
    
    print("\n Email MCP configuration uploaded successfully!")
    await cosmos.close()

if __name__ == "__main__":
    asyncio.run(upload_email_mcp())
```

Run it:

```bash
python upload_email_mcp.py
```

### Step 5: Update Environment Variables

Add the new MCP to your `.env`:

```bash
# Before:
LIST_OF_MCPS=sql_mcp,graph_mcp

# After:
LIST_OF_MCPS=sql_mcp,graph_mcp,email_mcp
```

### Step 6: Start the Email MCP Server

```bash
# Terminal 4: Email MCP Server
python -m mcps.email_server
```

Output:
```
Starting Email MCP Server on port 8003
Dev mode enabled - using dummy data
Server ready to accept connections
```

### Step 7: Restart Orchestrator

```bash
# Stop the orchestrator (Ctrl+C) and restart
python -m orchestrator.app
```

The orchestrator will automatically discover the new Email MCP!

### Step 8: Test the New MCP

```bash
# Test email search
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "user", "content": "Search my emails from manager about Q4"}
    ],
    "user_id": "test@example.com"
  }'
```

Response:
```json
{
  "session_id": "abc-123",
  "response": "I found 1 email from your manager about Q4:\n\n**Q4 Planning Meeting**\nFrom: manager@contoso.com\nDate: Oct 1, 2025\nPreview: Let's discuss Q4 objectives and goals...",
  "success": true,
  "rounds": 1,
  "mcps_used": ["email_mcp"],
  "execution_records": [
    {
      "tool_call_id": "call_xyz",
      "tool_name": "search_emails",
      "mcp_id": "email_mcp",
      "result": {
        "success": true,
        "emails": [
          {
            "id": "email-1",
            "subject": "Q4 Planning Meeting",
            "from": "manager@contoso.com",
            "date": "2025-10-01T14:30:00Z"
          }
        ]
      }
    }
  ]
}
```

### Step 9: Verify Discovery

```bash
# List all MCPs
curl http://localhost:8000/mcps
```

Response:
```json
{
  "mcps": [
    {"id": "sql_mcp", "name": "SQL MCP Server", "endpoint": "http://localhost:8001/mcp"},
    {"id": "graph_mcp", "name": "Graph MCP Server", "endpoint": "http://localhost:8002/mcp"},
    {"id": "email_mcp", "name": "Email MCP Server", "endpoint": "http://localhost:8003/mcp"}
  ],
  "count": 3
}
```

```bash
# List all tools
curl http://localhost:8000/tools
```

Response:
```json
{
  "tools": [
    {"name": "sql_query", "mcp_id": "sql_mcp", "description": "Execute SQL queries..."},
    {"name": "graph_query", "mcp_id": "graph_mcp", "description": "Execute graph queries..."},
    {"name": "search_emails", "mcp_id": "email_mcp", "description": "Search user's emails..."},
    {"name": "send_email", "mcp_id": "email_mcp", "description": "Send an email..."}
  ],
  "count": 4
}
```

### Step 10: Test Multi-Tool Orchestration

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {
        "role": "user",
        "content": "Find opportunities at Contoso, then search my emails about them, and summarize"
      }
    ],
    "user_id": "test@example.com"
  }'
```

The orchestrator will:
1. **Round 1**: Call `sql_query` tool (SQL MCP) to find opportunities
2. **Round 2**: Call `search_emails` tool (Email MCP) with account name "Contoso"
3. **Round 3**: Generate summary combining both results

### Summary: Adding a New MCP

1.  **Create MCP Server** (`mcps/your_mcp_server.py`)
   - Use FastMCP pattern
   - Define tools with `@mcp.tool()`
   - Add dev mode support

2.  **Create Definitions** (JSON files)
   - MCP definition with metadata
   - Tool definitions with JSON schemas

3.  **Upload to Cosmos DB** (Python script)
   - Upload MCP definition to `mcp_definitions`
   - Upload tool definitions to `agent_functions`

4.  **Update Environment** (`.env`)
   - Add MCP ID to `LIST_OF_MCPS`

5.  **Start Server** (Terminal)
   - Run your MCP server on unique port

6.  **Restart Orchestrator**
   - Auto-discovers new MCP
   - Loads tools dynamically

7.  **Test & Verify**
   - Test via `/chat` endpoint
   - Verify via `/mcps` and `/tools`

**That's it!** Your new MCP is now part of the agentic framework and can be orchestrated with all other MCPs. 

### Quick MCP Checklist

- [ ] MCP server implements FastMCP pattern
- [ ] Tools have proper type hints and docstrings
- [ ] RBAC context parameter included in tools
- [ ] Dev mode dummy data provided
- [ ] MCP definition uploaded to Cosmos DB
- [ ] Tool definitions uploaded to Cosmos DB
- [ ] Added to `LIST_OF_MCPS` environment variable
- [ ] Server runs on unique port
- [ ] Tested via orchestrator `/chat` endpoint
- [ ] Verified in `/mcps` and `/tools` endpoints

## Authentication

The framework uses Azure DefaultAzureCredential for all service-to-service calls:
- Orchestrator  Cosmos DB
- Orchestrator  MCPs
- MCPs  Fabric/Gremlin
- MCPs  Cosmos DB

For production, configure Managed Identity or Service Principal.

## Extending the Framework

### Add New Tool to Existing MCP

```python
@mcp.tool()
async def new_tool(
    param1: str,
    rbac_context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Tool description."""
    # Implementation
    return {"success": True, "data": []}
```

Then add tool definition to Cosmos DB.

### Create Custom MCP

```python
from fastmcp import FastMCP

mcp = FastMCP("Custom MCP Server")

@mcp.tool()
async def custom_tool(query: str) -> Dict[str, Any]:
    # Implementation
    return {"success": True}

if __name__ == "__main__":
    mcp.run(transport="http", port=8003)
```

## Troubleshooting

### MCP Not Discovered
- Check `LIST_OF_MCPS` environment variable
- Verify MCP definition exists in Cosmos DB
- Check RBAC configuration for user's role

### Tool Not Available
- Verify tool definition in Cosmos DB
- Check `mcp_id` matches MCP definition
- Verify user's role has access to tool

### Authentication Errors
- Ensure Azure DefaultAzureCredential is configured
- Check Managed Identity permissions
- Verify Cosmos DB RBAC roles assigned

## License

MIT
