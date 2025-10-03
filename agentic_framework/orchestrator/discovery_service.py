"""
MCP Discovery Service.

This service dynamically discovers MCP servers and their tools by calling
the MCP servers directly via HTTP.
"""

from typing import List, Dict, Any, Optional
import structlog
import httpx

from shared.config import get_settings
from shared.models import MCPDefinition, ToolDefinition, RBACContext, RBACConfig
from shared.cosmos_client import CosmosDBClient

# ============================================================================
# CONSTANTS
# ============================================================================
HTTP_CLIENT_TIMEOUT = 10.0

logger = structlog.get_logger(__name__)


class MCPDiscoveryService:
    """Service for discovering and managing MCP servers."""
    
    def __init__(self, cosmos_client: CosmosDBClient, settings=None):
        """Initialize the discovery service."""
        self.cosmos_client = cosmos_client
        self.settings = settings or get_settings()
        self.http_client = httpx.AsyncClient(timeout=HTTP_CLIENT_TIMEOUT)

        # Get MCP endpoints from settings (configured via MCP_ENDPOINTS env var)
        self.mcp_endpoints = self.settings.mcp_endpoints_dict

        logger.info("MCP Discovery Service initialized", mcp_count=len(self.mcp_endpoints))
    
    async def discover_mcps(
        self,
        rbac_context: Optional[RBACContext] = None
    ) -> List[Dict[str, Any]]:
        """
        Discover available MCP servers from configured endpoints.

        Args:
            rbac_context: User RBAC context for filtering (future use)

        Returns:
            List of MCP information with their tools
        """
        try:
            if not self.mcp_endpoints:
                logger.warning("No MCP endpoints configured in MCP_ENDPOINTS")
                return []

            logger.info("Discovering MCPs from endpoints", mcp_count=len(self.mcp_endpoints))

            all_mcps = []
            for mcp_name, endpoint in self.mcp_endpoints.items():
                mcp_info = await self._discover_mcp_from_server(mcp_name, endpoint)
                if mcp_info:
                    all_mcps.append(mcp_info)

            logger.info("MCPs discovered", count=len(all_mcps), mcps=[m['name'] for m in all_mcps])
            return all_mcps
            
        except Exception as e:
            logger.error("Failed to discover MCPs", error=str(e))
            return []
    
    async def _discover_mcp_from_server(self, mcp_name: str, endpoint: str) -> Optional[Dict[str, Any]]:
        """
        Discover MCP from its endpoint.

        Args:
            mcp_name: Name/ID of the MCP
            endpoint: HTTP endpoint URL for the MCP server

        Returns:
            MCP information dict
        """
        try:
            logger.info("Discovered MCP server", mcp_name=mcp_name, endpoint=endpoint)

            return {
                "id": mcp_name,
                "name": mcp_name,
                "endpoint": endpoint,
                "transport": "http",
                "enabled": True,
            }
            
        except Exception as e:
            logger.error("Failed to discover MCP from server", mcp_name=mcp_name, error=str(e))
            return None

    async def _filter_mcps_by_rbac(
        self,
        mcps: List[MCPDefinition],
        rbac_context: RBACContext
    ) -> List[MCPDefinition]:
        """Filter MCPs based on user roles and RBAC configuration."""
        try:
            rbac_configs = await self._load_rbac_configs(rbac_context.roles)
            
            allowed_mcp_ids = set()
            for config in rbac_configs:
                allowed_mcp_ids.update(config.mcp_access)
            
            filtered = [
                mcp for mcp in mcps
                if mcp.id in allowed_mcp_ids or self._check_mcp_access(mcp, rbac_context)
            ]
            
            return filtered
            
        except Exception as e:
            logger.error("Failed to filter MCPs by RBAC", error=str(e))
            return mcps
    
    def _check_mcp_access(self, mcp: MCPDefinition, rbac_context: RBACContext) -> bool:
        """Check if user has access to MCP based on roles and groups."""
        if not mcp.allowed_roles and not mcp.allowed_groups:
            return True
        
        for role in rbac_context.roles:
            if role in mcp.allowed_roles:
                return True
        
        return False
    
    async def _load_rbac_configs(self, roles: List[str]) -> List[RBACConfig]:
        """Load RBAC configurations for given roles."""
        try:
            if not roles:
                return []
            
            placeholders = ", ".join([f"'{role}'" for role in roles])
            query = f"SELECT * FROM c WHERE c.role_name IN ({placeholders})"
            
            items = await self.cosmos_client.query_items(
                container_name=self.settings.cosmos.rbac_config_container,
                query=query,
            )
            
            return [RBACConfig(**item) for item in items]
            
        except Exception as e:
            logger.error("Failed to load RBAC configs", error=str(e))
            return []
    
    async def get_all_available_tools(self) -> List[Dict[str, Any]]:
        """
        Get all available tools from all configured MCP servers.

        Returns:
            List of tool definitions with their MCP source
        """
        try:
            from fastmcp import Client

            if not self.mcp_endpoints:
                logger.warning("No MCP endpoints configured")
                return []

            all_tools = []

            for mcp_name, endpoint in self.mcp_endpoints.items():
                try:
                    # Connect to MCP server and get tools
                    client = Client(endpoint)
                    async with client:
                        mcp_tools = await client.list_tools()

                        for tool in mcp_tools:
                            # Convert FastMCP tool schema to OpenAI function schema
                            tool_def = {
                                "name": tool.name,
                                "description": tool.description,
                                "mcp_id": mcp_name,
                                "parameters": tool.inputSchema if hasattr(tool, 'inputSchema') else {}
                            }
                            all_tools.append(tool_def)

                        logger.info("Loaded tools for MCP", mcp_name=mcp_name, tool_count=len(mcp_tools))

                except Exception as e:
                    logger.error("Failed to get tools from MCP", mcp_name=mcp_name, error=str(e))
                    continue

            logger.info("All tools loaded", total_count=len(all_tools))
            return all_tools

        except Exception as e:
            logger.error("Failed to get all available tools", error=str(e))
            return []
    
    async def load_tool_definitions(
        self,
        mcp_id: str,
        rbac_context: Optional[RBACContext] = None
    ) -> List[ToolDefinition]:
        """
        Load tool definitions for a specific MCP.
        
        This is a fallback method that loads from Cosmos DB.
        For dev mode, we use get_all_available_tools() instead.
        
        Args:
            mcp_id: MCP identifier
            rbac_context: User RBAC context for filtering tools
        
        Returns:
            List of tool definitions
        """
        try:
            items = await self.cosmos_client.query_items(
                container_name=self.settings.cosmos.agent_functions_container,
                query="SELECT * FROM c WHERE c.mcp_id = @mcp_id",
                parameters=[{"name": "@mcp_id", "value": mcp_id}],
            )
            
            tools = [ToolDefinition(**item) for item in items]
            
            if self.settings.dev_mode:
                logger.info("Dev mode - returning all tools", mcp_id=mcp_id, count=len(tools))
                return tools
            
            if rbac_context:
                filtered_tools = await self._filter_tools_by_rbac(tools, rbac_context)
                logger.info(
                    "Tools filtered by RBAC",
                    mcp_id=mcp_id,
                    total=len(tools),
                    filtered=len(filtered_tools),
                )
                return filtered_tools
            
            return tools
            
        except Exception as e:
            logger.error("Failed to load tool definitions", mcp_id=mcp_id, error=str(e))
            return []
    
    async def _filter_tools_by_rbac(
        self,
        tools: List[ToolDefinition],
        rbac_context: RBACContext
    ) -> List[ToolDefinition]:
        """Filter tools based on user roles and RBAC configuration."""
        try:
            rbac_configs = await self._load_rbac_configs(rbac_context.roles)
            
            allowed_tool_names = set()
            for config in rbac_configs:
                allowed_tool_names.update(config.tool_access)
            
            filtered = [
                tool for tool in tools
                if tool.name in allowed_tool_names or self._check_tool_access(tool, rbac_context)
            ]
            
            return filtered
            
        except Exception as e:
            logger.error("Failed to filter tools by RBAC", error=str(e))
            return tools
    
    def _check_tool_access(self, tool: ToolDefinition, rbac_context: RBACContext) -> bool:
        """Check if user has access to tool based on roles."""
        if not tool.allowed_roles:
            return True
        
        for role in rbac_context.roles:
            if role in tool.allowed_roles:
                return True
        
        return False
    
    async def close(self):
        """Close HTTP client."""
        await self.http_client.aclose()
