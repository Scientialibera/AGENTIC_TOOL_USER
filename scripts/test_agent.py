"""Test orchestrator end-to-end with tool discovery and SQL queries."""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTIC_FRAMEWORK = ROOT / "agentic_framework"
sys.path.insert(0, str(AGENTIC_FRAMEWORK))

from orchestrator.orchestrator import Orchestrator
from shared.config import get_settings
from shared.models import UserRequest


async def test_orchestrator():
    """Test orchestrator with SQL queries."""
    settings = get_settings()
    orchestrator = Orchestrator(settings)

    print("="*80)
    print("ORCHESTRATOR END-TO-END TEST")
    print("="*80)
    print()

    # Test 1: Simple query
    print("TEST 1: Simple query - opportunities in negotiation")
    print("-"*80)
    request1 = UserRequest(
        user_id="test-user",
        message="Show me opportunities that are in negotiation stage"
    )
    print(f"User: {request1.message}")
    print()

    try:
        response1 = await orchestrator.orchestrate(request1)
        print(f"Response: {response1.response}")
        print(f"Tools called: {len(response1.tool_calls)}")
        for tool_call in response1.tool_calls:
            print(f"  - {tool_call.tool_name}")
    except Exception as e:
        print(f"Error: {e}")
    print()

    # Test 2: Complex query
    print("TEST 2: Complex query - tech companies with won deals")
    print("-"*80)
    request2 = UserRequest(
        user_id="test-user",
        message="Show me technology companies that have closed won opportunities over $100,000"
    )
    print(f"User: {request2.message}")
    print()

    try:
        response2 = await orchestrator.orchestrate(request2)
        print(f"Response: {response2.response}")
        print(f"Tools called: {len(response2.tool_calls)}")
    except Exception as e:
        print(f"Error: {e}")
    print()

    print("="*80)
    print("[OK] Orchestrator tests completed!")
    print("="*80)


if __name__ == "__main__":
    asyncio.run(test_orchestrator())
