# Frontend

This React + Express frontend can run locally (dev mode) or be deployed to Azure App Service.

Key scripts:
- `npm run start:dev` – CRA dev server with hot reload
- `npm start` – Production Express server (serves build + /login)

See `DEPLOY_AZURE_APP_SERVICE.md` for detailed Azure deployment steps (App Service Plan + Web App in resource group `salesforcebot-rg`).

# Salesforce AI Assistant - React Frontend

This is the React frontend for the Salesforce AI Assistant chatbot.

## Features

- 🔐 Username/Password authentication
- 💬 Real-time chat interface
- 🤖 Integration with Azure-hosted orchestrator API
- 📊 Shows execution metadata (rounds, MCPs used, execution time)
- 🎨 Beautiful gradient UI with smooth animations

## Setup

### 1. Install Dependencies

```bash
cd frontend
npm install
```

### 2. Configure API URL

For local testing against Azure API:
```bash
# The API URL is already set to your Azure endpoint in App.js
# No changes needed!
```

For local testing against local API:
```bash
# Create .env file
echo "REACT_APP_API_URL=http://localhost:8000" > .env
```

### 3. Run the App

```bash
npm start
```

The app will open at `http://localhost:3000`

## Usage

1. Enter any username/password (for demo purposes)
2. When prompted, paste your Azure AD token:
   ```bash
   az account get-access-token --query accessToken -o tsv
   ```
3. Start chatting with the AI assistant!

## Authentication

The frontend uses Azure AD tokens for authentication. The backend validates:
- **Issuer (tenant ID)** - Ensures token is from correct Azure AD tenant
- **Signature** - Validates token hasn't been tampered with

**Note:** For local testing, token expiration checking is disabled (see backend auth_provider.py).

## Environment Variables

- `REACT_APP_API_URL` - Backend API URL (default: your Azure Container App URL)

## Deployment to Azure

```bash
# Build the production app
npm run build

# Deploy to Azure Static Web Apps (example)
# Install Azure Static Web Apps CLI
npm install -g @azure/static-web-apps-cli

# Deploy
swa deploy ./build --env production
```

Or use Azure Container Apps, Azure App Service, or any static hosting service.
