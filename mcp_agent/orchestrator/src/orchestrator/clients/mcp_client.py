"""
MCP Protocol client for communicating with MCP servers.

This client handles HTTP-based communication with MCP servers using the
MCP protocol over HTTP transport.
"""

import httpx
import structlog
from typing import Dict, Any, List, Optional

logger = structlog.get_logger(__name__)


class MCPClient:
    """Client for communicating with MCP servers via HTTP."""

    def __init__(self, server_url: str, service_token: str, timeout: int = 30):
        """
        Initialize MCP client.

        Args:
            server_url: Base URL of the MCP server
            service_token: JWT token for service authentication
            timeout: Request timeout in seconds
        """
        self.server_url = server_url.rstrip("/")
        self.service_token = service_token
        self.timeout = timeout
        self._client = httpx.AsyncClient(timeout=timeout)

    async def list_tools(self) -> List[Dict[str, Any]]:
        """
        List available tools from the MCP server.

        Returns:
            List of tool definitions
        """
        try:
            response = await self._client.post(
                f"{self.server_url}/mcp/tools/list",
                headers={"Authorization": f"Bearer {self.service_token}"},
                json={},
            )
            response.raise_for_status()
            data = response.json()
            return data.get("tools", [])

        except Exception as e:
            logger.error("Failed to list tools from MCP server", server=self.server_url, error=str(e))
            return []

    async def call_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        rbac_context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Call a tool on the MCP server.

        Args:
            tool_name: Name of the tool to call
            arguments: Tool arguments
            rbac_context: RBAC context to pass to the tool

        Returns:
            Tool execution result
        """
        try:
            # Include RBAC context in arguments
            full_arguments = {**arguments}
            if rbac_context:
                full_arguments["rbac_context"] = rbac_context

            response = await self._client.post(
                f"{self.server_url}/mcp/tools/call",
                headers={"Authorization": f"Bearer {self.service_token}"},
                json={
                    "name": tool_name,
                    "arguments": full_arguments,
                },
            )
            response.raise_for_status()
            return response.json()

        except httpx.HTTPStatusError as e:
            logger.error(
                "HTTP error calling MCP tool",
                server=self.server_url,
                tool=tool_name,
                status=e.response.status_code,
                error=str(e)
            )
            return {
                "success": False,
                "error": f"HTTP {e.response.status_code}: {str(e)}",
            }
        except Exception as e:
            logger.error("Failed to call MCP tool", server=self.server_url, tool=tool_name, error=str(e))
            return {
                "success": False,
                "error": str(e),
            }

    async def close(self):
        """Close the HTTP client."""
        await self._client.aclose()
