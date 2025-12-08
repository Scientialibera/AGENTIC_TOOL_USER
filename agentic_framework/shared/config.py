"""
Configuration settings for the agentic framework.

This module defines settings with support for TOML config files and environment variables.
Priority: config.toml > environment variables > defaults
"""

import os
import sys
import json
from typing import Optional, List, Dict, Any
from pathlib import Path
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Python 3.11+ has tomllib built-in, otherwise use tomli
if sys.version_info >= (3, 11):
    import tomllib
else:
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None  # type: ignore

# Determine project root (3 levels up from this file)
PROJECT_ROOT = Path(__file__).parent.parent.parent

# Load configuration in priority order
config_data: Dict[str, Any] = {}

# 1. Load from config.toml if exists
config_toml_path = PROJECT_ROOT / "config.toml"
if config_toml_path.exists() and tomllib:
    with open(config_toml_path, "rb") as f:
        config_data = tomllib.load(f)

def get_nested_config(path: str, default: Any = None) -> Any:
    """
    Get a value from nested TOML config using dot notation.
    Example: get_nested_config('azure.openai.endpoint')
    """
    keys = path.split('.')
    value = config_data
    for key in keys:
        if isinstance(value, dict) and key in value:
            value = value[key]
        else:
            return default
    return value


class RBACSettings(BaseSettings):
    """RBAC configuration (NEW)."""

    model_config = SettingsConfigDict(extra="ignore")

    enabled: bool = Field(
        default_factory=lambda: get_nested_config('rbac.enabled', False),
        description="Enable Azure RBAC integration"
    )
    enforcement_mode: str = Field(
        default_factory=lambda: get_nested_config('rbac.enforcement_mode', 'soft'),
        description="Enforcement mode: soft (log) or hard (block)"
    )
    row_level_security: bool = Field(
        default_factory=lambda: get_nested_config('rbac.row_level_security', True),
        description="Enable row-level security filtering"
    )
    enable_column_filtering: bool = Field(
        default_factory=lambda: get_nested_config('rbac.enable_column_filtering', True),
        description="Enable column-level filtering based on roles"
    )


class TextToSQLSettings(BaseSettings):
    """Text-to-SQL configuration (NEW)."""

    model_config = SettingsConfigDict(extra="ignore")

    enable_embeddings: bool = Field(
        default_factory=lambda: get_nested_config('text_to_sql.enable_embeddings', True),
        description="Use embeddings for table discovery"
    )
    enable_value_matching: bool = Field(
        default_factory=lambda: get_nested_config('text_to_sql.enable_value_matching', True),
        description="Fuzzy match low-cardinality values"
    )
    enable_table_discovery: bool = Field(
        default_factory=lambda: get_nested_config('text_to_sql.enable_table_discovery', True),
        description="Auto-discover relevant tables"
    )
    similarity_threshold: float = Field(
        default_factory=lambda: get_nested_config('text_to_sql.similarity_threshold', 0.75),
        description="Embedding similarity threshold for table matching"
    )
    max_tables_per_query: int = Field(
        default_factory=lambda: get_nested_config('text_to_sql.max_tables_per_query', 5),
        description="Maximum tables to consider"
    )
    value_match_threshold: float = Field(
        default_factory=lambda: get_nested_config('text_to_sql.value_match_threshold', 0.80),
        description="Fuzzy match threshold for values"
    )
    enable_self_healing: bool = Field(
        default_factory=lambda: get_nested_config('text_to_sql.enable_self_healing', True),
        description="Retry failed queries with LLM feedback"
    )
    max_retry_attempts: int = Field(
        default_factory=lambda: get_nested_config('text_to_sql.max_retry_attempts', 3),
        description="Maximum retry attempts for failed queries"
    )
    enable_parameter_extraction: bool = Field(
        default_factory=lambda: get_nested_config('text_to_sql.enable_parameter_extraction', True),
        description="Ask LLM to fill parameter values"
    )


class AzureOpenAISettings(BaseSettings):
    """Azure OpenAI service configuration."""

    model_config = SettingsConfigDict(
        env_prefix="AOAI_",
        extra="ignore"
    )

    endpoint: str = Field(
        default_factory=lambda: get_nested_config('azure.openai.endpoint') or os.getenv('AOAI_ENDPOINT', ''),
        description="Azure OpenAI service endpoint"
    )

    @field_validator("endpoint", mode="before")
    @classmethod
    def ensure_openai_domain(cls, v):
        if v and ".cognitiveservices.azure.com" in v:
            v = v.replace(".cognitiveservices.azure.com", ".openai.azure.com")
        return v

    api_version: str = Field(
        default_factory=lambda: get_nested_config('azure.openai.api_version', '2024-06-01'),
        description="API version"
    )
    chat_deployment: str = Field(
        default_factory=lambda: get_nested_config('azure.openai.chat_deployment', ''),
        description="Chat completion deployment name"
    )
    embedding_deployment: str = Field(
        default_factory=lambda: get_nested_config('azure.openai.embedding_deployment', ''),
        description="Text embedding deployment name"
    )
    embedding_dimensions: int = Field(
        default_factory=lambda: get_nested_config('azure.openai.embedding_dimensions', 1536),
        description="Embedding vector dimensions"
    )
    max_tokens: int = Field(default=4000, description="Maximum tokens for completions")
    temperature: float = Field(default=0.1, description="Temperature for completions")


class CosmosDBSettings(BaseSettings):
    """Azure Cosmos DB configuration."""

    model_config = SettingsConfigDict(
        env_prefix="COSMOS_",
        extra="ignore"
    )

    endpoint: str = Field(
        default_factory=lambda: get_nested_config('azure.cosmos.endpoint') or os.getenv('COSMOS_ENDPOINT', ''),
        description="Cosmos DB account endpoint"
    )
    database_name: str = Field(
        default_factory=lambda: get_nested_config('azure.cosmos.database', 'appdb'),
        description="Database name"
    )

    # Container names
    mcp_definitions_container: str = Field(default="mcp_definitions", description="MCP definitions container")
    agent_functions_container: str = Field(
        default_factory=lambda: get_nested_config('azure.cosmos.containers.agent_functions', 'agent_functions'),
        description="Agent functions container"
    )
    prompts_container: str = Field(
        default_factory=lambda: get_nested_config('azure.cosmos.containers.prompts', 'prompts'),
        description="Prompts container"
    )
    rbac_config_container: str = Field(default="rbac_config", description="RBAC config container")
    chat_container: str = Field(
        default_factory=lambda: get_nested_config('azure.cosmos.containers.chat', 'unified_data'),
        description="Chat history container (unified)"
    )
    sql_schema_container: str = Field(
        default_factory=lambda: get_nested_config('azure.cosmos.containers.sql_schema', 'sql_schema'),
        description="SQL schema container"
    )

    # NEW: Text-to-SQL specific containers
    table_metadata_container: str = Field(
        default_factory=lambda: get_nested_config('azure.cosmos.containers.table_metadata', 'table_metadata'),
        description="Table metadata with embeddings"
    )
    value_mappings_container: str = Field(
        default_factory=lambda: get_nested_config('azure.cosmos.containers.value_mappings', 'value_mappings'),
        description="Low-cardinality value mappings"
    )
    rbac_policies_container: str = Field(
        default_factory=lambda: get_nested_config('azure.cosmos.containers.rbac_policies', 'rbac_policies'),
        description="RBAC policy definitions"
    )


class FabricSettings(BaseSettings):
    """Microsoft Fabric lakehouse configuration."""

    model_config = SettingsConfigDict(
        env_prefix="",
        extra="ignore",
        populate_by_name=True
    )

    mode: str = Field(
        default_factory=lambda: get_nested_config('azure.fabric.mode', 'http'),
        description="Connection mode (always http)"
    )
    sql_endpoint: Optional[str] = Field(
        default_factory=lambda: get_nested_config('azure.fabric.sql_endpoint') or os.getenv('FABRIC_SQL_ENDPOINT'),
        description="Fabric SQL endpoint"
    )
    database: str = Field(
        default_factory=lambda: get_nested_config('azure.fabric.database', 'lakehouse_db'),
        description="Fabric database name"
    )
    workspace_id: Optional[str] = Field(
        default_factory=lambda: get_nested_config('azure.fabric.workspace_id') or os.getenv('FABRIC_WORKSPACE_ID'),
        description="Fabric workspace ID"
    )
    lakehouse_id: Optional[str] = Field(
        default_factory=lambda: get_nested_config('azure.fabric.lakehouse_id') or os.getenv('FABRIC_LAKEHOUSE_ID'),
        description="Fabric lakehouse ID"
    )
    token_scope: str = Field(
        default_factory=lambda: get_nested_config('azure.fabric.token_scope', 'https://analysis.windows.net/powerbi/api/.default'),
        description="Azure AD token scope for Fabric"
    )
    driver: str = Field(
        default_factory=lambda: get_nested_config('azure.sql.driver', 'ODBC Driver 18 for SQL Server'),
        description="ODBC driver name to use for Fabric SQL connectivity"
    )
    connection_timeout: int = Field(default=30, description="Connection timeout in seconds")


class AzureSQLSettings(BaseSettings):
    """Azure SQL Database configuration (NEW)."""

    model_config = SettingsConfigDict(extra="ignore")

    enabled: bool = Field(
        default_factory=lambda: get_nested_config('azure.sql.enabled', False),
        description="Enable Azure SQL support"
    )
    server: Optional[str] = Field(
        default_factory=lambda: get_nested_config('azure.sql.server'),
        description="Azure SQL server FQDN"
    )
    database: Optional[str] = Field(
        default_factory=lambda: get_nested_config('azure.sql.database'),
        description="Azure SQL database name"
    )
    authentication: str = Field(
        default_factory=lambda: get_nested_config('azure.sql.authentication', 'azure_ad'),
        description="Authentication mode: azure_ad or connection_string"
    )
    token_scope: str = Field(
        default_factory=lambda: get_nested_config('azure.sql.token_scope', 'https://database.windows.net/.default'),
        description="Azure AD token scope for SQL"
    )
    driver: str = Field(
        default_factory=lambda: get_nested_config('azure.sql.driver', 'ODBC Driver 18 for SQL Server'),
        description="ODBC driver name"
    )


class MCPSettings(BaseSettings):
    """MCP configuration."""

    model_config = SettingsConfigDict(extra="ignore")

    mode: str = Field(
        default_factory=lambda: get_nested_config('mcp.mode', 'http'),
        description="MCP mode (always http)"
    )
    base_port: int = Field(
        default_factory=lambda: get_nested_config('mcp.base_port', 8000),
        description="Base port for MCP servers"
    )


class FrameworkSettings(BaseSettings):
    """Main framework configuration."""

    model_config = SettingsConfigDict(
        env_prefix="",
        extra="ignore",
        populate_by_name=True
    )

    app_name: str = Field(
        default_factory=lambda: get_nested_config('framework.app_name', 'Agentic Framework'),
        description="Application name"
    )
    version: str = Field(default="1.0.0", description="Application version")
    debug: bool = Field(
        default_factory=lambda: get_nested_config('framework.debug', False),
        description="Debug mode"
    )
    dev_mode: bool = Field(
        default_factory=lambda: get_nested_config('framework.dev_mode', False),
        description="Development mode (skips RBAC, returns dummy SQL data)"
    )
    bypass_token: bool = Field(
        default_factory=lambda: get_nested_config('framework.bypass_token', False),
        description="Bypass JWT token validation"
    )
    environment: str = Field(
        default_factory=lambda: get_nested_config('framework.environment', 'development'),
        description="Environment"
    )

    # Azure AD / Entra ID authentication
    azure_tenant_id: Optional[str] = Field(
        default_factory=lambda: get_nested_config('azure.auth.tenant_id') or os.getenv('AZURE_TENANT_ID'),
        description="Azure AD tenant ID for JWT validation"
    )
    azure_audience: Optional[str] = Field(
        default_factory=lambda: get_nested_config('azure.auth.audience') or os.getenv('AZURE_AUDIENCE'),
        description="Expected audience in JWT tokens"
    )

    # MCP endpoints as JSON string
    mcp_endpoints: str = Field(
        default_factory=lambda: _get_mcp_endpoints(),
        description="JSON dictionary of MCP names to endpoints"
    )

    @field_validator("mcp_endpoints", mode="before")
    @classmethod
    def fix_mcp_endpoints_json(cls, v):
        """Fix improperly formatted JSON from Azure CLI environment variables."""
        import re

        if isinstance(v, dict):
            return json.dumps(v)

        if isinstance(v, str):
            try:
                json.loads(v)
                return v
            except json.JSONDecodeError:
                pass

            # Fix missing quotes
            v = re.sub(r'\{(\w+):', r'{"\1":', v)
            v = re.sub(r',\s*(\w+):', r', "\1":', v)

            def fix_value(match):
                prefix = match.group(1)
                value = match.group(2).strip()
                suffix = match.group(3)

                if value.startswith('"') and value.endswith('"'):
                    return f'{prefix}{value}{suffix}'
                else:
                    return f'{prefix}"{value}"{suffix}'

            v = re.sub(r'(:\s*)([^,}]+?)(\s*[,}])', fix_value, v)

        return v

    # Nested settings
    rbac: RBACSettings = Field(default_factory=RBACSettings)
    text_to_sql: TextToSQLSettings = Field(default_factory=TextToSQLSettings)
    aoai: AzureOpenAISettings = Field(default_factory=AzureOpenAISettings)
    cosmos: CosmosDBSettings = Field(default_factory=CosmosDBSettings)
    fabric: FabricSettings = Field(default_factory=FabricSettings)
    azure_sql: AzureSQLSettings = Field(default_factory=AzureSQLSettings)
    mcp: MCPSettings = Field(default_factory=MCPSettings)

    @property
    def mcp_endpoints_dict(self) -> dict[str, str]:
        """Parse MCP endpoints from JSON string."""
        try:
            return json.loads(self.mcp_endpoints)
        except json.JSONDecodeError:
            logger = __import__('structlog').get_logger(__name__)
            logger.error("Failed to parse MCP_ENDPOINTS JSON", mcp_endpoints=self.mcp_endpoints)
            return {}


def _get_mcp_endpoints() -> str:
    """Get MCP endpoints from TOML or environment."""
    # Try TOML first
    endpoints = get_nested_config('mcp.endpoints')
    if endpoints:
        return json.dumps(endpoints)

    # Fall back to environment variable
    env_endpoints = os.getenv('MCP_ENDPOINTS')
    if env_endpoints:
        return env_endpoints

    # Default
    return '{"sql_mcp": "http://localhost:8003/mcp"}'


def get_settings() -> FrameworkSettings:
    """Get framework settings from TOML/environment."""
    return FrameworkSettings()


# Global settings instance
settings = get_settings()
