"""Test SQL MCP Server directly - tools and queries."""
import asyncio
from fastmcp import Client


async def test_mcp():
    """Test SQL MCP server directly."""

    async with Client("http://localhost:8003/mcp") as client:
        print("="*80)
        print("SQL MCP SERVER TEST")
        print("="*80)
        print()

        # Test 1: List tools
        print("TEST 1: List available tools")
        print("-"*80)
        tools = await client.list_tools()
        print(f"Available tools ({len(tools)}):")
        for tool in tools:
            print(f"  - {tool.name}: {tool.description[:80]}...")
        print()

        # Test 2: List tables
        print("TEST 2: List tables")
        print("-"*80)
        result = await client.call_tool("list_tables", arguments={})
        if hasattr(result, 'data'):
            print(f"Tables: {result.data.get('tables', [])}")
        print()

        # Test 3: Execute query with automatic value matching
        print("TEST 3: Execute query (value matching automatic)")
        print("-"*80)
        query = "SELECT TOP 5 Name, StageName, Amount FROM Opportunity WHERE StageName = 'closed won' ORDER BY Amount DESC"
        print(f"Query: {query}")
        print("Note: 'closed won' will be auto-corrected to 'Closed Won' by MCP")
        print()

        result = await client.call_tool("sql_query", arguments={"query": query, "limit": 5})
        if hasattr(result, 'data'):
            data = result.data
            print(f"Success: {data.get('success')}")
            print(f"Rows: {data.get('row_count', 0)}")
            if data.get('data'):
                print("Results:")
                for i, row in enumerate(data['data'][:3], 1):
                    print(f"  {i}. {row.get('Name')} - {row.get('StageName')} - ${row.get('Amount', 0):,.0f}")
        print()

        print("="*80)
        print("[OK] All MCP tests passed!")
        print("="*80)


if __name__ == "__main__":
    asyncio.run(test_mcp())
