# deploy.ps1
param(
  [Parameter(Mandatory=$true)][string]$BaseName,
  [Parameter(Mandatory=$true)][string]$Location,
  [ValidateSet('Core','Full')][string]$Mode = 'Core',

  [string]$Rg = "salesforcebot-rg",
  [string]$OpenAiModel = "gpt-4.1",
  [string]$OpenAiModelVersion = "2025-04-14"
)

$ErrorActionPreference = 'Stop'

# -------------------- helpers --------------------
function Ensure-Ext($name) {
  $exists = az extension list --query "[?name=='$name']" -o tsv 2>$null
  if (-not $exists) { az extension add -n $name --only-show-errors | Out-Null }
  else { az extension update -n $name --only-show-errors | Out-Null }
}
function Ensure-Provider($ns) {
  $state = az provider show -n $ns --query "registrationState" -o tsv 2>$null
  if ($state -ne "Registered") { az provider register -n $ns --wait | Out-Null }
}
function Exists($args) {
  $result = az @args -o json 2>$null
  if ($LASTEXITCODE -eq 0 -and $result) { return $true } else { return $false }
}
function Ensure-Role($oid, $scope, $roleName, $ptype="ServicePrincipal") {
  if (-not $scope) { return }
  $has = az role assignment list --assignee-object-id $oid --scope $scope --role $roleName -o tsv --query "[0].roleDefinitionName" 2>$null
  if (-not $has) {
    az role assignment create `
      --assignee-object-id $oid `
      --assignee-principal-type $ptype `
      --role $roleName `
      --scope $scope -o none
  }
}

# -------------------- context --------------------
$ctx = az account show -o json 2>$null | ConvertFrom-Json
if (-not $ctx) { throw "Please run 'az login' first." }
$tenantId = $ctx.tenantId
$subId    = $ctx.id

az config set extension.dynamic_install_allow_preview=true --only-show-errors | Out-Null
az config set core.only_show_errors=true --only-show-errors | Out-Null

# Providers & extensions we need
Ensure-Provider 'Microsoft.Web'                 # Static Web Apps
Ensure-Provider 'Microsoft.CognitiveServices'   # AOAI
Ensure-Provider 'Microsoft.DocumentDB'          # Cosmos DB
Ensure-Provider 'Microsoft.Cdn'                 # Azure Front Door Std/Premium
Ensure-Provider 'Microsoft.ApiManagement'       # APIM
Ensure-Provider 'Microsoft.Network'             # WAF policy attach
# Container Apps env is optional infra; create if possible but don't fail hard
Ensure-Provider 'Microsoft.App'
Ensure-Ext 'containerapp'

# -------------------- names --------------------
$N            = $BaseName.ToLower()
$MiName       = "$N-mi"
$SwaName      = "$N-swa"
# $AoaiName defined in OpenAI section to use eastus2 account
$EnvName      = "$N-env"        # ACA env (optional infra)
$ApimName     = "$N-apim"
$FdProfile    = "$N-fd"
$FdEndpoint   = "$N-ep"
$SwaOg        = "$N-swa-og"
$ApimOg       = "$N-apim-og"
$WafName      = "$N-waf"
$SecPolicy    = "$N-sec"
$CosmosSql    = "$N-cosmos-sql"
$CosmosGraph  = "$N-cosmos-graph"

# -------------------- RG --------------------
Write-Host ">>> Resource group" -ForegroundColor Cyan
if (-not (Exists @("group","show","-n",$Rg))) {
  az group create -n $Rg -l $Location -o none
}
$rgId = az group show -n $Rg --query id -o tsv

# -------------------- Managed Identity --------------------
Write-Host ">>> Managed Identity" -ForegroundColor Cyan
if (-not (Exists @("identity","show","-g",$Rg,"-n",$MiName))) {
  az identity create -g $Rg -n $MiName -l $Location -o none
}
$uami = az identity show -g $Rg -n $MiName -o json | ConvertFrom-Json
$miId = $uami.id
$miPid = $uami.principalId
$miClientId = $uami.clientId

# Give MI broad perms on the RG (you asked for "all permissions")
Ensure-Role $miPid $rgId "Owner"

# -------------------- Static Web Apps (service) --------------------
Write-Host ">>> Azure Static Web Apps (service)" -ForegroundColor Cyan
if (-not (Exists @("staticwebapp","show","-g",$Rg,"-n",$SwaName))) {
  az staticwebapp create -g $Rg -n $SwaName -l $Location --sku Free -o none
}
$swaHost = az staticwebapp show -g $Rg -n $SwaName --query "defaultHostname" -o tsv
$swaUrl  = "https://$swaHost"

# -------------------- Azure OpenAI (eastus2 for quota) --------------------
Write-Host ">>> Azure OpenAI + $OpenAiModel" -ForegroundColor Cyan
$aoaiLoc = "eastus2"  # eastus2 has available quota always
$AoaiName = "$BaseName-aoai-eastus2"  # Azure resource name (unique within RG)
$aoaiCreated = $false

if (-not (Exists @("cognitiveservices","account","show","-g",$Rg,"-n",$AoaiName))) {
  try {
    Write-Host "Creating Azure OpenAI account: $AoaiName in $aoaiLoc..." -ForegroundColor Yellow
    Write-Host "Attempting to set custom subdomain to: $AoaiName" -ForegroundColor Yellow
    
    az cognitiveservices account create `
      --name $AoaiName `
      --resource-group $Rg `
      --location $aoaiLoc `
      --kind OpenAI `
      --sku S0 `
      --custom-subdomain $AoaiName `
      --yes -o none
    
    # Verify creation was successful
    $testAccount = az cognitiveservices account show -g $Rg -n $AoaiName -o json 2>$null | ConvertFrom-Json
    if ($testAccount) {
      $aoaiCreated = $true
      Write-Host "Azure OpenAI account created successfully" -ForegroundColor Green
      
      # Set custom subdomain for token authentication
      Write-Host "Setting custom subdomain for token authentication..." -ForegroundColor Yellow
      try {
        az cognitiveservices account update -g $Rg -n $AoaiName --custom-domain $AoaiName -o none
        Write-Host "Custom subdomain configured successfully" -ForegroundColor Green
      } catch {
        Write-Warning "Failed to set custom subdomain: $($_.Exception.Message)"
      }
    } else {
      Write-Error "Azure OpenAI account creation appeared to succeed but account not found"
    }
  } catch {
    Write-Warning "Failed to create Azure OpenAI account: $($_.Exception.Message)"
    Write-Warning "Continuing deployment without Azure OpenAI..."
  }
} else {
  $aoaiCreated = $true
  Write-Host "Azure OpenAI account already exists" -ForegroundColor Green
  
  # Ensure custom subdomain is set for existing account
  $existingAccount = az cognitiveservices account show -g $Rg -n $AoaiName -o json | ConvertFrom-Json
  if (-not $existingAccount.properties.customSubDomainName) {
    Write-Host "Setting custom subdomain for existing account..." -ForegroundColor Yellow
    try {
      az cognitiveservices account update -g $Rg -n $AoaiName --custom-domain $AoaiName -o none
      Write-Host "Custom subdomain configured successfully" -ForegroundColor Green
    } catch {
      Write-Warning "Failed to set custom subdomain: $($_.Exception.Message)"
    }
  } else {
    Write-Host "Custom subdomain already configured" -ForegroundColor Green
  }
}

if ($aoaiCreated) {
  $aoaiId = az cognitiveservices account show -g $Rg -n $AoaiName --query id -o tsv
  # Prefer the custom subdomain endpoint
  $aoaiEndpoint = "https://$AoaiName.openai.azure.com/"

  # Model deployment (idempotent) - check if specific deployment name exists
  $deploymentName = $OpenAiModel  # Use model name as deployment name for simplicity
  $existingDep = az cognitiveservices account deployment show -g $Rg -n $AoaiName --deployment-name $deploymentName -o json 2>$null | ConvertFrom-Json
  if (-not $existingDep) {
    try {
      Write-Host "Deploying model $OpenAiModel as $deploymentName..." -ForegroundColor Yellow
      az cognitiveservices account deployment create -g $Rg -n $AoaiName --deployment-name $deploymentName `
        --model-name $OpenAiModel --model-version $OpenAiModelVersion --model-format OpenAI `
        --sku-capacity 50 --sku-name GlobalStandard -o none
      Write-Host "Model deployment created successfully" -ForegroundColor Green
    } catch {
      Write-Warning "Failed to deploy model: $($_.Exception.Message)"
    }
  } else {
    Write-Host "Model deployment '$deploymentName' already exists" -ForegroundColor Green
  }
  
  # Deploy embedding model (required for retrieval)
  $embeddingDeploymentName = "text-embedding-3-small"
  $existingEmbeddingDep = az cognitiveservices account deployment show -g $Rg -n $AoaiName --deployment-name $embeddingDeploymentName -o json 2>$null | ConvertFrom-Json
  if (-not $existingEmbeddingDep) {
    try {
      Write-Host "Deploying embedding model $embeddingDeploymentName..." -ForegroundColor Yellow
      az cognitiveservices account deployment create -g $Rg -n $AoaiName --deployment-name $embeddingDeploymentName `
        --model-name $embeddingDeploymentName --model-version 1 --model-format OpenAI `
        --sku-capacity 100 --sku-name Standard -o none
      Write-Host "Embedding model deployment created successfully" -ForegroundColor Green
    } catch {
      Write-Warning "Failed to deploy embedding model: $($_.Exception.Message)"
    }
  } else {
    Write-Host "Embedding model deployment '$embeddingDeploymentName' already exists" -ForegroundColor Green
  }

  # RBAC: AOAI
  Ensure-Role $miPid $aoaiId "Cognitive Services OpenAI User"
  
  # Add current user to OpenAI resource
  try {
    $currentUserId = az ad signed-in-user show --query id -o tsv 2>$null
    if ($currentUserId) {
      Ensure-Role $currentUserId $aoaiId "Cognitive Services OpenAI User" "User"
      Write-Host "Added current user to OpenAI resource" -ForegroundColor Green
    }
  } catch {
    Write-Warning "Could not add current user to OpenAI resource: $($_.Exception.Message)"
  }
  
  # Test OpenAI chat completions endpoint (uses Invoke-RestMethod to avoid quoting issues)
  Write-Host "Testing OpenAI chat completions endpoint..." -ForegroundColor Yellow
  try {
    $testToken = az account get-access-token --resource https://cognitiveservices.azure.com --query accessToken -o tsv 2>$null
    if ($testToken) {
      $testDeployment = $deploymentName
      $testEndpoint = "https://$AoaiName.openai.azure.com/openai/deployments/$testDeployment/chat/completions?api-version=2024-02-01"
      $testPayload = '{"messages":[{"role":"user","content":"Hello! This is a test."}],"max_tokens":20}'

      $headers = @{ Authorization = "Bearer $testToken"; "Content-Type" = "application/json" }
      $testResult = Invoke-RestMethod -Method Post -Uri $testEndpoint -Headers $headers -Body $testPayload -ErrorAction SilentlyContinue

      if ($null -ne $testResult -and $testResult.choices) {
        Write-Host " OpenAI chat completions endpoint test successful!" -ForegroundColor Green
      } else {
        Write-Host " OpenAI endpoint test did not return choices (may be DNS/propagation). Try manually:" -ForegroundColor Yellow
        Write-Host ('   $payload = ''{0}''' -f $testPayload) -ForegroundColor Gray
        Write-Host ('   Invoke-RestMethod -Method Post -Uri "{0}" -Headers @{{ Authorization = "Bearer <token>"; "Content-Type" = "application/json" }} -Body $payload' -f $testEndpoint) -ForegroundColor Gray
      }
    }
  } catch {
    Write-Warning ("Could not test OpenAI endpoint: {0}" -f $_.Exception.Message)
  }
} else {
  $aoaiEndpoint = "Not deployed due to errors"
  Write-Warning "Skipping Azure OpenAI operations since account creation failed"
}

# -------------------- Container Apps Environment (optional) --------------------
Write-Host ">>> Container Apps Environment (optional infra)" -ForegroundColor Cyan
# Some tenants hit "MaxNumberOfRegionalEnvironmentsInSubExceeded". Try to show first; fallback to list; if none create.
$envFound = $false
try {
  if (Exists @("containerapp","env","show","-g",$Rg,"-n",$EnvName)) { $envFound = $true }
} catch { $envFound = $false }
if (-not $envFound) {
  # fallback by listing in region (works even if 'env show' isn't recognized)
  $anyEnv = az containerapp env list -o json | ConvertFrom-Json | Where-Object { $_.location -eq $Location } | Select-Object -First 1
  if ($anyEnv) {
    $EnvName = $anyEnv.name
    Write-Warning "Reusing existing Container Apps environment in ${Location}: ${EnvName}"
    $envFound = $true
  }
}
if (-not $envFound) {
  try {
    az containerapp env create -g $Rg -n $EnvName -l $Location -o none
  } catch {
    Write-Warning "Could not create Container Apps env in $Location (quota or CLI). Continuing without it."
  }
}

# -------------------- Cosmos DB (NoSQL + Gremlin) - Core Infrastructure --------------------
Write-Host ">>> Cosmos DB (NoSQL + Gremlin)" -ForegroundColor Cyan
# NoSQL
if (-not (Exists @("cosmosdb","show","-g",$Rg,"-n",$CosmosSql))) {
  az cosmosdb create -g $Rg -n $CosmosSql `
    --kind GlobalDocumentDB `
    --locations regionName="$Location" failoverPriority=0 isZoneRedundant=False `
    --public-network-access Enabled -o none
}
if (-not (Exists @("cosmosdb","sql","database","show","-g",$Rg,"-a",$CosmosSql,"-n","appdb"))) {
  az cosmosdb sql database create -g $Rg -a $CosmosSql -n appdb -o none
}
$cosmosSqlId = az cosmosdb show -g $Rg -n $CosmosSql --query id -o tsv
$cosmosSqlEp = az cosmosdb show -g $Rg -n $CosmosSql --query documentEndpoint -o tsv

# Gremlin
if (-not (Exists @("cosmosdb","show","-g",$Rg,"-n",$CosmosGraph))) {
  az cosmosdb create -g $Rg -n $CosmosGraph `
    --capabilities EnableGremlin `
    --locations regionName="$Location" failoverPriority=0 isZoneRedundant=False `
    --public-network-access Enabled -o none
}
if (-not (Exists @("cosmosdb","gremlin","database","show","-g",$Rg,"-a",$CosmosGraph,"-n","graphdb"))) {
  az cosmosdb gremlin database create -g $Rg -a $CosmosGraph -n graphdb -o none
}
if (-not (Exists @("cosmosdb","gremlin","graph","show","-g",$Rg,"-a",$CosmosGraph,"-d","graphdb","-n","account_graph"))) {
  az cosmosdb gremlin graph create -g $Rg -a $CosmosGraph -d graphdb -n account_graph --partition-key-path "/partitionKey" -o none
}
$cosmosGraphId = az cosmosdb show -g $Rg -n $CosmosGraph --query id -o tsv
$cosmosGraphEp = az cosmosdb show -g $Rg -n $CosmosGraph --query documentEndpoint -o tsv

# RBAC for MI on Cosmos (data-plane) - may need adjustment per your security model
if ($aoaiCreated) {
  Ensure-Role $miPid $cosmosSqlId   "Azure AI Administrator"
  Ensure-Role $miPid $cosmosGraphId "Azure AI Administrator"
}

# -------------------- Full mode: APIM + AFD --------------------
if ($Mode -eq 'Full') {

  # ----- API Management (minimal API) -----
  Write-Host ">>> API Management (Developer)" -ForegroundColor Cyan
  if (-not (Exists @("apim","show","-g",$Rg,"-n",$ApimName))) {
    # publisher info
    $publisherName = $null; $publisherEmail = $null
    try { 
      $me = az ad signed-in-user show -o json 2>$null | ConvertFrom-Json
      if ($me) { 
        $publisherName = $me.displayName
        $publisherEmail = if ($me.mail){$me.mail}else{$me.userPrincipalName}
      }
    } catch {}
    if (-not $publisherName -or -not $publisherEmail) {
      $acct = az account show -o json | ConvertFrom-Json
      $upn  = $acct.user.name
      if (-not $publisherName) { $publisherName = $upn }
      if (-not $publisherEmail) { 
        $publisherEmail = if ($upn -like "*@*") { $upn } else { "$($env:USERNAME)@$($tenantId).onmicrosoft.com" }
      }
    }
    az apim create -g $Rg -n $ApimName -l $Location --publisher-email $publisherEmail --publisher-name $publisherName --sku-name Developer -o none
  }
  if (-not (Exists @("apim","api","show","-g",$Rg,"--service-name",$ApimName,"--api-id","acctbot"))) {
    az apim api create -g $Rg --service-name $ApimName --api-id acctbot --path "api" --display-name "acctbot" --protocols https -o none
    az apim api operation create -g $Rg --service-name $ApimName --api-id acctbot --url-template "/ask" --method POST --display-name "ask" -o none
  }

  # ----- Azure Front Door Standard (SWA /* and APIM /api/*) -----
  Write-Host ">>> Front Door (Std) + routes + WAF" -ForegroundColor Cyan
  if (-not (Exists @("afd","profile","show","-g",$Rg,"-n",$FdProfile))) {
    az afd profile create -g $Rg -n $FdProfile --sku Standard_AzureFrontDoor -o none
  }
  if (-not (Exists @("afd","endpoint","show","-g",$Rg,"--profile-name",$FdProfile,"-n",$FdEndpoint))) {
    az afd endpoint create -g $Rg --profile-name $FdProfile -n $FdEndpoint -o none
  }
  if (-not (Exists @("afd","origin-group","show","-g",$Rg,"--profile-name",$FdProfile,"-n",$SwaOg))) {
    az afd origin-group create -g $Rg --profile-name $FdProfile -n $SwaOg --session-affinity-enabled Disabled -o none
  }
  if (-not (Exists @("afd","origin","show","-g",$Rg,"--profile-name",$FdProfile,"--origin-group-name",$SwaOg,"-n","swa"))) {
    az afd origin create -g $Rg --profile-name $FdProfile --origin-group-name $SwaOg -n swa `
      --host-name $swaHost --origin-host-header $swaHost --enabled-state Enabled -o none
  }

  $apimGw = (az apim show -g $Rg -n $ApimName --query "gatewayUrl" -o tsv).Replace("https://","")
  if (-not (Exists @("afd","origin-group","show","-g",$Rg,"--profile-name",$FdProfile,"-n",$ApimOg))) {
    az afd origin-group create -g $Rg --profile-name $FdProfile -n $ApimOg -o none
  }
  if (-not (Exists @("afd","origin","show","-g",$Rg,"--profile-name",$FdProfile,"--origin-group-name",$ApimOg,"-n","apim"))) {
    az afd origin create -g $Rg --profile-name $FdProfile --origin-group-name $ApimOg -n apim `
      --host-name $apimGw --origin-host-header $apimGw --enabled-state Enabled -o none
  }

  if (-not (Exists @("afd","route","show","-g",$Rg,"--profile-name",$FdProfile,"--endpoint-name",$FdEndpoint,"-n","api-route"))) {
    az afd route create -g $Rg --profile-name $FdProfile --endpoint-name $FdEndpoint -n api-route `
      --origin-group $ApimOg --https-redirect Enabled --forwarding-protocol HttpsOnly `
      --supported-protocols Https --patterns-to-match "/api/*" -o none
  }
  if (-not (Exists @("afd","route","show","-g",$Rg,"--profile-name",$FdProfile,"--endpoint-name",$FdEndpoint,"-n","spa-route"))) {
    az afd route create -g $Rg --profile-name $FdProfile --endpoint-name $FdEndpoint -n spa-route `
      --origin-group $SwaOg --https-redirect Enabled --forwarding-protocol HttpsOnly `
      --supported-protocols Https --patterns-to-match "/*" -o none
  }

  if (-not (Exists @("network","front-door","waf-policy","show","-g",$Rg,"-n",$WafName))) {
    az network front-door waf-policy create -g $Rg -n $WafName --mode Prevention --sku Standard_AzureFrontDoor -o none
  }
  $wafId = az network front-door waf-policy show -g $Rg -n $WafName --query id -o tsv
  $afdEndpointRes = "/subscriptions/$subId/resourceGroups/$Rg/providers/Microsoft.Cdn/profiles/$FdProfile/afdEndpoints/$FdEndpoint"
  if (-not (Exists @("afd","security-policy","show","-g",$Rg,"--profile-name",$FdProfile,"--security-policy-name",$SecPolicy))) {
    az afd security-policy create -g $Rg --profile-name $FdProfile --security-policy-name $SecPolicy --domains $afdEndpointRes --waf-policy $wafId -o none
  }
}

# -------------------- Summary --------------------
Write-Host ""
Write-Host "================ DEPLOYMENT COMPLETE ================" -ForegroundColor Cyan
Write-Host ("SWA URL              : {0}" -f $swaUrl)
Write-Host ("AOAI endpoint        : {0}" -f $aoaiEndpoint)
Write-Host ("AOAI chat model      : {0}" -f $OpenAiModel)
Write-Host ("AOAI embedding model : text-embedding-3-small")
Write-Host ("Cosmos NoSQL ep      : {0}" -f $cosmosSqlEp)
Write-Host ("Cosmos Gremlin ep    : {0}" -f $cosmosGraphEp)
Write-Host ("Managed Identity     : {0} (clientId: {1})" -f $MiName, $miClientId)
Write-Host ("Mode                 : {0}" -f $Mode)
Write-Host "====================================================="
