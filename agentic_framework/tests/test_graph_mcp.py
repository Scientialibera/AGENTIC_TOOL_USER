"""
Test script for Graph MCP Server.

This script tests the Graph MCP server with a valid Gremlin query.
"""

import asyncio
import json
from fastmcp import Client


async def test_simple_graph_query():
    """Test with a simpler natural language query."""
    
    async with Client("http://localhost:8002/mcp") as client:
        print("\n" + "="*70)
        print(" Testing with natural language query")
        print("="*70)
        
        # Natural language query
        natural_query = "Show me accounts similar to Microsoft Corporation with ai_chatbot sows"
        
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
        
        print(f"\n  Natural query: {natural_query}")
        
        try:
            result = await client.call_tool(
                "graph_query",
                arguments={
                    "query": natural_query,
                    "rbac_context": rbac_context,
                    "accounts_mentioned": ["Microsoft Corporation"]
                }
            )
            
            print("\n Natural language query executed!")
            print("\n Result:")
            print(json.dumps(result, indent=2, default=str))
            
        except Exception as e:
            print(f"\n Error: {e}")


async def main():
    """Run all tests."""
    print("="*70)
    print(" Testing Graph MCP Server")
    print("="*70)
    
    
    # Test 2: Natural language query
    await test_simple_graph_query()
    
    print("\n" + "="*70)
    print(" All tests completed!")
    print("="*70)


if __name__ == "__main__":
    asyncio.run(main())
