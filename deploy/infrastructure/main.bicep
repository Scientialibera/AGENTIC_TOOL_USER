// =============================================================================
// MAIN BICEP TEMPLATE - Agentic Framework Infrastructure
// =============================================================================
// This template deploys the complete infrastructure for the agentic framework
// including Azure OpenAI, Cosmos DB, Container Apps Environment, and supporting services

targetScope = 'resourceGroup'

// =============================================================================
// PARAMETERS
// =============================================================================
@description('Base name for all resources (e.g., "mybot"). Resources will be named <baseName>-<resourceType>')
@minLength(3)
@maxLength(15)
param baseName string

@description('Azure region for resource deployment')
param location string = resourceGroup().location

@description('Environment name (dev, staging, prod)')
@allowed(['dev', 'staging', 'prod'])
param environment string = 'dev'

@description('Azure OpenAI deployment model')
param openAiChatModel string = 'gpt-4'

@description('Azure OpenAI model version')
param openAiModelVersion string = '2024-08-06'

@description('Azure OpenAI embedding model')
param openAiEmbeddingModel string = 'text-embedding-3-small'

@description('Cosmos DB NoSQL throughput (RU/s). Use 400 for dev, 1000+ for prod')
@minValue(400)
@maxValue(10000)
param cosmosDbThroughput int = 400

@description('Cosmos DB Gremlin throughput (RU/s). Use 400 for dev, 1000+ for prod')
@minValue(400)
@maxValue(10000)
param gremlinDbThroughput int = 400

@description('Container Apps Environment pricing tier')
@allowed(['Consumption', 'Premium'])
param containerAppsPlan string = 'Consumption'

@description('Enable Azure Container Registry for custom images')
param enableContainerRegistry bool = true

@description('Tags to apply to all resources')
param tags object = {
  Environment: environment
  Application: 'AgenticFramework'
  ManagedBy: 'Bicep'
}

// =============================================================================
// VARIABLES
// =============================================================================
var uniqueSuffix = uniqueString(resourceGroup().id, baseName)
var cosmosAccountName = '${baseName}-cosmos-${uniqueSuffix}'
var cosmosDbName = 'agentic_db'
var gremlinAccountName = '${baseName}-graph-${uniqueSuffix}'
var gremlinDbName = 'graphdb'
var openAiAccountName = '${baseName}-openai-${uniqueSuffix}'
var containerRegistryName = replace('${baseName}acr${uniqueSuffix}', '-', '') // ACR names can't have dashes
var containerAppsEnvName = '${baseName}-aca-env'
var logAnalyticsName = '${baseName}-logs'
var managedIdentityName = '${baseName}-identity'

// Container names for Cosmos DB NoSQL
var containerNames = [
  'agent_functions'
  'mcp_definitions'
  'prompts'
  'rbac_config'
  'unified_data'
  'sql_schema'
]

// =============================================================================
// MODULE IMPORTS
// =============================================================================

// Managed Identity
module identity 'modules/identity.bicep' = {
  name: 'deploy-identity'
  params: {
    name: managedIdentityName
    location: location
    tags: tags
  }
}

// Azure OpenAI
module openai 'modules/openai.bicep' = {
  name: 'deploy-openai'
  params: {
    name: openAiAccountName
    location: location
    chatModelName: openAiChatModel
    chatModelVersion: openAiModelVersion
    embeddingModelName: openAiEmbeddingModel
    tags: tags
  }
}

// Cosmos DB (NoSQL API)
module cosmos 'modules/cosmos.bicep' = {
  name: 'deploy-cosmos'
  params: {
    accountName: cosmosAccountName
    location: location
    databaseName: cosmosDbName
    containerNames: containerNames
    throughput: cosmosDbThroughput
    tags: tags
  }
}

// Cosmos DB (Gremlin API) - separate account required
module gremlin 'modules/gremlin.bicep' = {
  name: 'deploy-gremlin'
  params: {
    accountName: gremlinAccountName
    location: location
    databaseName: gremlinDbName
    graphName: 'account_graph'
    throughput: gremlinDbThroughput
    tags: tags
  }
}

// Container Registry (optional)
module acr 'modules/acr.bicep' = if (enableContainerRegistry) {
  name: 'deploy-acr'
  params: {
    name: containerRegistryName
    location: location
    tags: tags
  }
}

// Log Analytics for Container Apps
module logs 'modules/logs.bicep' = {
  name: 'deploy-logs'
  params: {
    name: logAnalyticsName
    location: location
    tags: tags
  }
}

// Container Apps Environment
module containerApps 'modules/container-apps.bicep' = {
  name: 'deploy-container-apps'
  params: {
    name: containerAppsEnvName
    location: location
    logAnalyticsWorkspaceId: logs.outputs.workspaceId
    pricingTier: containerAppsPlan
    tags: tags
  }
}

// =============================================================================
// RBAC ASSIGNMENTS
// =============================================================================

// Assign Managed Identity permissions to Azure OpenAI
resource openaiRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(openai.outputs.openAiId, identity.outputs.principalId, 'CognitiveServicesOpenAIUser')
  scope: resourceGroup()
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd') // Cognitive Services OpenAI User
    principalId: identity.outputs.principalId
    principalType: 'ServicePrincipal'
  }
}

// Assign Managed Identity permissions to Cosmos DB (NoSQL)
resource cosmosRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(cosmos.outputs.cosmosAccountId, identity.outputs.principalId, 'CosmosDBDataContributor')
  scope: resourceGroup()
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '00000000-0000-0000-0000-000000000002') // Cosmos DB Built-in Data Contributor
    principalId: identity.outputs.principalId
    principalType: 'ServicePrincipal'
  }
}

// Assign Managed Identity permissions to ACR (if enabled)
resource acrRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (enableContainerRegistry) {
  name: guid(acr.outputs.acrId, identity.outputs.principalId, 'AcrPull')
  scope: resourceGroup()
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d') // AcrPull
    principalId: identity.outputs.principalId
    principalType: 'ServicePrincipal'
  }
}

// =============================================================================
// OUTPUTS
// =============================================================================
output managedIdentityId string = identity.outputs.identityId
output managedIdentityClientId string = identity.outputs.clientId
output managedIdentityPrincipalId string = identity.outputs.principalId

output openAiEndpoint string = openai.outputs.endpoint
output openAiChatDeployment string = openai.outputs.chatDeploymentName
output openAiEmbeddingDeployment string = openai.outputs.embeddingDeploymentName

output cosmosEndpoint string = cosmos.outputs.endpoint
output cosmosDatabaseName string = cosmosDbName

output gremlinEndpoint string = gremlin.outputs.gremlinEndpoint
output gremlinDatabaseName string = gremlinDbName

output containerAppsEnvironmentId string = containerApps.outputs.environmentId
output containerAppsEnvironmentDomain string = containerApps.outputs.defaultDomain

output containerRegistryName string = enableContainerRegistry ? acr.outputs.registryName : ''
output containerRegistryLoginServer string = enableContainerRegistry ? acr.outputs.loginServer : ''

output logAnalyticsWorkspaceId string = logs.outputs.workspaceId
