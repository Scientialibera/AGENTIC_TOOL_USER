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
    schema_metadata_container: str = Field(default="schema_metadata", description="Schema metadata container for text-to-SQL")


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


class SqlSettings(BaseSettings):
    """Unified SQL configuration for Fabric SQL and Azure SQL."""
    
    model_config = SettingsConfigDict(
        env_prefix="SQL_",
        extra="ignore",
        populate_by_name=True
    )
    
    endpoint: Optional[str] = Field(default=None, description="SQL endpoint (Fabric or Azure SQL)", alias='SQL_ENDPOINT')
    database: str = Field(default="lakehouse_db", description="Database name", alias='SQL_DATABASE')
    engine_type: str = Field(default="fabric", description="SQL engine type: fabric or azure_sql", alias='SQL_ENGINE_TYPE')
    connection_timeout: int = Field(default=30, description="Connection timeout in seconds", alias='SQL_CONNECTION_TIMEOUT')
    
    # Legacy fabric-specific aliases for backward compatibility
    @classmethod
    def from_fabric_settings(cls, fabric_endpoint: Optional[str], fabric_database: str):
        """Create SqlSettings from legacy Fabric environment variables."""
        return cls(
            endpoint=fabric_endpoint,
            database=fabric_database,
            engine_type="fabric"
        )


class FabricSettings(BaseSettings):
    """Microsoft Fabric lakehouse configuration (legacy, use SqlSettings)."""
    
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
    dev_mode: bool = Field(default=False, description="Development mode (skips RBAC, returns dummy SQL data)", alias='DEV_MODE')
    bypass_token: bool = Field(default=False, description="Bypass JWT token validation for API and MCP endpoints", alias='BYPASS_TOKEN')
    environment: str = Field(default="development", description="Environment", alias='ENVIRONMENT')
    
    # RBAC configuration
    rbac_enabled: bool = Field(default=True, description="Enable application-level RBAC", alias='RBAC_ENABLED')
    rbac_mode: str = Field(default="cosmos", description="RBAC mode: cosmos, sql, or off", alias='RBAC_MODE')
    
    # Azure AD / Entra ID authentication
    azure_tenant_id: Optional[str] = Field(default=None, description="Azure AD tenant ID for JWT validation", alias='AZURE_TENANT_ID')
    azure_audience: Optional[str] = Field(default=None, description="Expected audience in JWT tokens (API app registration ID)", alias='AZURE_AUDIENCE')

    # MCP endpoints as JSON string: {"sql_mcp": "http://localhost:8001/mcp", "graph_mcp": "http://localhost:8002/mcp"}
    mcp_endpoints: str = Field(
        default='{"sql_mcp": "http://localhost:8001/mcp", "graph_mcp": "http://localhost:8002/mcp"}',
        description="JSON dictionary of MCP names to endpoints",
        alias='MCP_ENDPOINTS'
    )

    @field_validator("mcp_endpoints", mode="before")
    @classmethod
    def fix_mcp_endpoints_json(cls, v):
        """Fix improperly formatted JSON from Azure CLI environment variables."""
        import re
        import json
        
        if isinstance(v, dict):
            # Already a dict, convert to JSON string
            return json.dumps(v)
        
        if isinstance(v, str):
            # Try parsing as-is first
            try:
                json.loads(v)
                return v  # Already valid JSON
            except json.JSONDecodeError:
                pass
            
            # Fix missing quotes: {key: value} -> {"key": "value"}
            # Match unquoted keys followed by colon
            v = re.sub(r'\{(\w+):', r'{"\1":', v)  # First key
            v = re.sub(r',\s*(\w+):', r', "\1":', v)  # Subsequent keys
            
            # Fix unquoted values (anything between : and , or })
            # This won't touch already quoted values
            def fix_value(match):
                prefix = match.group(1)  # ": 
                value = match.group(2).strip()  # the value
                suffix = match.group(3)  # , or }
                
                # If value already has quotes, don't add more
                if value.startswith('"') and value.endswith('"'):
                    return f'{prefix}{value}{suffix}'
                else:
                    return f'{prefix}"{value}"{suffix}'
            
            v = re.sub(r'(:\s*)([^,}]+?)(\s*[,}])', fix_value, v)
            
        return v

    aoai: AzureOpenAISettings
    cosmos: CosmosDBSettings
    gremlin: GremlinSettings
    fabric: FabricSettings
    sql: SqlSettings

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
    # Try to load SQL settings, fallback to Fabric settings for backward compatibility
    try:
        sql_settings = SqlSettings()
    except Exception:
        # If SQL_ env vars not set, use FABRIC_ env vars
        fabric_temp = FabricSettings()
        sql_settings = SqlSettings.from_fabric_settings(
            fabric_endpoint=fabric_temp.sql_endpoint,
            fabric_database=fabric_temp.database
        )
    
    return FrameworkSettings(
        aoai=AzureOpenAISettings(),
        cosmos=CosmosDBSettings(),
        gremlin=GremlinSettings(),
        fabric=FabricSettings(),
        sql=sql_settings,
    )
