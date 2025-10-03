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
    print("=== SQL MCP Tools ===")
    sql_tools = await get_tools_from_mcp("http://localhost:8001")
    for tool in sql_tools:
        print(f"Name: {tool.name}")
        print(f"Description: {tool.description}")
        print(f"Schema: {tool.inputSchema}")
        print()

    print("\n=== Graph MCP Tools ===")
    graph_tools = await get_tools_from_mcp("http://localhost:8002")
    for tool in graph_tools:
        print(f"Name: {tool.name}")
        print(f"Description: {tool.description}")
        print(f"Schema: {tool.inputSchema}")
        print()

if __name__ == "__main__":
    asyncio.run(main())
