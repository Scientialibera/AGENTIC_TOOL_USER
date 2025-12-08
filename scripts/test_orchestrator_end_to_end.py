"""Test the orchestrator end-to-end with tool discovery and SQL queries."""
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
    """Test orchestrator with real SQL queries."""
    settings = get_settings()
    orchestrator = Orchestrator(settings)

    print("="*80)
    print("ORCHESTRATOR END-TO-END TEST - SQL Agent with Value Mappings")
    print("="*80)
    print()

    # Test 1: Simple query - should discover SQL MCP tools and execute
    print("="*80)
    print("TEST 1: Simple query - 'Show me all opportunities in negotiation'")
    print("="*80)
    print()

    request1 = UserRequest(
        user_id="test-user-1",
        message="Show me all opportunities that are in negotiation stage"
    )

    print(f"User: {request1.message}")
    print("\nExpected behavior:")
    print("  1. Orchestrator discovers available MCPs (SQL MCP)")
    print("  2. Discovers SQL MCP tools (sql_query, list_tables, etc.)")
    print("  3. Generates T-SQL query")
    print("  4. Uses value_mappings to map 'negotiation' -> 'Negotiation'")
    print("  5. Executes query and returns results")
    print()

    try:
        response1 = await orchestrator.orchestrate(request1)
        print(f"\nOrchestrator Response:")
        print(f"{response1.response}")
        print()
        if response1.sql_query:
            print(f"SQL Query executed: {response1.sql_query}")
        print(f"Tool calls made: {len(response1.tool_calls)}")
        for i, tool_call in enumerate(response1.tool_calls, 1):
            print(f"  {i}. {tool_call.tool_name}")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

    # Test 2: Complex query with multiple conditions
    print("\n" + "="*80)
    print("TEST 2: Complex query - 'Which tech companies have won deals over $100k?'")
    print("="*80)
    print()

    request2 = UserRequest(
        user_id="test-user-2",
        message="Show me technology companies that have closed won opportunities over $100,000"
    )

    print(f"User: {request2.message}")
    print("\nExpected behavior:")
    print("  1. Discovers SQL MCP tools")
    print("  2. Generates JOIN query between Account and Opportunity")
    print("  3. Maps 'technology' -> 'Technology' and 'closed won' -> 'Closed Won'")
    print("  4. Filters by amount > 100000")
    print()

    try:
        response2 = await orchestrator.orchestrate(request2)
        print(f"\nOrchestrator Response:")
        print(f"{response2.response}")
        print()
        if response2.sql_query:
            print(f"SQL Query executed: {response2.sql_query}")
        print(f"Tool calls made: {len(response2.tool_calls)}")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

    # Test 3: Query involving reserved keyword [Case]
    print("\n" + "="*80)
    print("TEST 3: Reserved keyword - 'Show me high priority open cases'")
    print("="*80)
    print()

    request3 = UserRequest(
        user_id="test-user-3",
        message="Show me all open cases with high or critical priority"
    )

    print(f"User: {request3.message}")
    print("\nExpected behavior:")
    print("  1. Uses [Case] table (reserved keyword)")
    print("  2. Maps priority values: 'high' -> 'High', 'critical' -> 'Critical'")
    print("  3. Filters for non-closed statuses")
    print()

    try:
        response3 = await orchestrator.orchestrate(request3)
        print(f"\nOrchestrator Response:")
        print(f"{response3.response}")
        print()
        if response3.sql_query:
            print(f"SQL Query executed: {response3.sql_query}")
        print(f"Tool calls made: {len(response3.tool_calls)}")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "="*80)
    print("[OK] Orchestrator end-to-end tests completed!")
    print("="*80)


if __name__ == "__main__":
    asyncio.run(test_orchestrator())
