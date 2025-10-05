# Interpreter MCP Server

This MCP provides code execution capabilities using Azure OpenAI Assistants (Code Interpreter).

## Local Setup

```powershell
cd mcps/interpreter
pip install -r requirements.txt
python server.py
```

Server will start on http://localhost:8003

## Environment Variables

Required:
- `AOAI_ENDPOINT` - Azure OpenAI endpoint
- `AOAI_CHAT_DEPLOYMENT` - Chat model deployment name
- `COSMOS_ENDPOINT` - Cosmos DB endpoint
- `COSMOS_DATABASE_NAME` - Database name

Optional:
- `DEV_MODE=true` - Enable dev mode with auth bypass

## Docker Build

```powershell
# From agentic_framework root
docker build -t interpreter-mcp -f mcps/interpreter/Dockerfile .
docker run -p 8003:8003 --env-file .env interpreter-mcp
```

## Testing

Use the existing test file at `tests/test_interpreter_mcp.py` to invoke the tool.
