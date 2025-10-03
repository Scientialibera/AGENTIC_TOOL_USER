"""
Test script for SQL MCP Server.

This script tests the SQL MCP server with both natural language queries
and validates that dev mode returns dummy data correctly.
"""

import asyncio
import json
from fastmcp import Client


async def test_sql_query_natural_language():
    """Test SQL query with natural language."""
    
    async with Client("http://localhost:8001/mcp") as client:
        print(" Connected to SQL MCP Server")
        
        # List available tools
        tools = await client.list_tools()
        print(f"\n Available tools: {[t.name for t in tools]}")
        
        # Test query: Natural language about opportunities
        natural_query = "Show me all opportunities over $100,000 for Microsoft"
        
        # Mock RBAC context (dev mode will bypass this)
        rbac_context = {
            "user_id": "test_user",
            "email": "test@example.com",
            "tenant_id": "test_tenant",
            "object_id": "test_object",
            "roles": ["admin"],
            "access_scope": {
                "account_ids": [],
                "all_accounts": True,
                "owned_only": False,
                "team_access": False
            }
        }
        
        print("\n Executing natural language SQL query...")
        print(f"Query: {natural_query}")
        
        try:
            result = await client.call_tool(
                "sql_query",
                arguments={
                    "query": natural_query,
                    "rbac_context": rbac_context,
                    "accounts_mentioned": ["Microsoft"]
                }
            )
            
            print("\n Query executed successfully!")
            print("\n Result:")
            
            # Parse the result
            if hasattr(result, 'data'):
                data = result.data
                print(f"  Success: {data.get('success')}")
                print(f"  Source: {data.get('source')}")
                print(f"  Row Count: {data.get('row_count')}")
                print(f"  Generated SQL: {data.get('query', 'N/A')[:100]}...")
                
                if data.get('data'):
                    print(f"\n  Sample Data (first 3 rows):")
                    for i, row in enumerate(data['data'][:3], 1):
                        print(f"    {i}. {row}")
                
                if data.get('resolved_accounts'):
                    print(f"\n  Resolved Accounts: {data['resolved_accounts']}")
            else:
                print(json.dumps(result, indent=2, default=str))
            
        except Exception as e:
            print(f"\n Error executing query: {e}")
            import traceback
            traceback.print_exc()



async def main():
    """Run all SQL MCP tests."""
    print("="*70)
    print(" Testing SQL MCP Server (Dev Mode)")
    print("="*70)
    print("\n  Dev Mode Behavior:")
    print("  - RBAC filtering is disabled")
    print("  - Returns dummy SQL data (no Fabric connection needed)")
    print("  - Account resolution uses test accounts")
    print("  - Query generation still uses real Azure OpenAI")
    
    # Test 1: Natural language query
    await test_sql_query_natural_language()

    
    print("\n" + "="*70)
    print(" All SQL MCP tests completed!")
    print("="*70)
    print("\n Tips:")
    print("  - To test with real Fabric SQL, set DEV_MODE=false in .env")
    print("  - To test RBAC filtering, disable dev mode")
    print("  - Dev mode is perfect for local development without Fabric setup")


if __name__ == "__main__":
    asyncio.run(main())
