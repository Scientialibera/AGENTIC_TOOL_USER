# Agentic Framework - Enterprise Deployment

This directory contains enterprise-grade deployment automation for the Agentic Framework, designed for easy client deployments in multi-tenant Azure environments.

## 📁 Directory Structure

```
deploy/
├── main.ps1                       # Master orchestration script (start here!)
├── infrastructure/                # Infrastructure as Code (Bicep)
│   ├── main.bicep                 # Main infrastructure template
│   ├── modules/                   # Modular Bicep components
│   │   ├── identity.bicep         # Managed Identity
│   │   ├── openai.bicep           # Azure OpenAI
│   │   ├── cosmos.bicep           # Cosmos DB (NoSQL)
│   │   ├── gremlin.bicep          # Cosmos DB (Gremlin)
│   │   ├── acr.bicep              # Container Registry
│   │   ├── logs.bicep             # Log Analytics
│   │   └── container-apps.bicep   # Container Apps Environment
│   └── parameters/                # Environment-specific parameters
│       ├── dev.parameters.json
│       └── prod.parameters.json
├── security/                      # RBAC and permissions
│   └── configure-rbac.ps1         # Automated RBAC assignment
├── data/                          # Data initialization
│   └── init-cosmos-data.py        # Cosmos DB data seeding
├── apps/                          # Application deployment
│   └── deploy-container-apps.ps1  # Container Apps deployment
└── utils/                         # Helper scripts
    └── generate-env.ps1           # .env file generator
```

## 🚀 Quick Start (New Client Deployment)

Deploy the complete framework in a new Azure subscription/tenant:

```powershell
# 1. Login to client's Azure tenant
az login --tenant <client-tenant-id>

# 2. Set the subscription
az account set --subscription <client-subscription-id>

# 3. Run the master deployment script
.\deploy\main.ps1 -BaseName "clientbot" -Location "eastus" -Environment "prod"
```

That's it! The script will:
- ✅ Deploy all Azure infrastructure (Bicep)
- ✅ Configure managed identity permissions
- ✅ Generate `.env` file
- ✅ Initialize Cosmos DB with sample data
- ✅ Deploy all Container Apps

## 📋 Prerequisites

### Required Tools
- **PowerShell 7+** - [Download](https://aka.ms/powershell)
- **Azure CLI** - [Download](https://aka.ms/azure-cli)
- **Docker Desktop** - [Download](https://www.docker.com/products/docker-desktop) (for Container Apps)
- **Python 3.11+** - [Download](https://www.python.org/downloads/) (for data initialization)

### Required Azure Permissions

The deploying user or service principal needs:
- **Subscription Contributor** - To create resources
- **User Access Administrator** - To assign RBAC roles
- **Azure OpenAI Contributor** - To create OpenAI deployments

### Azure Resource Providers

Ensure these are registered in the subscription:
```powershell
az provider register --namespace Microsoft.CognitiveServices
az provider register --namespace Microsoft.DocumentDB
az provider register --namespace Microsoft.App
az provider register --namespace Microsoft.ContainerRegistry
az provider register --namespace Microsoft.OperationalInsights
az provider register --namespace Microsoft.ManagedIdentity
```

## 📖 Detailed Deployment Steps

### Option 1: Complete Deployment (Recommended)

Use the master script for a full zero-to-hero deployment:

```powershell
.\deploy\main.ps1 `
    -BaseName "mybot" `
    -Location "eastus" `
    -Environment "prod"
```

### Option 2: Step-by-Step Deployment

For more control, run each phase individually:

#### Step 1: Deploy Infrastructure

```powershell
# Deploy using Bicep
az group create -n mybot-rg -l eastus

az deployment group create `
    --name "agentic-deployment" `
    --resource-group "mybot-rg" `
    --template-file ".\deploy\infrastructure\main.bicep" `
    --parameters ".\deploy\infrastructure\parameters\prod.parameters.json" `
    --parameters baseName=mybot location=eastus
```

#### Step 2: Configure RBAC

```powershell
.\deploy\security\configure-rbac.ps1 -ResourceGroup "mybot-rg"
```

#### Step 3: Generate .env File

```powershell
.\deploy\utils\generate-env.ps1 -ResourceGroup "mybot-rg"
```

#### Step 4: Initialize Data

```powershell
python .\deploy\data\init-cosmos-data.py
```

#### Step 5: Deploy Container Apps

```powershell
.\deploy\apps\deploy-container-apps.ps1 -ResourceGroup "mybot-rg"
```

## 🔧 Configuration

### Environment-Specific Parameters

Customize deployment for different environments using parameter files:

**Development** (`infrastructure/parameters/dev.parameters.json`):
- Lower throughput (400 RU/s)
- Consumption plan for Container Apps
- Minimal replicas

**Production** (`infrastructure/parameters/prod.parameters.json`):
- Higher throughput (1000 RU/s)
- Premium plan option for Container Apps
- Auto-scaling enabled

### Naming Conventions

Resources are named using the pattern: `<baseName>-<resourceType>-<uniqueSuffix>`

Examples:
- Managed Identity: `mybot-identity`
- Azure OpenAI: `mybot-openai-abc123`
- Cosmos DB: `mybot-cosmos-abc123`
- Container Registry: `mybotacrabc123`

## 🔐 Security & RBAC

The framework uses a single User-Assigned Managed Identity with these permissions:

### Azure OpenAI
- **Role**: Cognitive Services OpenAI User
- **Scope**: OpenAI account
- **Purpose**: LLM inference

### Cosmos DB (NoSQL)
- **Role**: Cosmos DB Built-in Data Contributor
- **Scope**: Cosmos DB account
- **Purpose**: Read/write configuration and chat data

### Cosmos DB (Gremlin)
- **Role**: Cosmos DB Built-in Data Contributor
- **Scope**: Gremlin account
- **Purpose**: Graph queries

### Container Registry
- **Role**: AcrPull
- **Scope**: Container Registry
- **Purpose**: Pull Docker images

All permissions are assigned automatically by `security/configure-rbac.ps1`.

## 🏗️ Infrastructure Components

### Required Resources
- **Managed Identity** - Authentication for all services
- **Azure OpenAI** - LLM and embeddings
- **Cosmos DB (NoSQL)** - Configuration, prompts, chat history
- **Cosmos DB (Gremlin)** - Graph relationships
- **Container Apps Environment** - Host for microservices
- **Log Analytics** - Monitoring and diagnostics

### Optional Resources
- **Azure Container Registry** - Custom Docker images (set `enableContainerRegistry=true`)

## 🧪 Testing the Deployment

### Verify Infrastructure

```powershell
# List all resources
az resource list -g mybot-rg -o table

# Check Container Apps status
az containerapp list -g mybot-rg --query "[].{Name:name, Status:properties.runningStatus}" -o table
```

### Test Orchestrator API

```powershell
# Get orchestrator URL
$orchUrl = az containerapp show -n orchestrator -g mybot-rg --query "properties.configuration.ingress.fqdn" -o tsv

# Health check
curl "https://$orchUrl/health"

# List MCPs
curl "https://$orchUrl/mcps"

# List tools
curl "https://$orchUrl/tools"

# Test chat
curl -X POST "https://$orchUrl/chat" `
    -H "Content-Type: application/json" `
    -d '{
        "messages": [{"role": "user", "content": "Hello"}],
        "user_id": "test@example.com"
    }'
```

### View Logs

```powershell
# Orchestrator logs
az containerapp logs show -n orchestrator -g mybot-rg --tail 50 --follow

# MCP logs
az containerapp logs show -n sql-mcp -g mybot-rg --tail 50
```

## 🔄 Updating the Deployment

### Update Container Apps Only

```powershell
.\deploy\main.ps1 `
    -BaseName "mybot" `
    -SkipInfrastructure `
    -SkipData
```

### Update Data Only

```powershell
.\deploy\main.ps1 `
    -BaseName "mybot" `
    -SkipInfrastructure `
    -SkipApps
```

### Rebuild and Redeploy Specific Container App

```powershell
# Rebuild Docker image
docker build -t mybot acrabc123.azurecr.io/orchestrator:v2 -f ./agentic_framework/orchestrator/Dockerfile ./agentic_framework
docker push mybotacrabc123.azurecr.io/orchestrator:v2

# Update Container App
az containerapp update `
    -n orchestrator `
    -g mybot-rg `
    --image mybotacrabc123.azurecr.io/orchestrator:v2
```

## 🗑️ Cleanup

### Delete All Resources

```powershell
# Delete resource group (removes everything)
az group delete -n mybot-rg --yes --no-wait
```

### Delete Specific Resources

```powershell
# Delete Container Apps only
az containerapp delete -n orchestrator -g mybot-rg --yes
az containerapp delete -n sql-mcp -g mybot-rg --yes
az containerapp delete -n graph-mcp -g mybot-rg --yes
```

## 📊 Cost Estimation

Typical monthly costs for different environments:

### Development
- Azure OpenAI: ~$50 (30K TPM chat, 120K TPM embeddings)
- Cosmos DB: ~$25 (400 RU/s x 2 accounts)
- Container Apps: ~$30 (Consumption plan)
- **Total**: ~$105/month

### Production
- Azure OpenAI: ~$200+ (varies by usage)
- Cosmos DB: ~$60 (1000 RU/s x 2 accounts)
- Container Apps: ~$100 (Premium plan with scaling)
- **Total**: ~$360+/month

*Estimates based on East US pricing. Actual costs vary by usage.*

## 🆘 Troubleshooting

### Common Issues

**Issue**: "Not authorized to perform action"
**Solution**: Ensure you have Contributor + User Access Administrator roles on the subscription

**Issue**: "Resource provider not registered"
**Solution**: Run `az provider register --namespace <provider>` for each required provider

**Issue**: "Container App fails to start"
**Solution**: Check logs with `az containerapp logs show` and verify environment variables

**Issue**: "Cosmos DB connection fails"
**Solution**: Verify RBAC permissions with `configure-rbac.ps1` and wait 60 seconds for propagation

**Issue**: "Docker image pull failed"
**Solution**: Ensure managed identity has AcrPull role on container registry

### Get Support

1. Check logs: `az containerapp logs show -n <app-name> -g <rg> --tail 100`
2. Review deployment outputs: `az deployment group show -n <deployment-name> -g <rg>`
3. Verify resource health: `az resource list -g <rg> --query "[].{Name:name, Type:type, Status:provisioningState}"`

## 📚 Additional Resources

- [Azure Bicep Documentation](https://learn.microsoft.com/azure/azure-resource-manager/bicep/)
- [Container Apps Documentation](https://learn.microsoft.com/azure/container-apps/)
- [Azure OpenAI Documentation](https://learn.microsoft.com/azure/ai-services/openai/)
- [Cosmos DB Documentation](https://learn.microsoft.com/azure/cosmos-db/)
- [Managed Identity Documentation](https://learn.microsoft.com/azure/active-directory/managed-identities-azure-resources/)

## 🔗 Related Documentation

- [Main README](../README.md) - Project overview
- [CLAUDE.md](../CLAUDE.md) - Development guide
- [DEPLOYMENT.md](../DEPLOYMENT.md) - Legacy deployment docs
