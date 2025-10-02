"""
MCP Loader Service for dynamically loading and managing MCP clients.

This service manages MCP server connections based on user roles and maintains
a pool of MCP clients for tool discovery and execution.
"""

import structlog
from typing import Dict, List, Optional
from orchestrator.clients.mcp_client import MCPClient

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../.."))

from shared.utils.auth_utils import create_service_token

logger = structlog.get_logger(__name__)


class MCPLoaderService:
    """Service for loading and managing MCP server connections."""

    def __init__(
        self,
        mcp_servers: Dict[str, str],
        service_jwt_secret: str,
        service_jwt_expiry_minutes: int = 60,
        dev_mode: bool = False,
    ):
        """
        Initialize MCP loader service.

        Args:
            mcp_servers: Mapping of MCP names to endpoint URLs
            service_jwt_secret: Secret for creating service tokens
            service_jwt_expiry_minutes: Token expiry time in minutes
            dev_mode: If True, bypass service token creation (use dev token)
        """
        self.mcp_servers = mcp_servers
        self.service_jwt_secret = service_jwt_secret
        self.service_jwt_expiry_minutes = service_jwt_expiry_minutes
        self.dev_mode = dev_mode
        self._mcp_clients: Dict[str, MCPClient] = {}
        self._mcp_tools: Dict[str, List[Dict]] = {}

        logger.info("Initialized MCP Loader Service", mcp_count=len(mcp_servers), dev_mode=dev_mode)

    async def load_mcp_clients(self, mcp_names: List[str]) -> Dict[str, MCPClient]:
        """
        Load MCP clients for the given MCP names.

        Args:
            mcp_names: List of MCP names to load

        Returns:
            Dictionary mapping MCP names to initialized clients
        """
        clients = {}

        for mcp_name in mcp_names:
            if mcp_name not in self.mcp_servers:
                logger.warning("MCP server not configured", mcp_name=mcp_name)
                continue

            if mcp_name in self._mcp_clients:
                clients[mcp_name] = self._mcp_clients[mcp_name]
                logger.debug("Reusing existing MCP client", mcp_name=mcp_name)
                continue

            # Create service token for MCP communication
            if self.dev_mode:
                service_token = "dev-token"
                logger.debug("Dev mode: using dev token for MCP", mcp_name=mcp_name)
            else:
                service_token = create_service_token(
                    service_name="orchestrator",
                    secret_key=self.service_jwt_secret,
                    expires_in_minutes=self.service_jwt_expiry_minutes,
                )

            # Create MCP client
            mcp_url = self.mcp_servers[mcp_name]
            client = MCPClient(
                server_url=mcp_url,
                service_token=service_token,
            )

            self._mcp_clients[mcp_name] = client
            clients[mcp_name] = client

            logger.info("Loaded MCP client", mcp_name=mcp_name, url=mcp_url)

        return clients

    async def discover_tools(self, mcp_names: List[str]) -> Dict[str, List[Dict]]:
        """
        Discover available tools from the given MCP servers.

        Args:
            mcp_names: List of MCP names to discover tools from

        Returns:
            Dictionary mapping MCP names to their tool lists
        """
        clients = await self.load_mcp_clients(mcp_names)
        tools = {}

        for mcp_name, client in clients.items():
            if mcp_name in self._mcp_tools:
                tools[mcp_name] = self._mcp_tools[mcp_name]
                logger.debug("Reusing cached tools", mcp_name=mcp_name, tool_count=len(tools[mcp_name]))
                continue

            try:
                mcp_tools = await client.list_tools()
                self._mcp_tools[mcp_name] = mcp_tools
                tools[mcp_name] = mcp_tools

                logger.info("Discovered tools from MCP", mcp_name=mcp_name, tool_count=len(mcp_tools))

            except Exception as e:
                logger.error("Failed to discover tools from MCP", mcp_name=mcp_name, error=str(e))
                tools[mcp_name] = []

        return tools

    def get_client(self, mcp_name: str) -> Optional[MCPClient]:
        """
        Get an existing MCP client by name.

        Args:
            mcp_name: Name of the MCP

        Returns:
            MCPClient instance or None if not loaded
        """
        return self._mcp_clients.get(mcp_name)

    async def close_all(self):
        """Close all MCP clients."""
        for mcp_name, client in self._mcp_clients.items():
            try:
                await client.close()
                logger.debug("Closed MCP client", mcp_name=mcp_name)
            except Exception as e:
                logger.error("Failed to close MCP client", mcp_name=mcp_name, error=str(e))

        self._mcp_clients.clear()
        self._mcp_tools.clear()
        logger.info("Closed all MCP clients")
