
param(
	[string]$ResourceGroup
)

# Resolve repository root up-front so env files are read/written from the repo root
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$repoRoot = Resolve-Path (Join-Path -Path $scriptDir -ChildPath "..\..")

# Paths to env files in the repository root
$envPath = Join-Path -Path $repoRoot -ChildPath ".env"
$examplePath = Join-Path -Path $repoRoot -ChildPath ".env.example"

# This script merges `.env.example` into `.env` and performs best-effort Azure discovery
# when a resource group is supplied. Discovery requires the Azure CLI (`az`) and an
# authenticated principal. Management/provisioning operations are executed via AAD/az and
# do NOT use account keys. If discovery or provisioning fails due to permission limits,
# set the required environment variables manually or have an administrator pre-create
# the Cosmos DB resources.

function Test-EnvFileBOM {
	param([string]$path)
	if (Test-Path $path) {
		$bytes = Get-Content -Path $path -Encoding Byte -TotalCount 3
		if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
			return $true
		}
	}
	return $false
}

function Remove-EnvFileBOM {
	param([string]$path)
	if (Test-Path $path) {
		$content = Get-Content -Path $path -Encoding UTF8 -Raw
		if ($content -and $content.StartsWith([char]0xFEFF)) {
			$content = $content.Substring(1)
			Set-Content -Path $path -Value $content -Encoding UTF8 -NoNewline
			Write-Output "Removed BOM from $path"
		}
	}
}

function Read-EnvFile {
	param([string]$path)
	$h = @{}
	if (Test-Path $path) {
		Get-Content $path | ForEach-Object {
			if ($_ -match '^(\s*#|\s*$)') { return }
			$parts = $_ -split '=', 2
			if ($parts.Length -eq 2) { $h[$parts[0].Trim()] = $parts[1].Trim() }
		}
	}
	return $h
}

function Write-EnvFile {
	param([string]$path, [hashtable]$env)
	$orderedKeys = @(
		'DEV_MODE','AOAI_ENDPOINT','AOAI_CHAT_DEPLOYMENT','AOAI_EMBEDDING_DEPLOYMENT',
		'AZURE_OPENAI_ENDPOINT','AZURE_OPENAI_API_VERSION','AZURE_OPENAI_CHAT_DEPLOYMENT_NAME','AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME',
		'COSMOS_ENDPOINT','COSMOS_DATABASE_NAME','COSMOS_CHAT_CONTAINER','COSMOS_CACHE_CONTAINER','COSMOS_FEEDBACK_CONTAINER','COSMOS_PROCESSED_FILES_CONTAINER','COSMOS_PROMPTS_CONTAINER','COSMOS_SQL_SCHEMA_CONTAINER','COSMOS_ACCOUNT_RESOLVER_CONTAINER','COSMOS_AGENT_FUNCTIONS_CONTAINER',
		'AZURE_COSMOS_ENDPOINT','AZURE_COSMOS_DATABASE','AZURE_COSMOS_HISTORY_CONTAINER','AZURE_COSMOS_FEEDBACK_CONTAINER','AZURE_COSMOS_GREMLIN_ENDPOINT','AZURE_COSMOS_GREMLIN_DATABASE','AZURE_COSMOS_GREMLIN_GRAPH','AZURE_COSMOS_GREMLIN_PORT',
		'GREMLIN_ENDPOINT','GREMLIN_USERNAME',
		'FABRIC_SQL_ENDPOINT','FABRIC_SQL_DATABASE','FABRIC_WORKSPACE_ID',
		'AZURE_SEARCH_ENDPOINT','AZURE_SEARCH_INDEX',
		'APPLICATIONINSIGHTS_CONNECTION_STRING',
		'CONTAINER_APP_RESOURCE_GROUP','CONTAINER_APP_ENVIRONMENT','CONTAINER_APP_SUBSCRIPTION_ID',
		'AZURE_AD_TENANT_ID'
	)
	$lines = @()
	foreach ($k in $orderedKeys) {
		if ($env.ContainsKey($k)) { $lines += "$k=$($env[$k])" }
	}
	foreach ($k in $env.Keys) {
		if (-not ($orderedKeys -contains $k)) { $lines += "$k=$($env[$k])" }
	}
	# Write file without BOM using .NET StreamWriter
	$content = $lines -join "`n"
	try {
		$stream = [System.IO.StreamWriter]::new($path, $false, [System.Text.UTF8Encoding]::new($false))
		$stream.Write($content)
		$stream.Close()
	} catch {
		# Fallback to Set-Content if StreamWriter fails
		Set-Content -Path $path -Value $content -Encoding UTF8
	}
	
	# Verify no BOM was accidentally added
	if (Test-EnvFileBOM -path $path) {
		Write-Warning "BOM detected after writing $path - this should not happen. Please check your PowerShell version."
	}
}

# Merge .env.example into .env, preserving existing values and adding missing ones
# (env path variables resolved at top of script to repository root)

# Check for BOM in existing .env file
if (Test-EnvFileBOM -path $envPath) {
	Write-Warning ".env file contains a UTF-8 BOM (Byte Order Mark) which can cause environment variable parsing issues."
	Write-Warning "This may cause the application to fail to start."
	Remove-EnvFileBOM -path $envPath
}

Write-Output "Merging .env.example into .env..."

# Read existing envs
$envVars = Read-EnvFile -path $envPath
$exampleVars = Read-EnvFile -path $examplePath

# Add missing example vars to envVars
foreach ($key in $exampleVars.Keys) {
	if (-not $envVars.ContainsKey($key)) {
		$envVars[$key] = $exampleVars[$key]
	}
}

# Attempt to auto-detect resource group if not provided via parameter
if (-not $ResourceGroup) {
	try {
		if ($envVars.ContainsKey('COSMOS_ENDPOINT') -and $envVars['COSMOS_ENDPOINT']) {
			$cosEnd = $envVars['COSMOS_ENDPOINT']
			$acct = $cosEnd.Replace('https://','') -split '\.' | Select-Object -First 1
			if ($acct) {
				Write-Output "Attempting to auto-detect resource group for Cosmos account: $acct"
				try {
					$lookup = az resource list --resource-type 'Microsoft.DocumentDB/databaseAccounts' --query "[?contains(name, `'$acct'`)]" -o json 2>$null | ConvertFrom-Json
					if ($lookup -and $lookup.Length -gt 0 -and $lookup[0].resourceGroup) {
						$ResourceGroup = $lookup[0].resourceGroup
						Write-Output "Auto-detected resource group: $ResourceGroup"
					}
				} catch {
					Write-Warning "az lookup failed while auto-detecting resource group: $_"
				}
			}
		}
	} catch {
		# noop - best-effort only
	}
}

# If a resource group is provided, attempt to discover AOAI/Cosmos endpoints and deployment names
if ($ResourceGroup) {
	try {
		az account show > $null 2>&1
	} catch {
		Write-Warning "Azure CLI not available or not logged in. Skipping azure discovery."
		$ResourceGroup = $null
	}
}

if ($ResourceGroup) {
	Write-Output "Attempting Azure resource discovery in resource group: $ResourceGroup"
	# Discover cognitive accounts
	$cogs = az resource list -g $ResourceGroup --query "[?type=='Microsoft.CognitiveServices/accounts']" -o json | ConvertFrom-Json
	$foundAoai = $null
	foreach ($c in $cogs) {
		if ($c.Kind -and $c.Kind -match 'OpenAI') { $foundAoai = $c; break }
		if ($c.Name -and $c.Name -match 'openai|aoai|open-ai|aoai') { $foundAoai = $c; break }
	}

	if ($foundAoai) {
		$aoaiName = $foundAoai.name
		if ($foundAoai.kind -eq 'OpenAI') {
			$aoaiEndpoint = "https://$($aoaiName).openai.azure.com"
			Write-Output "Detected Azure OpenAI account: $aoaiName (kind=OpenAI) -> $aoaiEndpoint"
		} else {
			$aoaiEndpoint = "https://$($aoaiName).cognitiveservices.azure.com"
			Write-Output "Detected Cognitive Services account: $aoaiName (kind=$($foundAoai.kind)) -> $aoaiEndpoint"
		}
		$envVars['AOAI_ENDPOINT'] = $aoaiEndpoint

		# Attempt to list deployments via az openai, else fallback to management REST
		$deployments = $null
		try {
			Write-Output "Attempting to list deployments via 'az openai deployment list'..."
			$raw = az cognitiveservices account deployment list --resource-group $ResourceGroup --name $aoaiName -o json 2>$null
			if ($raw) { $deployments = $raw | ConvertFrom-Json }
		} catch {
			Write-Output "'az openai' not available; trying REST fallback."
		}

		if (-not $deployments) {
			try {
				$sub = (az account show -o json | ConvertFrom-Json).id
				$api = "https://management.azure.com/subscriptions/$sub/resourceGroups/$ResourceGroup/providers/Microsoft.CognitiveServices/accounts/$aoaiName/openai/deployments?api-version=2022-12-01"
				$raw = az rest --method get --uri $api -o json 2>$null
				if ($raw) { $resp = $raw | ConvertFrom-Json; if ($resp.value) { $deployments = $resp.value } }
			} catch {
				Write-Warning "Failed to query deployments via REST fallback: $_"
			}
		}

		# Priority-aware selection: collect candidates then pick by preferred model order
		$chatDeployment = $null
		$embedDeployment = $null
		if ($deployments) {
			$chatCandidates = @()
			$embedCandidates = @()
			foreach ($d in $deployments) {
				$dName = $d.name
				$model = $null
				if ($d.model) { $model = $d.model }
				elseif ($d.properties -and $d.properties.model) { $model = $d.properties.model }
				if (-not $model) { continue }
				$lm = $model.ToString().ToLower()

				if ($lm -match 'embed' -or $lm -match 'text-embedding') {
					$embedCandidates += @{ name = $dName; model = $lm }
				} elseif ($lm -match 'gpt' -or $lm -match 'chat' -or $lm -match 'turbo') {
					$chatCandidates += @{ name = $dName; model = $lm }
				}
			}

			# Preferred chat model order (higher priority first)
			$preferredChat = @('gpt-4.1','gpt-4o','gpt-4','gpt-3.5','gpt')
			foreach ($p in $preferredChat) {
				foreach ($c in $chatCandidates) {
					if ($c.model -like "*$p*") { $chatDeployment = $c.name; break }
				}
				if ($chatDeployment) { break }
			}
			# Fallback to first candidate if no preferred match
			if (-not $chatDeployment -and $chatCandidates.Count -gt 0) { $chatDeployment = $chatCandidates[0].name }

			# Preferred embedding order
			$preferredEmbed = @('text-embedding-3-large','text-embedding-3-small','text-embedding-3','embedding','text-embedding')
			foreach ($p in $preferredEmbed) {
				foreach ($e in $embedCandidates) {
					if ($e.model -like "*$p*") { $embedDeployment = $e.name; break }
				}
				if ($embedDeployment) { break }
			}
			if (-not $embedDeployment -and $embedCandidates.Count -gt 0) { $embedDeployment = $embedCandidates[0].name }
		}

		if ($chatDeployment) { $envVars['AOAI_CHAT_DEPLOYMENT'] = $chatDeployment; Write-Output "Detected chat deployment: $chatDeployment" }

		if ($embedDeployment) { $envVars['AOAI_EMBEDDING_DEPLOYMENT'] = $embedDeployment; Write-Output "Detected embedding deployment: $embedDeployment" }

		# If we still have placeholders, prefer any existing AZURE_OPENAI_* keys found in the merged env
		$altChatKeys = @('AZURE_OPENAI_CHAT_DEPLOYMENT','AZURE_OPENAI_CHAT_DEPLOYMENT_NAME','AZURE_OPENAI_CHAT_DEPLOYMENTNAME','AZURE_OPENAI_CHAT_DEPLOYMENT')
		foreach ($k in $altChatKeys) {
			if ($envVars.ContainsKey($k) -and $envVars[$k] -and $envVars[$k] -ne 'chat-deployment' -and ($envVars['AOAI_CHAT_DEPLOYMENT'] -eq 'chat-deployment' -or -not $envVars['AOAI_CHAT_DEPLOYMENT'])) {
				$envVars['AOAI_CHAT_DEPLOYMENT'] = $envVars[$k]
				Write-Output "Using existing $k -> $($envVars[$k]) for AOAI_CHAT_DEPLOYMENT"
				break
			}
		}

		$altEmbedKeys = @('AZURE_OPENAI_EMBEDDING_DEPLOYMENT','AZURE_OPENAI_EMBEDDING_DEPLOYMENT_NAME','AZURE_OPENAI_EMBEDDING_DEPLOYMENTNAME','AZURE_OPENAI_EMBEDDING_DEPLOYMENT')
		foreach ($k in $altEmbedKeys) {
			if ($envVars.ContainsKey($k) -and $envVars[$k] -and $envVars[$k] -ne 'embedding-deployment' -and ($envVars['AOAI_EMBEDDING_DEPLOYMENT'] -eq 'embedding-deployment' -or -not $envVars['AOAI_EMBEDDING_DEPLOYMENT'])) {
				$envVars['AOAI_EMBEDDING_DEPLOYMENT'] = $envVars[$k]
				Write-Output "Using existing $k -> $($envVars[$k]) for AOAI_EMBEDDING_DEPLOYMENT"
				break
			}
		}

		# Set AZURE_OPENAI_ENDPOINT from AOAI_ENDPOINT
		# Note: AZURE_OPENAI_ENDPOINT is not in .env.example, so we don't set it
	} else {
		Write-Warning "No Azure OpenAI account detected in RG $ResourceGroup"
	}

	# Persist the resource group into the merged env so other scripts can use it
	$envVars['CONTAINER_APP_RESOURCE_GROUP'] = $ResourceGroup

	# Discover Cosmos DB accounts
	$cosmosAccounts = az resource list -g $ResourceGroup --query "[?type=='Microsoft.DocumentDB/databaseAccounts']" -o json | ConvertFrom-Json
	if ($cosmosAccounts -and $cosmosAccounts.Length -gt 0) {
		foreach ($cos in $cosmosAccounts) {
			$cosmosName = $cos.name
			$cosmosEndpoint = "https://$($cosmosName).documents.azure.com:443/"
			
			# Check capabilities to determine API type
			$capabilities = az cosmosdb show -g $ResourceGroup -n $cosmosName --query "capabilities" -o json | ConvertFrom-Json
			
			$hasGremlin = $false
			if ($capabilities) {
				foreach ($cap in $capabilities) {
					if ($cap.name -eq "EnableGremlin") {
						$hasGremlin = $true
						break
					}
				}
			}
			
			if ($hasGremlin) {
				# This is a Gremlin/Graph API account
				$gremlinEndpoint = "https://$($cosmosName).gremlin.cosmos.azure.com:443/"
				Write-Output "Detected Cosmos DB Gremlin account: $cosmosName -> $gremlinEndpoint"
				$envVars['AZURE_COSMOS_GREMLIN_ENDPOINT'] = $gremlinEndpoint
			} else {
				# This is a SQL API account
				Write-Output "Detected Cosmos DB SQL account: $cosmosName -> $cosmosEndpoint"
				$envVars['COSMOS_ENDPOINT'] = $cosmosEndpoint
				if (-not $envVars.ContainsKey('COSMOS_DATABASE_NAME')) { $envVars['COSMOS_DATABASE_NAME'] = 'appdb' }
				# Set default container names for SQL API
				if (-not $envVars.ContainsKey('COSMOS_CHAT_CONTAINER')) { $envVars['COSMOS_CHAT_CONTAINER'] = 'chat_history' }
				if (-not $envVars.ContainsKey('COSMOS_CACHE_CONTAINER')) { $envVars['COSMOS_CACHE_CONTAINER'] = 'cache' }
				if (-not $envVars.ContainsKey('COSMOS_FEEDBACK_CONTAINER')) { $envVars['COSMOS_FEEDBACK_CONTAINER'] = 'feedback' }
				if (-not $envVars.ContainsKey('COSMOS_PROCESSED_FILES_CONTAINER')) { $envVars['COSMOS_PROCESSED_FILES_CONTAINER'] = 'processed_files' }
				if (-not $envVars.ContainsKey('COSMOS_PROMPTS_CONTAINER')) { $envVars['COSMOS_PROMPTS_CONTAINER'] = 'prompts' }
				if (-not $envVars.ContainsKey('COSMOS_SQL_SCHEMA_CONTAINER')) { $envVars['COSMOS_SQL_SCHEMA_CONTAINER'] = 'sql_schema' }
				if (-not $envVars.ContainsKey('COSMOS_ACCOUNT_RESOLVER_CONTAINER')) { $envVars['COSMOS_ACCOUNT_RESOLVER_CONTAINER'] = 'account_resolver' }
				if (-not $envVars.ContainsKey('COSMOS_AGENT_FUNCTIONS_CONTAINER')) { $envVars['COSMOS_AGENT_FUNCTIONS_CONTAINER'] = 'agent_functions' }
				if (-not $envVars.ContainsKey('COSMOS_CONTRACTS_TEXT_CONTAINER')) { $envVars['COSMOS_CONTRACTS_TEXT_CONTAINER'] = 'contracts_text' }
			}
		}
	} else {
		Write-Warning "No Cosmos DB accounts detected in RG $ResourceGroup"
	}

	# Attempt to detect Gremlin/graph endpoint
	# Note: GREMLIN_ENDPOINT is not in .env.example, so we don't set it

	# Detect Application Insights
	# Note: APPLICATIONINSIGHTS_CONNECTION_STRING is not in .env.example, so we don't set it

	# Detect Azure Search
	try {
		$searchServices = az resource list -g $ResourceGroup --query "[?type=='Microsoft.Search/searchServices']" -o json | ConvertFrom-Json
		if ($searchServices -and $searchServices.Length -gt 0) {
			$search = $searchServices[0]
			$searchName = $search.name
			$searchEndpoint = "https://$searchName.search.windows.net"
			Write-Output "Detected Azure Search: $searchName -> $searchEndpoint"
			$envVars['AZURE_SEARCH_ENDPOINT'] = $searchEndpoint
			if (-not $envVars.ContainsKey('AZURE_SEARCH_INDEX')) { $envVars['AZURE_SEARCH_INDEX'] = 'contracts-index' }
		}
	} catch {
		Write-Warning "Failed to detect Azure Search: $_"
	}

	# Detect Power BI Workspace (if any, but hard to query via az)
	# For now, skip or set placeholder

	# Detect Fabric Workspace
	try {
		$fabricWorkspaces = az resource list -g $ResourceGroup --query "[?type=='Microsoft.Fabric/workspaces']" -o json | ConvertFrom-Json
		if ($fabricWorkspaces -and $fabricWorkspaces.Length -gt 0) {
			$fw = $fabricWorkspaces[0]
			$workspaceId = $fw.name
			$fabricEndpoint = "https://$workspaceId.datawarehouse.fabric.microsoft.com"
			Write-Output "Detected Fabric Workspace: $workspaceId -> $fabricEndpoint"
			$envVars['FABRIC_WORKSPACE_ID'] = $workspaceId
			$envVars['FABRIC_SQL_ENDPOINT'] = $fabricEndpoint
			if (-not $envVars.ContainsKey('FABRIC_SQL_DATABASE')) { $envVars['FABRIC_SQL_DATABASE'] = 'lakehouse_db' }
		}
	} catch {
		Write-Warning "Failed to detect Fabric Workspace: $_"
	}
}

############################################################
# Persist resource info and write .env files at repo root
############################################################

# If we have a resource group, persist it and attempt to discover subscription/tenant
if ($ResourceGroup) {
	if (-not $envVars.ContainsKey('CONTAINER_APP_RESOURCE_GROUP') -or $envVars['CONTAINER_APP_RESOURCE_GROUP'] -match 'your') {
		$envVars['CONTAINER_APP_RESOURCE_GROUP'] = $ResourceGroup
	}
	if (-not $envVars.ContainsKey('CONTAINER_APP_ENVIRONMENT') -or $envVars['CONTAINER_APP_ENVIRONMENT'] -match 'your') {
		$envVars['CONTAINER_APP_ENVIRONMENT'] = $ResourceGroup
	}
	try {
		$acct = az account show -o json | ConvertFrom-Json
		$sub = $acct.id
		$tenant = $acct.tenantId
		if ($sub) {
			if (-not $envVars.ContainsKey('CONTAINER_APP_SUBSCRIPTION_ID') -or $envVars['CONTAINER_APP_SUBSCRIPTION_ID'] -match 'your') {
				$envVars['CONTAINER_APP_SUBSCRIPTION_ID'] = $sub
			}
		}
		if ($tenant) {
			if (-not $envVars.ContainsKey('AZURE_AD_TENANT_ID') -or $envVars['AZURE_AD_TENANT_ID'] -match 'your') {
				$envVars['AZURE_AD_TENANT_ID'] = $tenant
			}
		}
	} catch { Write-Warning "Could not detect subscription id or tenant id: $_" }
}

# Determine repository root (two levels up from scripts/test_env)
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$repoRoot = Resolve-Path (Join-Path -Path $scriptDir -ChildPath "..\..")
$rootEnvPath = Join-Path -Path $repoRoot -ChildPath ".env"
$chatbotDir = Join-Path -Path $repoRoot -ChildPath "chatbot"
$chatbotEnvPath = Join-Path -Path $chatbotDir -ChildPath ".env"

# Ensure chatbot directory exists
if (-not (Test-Path $chatbotDir)) { New-Item -ItemType Directory -Path $chatbotDir | Out-Null }

# Force DEV_MODE to always be true for development
$envVars['DEV_MODE'] = 'true'

Write-Output "Writing merged .env to $rootEnvPath and $chatbotEnvPath (repo root: $repoRoot)"

# read existing root env (create if missing)
if (-not (Test-Path $rootEnvPath)) { New-Item -ItemType File -Path $rootEnvPath -Force | Out-Null }
$rootEnv = Read-EnvFile -path $rootEnvPath
foreach ($k in $envVars.Keys) { $rootEnv[$k] = $envVars[$k] }
Write-EnvFile -path $rootEnvPath -env $rootEnv

# read/create chatbot env
if (-not (Test-Path $chatbotEnvPath)) { New-Item -ItemType File -Path $chatbotEnvPath -Force | Out-Null }
$chatEnv = Read-EnvFile -path $chatbotEnvPath
foreach ($k in $envVars.Keys) { $chatEnv[$k] = $envVars[$k] }
Write-EnvFile -path $chatbotEnvPath -env $chatEnv

Write-Output "Merged .env written."

# Diagnostic: print merged env vars so the caller can see what was written
Write-Output "--- MERGED ENV VARS ---"
foreach ($k in $rootEnv.Keys | Sort-Object) {
	Write-Output "$k=$($rootEnv[$k])"
}
Write-Output "--- END MERGED ENV VARS ---"

############################################################
# NOTE: Container provisioning (chat history, prompts, agent functions, etc.)
# is intentionally delegated to `scripts/test_env/init_data.py` or the
# infrastructure deployment script `scripts/infra/deploy.ps1`.
#
# `set_env.ps1` now only merges environment variables and performs discovery.
# To create containers and upload initial data, run:
#   python scripts/test_env/init_data.py
############################################################
Write-Output "Note: This script attempts to auto-discover endpoints and AOAI deployment names; if deployments aren't found they must be set manually in the .env files."
