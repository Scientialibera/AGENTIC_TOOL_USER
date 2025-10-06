// =============================================================================
// COSMOS DB (Gremlin API) MODULE
// =============================================================================
// Creates Cosmos DB account with Gremlin API for graph queries

param accountName string
param location string
param databaseName string
param graphName string
param throughput int = 400
param tags object = {}

resource gremlinAccount 'Microsoft.DocumentDB/databaseAccounts@2023-04-15' = {
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
    capabilities: [
      {
        name: 'EnableGremlin'
      }
    ]
    enableAutomaticFailover: false
    enableMultipleWriteLocations: false
    publicNetworkAccess: 'Enabled'
  }
  tags: tags
}

resource database 'Microsoft.DocumentDB/databaseAccounts/gremlinDatabases@2023-04-15' = {
  parent: gremlinAccount
  name: databaseName
  properties: {
    resource: {
      id: databaseName
    }
  }
}

resource graph 'Microsoft.DocumentDB/databaseAccounts/gremlinDatabases/graphs@2023-04-15' = {
  parent: database
  name: graphName
  properties: {
    resource: {
      id: graphName
      partitionKey: {
        paths: ['/partitionKey']
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

output gremlinAccountId string = gremlinAccount.id
output gremlinEndpoint string = 'wss://${gremlinAccount.name}.gremlin.cosmos.azure.com:443/'
output databaseName string = database.name
output graphName string = graph.name
