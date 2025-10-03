#!/usr/bin/env python3
"""Test script for UnifiedDataService with session-centric storage."""

import asyncio
import sys
from pathlib import Path

# Add agentic_framework to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "agentic_framework"))

from shared.config import get_settings
from shared.cosmos_client import CosmosDBClient
from shared.unified_service import UnifiedDataService
from shared.models import RBACContext


async def test_session_lifecycle():
    """Test complete session lifecycle."""
    print("=" * 80)
    print("UNIFIED DATA SERVICE - SESSION LIFECYCLE TEST")
    print("=" * 80)

    # Initialize
    settings = get_settings()
    cosmos_client = CosmosDBClient(settings.cosmos)
    service = UnifiedDataService(cosmos_client, settings.cosmos)

    session_id = "test_session_lifecycle"
    user_id = "test@example.com"

    try:
        # Test 1: Create new session with first turn
        print("\n[TEST 1] Create new session with first turn")
        print(f"Session ID: {session_id}")
        print(f"User ID: {user_id}")

        session = await service.add_conversation_turn(
            session_id=session_id,
            user_id=user_id,
            user_message_content="What accounts have AI chatbot SOWs?",
            assistant_message_content="I found 5 accounts with AI chatbot SOWs: Microsoft, Salesforce, Google, AWS, SAP",
            mcp_calls=[
                {
                    "id": "mcp_001",
                    "mcp_name": "graph_mcp",
                    "tool_name": "query_graph",
                    "arguments": {"query": "g.V().has('offering', 'ai_chatbot')"},
                    "result": {"accounts": ["Microsoft", "Salesforce", "Google", "AWS", "SAP"]}
                }
            ],
            tool_calls=[
                {
                    "id": "tool_001",
                    "name": "query_graph",
                    "arguments": '{"query": "g.V().has(\'offering\', \'ai_chatbot\')"}',
                    "result": '{"accounts": ["Microsoft", "Salesforce", "Google", "AWS", "SAP"]}'
                }
            ],
            metadata={"planning_time_ms": 150, "execution_time_ms": 450}
        )

        print(f"[OK] Session created with {len(session.turns)} turn(s)")
        print(f"  - Turn ID: {session.turns[0].turn_id}")
        print(f"  - User message: {session.turns[0].user_message.content[:50]}...")
        print(f"  - Assistant message: {session.turns[0].assistant_message.content[:50]}...")
        print(f"  - MCP calls: {len(session.turns[0].mcp_calls)}")
        print(f"  - Tool calls: {len(session.turns[0].tool_calls)}")

        # Test 2: Retrieve existing session (no messages)
        print("\n[TEST 2] Retrieve existing session history")

        retrieved_session = await service.get_session_history(session_id, user_id)

        if retrieved_session:
            print(f"[OK] Retrieved session with {len(retrieved_session.turns)} turn(s)")
            print(f"  - Session ID: {retrieved_session.session_id}")
            print(f"  - User ID: {retrieved_session.user_id}")
            print(f"  - Created at: {retrieved_session.created_at}")
            print(f"  - Updated at: {retrieved_session.updated_at}")
        else:
            print("[FAIL] Could not retrieve session")

        # Test 3: Add second turn to existing session
        print("\n[TEST 3] Add second turn to existing session")

        session = await service.add_conversation_turn(
            session_id=session_id,
            user_id=user_id,
            user_message_content="Tell me more about the Microsoft SOW",
            assistant_message_content="The Microsoft AI Chatbot PoC was a $250k engagement in 2023...",
            metadata={"planning_time_ms": 120, "execution_time_ms": 300}
        )

        print(f"[OK] Added second turn, session now has {len(session.turns)} turn(s)")
        print(f"  - Turn 2 ID: {session.turns[1].turn_id}")
        print(f"  - Turn number: {session.turns[1].turn_number}")

        # Test 4: Add feedback to most recent turn
        print("\n[TEST 4] Add feedback to most recent turn")

        session = await service.add_feedback_to_latest_turn(
            session_id=session_id,
            user_id=user_id,
            feedback_type="thumbs_up",
            comment="Great answer, very helpful!"
        )

        latest_turn = session.get_latest_turn()
        print(f"[OK] Added feedback to turn {latest_turn.turn_id}")
        print(f"  - Feedback count: {len(latest_turn.feedback)}")
        print(f"  - Feedback type: {latest_turn.feedback[0]['type']}")
        print(f"  - Comment: {latest_turn.feedback[0]['comment']}")

        # Test 5: Add more feedback to same turn
        print("\n[TEST 5] Add additional feedback to same turn")

        session = await service.add_feedback_to_latest_turn(
            session_id=session_id,
            user_id=user_id,
            feedback_type="flag",
            comment="Minor formatting issue"
        )

        latest_turn = session.get_latest_turn()
        print(f"[OK] Added second feedback to turn {latest_turn.turn_id}")
        print(f"  - Total feedback count: {len(latest_turn.feedback)}")

        # Test 6: Retrieve full session and verify structure
        print("\n[TEST 6] Retrieve full session and verify structure")

        final_session = await service.get_session_history(session_id, user_id)

        print(f"[OK] Final session state:")
        print(f"  - Total turns: {len(final_session.turns)}")

        for i, turn in enumerate(final_session.turns, 1):
            print(f"\n  Turn {i} ({turn.turn_id}):")
            print(f"    - User: {turn.user_message.content[:40]}...")
            print(f"    - Assistant: {turn.assistant_message.content[:40]}...")
            print(f"    - MCP calls: {len(turn.mcp_calls)}")
            print(f"    - Tool calls: {len(turn.tool_calls)}")
            print(f"    - Feedback entries: {len(turn.feedback)}")
            if turn.feedback:
                for fb in turn.feedback:
                    print(f"      * {fb['type']}: {fb.get('comment', 'N/A')}")

        # Test 7: Delete session
        print("\n[TEST 7] Delete session")

        deleted = await service.delete_session(session_id, user_id)

        if deleted:
            print("[OK] Session deleted successfully")

            # Verify deletion
            check_session = await service.get_session_history(session_id, user_id)
            if check_session is None:
                print("[OK] Verified session was deleted")
            else:
                print("[FAIL] Session still exists after deletion")
        else:
            print("[FAIL] Failed to delete session")

        # Test 8: Try to get non-existent session
        print("\n[TEST 8] Try to retrieve non-existent session")

        no_session = await service.get_session_history("nonexistent_session", user_id)

        if no_session is None:
            print("[OK] Correctly returns None for non-existent session")
        else:
            print("[FAIL] Should return None for non-existent session")

        print("\n" + "=" * 80)
        print("ALL TESTS PASSED")
        print("=" * 80)

    except Exception as e:
        print(f"\n[FAIL] Test failed with error: {e}")
        import traceback
        traceback.print_exc()

    finally:
        await service.close()


async def test_cache_operations():
    """Test cache operations."""
    print("\n\n" + "=" * 80)
    print("UNIFIED DATA SERVICE - CACHE OPERATIONS TEST")
    print("=" * 80)

    settings = get_settings()
    cosmos_client = CosmosDBClient(settings.cosmos)
    service = UnifiedDataService(cosmos_client, settings.cosmos)

    # Create mock RBAC context
    rbac_context = RBACContext(
        user_id="test@example.com",
        email="test@example.com",
        tenant_id="test-tenant",
        object_id="test-object",
        roles=["sales_rep"]
    )

    try:
        # Test 1: Cache miss
        print("\n[TEST 1] Cache miss on first request")

        cached = await service.get_cached_query_result(
            query="SELECT * FROM accounts WHERE industry='Technology'",
            rbac_context=rbac_context,
            query_type="sql"
        )

        if cached is None:
            print("[OK] Cache miss as expected")
        else:
            print(f"[FAIL] Expected cache miss, got: {cached}")

        # Test 2: Set cache
        print("\n[TEST 2] Set cache value")

        await service.set_cached_query_result(
            query="SELECT * FROM accounts WHERE industry='Technology'",
            result={"accounts": ["Microsoft", "Salesforce", "Oracle"]},
            rbac_context=rbac_context,
            query_type="sql"
        )

        print("[OK] Cache value set")

        # Test 3: Cache hit
        print("\n[TEST 3] Cache hit on second request")

        cached = await service.get_cached_query_result(
            query="SELECT * FROM accounts WHERE industry='Technology'",
            rbac_context=rbac_context,
            query_type="sql"
        )

        if cached:
            print(f"[OK] Cache hit! Result: {cached}")
        else:
            print("[FAIL] Expected cache hit, got None")

        print("\n" + "=" * 80)
        print("CACHE TESTS PASSED")
        print("=" * 80)

    except Exception as e:
        print(f"\n[FAIL] Cache test failed: {e}")
        import traceback
        traceback.print_exc()

    finally:
        await service.close()


async def main():
    """Run all tests."""
    await test_session_lifecycle()
    await test_cache_operations()


if __name__ == "__main__":
    asyncio.run(main())
