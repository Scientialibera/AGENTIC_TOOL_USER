"""Test script to fetch tools from MCP servers."""
import asyncio
from fastmcp import Client

async def get_tools_from_mcp(endpoint: str):
    """Get tools from an MCP server."""
    client = Client(endpoint)
    async with client:
        tools = await client.list_tools()
        return tools

async def main():
    # Test Azure endpoints
    endpoints = {
        "SQL MCP": "https://sql-mcp.internal.calmpebble-eb198128.westus2.azurecontainerapps.io/mcp",
        "Graph MCP": "https://graph-mcp.internal.calmpebble-eb198128.westus2.azurecontainerapps.io/mcp",
        "Interpreter MCP": "https://interpreter-mcp.internal.calmpebble-eb198128.westus2.azurecontainerapps.io/mcp"
    }

    for name, endpoint in endpoints.items():
        print(f"\n=== {name} ({endpoint}) ===")
        try:
            tools = await get_tools_from_mcp(endpoint)
            print(f"✅ Successfully connected! Found {len(tools)} tool(s)")
            for tool in tools:
                print(f"  - Name: {tool.name}")
                print(f"    Description: {tool.description}")
                print(f"    Schema: {tool.inputSchema}")
                print()
        except Exception as e:
            print(f"❌ Error: {type(e).__name__}: {e}")

if __name__ == "__main__":
    asyncio.run(main())
