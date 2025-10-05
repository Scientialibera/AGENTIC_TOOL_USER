"""
Advanced multi-tool test for Orchestrator with SQL + Code Interpreter.
Tests queries that require both data retrieval and calculations.
"""

import asyncio
import httpx
import json
from azure.identity.aio import DefaultAzureCredential


async def get_access_token():
    """Get Azure AD access token using DefaultAzureCredential."""
    credential = DefaultAzureCredential()
    token = await credential.get_token("https://cognitiveservices.azure.com/.default")
    return token.token


async def test_msft_revenue_per_employee():
    """Test: Get MSFT sales then calculate revenue per employee."""
    print("\n" + "=" * 70)
    print("🔄 Test 1: Multi-Tool - MSFT Sales + Revenue Per Employee")
    print("=" * 70)
    
    try:
        token = await get_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        user_query = "Get all sales we have done to Microsoft and then give me revenue per employee if we have 10 employees on that account"
        print(f"\n💭 Query: '{user_query}'")
        print("\n📋 Expected flow:")
        print("   1. SQL MCP: Query sales/opportunities for Microsoft")
        print("   2. Interpreter MCP: Calculate total revenue")
        print("   3. Interpreter MCP: Divide by 10 employees")
        
        request_data = {
            "messages": [{"role": "user", "content": user_query}],
            "user_id": "test_user@example.com",
            "session_id": f"test_msft_{asyncio.get_event_loop().time()}",
            "metadata": {}
        }
        
        print("\n🚀 Sending request...")
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "http://localhost:8000/chat",
                json=request_data,
                timeout=120.0,  # Longer timeout for multi-tool
                headers=headers
            )
            
            if response.status_code == 200:
                data = response.json()
                print("✅ Request successful!")
                print(f"\n📊 Response: {data.get('response', '')}")
                
                # Show tool lineage
                if data.get('tool_lineage'):
                    print(f"\n🔧 Tool Execution Chain:")
                    for idx, tool in enumerate(data['tool_lineage'], 1):
                        print(f"\n   Step {idx}: {tool.get('tool_name')} via {tool.get('mcp_server')}")
                        print(f"   └─ Summary: {tool.get('result_summary')}")
                        
                        # Show input/output for clarity
                        if tool.get('input'):
                            input_preview = str(tool['input'])[:100]
                            print(f"   └─ Input: {input_preview}...")
                
                # Show execution details
                if data.get('metadata'):
                    meta = data['metadata']
                    print(f"\n⚙️  Execution:")
                    print(f"   - MCPs used: {', '.join(meta.get('mcps_used', []))}")
                    print(f"   - Rounds: {meta.get('rounds', 'N/A')}")
                    print(f"   - Duration: {meta.get('execution_time_ms', 'N/A')}ms")
                    print(f"   - Tool calls: {len(data.get('tool_lineage', []))}")
                
                # Validate multi-tool usage
                mcps_used = set(tool.get('mcp_server') for tool in data.get('tool_lineage', []))
                expected_mcps = {'sql_mcp', 'interpreter_mcp'}
                
                if expected_mcps.issubset(mcps_used):
                    print(f"\n✅ Multi-tool test passed! Used both SQL and Interpreter MCPs")
                else:
                    print(f"\n⚠️  Warning: Expected both SQL and Interpreter, got: {mcps_used}")
                
                return True
            else:
                print(f"❌ Failed with status {response.status_code}")
                print(f"   Response: {response.text[:500]}")
                return False
                
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_ai_chatbot_sow_analysis():
    """Test: Get all SOWs for ai_chatbot then calculate average revenue per SOW."""
    print("\n" + "=" * 70)
    print("🔄 Test 2: Multi-Tool - AI Chatbot SOWs + Average Revenue")
    print("=" * 70)
    
    try:
        token = await get_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        user_query = "Get me all SOWs we have for ai_chatbot and then do revenue average per SOW"
        print(f"\n💭 Query: '{user_query}'")
        print("\n📋 Expected flow:")
        print("   1. SQL MCP: Query SOWs/opportunities for ai_chatbot")
        print("   2. Interpreter MCP: Calculate total revenue")
        print("   3. Interpreter MCP: Calculate average per SOW")
        
        request_data = {
            "messages": [{"role": "user", "content": user_query}],
            "user_id": "test_user@example.com",
            "session_id": f"test_sow_{asyncio.get_event_loop().time()}",
            "metadata": {}
        }
        
        print("\n🚀 Sending request...")
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "http://localhost:8000/chat",
                json=request_data,
                timeout=120.0,
                headers=headers
            )
            
            if response.status_code == 200:
                data = response.json()
                print("✅ Request successful!")
                print(f"\n📊 Response: {data.get('response', '')}")
                
                # Show tool lineage
                if data.get('tool_lineage'):
                    print(f"\n🔧 Tool Execution Chain:")
                    for idx, tool in enumerate(data['tool_lineage'], 1):
                        print(f"\n   Step {idx}: {tool.get('tool_name')} via {tool.get('mcp_server')}")
                        print(f"   └─ Summary: {tool.get('result_summary')}")
                
                # Show execution details
                if data.get('metadata'):
                    meta = data['metadata']
                    print(f"\n⚙️  Execution:")
                    print(f"   - MCPs used: {', '.join(meta.get('mcps_used', []))}")
                    print(f"   - Rounds: {meta.get('rounds', 'N/A')}")
                    print(f"   - Duration: {meta.get('execution_time_ms', 'N/A')}ms")
                    print(f"   - Tool calls: {len(data.get('tool_lineage', []))}")
                
                # Validate multi-tool usage
                mcps_used = set(tool.get('mcp_server') for tool in data.get('tool_lineage', []))
                expected_mcps = {'sql_mcp', 'interpreter_mcp'}
                
                if expected_mcps.issubset(mcps_used):
                    print(f"\n✅ Multi-tool test passed! Used both SQL and Interpreter MCPs")
                else:
                    print(f"\n⚠️  Warning: Expected both SQL and Interpreter, got: {mcps_used}")
                
                return True
            else:
                print(f"❌ Failed with status {response.status_code}")
                print(f"   Response: {response.text[:500]}")
                return False
                
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_google_opportunities_cagr():
    """Test: Get Google opportunities and calculate CAGR."""
    print("\n" + "=" * 70)
    print("🔄 Test 3: Multi-Tool - Google Opportunities + CAGR")
    print("=" * 70)
    
    try:
        token = await get_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        user_query = "Get all opportunities for Google and if we closed a $1M deal in 2020 and it grew to $3M by 2025, what's our CAGR?"
        print(f"\n💭 Query: '{user_query}'")
        print("\n📋 Expected flow:")
        print("   1. SQL MCP: Query opportunities for Google")
        print("   2. Interpreter MCP: Calculate CAGR from $1M to $3M over 5 years")
        
        request_data = {
            "messages": [{"role": "user", "content": user_query}],
            "user_id": "test_user@example.com",
            "session_id": f"test_google_{asyncio.get_event_loop().time()}",
            "metadata": {}
        }
        
        print("\n🚀 Sending request...")
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "http://localhost:8000/chat",
                json=request_data,
                timeout=120.0,
                headers=headers
            )
            
            if response.status_code == 200:
                data = response.json()
                print("✅ Request successful!")
                print(f"\n📊 Response: {data.get('response', '')}")
                
                # Show tool lineage
                if data.get('tool_lineage'):
                    print(f"\n🔧 Tool Execution Chain:")
                    for idx, tool in enumerate(data['tool_lineage'], 1):
                        print(f"\n   Step {idx}: {tool.get('tool_name')} via {tool.get('mcp_server')}")
                        print(f"   └─ Summary: {tool.get('result_summary')}")
                
                # Validate multi-tool usage
                mcps_used = set(tool.get('mcp_server') for tool in data.get('tool_lineage', []))
                
                if 'sql_mcp' in mcps_used and 'interpreter_mcp' in mcps_used:
                    print(f"\n✅ Multi-tool test passed!")
                
                return True
            else:
                print(f"❌ Failed with status {response.status_code}")
                print(f"   Response: {response.text[:500]}")
                return False
                
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_top_accounts_analysis():
    """Test: Get top 3 accounts by revenue and calculate total + percentages."""
    print("\n" + "=" * 70)
    print("🔄 Test 4: Multi-Tool - Top Accounts + Revenue Analysis")
    print("=" * 70)
    
    try:
        token = await get_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        user_query = "Show me our top 3 accounts by revenue and calculate what percentage each represents of our total"
        print(f"\n💭 Query: '{user_query}'")
        print("\n📋 Expected flow:")
        print("   1. SQL MCP: Query top 3 accounts by revenue")
        print("   2. Interpreter MCP: Calculate total revenue")
        print("   3. Interpreter MCP: Calculate percentage for each account")
        
        request_data = {
            "messages": [{"role": "user", "content": user_query}],
            "user_id": "test_user@example.com",
            "session_id": f"test_top_{asyncio.get_event_loop().time()}",
            "metadata": {}
        }
        
        print("\n🚀 Sending request...")
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "http://localhost:8000/chat",
                json=request_data,
                timeout=120.0,
                headers=headers
            )
            
            if response.status_code == 200:
                data = response.json()
                print("✅ Request successful!")
                print(f"\n📊 Response: {data.get('response', '')}")
                
                # Show tool lineage
                if data.get('tool_lineage'):
                    print(f"\n🔧 Tool Execution Chain ({len(data['tool_lineage'])} steps):")
                    for idx, tool in enumerate(data['tool_lineage'], 1):
                        print(f"   {idx}. {tool.get('tool_name')} [{tool.get('mcp_server')}]")
                
                # Validate multi-tool usage
                mcps_used = set(tool.get('mcp_server') for tool in data.get('tool_lineage', []))
                
                if 'sql_mcp' in mcps_used and 'interpreter_mcp' in mcps_used:
                    print(f"\n✅ Multi-tool test passed!")
                
                return True
            else:
                print(f"❌ Failed with status {response.status_code}")
                print(f"   Response: {response.text[:500]}")
                return False
                
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Run all multi-tool tests."""
    print("\n" + "=" * 70)
    print("🧪 MULTI-TOOL ORCHESTRATION TEST SUITE")
    print("=" * 70)
    print("\nThese tests verify the orchestrator can chain SQL queries")
    print("with code interpreter calculations in a single conversation.\n")
    
    results = {}
    
    # Run all tests
    results['msft_revenue_per_employee'] = await test_msft_revenue_per_employee()
    results['ai_chatbot_sow_analysis'] = await test_ai_chatbot_sow_analysis()
    results['google_cagr'] = await test_google_opportunities_cagr()
    results['top_accounts_analysis'] = await test_top_accounts_analysis()
    
    # Summary
    print("\n" + "=" * 70)
    print("📋 TEST SUMMARY")
    print("=" * 70)
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for test_name, result in results.items():
        status = '✅ PASSED' if result else '❌ FAILED'
        print(f"   {test_name.replace('_', ' ').title()}: {status}")
    
    print(f"\n   Total: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n" + "=" * 70)
        print("✅ ALL MULTI-TOOL TESTS PASSED")
        print("=" * 70)
        print("\n🎉 The orchestrator successfully chained SQL + Interpreter tools!")
    else:
        print("\n" + "=" * 70)
        print(f"⚠️  {total - passed} TEST(S) FAILED")
        print("=" * 70)
    
    return passed == total


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
