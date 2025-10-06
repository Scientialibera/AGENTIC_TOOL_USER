# Agentic Framework - 5-Minute Quickstart

Deploy the complete framework to a client's Azure tenant in 5 minutes.

## Prerequisites Checklist

- [ ] **PowerShell 7+** installed
- [ ] **Azure CLI** installed (`az --version`)
- [ ] **Docker Desktop** running
- [ ] **Python 3.11+** installed
- [ ] Logged into client's Azure (`az login --tenant <tenant-id>`)
- [ ] Subscription selected (`az account set --subscription <sub-id>`)

## One-Command Deployment

```powershell
.\deploy\main.ps1 -BaseName "clientbot" -Location "eastus" -Environment "prod"
```

**That's it!** The script will:
- ✅ Deploy all infrastructure (Bicep)
- ✅ Configure RBAC permissions
- ✅ Generate `.env` file
- ✅ Initialize Cosmos DB
- ✅ Deploy all Container Apps

## What Gets Deployed

### Azure Resources
| Resource | SKU | Purpose |
|----------|-----|---------|
| Azure OpenAI | S0 | LLM inference (GPT-4 + embeddings) |
| Cosmos DB (NoSQL) | 400 RU/s | Configuration, prompts, chat history |
| Cosmos DB (Gremlin) | 400 RU/s | Graph relationships |
| Container Apps Env | Consumption | Host for microservices |
| Container Registry | Basic | Docker images |
| Managed Identity | N/A | Authentication |
| Log Analytics | Pay-as-you-go | Monitoring |

### Container Apps
| App | Port | Ingress | Purpose |
|-----|------|---------|---------|
| **orchestrator** | 8000 | External | Main API endpoint |
| **graph-mcp** | 8001 | Internal | Graph/relationship queries |
| **interpreter-mcp** | 8002 | Internal | Code execution |
| **sql-mcp** | 8003 | Internal | SQL queries |

## Cost Estimate

**Production (~$360/month)**:
- Azure OpenAI: ~$200 (usage-based)
- Cosmos DB: ~$60 (1000 RU/s × 2)
- Container Apps: ~$100 (with scaling)

**Development (~$105/month)**:
- Azure OpenAI: ~$50
- Cosmos DB: ~$25 (400 RU/s × 2)
- Container Apps: ~$30

## Post-Deployment

### 1. Get Orchestrator URL

```powershell
az containerapp show -n orchestrator -g clientbot-rg --query "properties.configuration.ingress.fqdn" -o tsv
```

### 2. Test the Deployment

```powershell
# Health check
curl https://<orchestrator-url>/health

# List available MCPs
curl https://<orchestrator-url>/mcps

# Test chat endpoint
curl -X POST https://<orchestrator-url>/chat `
    -H "Content-Type: application/json" `
    -d '{
        "messages": [{"role": "user", "content": "Hello"}],
        "user_id": "test@example.com"
    }'
```

### 3. View Logs

```powershell
# Orchestrator logs
az containerapp logs show -n orchestrator -g clientbot-rg --tail 50 --follow

# MCP logs
az containerapp logs show -n sql-mcp -g clientbot-rg --tail 50
```

## Customization

### Change Environment Settings

Edit `deploy/infrastructure/parameters/prod.parameters.json`:
- Increase/decrease Cosmos DB throughput
- Change model deployments
- Adjust Container Apps scaling

Then redeploy:
```powershell
.\deploy\main.ps1 -BaseName "clientbot" -SkipData -SkipApps
```

### Update Application Code

```powershell
# Rebuild and redeploy Container Apps only
.\deploy\apps\deploy-container-apps.ps1 -ResourceGroup "clientbot-rg"
```

### Add Custom Data

Edit files in `scripts/assets/`:
- `prompts/` - System prompts
- `functions/tools/` - Tool definitions
- `schema/` - SQL schema

Then reinitialize:
```powershell
python .\deploy\data\init-cosmos-data.py
```

## Troubleshooting

### "Not authorized to perform action"
**Fix**: Ensure you have Contributor + User Access Administrator roles

### "Container App won't start"
**Fix**: Check logs with `az containerapp logs show -n <app> -g <rg>`

### "MCP not discovered"
**Fix**: Verify MCP is running: `az containerapp list -g <rg> -o table`

### "Cosmos DB connection failed"
**Fix**: Wait 60 seconds for RBAC to propagate, or run `.\deploy\security\configure-rbac.ps1` again

## Next Steps

1. **Configure Authentication** - Set up Azure AD app registration for production JWT validation
2. **Deploy Frontend** - Deploy the web UI for end users
3. **Set up Monitoring** - Configure Application Insights alerts
4. **Scale Resources** - Adjust Cosmos DB throughput and Container Apps replicas based on load

## Support

- 📖 Full documentation: [deploy/README.md](README.md)
- 🏗️ Architecture guide: [../CLAUDE.md](../CLAUDE.md)
- 📝 Main README: [../README.md](../README.md)

---

**Deployment Time**: ~15-20 minutes
**Total Cost**: Starting at ~$105/month (dev) or ~$360/month (prod)
