"""
Salesforce MCP configuration settings.

This module defines settings for the Salesforce MCP server including
Fabric Lakehouse, Gremlin, and authentication configuration.
"""

import os
from typing import Optional, List
from pydantic import Field, validator
from pydantic_settings import BaseSettings


class FabricLakehouseSettings(BaseSettings):
    """Microsoft Fabric Lakehouse configuration."""

    sql_endpoint: str = Field(..., description="SQL endpoint URL")
    database: str = Field(..., description="Database name")
    workspace_id: str = Field(..., description="Workspace ID")
    connection_timeout: int = Field(default=30, description="Connection timeout in seconds")

    class Config:
        env_prefix = "FABRIC_LAKEHOUSE_"
        env_file = ".env"
        extra = "ignore"


class GremlinSettings(BaseSettings):
    """Gremlin graph database configuration."""

    endpoint: Optional[str] = Field(default=None, description="Gremlin endpoint", alias='AZURE_COSMOS_GREMLIN_ENDPOINT')
    database_name: str = Field(default="graphdb", description="Graph database name")
    graph_name: str = Field(default="account_graph", description="Graph container name")
    max_concurrent_connections: int = Field(default=10, description="Max concurrent connections")
    connection_timeout: int = Field(default=30, description="Connection timeout in seconds")

    class Config:
        env_prefix = "GREMLIN_"
        env_file = ".env"
        extra = "ignore"
        allow_population_by_field_name = True


class CosmosDBSettings(BaseSettings):
    """Azure Cosmos DB configuration for repositories."""

    endpoint: str = Field(..., description="Cosmos DB account endpoint")
    database_name: str = Field(..., description="Database name")
    sql_schema_container: str = Field(default="sql_schema", description="SQL schema container")

    class Config:
        env_prefix = "COSMOS_"
        env_file = ".env"
        extra = "ignore"


class SalesforceMCPSettings(BaseSettings):
    """Main Salesforce MCP configuration."""

    # Application
    app_name: str = Field(default="Salesforce MCP", description="Application name")
    version: str = Field(default="1.0.0", description="Application version")
    debug: bool = Field(default=False, description="Debug mode")
    dev_mode: bool = Field(default=False, description="Development mode (bypasses auth)")

    # API
    api_host: str = Field(default="0.0.0.0", description="API host")
    api_port: int = Field(default=8001, description="API port")

    # Azure Services
    fabric_lakehouse: FabricLakehouseSettings
    gremlin: GremlinSettings
    cosmos_db: CosmosDBSettings

    # Service authentication
    service_jwt_secret: str = Field(
        default="your-secret-key-change-in-production",
        description="Secret key for service JWT validation"
    )

    # Logging
    log_level: str = Field(default="INFO", description="Logging level")

    class Config:
        env_file = ".env"
        extra = "ignore"
        case_sensitive = False


# Initialize settings
settings = SalesforceMCPSettings(
    fabric_lakehouse=FabricLakehouseSettings(),
    gremlin=GremlinSettings(),
    cosmos_db=CosmosDBSettings(),
)
