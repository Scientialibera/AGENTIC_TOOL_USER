// =============================================================================
// AZURE OPENAI MODULE
// =============================================================================
// Creates Azure OpenAI account with chat and embedding deployments

param name string
param location string
param chatModelName string
param chatModelVersion string
param embeddingModelName string
param tags object = {}

resource openAiAccount 'Microsoft.CognitiveServices/accounts@2023-05-01' = {
  name: name
  location: location
  kind: 'OpenAI'
  sku: {
    name: 'S0'
  }
  properties: {
    customSubDomainName: name
    publicNetworkAccess: 'Enabled'
    networkAcls: {
      defaultAction: 'Allow'
    }
  }
  tags: tags
}

// Chat model deployment
resource chatDeployment 'Microsoft.CognitiveServices/accounts/deployments@2023-05-01' = {
  parent: openAiAccount
  name: chatModelName
  sku: {
    name: 'Standard'
    capacity: 30 // TPM in thousands (30K TPM)
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: chatModelName
      version: chatModelVersion
    }
  }
}

// Embedding model deployment
resource embeddingDeployment 'Microsoft.CognitiveServices/accounts/deployments@2023-05-01' = {
  parent: openAiAccount
  name: embeddingModelName
  sku: {
    name: 'Standard'
    capacity: 120 // TPM in thousands (120K TPM)
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: embeddingModelName
      version: '1' // Embedding models use version '1'
    }
  }
  dependsOn: [
    chatDeployment
  ]
}

output openAiId string = openAiAccount.id
output endpoint string = openAiAccount.properties.endpoint
output chatDeploymentName string = chatDeployment.name
output embeddingDeploymentName string = embeddingDeployment.name
