"""
Configuration settings for the agentic framework.

This module defines settings with support for environment variables
and Azure services using DefaultAzureCredential.
"""

import os
from typing import Optional, List
from pathlib import Path
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv

# Load .env file from parent directory
env_path = Path(__file__).parent.parent.parent / ".env"
if env_path.exists():
    load_dotenv(env_path)
else:
    # Try loading from current directory as fallback
    load_dotenv()


class AzureOpenAISettings(BaseSettings):
    """Azure OpenAI service configuration."""
    
    model_config = SettingsConfigDict(
        env_prefix="AOAI_",
        extra="ignore"
    )
    
    endpoint: str = Field(..., description="Azure OpenAI service endpoint")
    
    @field_validator("endpoint", mode="before")
    @classmethod
    def ensure_openai_domain(cls, v):
        if v and ".cognitiveservices.azure.com" in v:
            v = v.replace(".cognitiveservices.azure.com", ".openai.azure.com")
        return v
    
    api_version: str = Field(default="2024-08-01-preview", description="API version")
    chat_deployment: str = Field(..., description="Chat completion deployment name")
    embedding_deployment: str = Field(..., description="Text embedding deployment name")
    max_tokens: int = Field(default=4000, description="Maximum tokens for completions")
    temperature: float = Field(default=0.1, description="Temperature for completions")


class CosmosDBSettings(BaseSettings):
    """Azure Cosmos DB configuration."""
    
    model_config = SettingsConfigDict(
        env_prefix="COSMOS_",
        extra="ignore"
    )
    
    endpoint: str = Field(..., description="Cosmos DB account endpoint")
    database_name: str = Field(..., description="Database name")
    mcp_definitions_container: str = Field(default="mcp_definitions", description="MCP definitions container")
    agent_functions_container: str = Field(default="agent_functions", description="Agent functions container")
    prompts_container: str = Field(default="prompts", description="Prompts container")
    rbac_config_container: str = Field(default="rbac_config", description="RBAC config container")
    chat_container: str = Field(default="unified_data", description="Chat history container (unified)")


class GremlinSettings(BaseSettings):
    """Gremlin graph database configuration."""
    
    model_config = SettingsConfigDict(
        env_prefix="",
        extra="ignore",
        populate_by_name=True
    )
    
    endpoint: Optional[str] = Field(default=None, description="Gremlin endpoint", alias='AZURE_COSMOS_GREMLIN_ENDPOINT')
    database_name: str = Field(default="graphdb", description="Graph database name", alias='AZURE_COSMOS_GREMLIN_DATABASE')
    graph_name: str = Field(default="account_graph", description="Graph container name", alias='AZURE_COSMOS_GREMLIN_GRAPH')
    port: int = Field(default=443, description="Gremlin port", alias='AZURE_COSMOS_GREMLIN_PORT')
    max_concurrent_connections: int = Field(default=10, description="Max concurrent connections")
    connection_timeout: int = Field(default=30, description="Connection timeout in seconds")


class FabricSettings(BaseSettings):
    """Microsoft Fabric lakehouse configuration."""
    
    model_config = SettingsConfigDict(
        env_prefix="",
        extra="ignore",
        populate_by_name=True
    )
    
    sql_endpoint: Optional[str] = Field(default=None, description="Fabric SQL endpoint", alias='FABRIC_SQL_ENDPOINT')
    database: str = Field(default="lakehouse_db", description="Fabric database name", alias='FABRIC_SQL_DATABASE')
    workspace_id: Optional[str] = Field(default=None, description="Fabric workspace ID", alias='FABRIC_WORKSPACE_ID')
    lakehouse_id: Optional[str] = Field(default=None, description="Fabric lakehouse ID", alias='FABRIC_LAKEHOUSE_ID')
    connection_timeout: int = Field(default=30, description="Connection timeout in seconds")


class FrameworkSettings(BaseSettings):
    """Main framework configuration."""

    model_config = SettingsConfigDict(
        env_prefix="",
        extra="ignore",
        populate_by_name=True
    )

    app_name: str = Field(default="Agentic Framework", description="Application name", alias='APP_NAME')
    version: str = Field(default="1.0.0", description="Application version")
    debug: bool = Field(default=False, description="Debug mode", alias='DEBUG')
    dev_mode: bool = Field(default=False, description="Development mode (skips RBAC and auth)", alias='DEV_MODE')
    environment: str = Field(default="development", description="Environment", alias='ENVIRONMENT')
    
    # Azure AD / Entra ID authentication
    azure_tenant_id: Optional[str] = Field(default=None, description="Azure AD tenant ID for JWT validation", alias='AZURE_TENANT_ID')
    azure_audience: Optional[str] = Field(default=None, description="Expected audience in JWT tokens (API app registration ID)", alias='AZURE_AUDIENCE')

    # MCP endpoints as JSON string: {"sql_mcp": "http://localhost:8001/mcp", "graph_mcp": "http://localhost:8002/mcp"}
    mcp_endpoints: str = Field(
        default='{"sql_mcp": "http://localhost:8001/mcp", "graph_mcp": "http://localhost:8002/mcp"}',
        description="JSON dictionary of MCP names to endpoints",
        alias='MCP_ENDPOINTS'
    )

    aoai: AzureOpenAISettings
    cosmos: CosmosDBSettings
    gremlin: GremlinSettings
    fabric: FabricSettings

    @property
    def mcp_endpoints_dict(self) -> dict[str, str]:
        """Parse MCP endpoints from JSON string."""
        import json
        try:
            return json.loads(self.mcp_endpoints)
        except json.JSONDecodeError:
            logger = __import__('structlog').get_logger(__name__)
            logger.error("Failed to parse MCP_ENDPOINTS JSON", mcp_endpoints=self.mcp_endpoints)
            return {}


def get_settings() -> FrameworkSettings:
    """Get framework settings from environment."""
    return FrameworkSettings(
        aoai=AzureOpenAISettings(),
        cosmos=CosmosDBSettings(),
        gremlin=GremlinSettings(),
        fabric=FabricSettings(),
    )
