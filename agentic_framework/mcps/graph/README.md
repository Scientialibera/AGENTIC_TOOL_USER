# Graph MCP Server

Provides graph query capabilities for the agentic framework.

## Features

- Natural language to Gremlin query translation
- Azure Cosmos DB Gremlin API support
- Fuzzy account name matching
- Dev mode with dummy data
- Query result caching

## Development

### Local Setup

```bash
cd mcps/graph
pip install -r requirements.txt
python server.py
```

Server will start on http://localhost:8002

### Environment Variables

Required:
- `AOAI_ENDPOINT` - Azure OpenAI endpoint
- `AOAI_CHAT_DEPLOYMENT` - Chat model deployment name
- `COSMOS_ENDPOINT` - Cosmos DB endpoint
- `COSMOS_DATABASE_NAME` - Database name

Optional:
- `AZURE_COSMOS_GREMLIN_ENDPOINT` - Gremlin endpoint
- `AZURE_COSMOS_GREMLIN_DATABASE` - Gremlin database name
- `AZURE_COSMOS_GREMLIN_GRAPH` - Graph name
- `DEV_MODE=true` - Enable dev mode with dummy data

### Docker Build

```bash
# From agentic_framework root
docker build -t graph-mcp -f mcps/graph/Dockerfile .
docker run -p 8002:8002 --env-file .env graph-mcp
```

### Testing

```bash
# Health check
curl http://localhost:8002/health

# Test tool (via orchestrator)
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "Show relationships for Microsoft"}],
    "user_id": "test@example.com"
  }'
```

## Tools

### graph_query

Execute graph queries against Cosmos DB Gremlin API.

**Parameters:**
- `query` (string, required): Natural language query
- `accounts_mentioned` (array, optional): Account names to resolve
- `limit` (integer, optional): Max results (default: 100)
- `rbac_context` (object, optional): User RBAC context

**Returns:**
- `success` (boolean): Operation status
- `data` (array): Query results
- `count` (integer): Number of results
- `query_executed` (string): Actual Gremlin query

## Architecture

```
Graph MCP Server
 Azure OpenAI (query generation)
 Account Resolver (fuzzy matching)
 Gremlin Client (query execution)
 Cosmos DB (result caching)
```

## Production Deployment

See [../deploy/deploy-aca.ps1](../deploy/deploy-aca.ps1) for Azure Container Apps deployment.
