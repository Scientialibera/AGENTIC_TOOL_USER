"""
Simple test script for Orchestrator health check.
"""

import asyncio
import httpx
from azure.identity.aio import DefaultAzureCredential


async def get_access_token():
    """Get Azure AD access token using DefaultAzureCredential."""
    credential = DefaultAzureCredential()
    token = await credential.get_token("https://cognitiveservices.azure.com/.default")
    return token.token

async def test_orchestrator_health():
    """Test if orchestrator is running and authenticated."""
    print("\n" + "=" * 70)
    print("🧪 Testing Orchestrator Health")
    print("=" * 70)
    
    try:
        # Get Azure AD access token
        print("\n📋 Getting Azure AD access token...")
        token = await get_access_token()
        print("✅ Obtained Azure AD access token")
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        # Test health endpoint
        print("\n🔍 Testing /health endpoint...")
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "http://localhost:8000/health",
                timeout=5.0,
                headers=headers
            )
            
            if response.status_code == 200:
                data = response.json()
                print("✅ Orchestrator is healthy!")
                print(f"   Status: {data.get('status')}")
                print(f"   Version: {data.get('version')}")
                print(f"   Timestamp: {data.get('timestamp')}")
                return True
            else:
                print(f"❌ Orchestrator returned status {response.status_code}")
                print(f"   Response: {response.text}")
                return False
                
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_chat_query():
    """Test a real chat query through the orchestrator."""
    print("\n" + "=" * 70)
    print("💬 Testing Chat Query")
    print("=" * 70)
    
    try:
        # Get Azure AD access token
        print("\n📋 Getting Azure AD access token...")
        token = await get_access_token()
        print("✅ Obtained Azure AD access token")
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        # Create chat request
        user_query = "Show me all opportunities over $100,000"
        print(f"\n💭 Sending query: '{user_query}'")
        
        request_data = {
            "messages": [
                {
                    "role": "user",
                    "content": user_query
                }
            ],
            "user_id": "test_user@example.com",
            "session_id": "test_session_001",
            "metadata": {}
        }
        
        # Send chat request
        print("🚀 Sending chat request...")
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "http://localhost:8000/chat",
                json=request_data,
                timeout=60.0,
                headers=headers
            )
            
            if response.status_code == 200:
                data = response.json()
                print("✅ Chat query executed successfully!")
                print(f"\n📊 Response:")
                print(f"   Success: {data.get('success')}")
                print(f"   Message: {data.get('response', 'N/A')[:200]}...")
                
                if data.get('execution_metadata'):
                    meta = data['execution_metadata']
                    print(f"\n⚙️  Execution Details:")
                    print(f"   - Rounds: {meta.get('rounds', 'N/A')}")
                    print(f"   - Agent Calls: {meta.get('total_agent_calls', 'N/A')}")
                    print(f"   - Duration: {meta.get('duration_seconds', 'N/A')}s")
                
                return True
            else:
                print(f"❌ Chat query failed with status {response.status_code}")
                print(f"   Response: {response.text[:500]}")
                return False
                
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Run orchestrator tests."""
    print("\n" + "=" * 70)
    print("🧪 ORCHESTRATOR TEST SUITE")
    print("=" * 70)
    
    # Test 1: Health Check
    health_result = await test_orchestrator_health()
    
    if not health_result:
        print("\n⚠️  Orchestrator is not running! Skipping chat test.")
        print("\n💡 To start the orchestrator:")
        print("   cd C:\\Users\\emili\\Documents\\AGENTIC_TOOL_USER\\agentic_framework")
        print("   $env:PYTHONPATH=\"C:\\Users\\emili\\Documents\\AGENTIC_TOOL_USER\\agentic_framework\"")
        print("   python orchestrator/app.py")
        return
    
    # Test 2: Chat Query
    chat_result = await test_chat_query()
    
    # Summary
    print("\n" + "=" * 70)
    print("📋 TEST SUMMARY")
    print("=" * 70)
    print(f"   Health Check: {'✅ PASSED' if health_result else '❌ FAILED'}")
    print(f"   Chat Query:   {'✅ PASSED' if chat_result else '❌ FAILED'}")
    
    if health_result and chat_result:
        print("\n" + "=" * 70)
        print("✅ ALL TESTS PASSED")
        print("=" * 70)
    else:
        print("\n" + "=" * 70)
        print("❌ SOME TESTS FAILED")
        print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
