# SQL MCP Server

Provides SQL query capabilities for the agentic framework.

## Features

- Natural language to SQL query translation
- Microsoft Fabric lakehouse support
- Fuzzy account name matching
- Dev mode with dummy data
- Query result caching

## Development

### Local Setup

```bash
cd mcps/sql
pip install -r requirements.txt
python server.py
```

Server will start on http://localhost:8001

### Environment Variables

Required:
- `AOAI_ENDPOINT` - Azure OpenAI endpoint
- `AOAI_CHAT_DEPLOYMENT` - Chat model deployment name
- `COSMOS_ENDPOINT` - Cosmos DB endpoint
- `COSMOS_DATABASE_NAME` - Database name

Optional:
- `FABRIC_SQL_ENDPOINT` - Fabric SQL endpoint
- `FABRIC_SQL_DATABASE` - Fabric database name
- `DEV_MODE=true` - Enable dev mode with dummy data

### Docker Build

```bash
# From agentic_framework root
docker build -t sql-mcp -f mcps/sql/Dockerfile .
docker run -p 8001:8001 --env-file .env sql-mcp
```

### Testing

```bash
# Health check
curl http://localhost:8001/health

# Test tool (via orchestrator)
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "Show contacts at Microsoft"}],
    "user_id": "test@example.com"
  }'
```

## Tools

### sql_query

Execute SQL queries against Fabric lakehouse data.

**Parameters:**
- `query` (string, required): Natural language query
- `accounts_mentioned` (array, optional): Account names to resolve
- `limit` (integer, optional): Max results (default: 100)
- `rbac_context` (object, optional): User RBAC context

**Returns:**
- `success` (boolean): Operation status
- `data` (array): Query results
- `count` (integer): Number of results
- `query_executed` (string): Actual SQL query

## Architecture

```
SQL MCP Server
 Azure OpenAI (query generation)
 Account Resolver (fuzzy matching)
 Fabric SQL Client (query execution)
 Cosmos DB (result caching)
```

## Production Deployment

See [../deploy/deploy-aca.ps1](../deploy/deploy-aca.ps1) for Azure Container Apps deployment.
