// =============================================================================
// COSMOS DB (NoSQL API) MODULE
// =============================================================================
// Creates Cosmos DB account with NoSQL API and containers

param accountName string
param location string
param databaseName string
param containerNames array
param throughput int = 400
param tags object = {}

resource cosmosAccount 'Microsoft.DocumentDB/databaseAccounts@2023-04-15' = {
  name: accountName
  location: location
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    consistencyPolicy: {
      defaultConsistencyLevel: 'Session'
    }
    locations: [
      {
        locationName: location
        failoverPriority: 0
        isZoneRedundant: false
      }
    ]
    capabilities: []
    enableAutomaticFailover: false
    enableMultipleWriteLocations: false
    publicNetworkAccess: 'Enabled'
  }
  tags: tags
}

resource database 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2023-04-15' = {
  parent: cosmosAccount
  name: databaseName
  properties: {
    resource: {
      id: databaseName
    }
  }
}

// Create containers with appropriate partition keys
resource agentFunctionsContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2023-04-15' = {
  parent: database
  name: 'agent_functions'
  properties: {
    resource: {
      id: 'agent_functions'
      partitionKey: {
        paths: ['/mcp_id']
        kind: 'Hash'
      }
      indexingPolicy: {
        indexingMode: 'consistent'
        automatic: true
      }
    }
    options: {
      throughput: throughput
    }
  }
}

resource mcpDefinitionsContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2023-04-15' = {
  parent: database
  name: 'mcp_definitions'
  properties: {
    resource: {
      id: 'mcp_definitions'
      partitionKey: {
        paths: ['/id']
        kind: 'Hash'
      }
    }
    options: {
      throughput: throughput
    }
  }
}

resource promptsContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2023-04-15' = {
  parent: database
  name: 'prompts'
  properties: {
    resource: {
      id: 'prompts'
      partitionKey: {
        paths: ['/id']
        kind: 'Hash'
      }
    }
    options: {
      throughput: throughput
    }
  }
}

resource rbacConfigContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2023-04-15' = {
  parent: database
  name: 'rbac_config'
  properties: {
    resource: {
      id: 'rbac_config'
      partitionKey: {
        paths: ['/role_name']
        kind: 'Hash'
      }
    }
    options: {
      throughput: throughput
    }
  }
}

resource unifiedDataContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2023-04-15' = {
  parent: database
  name: 'unified_data'
  properties: {
    resource: {
      id: 'unified_data'
      partitionKey: {
        paths: ['/session_id']
        kind: 'Hash'
      }
    }
    options: {
      throughput: throughput
    }
  }
}

resource sqlSchemaContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2023-04-15' = {
  parent: database
  name: 'sql_schema'
  properties: {
    resource: {
      id: 'sql_schema'
      partitionKey: {
        paths: ['/id']
        kind: 'Hash'
      }
    }
    options: {
      throughput: throughput
    }
  }
}

output cosmosAccountId string = cosmosAccount.id
output endpoint string = cosmosAccount.properties.documentEndpoint
output databaseName string = database.name
