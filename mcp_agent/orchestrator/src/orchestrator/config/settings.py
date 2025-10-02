"""
Orchestrator configuration settings.

This module defines settings for the orchestrator service including Azure services,
MCP server endpoints, and role-based MCP access mappings.
"""

import os
from typing import Optional, List, Dict
from pydantic import Field, validator
from pydantic_settings import BaseSettings


class AzureOpenAISettings(BaseSettings):
    """Azure OpenAI service configuration."""

    endpoint: str = Field(..., description="Azure OpenAI service endpoint")

    @validator("endpoint", pre=True, always=True)
    def ensure_openai_domain(cls, v):
        if v and ".cognitiveservices.azure.com" in v:
            v = v.replace(".cognitiveservices.azure.com", ".openai.azure.com")
        return v

    api_version: str = Field(default="2024-02-15-preview", description="API version")
    chat_deployment: str = Field(..., description="Chat completion deployment name")
    embedding_deployment: str = Field(..., description="Text embedding deployment name")
    max_tokens: int = Field(default=4000, description="Maximum tokens for completions")
    temperature: float = Field(default=0.1, description="Temperature for completions")

    class Config:
        env_prefix = "AOAI_"
        env_file = ".env"
        extra = "ignore"


class CosmosDBSettings(BaseSettings):
    """Azure Cosmos DB configuration."""

    endpoint: str = Field(..., description="Cosmos DB account endpoint")
    database_name: str = Field(..., description="Database name")
    chat_container: str = Field(default="chat_history", description="Chat history container")
    prompts_container: str = Field(default="prompts", description="Prompts container")

    class Config:
        env_prefix = "COSMOS_"
        env_file = ".env"
        extra = "ignore"


class MCPServerConfig(BaseSettings):
    """Configuration for a single MCP server."""

    name: str = Field(..., description="MCP server name")
    endpoint: str = Field(..., description="MCP server endpoint URL")
    enabled: bool = Field(default=True, description="Whether MCP is enabled")
    required_roles: List[str] = Field(default_factory=list, description="Roles that can access this MCP")

    class Config:
        extra = "ignore"


class OrchestratorSettings(BaseSettings):
    """Main orchestrator configuration."""

    # Application
    app_name: str = Field(default="MCP Orchestrator", description="Application name")
    version: str = Field(default="1.0.0", description="Application version")
    debug: bool = Field(default=False, description="Debug mode")
    dev_mode: bool = Field(default=False, description="Development mode (bypasses auth)")

    # API
    api_host: str = Field(default="0.0.0.0", description="API host")
    api_port: int = Field(default=8000, description="API port")
    api_prefix: str = Field(default="/api/v1", description="API prefix")

    # CORS
    cors_origins: List[str] = Field(default_factory=lambda: ["*"], description="CORS origins")

    # Azure Services
    azure_openai: AzureOpenAISettings
    cosmos_db: CosmosDBSettings

    # MCP Configuration
    mcp_servers: Dict[str, str] = Field(
        default_factory=dict,
        description="MCP servers mapping: {name: endpoint}"
    )

    # Role to MCP mapping
    role_mcp_mapping: Dict[str, List[str]] = Field(
        default_factory=lambda: {
            "admin": ["salesforce_mcp", "analytics_mcp", "documents_mcp"],
            "sales_manager": ["salesforce_mcp", "analytics_mcp"],
            "sales_rep": ["salesforce_mcp"],
        },
        description="Mapping of roles to accessible MCP names"
    )

    # Service authentication
    service_jwt_secret: str = Field(
        default="your-secret-key-change-in-production",
        description="Secret key for service-to-service JWT"
    )
    service_jwt_expiry_minutes: int = Field(
        default=60,
        description="Service JWT expiry in minutes"
    )

    # Logging
    log_level: str = Field(default="INFO", description="Logging level")

    class Config:
        env_file = ".env"
        extra = "ignore"
        case_sensitive = False

    @validator("mcp_servers", pre=True, always=True)
    def parse_mcp_servers(cls, v):
        """Parse MCP_SERVERS from environment variable if string."""
        if isinstance(v, str):
            import json
            try:
                return json.loads(v)
            except:
                return {}
        return v or {}

    @validator("role_mcp_mapping", pre=True, always=True)
    def parse_role_mcp_mapping(cls, v):
        """Parse ROLE_MCP_MAPPING from environment variable if string."""
        if isinstance(v, str):
            import json
            try:
                return json.loads(v)
            except:
                return {
                    "admin": ["salesforce_mcp"],
                    "sales_manager": ["salesforce_mcp"],
                    "sales_rep": ["salesforce_mcp"],
                }
        return v or {
            "admin": ["salesforce_mcp"],
            "sales_manager": ["salesforce_mcp"],
            "sales_rep": ["salesforce_mcp"],
        }


# Initialize settings with defaults from environment
settings = OrchestratorSettings(
    azure_openai=AzureOpenAISettings(),
    cosmos_db=CosmosDBSettings(),
)
