// =============================================================================
// CONTAINER APPS ENVIRONMENT MODULE
// =============================================================================
// Creates Container Apps Environment with Log Analytics integration

param name string
param location string
param logAnalyticsWorkspaceId string
param pricingTier string = 'Consumption'
param tags object = {}

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2022-10-01' existing = {
  name: split(logAnalyticsWorkspaceId, '/')[8]
}

resource containerAppsEnv 'Microsoft.App/managedEnvironments@2023-05-01' = {
  name: name
  location: location
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalytics.properties.customerId
        sharedKey: logAnalytics.listKeys().primarySharedKey
      }
    }
    zoneRedundant: false
    workloadProfiles: pricingTier == 'Premium' ? [
      {
        name: 'Consumption'
        workloadProfileType: 'Consumption'
      }
    ] : null
  }
  tags: tags
}

output environmentId string = containerAppsEnv.id
output defaultDomain string = containerAppsEnv.properties.defaultDomain
