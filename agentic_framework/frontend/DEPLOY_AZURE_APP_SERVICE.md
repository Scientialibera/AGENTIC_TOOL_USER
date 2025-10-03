Azure App Service Deployment (Frontend)
======================================

This document outlines manual deployment of the React frontend (served by Express) to Azure App Service.

Resources (existing / to create):
- Resource Group: salesforcebot-rg
- App Service Plan: salesforcebot-plan (Linux, S1 or B1)
- Web App: salesforcebot-frontend (adjust if name taken)

Local Build
-----------
1. Install deps: npm install
2. Build: npm run build
3. (Optional) Test locally: APP_PASSWORD_HASH=<hash> APP_USERNAME=demo node server.js

Generate Password Hash
----------------------
node -e "const bcrypt=require('bcryptjs'); const pw='REPLACE_WITH_PASSWORD'; bcrypt.genSalt(12, (e,s)=>bcrypt.hash(pw,s,(e,h)=>console.log(h)));"

Azure CLI Steps
---------------
az group create -n salesforcebot-rg -l westus2   # (skip if exists)
az appservice plan create -g salesforcebot-rg -n salesforcebot-plan --sku B1 --is-linux
az webapp create -g salesforcebot-rg -p salesforcebot-plan -n salesforcebot-frontend --runtime "NODE:20-lts"

Configure Settings (store only hash):
az webapp config appsettings set -g salesforcebot-rg -n salesforcebot-frontend --settings APP_USERNAME=demo APP_PASSWORD_HASH="<bcrypt-hash>" NODE_ENV=production

Deployment Options
------------------
ZIP Deploy:
  npm ci
  npm run build
  powershell Compress-Archive -Path build/* -DestinationPath site.zip
  az webapp deploy --resource-group salesforcebot-rg --name salesforcebot-frontend --src-path site.zip --type zip

Container Deploy (Alternative):
  Create a Dockerfile based on node:20-alpine that runs `npm ci && npm run build` then `node server.js`.

Post-Deployment
---------------
az webapp browse -g salesforcebot-rg -n salesforcebot-frontend

Logs:
az webapp log config -g salesforcebot-rg -n salesforcebot-frontend --application-logging filesystem --level information
az webapp log tail -g salesforcebot-rg -n salesforcebot-frontend

Rollback
--------
Redeploy previous ZIP or use deployment slots (create slot before initial prod rollout for safer swaps).

Security Notes
--------------
- Only store bcrypt hash, never plaintext.
- Consider enabling HTTPS-only (default on) and adding Azure Front Door / WAF for production.
- Restrict CORS origins if adding API reverse proxy behavior.
