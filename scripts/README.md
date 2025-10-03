Scripts for local development and deploying artifacts to Cosmos DB.

Files:
- test_env/set_env.ps1: Writes a .env file with sensible defaults for development.
- test_env/start_server.ps1: Starts the FastAPI app with uvicorn and writes logs to server.log.
- test_env/upload_artifacts.py: Python script that uploads prompts and function definitions from scripts/assets to Cosmos DB. It deletes existing items before reuploading.
- infra/deploy.ps1: Deployment script for infrastructure.

Usage:
1. From project root, create the .env:
   Powershell: .\scripts\test_env\set_env.ps1
2. Start the server:
   Powershell: .\scripts\test_env\start_server.ps1
3. Upload prompts and functions:
   python .\scripts\test_env\upload_artifacts.py

Notes:
- The upload script expects the app settings in .env and will attempt to create a Cosmos DB client using the configured endpoint and credentials.
- The scripts consolidate previously scattered files under scripts/assets for easier management.
 
```markdown
Scripts for local development and for uploading prompts and agent/function artifacts to Cosmos DB.

Overview
 - `test_env/set_env.ps1` - merges `.env.example` into `.env` (preserving existing values) and, if provided, performs best-effort Azure discovery for AOAI and Cosmos endpoints and AOAI deployment names. Requires the Azure CLI (az) and an authenticated principal.
 - `test_env/start_server.ps1` - starts the FastAPI app with uvicorn and writes logs to `server.log`.
 - `test_env/upload_artifacts.py` - deterministic uploader that loads settings from `.env` and uploads prompts and function/agent definitions from `scripts/assets` into Cosmos DB.
 - `infra/deploy.ps1` - deployment script for infrastructure provisioning.

Key security and provisioning notes
 - These scripts do NOT use or recommend account keys. All provisioning and management operations are performed using AAD via the Azure CLI (az) or must be pre-created by an administrator.
 - If you do not have management permissions, pre-create the Cosmos DB database and containers (or ask an administrator to do so). The uploader will fail with a clear error if it cannot access the database/containers.

Usage (typical dev flow)
1. From the project root, merge and populate .env (optionally provide a resource group to auto-discover endpoints):
   Powershell: .\scripts\test_env\set_env.ps1 -ResourceGroup <your-resource-group>
2. Start the API in the background (writes logs to `server.log`):
   Powershell: .\scripts\test_env\start_server.ps1
3. Wait until the server /health endpoint returns 200, then upload prompts and functions:
   python .\scripts\test_env\upload_artifacts.py

Where the artifacts live
 - `scripts/assets/prompts` - system prompts (markdown files). Filenames map to prompt IDs.
 - `scripts/assets/functions/tools` - tool/function JSON definitions. Files should contain a top-level `functions` array.
 - `scripts/assets/functions/agents` - agent registration JSON files describing agent metadata.

How the uploader behaves
 - The uploader loads `.env` to obtain AOAI/COSMOS/SEARCH settings.
 - Before attempting to connect, it performs a best-effort provisioning step using the Azure CLI (AAD) to create the database and containers if they are missing and the signed-in principal has permissions.
 - If provisioning is not allowed for the signed-in principal, the uploader will exit with an error and instructions to pre-create the required Cosmos resources.

Troubleshooting
 - If the uploader fails with Cosmos DB authorization errors, ensure your az account has the necessary data-plane RBAC role (e.g., Cosmos DB Built-in Data Contributor) or create the database/containers manually.
 - If AOAI deployments are not discovered automatically, set `AOAI_CHAT_DEPLOYMENT` and `AOAI_EMBEDDING_DEPLOYMENT` in `.env`.

```
