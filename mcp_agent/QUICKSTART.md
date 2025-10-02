# MCP Agent Framework - Quick Start Guide

## 🚀 Ready to Run in 5 Minutes

### Prerequisites
- Python 3.11+
- Azure CLI installed and logged in (`az login`)
- Access to Azure resources (OpenAI, Cosmos DB, etc.)

### Step 1: Navigate to Project
```bash
cd mcp_agent
```

### Step 2: Environment Setup

The `.env` files are already configured for dev mode! Just verify they exist:
```bash
ls orchestrator/.env
ls mcps/salesforce_mcp/.env
```

Both files have `DEV_MODE=true` set, which means:
- ✅ No JWT validation required
- ✅ Uses Azure CLI credentials
- ✅ Default admin user for testing

### Step 3: Run Orchestrator

**Terminal 1 - Start Orchestrator**:
```bash
cd orchestrator
pip install -r requirements.txt
export PYTHONPATH=$PYTHONPATH:$(pwd)/../../shared  # Linux/Mac
# or
set PYTHONPATH=%PYTHONPATH%;%cd%\..\..\shared      # Windows CMD
# or
$env:PYTHONPATH += ";$(pwd)\..\..\shared"          # Windows PowerShell

python src/main.py
```

Expected output:
```
INFO: Starting MCP Orchestrator
INFO: Azure OpenAI client initialized
INFO: Cosmos DB client initialized
INFO: MCP loader service initialized, mcp_count=1
INFO: Application started successfully
```

### Step 4: Run Salesforce MCP

**Terminal 2 - Start Salesforce MCP**:
```bash
cd mcps/salesforce_mcp
pip install -r requirements.txt
export PYTHONPATH=$PYTHONPATH:$(pwd)/../../../shared  # Linux/Mac
# or
set PYTHONPATH=%PYTHONPATH%;%cd%\..\..\..\shared      # Windows CMD
# or
$env:PYTHONPATH += ";$(pwd)\..\..\..\shared"          # Windows PowerShell

python src/main.py
```

Expected output:
```
INFO: Starting Salesforce MCP, dev_mode=true
INFO: Salesforce MCP started successfully
```

### Step 5: Test the System

**Terminal 3 - Send Test Request**:
```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [
      {"role": "user", "content": "What tools do you have available?"}
    ],
    "user_id": "dev@example.com"
  }'
```

Expected response:
```json
{
  "session_id": "...",
  "turn_id": "...",
  "choices": [{
    "message": {
      "role": "assistant",
      "content": "I have access to several tools including SQL queries, graph queries, and account resolution..."
    }
  }],
  "execution_time_ms": 1234
}
```

## 🐛 Troubleshooting

### Import Errors
If you see `ModuleNotFoundError`:
```bash
# Make sure PYTHONPATH includes shared module
echo $PYTHONPATH  # Should show path to shared/
```

### Azure Authentication Errors
```bash
# Ensure you're logged in
az login

# Verify account
az account show
```

### Port Already in Use
```bash
# Orchestrator (port 8000)
lsof -i :8000  # Find process
kill -9 <PID>  # Kill it

# Salesforce MCP (port 8001)
lsof -i :8001
kill -9 <PID>
```

### Cannot Connect to Azure Resources
1. Check `.env` files have correct endpoints
2. Verify Azure CLI credentials: `az account show`
3. Check resource permissions

## 🐳 Docker Alternative

If you prefer Docker:

```bash
# From mcp_agent/ directory
docker-compose up --build
```

This starts both orchestrator and salesforce_mcp automatically!

## 📝 Test Scenarios

### 1. Tool Discovery
```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "What can you help me with?"}],
    "user_id": "dev@example.com"
  }'
```

### 2. SQL Query (if Fabric configured)
```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "Show me all accounts"}],
    "user_id": "dev@example.com"
  }'
```

### 3. Account Resolution
```bash
curl -X POST http://localhost:8000/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "Find account Contoso"}],
    "user_id": "dev@example.com"
  }'
```

## 🎯 What's Happening Under the Hood

1. **Request arrives** at orchestrator (`/api/v1/chat`)
2. **Auth service** extracts RBAC context (dev user with admin role)
3. **MCP loader** determines accessible MCPs (salesforce_mcp)
4. **Tool discovery** fetches tools from salesforce_mcp
5. **Orchestrator LLM** receives user question + available tools
6. **LLM decides** which tools to call
7. **MCP client** routes tool calls to salesforce_mcp
8. **Salesforce MCP** executes tools (SQL/Graph queries)
9. **Results** are sent back to orchestrator
10. **Final synthesis** generates natural language response

## 🔍 Verify It's Working

Check the logs for these key messages:

**Orchestrator**:
```
INFO: Discovering tools from MCPs, mcps=['salesforce_mcp']
INFO: Tool discovery complete, total_tools=3
INFO: Determined accessible MCPs, roles=['admin'], mcps=['salesforce_mcp']
```

**Salesforce MCP**:
```
INFO: Executing SQL query
INFO: Executing Gremlin query
```

## ✅ Success!

If you see:
- ✅ Both services started without errors
- ✅ Curl request returns a JSON response
- ✅ Response contains an assistant message

**You're ready to go!** 🎉

## 📚 Next Steps

1. Read [README.md](README.md) for architecture details
2. Read [IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md) for design decisions
3. Try adding a new MCP (copy salesforce_mcp template)
4. Explore the code and customize for your use case

## 🆘 Still Having Issues?

Check:
1. Python version: `python --version` (should be 3.11+)
2. Azure CLI version: `az --version`
3. Network connectivity to Azure
4. `.env` files exist and are readable
5. All dependencies installed: `pip list`

If all else fails, check the logs in both terminals for specific error messages.
