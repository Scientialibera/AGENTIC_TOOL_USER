"""
Test script for Orchestrator with Code Interpreter MCP.
Tests mathematical calculations and data analysis through the interpreter.
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


async def test_simple_math():
    """Test simple mathematical calculation."""
    print("\n" + "=" * 70)
    print("🧮 Test 1: Simple Math Calculation")
    print("=" * 70)
    
    try:
        token = await get_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        user_query = "Calculate 157 * 234 + 891"
        print(f"\n💭 Query: '{user_query}'")
        
        request_data = {
            "messages": [{"role": "user", "content": user_query}],
            "user_id": "test_user@example.com",
            "session_id": f"test_math_{asyncio.get_event_loop().time()}",
            "metadata": {}
        }
        
        print("🚀 Sending request...")
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "http://localhost:8000/chat",
                json=request_data,
                timeout=90.0,
                headers=headers
            )
            
            if response.status_code == 200:
                data = response.json()
                print("✅ Request successful!")
                print(f"\n📊 Response: {data.get('response', '')}")
                
                # Show tool lineage
                if data.get('tool_lineage'):
                    print(f"\n🔧 Tool Usage:")
                    for idx, tool in enumerate(data['tool_lineage'], 1):
                        print(f"   {idx}. {tool.get('tool_name')} via {tool.get('mcp_server')}")
                        print(f"      Result: {tool.get('result_summary')}")
                
                # Show execution details
                if data.get('metadata'):
                    meta = data['metadata']
                    print(f"\n⚙️  Execution:")
                    print(f"   - MCPs used: {', '.join(meta.get('mcps_used', []))}")
                    print(f"   - Rounds: {meta.get('rounds', 'N/A')}")
                    print(f"   - Duration: {meta.get('execution_time_ms', 'N/A')}ms")
                
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


async def test_revenue_calculation():
    """Test revenue per employee calculation."""
    print("\n" + "=" * 70)
    print("💼 Test 2: Revenue Per Employee Calculation")
    print("=" * 70)
    
    try:
        token = await get_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        user_query = "If our company made $5.2 million in revenue and we have 87 employees, what's the revenue per employee?"
        print(f"\n💭 Query: '{user_query}'")
        
        request_data = {
            "messages": [{"role": "user", "content": user_query}],
            "user_id": "test_user@example.com",
            "session_id": f"test_revenue_{asyncio.get_event_loop().time()}",
            "metadata": {}
        }
        
        print("🚀 Sending request...")
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "http://localhost:8000/chat",
                json=request_data,
                timeout=90.0,
                headers=headers
            )
            
            if response.status_code == 200:
                data = response.json()
                print("✅ Request successful!")
                print(f"\n📊 Response: {data.get('response', '')}")
                
                if data.get('tool_lineage'):
                    print(f"\n🔧 Tool Usage:")
                    for idx, tool in enumerate(data['tool_lineage'], 1):
                        print(f"   {idx}. {tool.get('tool_name')} via {tool.get('mcp_server')}")
                        if tool.get('output'):
                            output = tool['output']
                            if isinstance(output, dict) and output.get('result'):
                                print(f"      Result preview: {str(output['result'])[:200]}")
                
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


async def test_data_analysis():
    """Test data analysis with monthly revenues."""
    print("\n" + "=" * 70)
    print("📊 Test 3: Monthly Revenue Analysis")
    print("=" * 70)
    
    try:
        token = await get_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        user_query = """Analyze these monthly revenues and tell me the total, average, and standard deviation:
        January: $52,000
        February: $48,000
        March: $61,000
        April: $55,000
        May: $72,000
        June: $68,000"""
        
        print(f"\n💭 Query: Monthly revenue analysis")
        
        request_data = {
            "messages": [{"role": "user", "content": user_query}],
            "user_id": "test_user@example.com",
            "session_id": f"test_analysis_{asyncio.get_event_loop().time()}",
            "metadata": {}
        }
        
        print("🚀 Sending request...")
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "http://localhost:8000/chat",
                json=request_data,
                timeout=90.0,
                headers=headers
            )
            
            if response.status_code == 200:
                data = response.json()
                print("✅ Request successful!")
                print(f"\n📊 Response: {data.get('response', '')}")
                
                if data.get('tool_lineage'):
                    print(f"\n🔧 Tool Usage:")
                    for idx, tool in enumerate(data['tool_lineage'], 1):
                        print(f"   {idx}. {tool.get('tool_name')} via {tool.get('mcp_server')}")
                
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


async def test_cagr_calculation():
    """Test CAGR calculation."""
    print("\n" + "=" * 70)
    print("📈 Test 4: CAGR Calculation")
    print("=" * 70)
    
    try:
        token = await get_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        user_query = "Calculate the compound annual growth rate if we started with $100,000 and ended with $250,000 over 5 years"
        print(f"\n💭 Query: '{user_query}'")
        
        request_data = {
            "messages": [{"role": "user", "content": user_query}],
            "user_id": "test_user@example.com",
            "session_id": f"test_cagr_{asyncio.get_event_loop().time()}",
            "metadata": {}
        }
        
        print("🚀 Sending request...")
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "http://localhost:8000/chat",
                json=request_data,
                timeout=90.0,
                headers=headers
            )
            
            if response.status_code == 200:
                data = response.json()
                print("✅ Request successful!")
                print(f"\n📊 Response: {data.get('response', '')}")
                
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
    """Run all interpreter tests."""
    print("\n" + "=" * 70)
    print("🧪 CODE INTERPRETER MCP TEST SUITE")
    print("=" * 70)
    print("\nThese tests verify the orchestrator can route math/calculation")
    print("queries to the Code Interpreter MCP for execution.\n")
    
    results = {}
    
    # Run all tests
    results['simple_math'] = await test_simple_math()
    results['revenue_calc'] = await test_revenue_calculation()
    results['data_analysis'] = await test_data_analysis()
    results['cagr'] = await test_cagr_calculation()
    
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
        print("✅ ALL TESTS PASSED")
        print("=" * 70)
    else:
        print("\n" + "=" * 70)
        print(f"⚠️  {total - passed} TEST(S) FAILED")
        print("=" * 70)
    
    return passed == total


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)
