"""
Test script for Orchestrator.

This script tests the orchestrator's ability to coordinate between
SQL and Graph MCP servers to answer complex queries.
"""

import asyncio
import json
import httpx


async def test_orchestrator_health():
    """Test if orchestrator is running."""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get("http://localhost:8000/health", timeout=5.0)
            if response.status_code == 200:
                print(" Orchestrator is healthy")
                return True
            else:
                print(f"  Orchestrator returned status {response.status_code}")
                return False
        except Exception as e:
            print(f" Orchestrator is not running: {e}")
            return False


async def test_list_mcps():
    """Test listing available MCPs."""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get("http://localhost:8000/mcps", timeout=10.0)
            if response.status_code == 200:
                data = response.json()
                print("\n Available MCPs:")
                for mcp in data.get("mcps", []):
                    print(f"  - {mcp.get('id')}: {mcp.get('name')}")
                return True
            else:
                print(f" Failed to list MCPs: {response.status_code}")
                return False
        except Exception as e:
            print(f" Error listing MCPs: {e}")
            return False


async def test_list_tools():
    """Test listing available tools."""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get("http://localhost:8000/tools", timeout=10.0)
            if response.status_code == 200:
                data = response.json()
                print("\n Available Tools:")
                for tool in data.get("tools", []):
                    print(f"  - {tool.get('name')} (from {tool.get('mcp_id')})")
                    print(f"    {tool.get('description', 'No description')[:80]}...")
                return True
            else:
                print(f" Failed to list tools: {response.status_code}")
                return False
        except Exception as e:
            print(f" Error listing tools: {e}")
            return False


async def test_sql_query_through_orchestrator():
    """Test SQL query through orchestrator."""
    print("\n" + "="*70)
    print(" Testing SQL Query via Orchestrator")
    print("="*70)
    
    async with httpx.AsyncClient() as client:
        user_query = "Show me all opportunities over $100,000 for Microsoft"
        
        request_data = {
            "messages": [
                {
                    "role": "user",
                    "content": user_query
                }
            ],
            "user_id": "test_user@example.com",
            "session_id": "test_session_1",
            "metadata": {}
        }
        
        print(f"\n Sending query: {user_query}")
        
        try:
            response = await client.post(
                "http://localhost:8000/chat",
                json=request_data,
                timeout=60.0
            )
            
            if response.status_code == 200:
                data = response.json()
                print("\n Query executed successfully!")
                print(f"\n Response:")
                print(f"  Success: {data.get('success')}")
                print(f"  Response: {data.get('response', 'N/A')[:200]}...")
                
                if data.get('execution_metadata'):
                    meta = data['execution_metadata']
                    print(f"\n  Execution Details:")
                    print(f"    - Rounds: {meta.get('rounds', 'N/A')}")
                    print(f"    - Agent Calls: {meta.get('total_agent_calls', 'N/A')}")
                
                return True
            else:
                print(f" Query failed: {response.status_code}")
                print(f"Response: {response.text[:500]}")
                return False
                
        except Exception as e:
            print(f" Error executing query: {e}")
            import traceback
            traceback.print_exc()
            return False


async def test_graph_query_through_orchestrator():
    """Test Graph query through orchestrator."""
    print("\n" + "="*70)
    print(" Testing Graph Query via Orchestrator")
    print("="*70)
    
    async with httpx.AsyncClient() as client:
        user_query = "Show me accounts who have SOWs of type 'ai_chatbot'"
        request_data = {
            "messages": [
                {
                    "role": "user",
                    "content": user_query
                }
            ],
            "user_id": "test_user@example.com",
            "session_id": "test_session_2",
            "metadata": {}
        }
        
        print(f"\n Sending query: {user_query}")
        
        try:
            response = await client.post(
                "http://localhost:8000/chat",
                json=request_data,
                timeout=60.0
            )
            
            if response.status_code == 200:
                data = response.json()
                print("\n Query executed successfully!")
                print(f"\n Response:")
                print(f"  Success: {data.get('success')}")
                print(f"  Response: {data.get('response', 'N/A')[:200]}...")
                
                return True
            else:
                print(f" Query failed: {response.status_code}")
                print(f"Response: {response.text[:500]}")
                return False
                
        except Exception as e:
            print(f" Error executing query: {e}")
            return False



async def main():
    """Run all orchestrator tests."""
    print("="*70)
    print(" Testing Orchestrator")
    print("="*70)
    print("\n  Prerequisites:")
    print("  1. SQL MCP Server running on port 8001")
    print("  2. Graph MCP Server running on port 8002")
    print("  3. Orchestrator running on port 8000")
    print("  4. DEV_MODE=true for local testing")
    
    # Test 1: Health check
    print("\n" + "="*70)
    print(" Health Check")
    print("="*70)
    healthy = await test_orchestrator_health()
    
    if not healthy:
        print("\n Orchestrator is not running!")
        print("\n To start the orchestrator:")
        print("   cd C:\\Users\\emili\\Documents\\AGENTIC_TOOL_USER\\agentic_framework")
        print("   python -m orchestrator.app")
        return
    
    # Test 2: List MCPs
    await test_list_mcps()
    
    # Test 3: List Tools
    await test_list_tools()
    
    # Test 4: SQL query
    await test_sql_query_through_orchestrator()
    
    # Test 5: Graph query
    await test_graph_query_through_orchestrator()
    
    print("\n" + "="*70)
    print(" All orchestrator tests completed!")
    print("="*70)


if __name__ == "__main__":
    asyncio.run(main())
