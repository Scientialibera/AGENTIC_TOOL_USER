#!/usr/bin/env python3
"""
Test script to directly interact with CosmosDBClient and understand issues.

This script will:
1. Connect to Cosmos DB
2. Test create_item
3. Test read_item
4. Test upsert_item
5. Test query_items
6. Test delete_item
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime
import json

# Add agentic_framework to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "agentic_framework"))

from shared.config import get_settings
from shared.cosmos_client import CosmosDBClient

# Test container name
TEST_CONTAINER = "unified_data"


async def test_cosmos_operations():
    """Test all Cosmos DB operations."""
    print("=" * 80)
    print("COSMOS DB CLIENT TEST SCRIPT")
    print("=" * 80)

    # Initialize
    settings = get_settings()
    print(f"\n[OK] Settings loaded")
    print(f"  - Endpoint: {settings.cosmos.endpoint}")
    print(f"  - Database: {settings.cosmos.database_name}")
    print(f"  - Container: {TEST_CONTAINER}")

    cosmos_client = CosmosDBClient(settings.cosmos)
    print(f"\n[OK] CosmosDBClient initialized")

    try:
        # Test 1: Create Item
        print("\n" + "=" * 80)
        print("TEST 1: CREATE ITEM")
        print("=" * 80)

        test_item_1 = {
            "id": "test_item_1",
            "type": "test",
            "message": "This is a test item",
            "created_at": datetime.utcnow().isoformat(),
            "number": 42
        }

        print(f"\nCreating item with ID: {test_item_1['id']}")
        print(f"Item data: {json.dumps(test_item_1, indent=2)}")

        try:
            created_item = await cosmos_client.create_item(
                container_name=TEST_CONTAINER,
                item=test_item_1
            )
            print(f"[OK] Item created successfully!")
            print(f"  - ID: {created_item.get('id')}")
            print(f"  - _etag: {created_item.get('_etag', 'N/A')}")
        except Exception as e:
            print(f"[FAIL] Failed to create item: {e}")
            print(f"  Error type: {type(e).__name__}")

        # Test 2: Read Item
        print("\n" + "=" * 80)
        print("TEST 2: READ ITEM")
        print("=" * 80)

        print(f"\nReading item with ID: test_item_1")
        print(f"Using partition_key_value: test_item_1")

        try:
            read_item = await cosmos_client.read_item(
                container_name=TEST_CONTAINER,
                item_id="test_item_1",
                partition_key_value="test_item_1"
            )
            if read_item:
                print(f"[OK] Item read successfully!")
                print(f"  - ID: {read_item.get('id')}")
                print(f"  - Message: {read_item.get('message')}")
                print(f"  - Number: {read_item.get('number')}")
            else:
                print(f"[FAIL] Item not found")
        except Exception as e:
            print(f"[FAIL] Failed to read item: {e}")
            print(f"  Error type: {type(e).__name__}")

        # Test 3: Upsert Item (update existing)
        print("\n" + "=" * 80)
        print("TEST 3: UPSERT ITEM (Update)")
        print("=" * 80)

        test_item_1["message"] = "This item has been updated"
        test_item_1["number"] = 100
        test_item_1["updated_at"] = datetime.utcnow().isoformat()

        print(f"\nUpserting item with ID: {test_item_1['id']}")
        print(f"Updated fields: message={test_item_1['message']}, number={test_item_1['number']}")

        try:
            upserted_item = await cosmos_client.upsert_item(
                container_name=TEST_CONTAINER,
                item=test_item_1
            )
            print(f"[OK] Item upserted successfully!")
            print(f"  - ID: {upserted_item.get('id')}")
            print(f"  - Message: {upserted_item.get('message')}")
            print(f"  - Number: {upserted_item.get('number')}")
        except Exception as e:
            print(f"[FAIL] Failed to upsert item: {e}")
            print(f"  Error type: {type(e).__name__}")

        # Test 4: Upsert Item (create new)
        print("\n" + "=" * 80)
        print("TEST 4: UPSERT ITEM (Create New)")
        print("=" * 80)

        test_item_2 = {
            "id": "test_item_2",
            "type": "test",
            "message": "Created via upsert",
            "created_at": datetime.utcnow().isoformat(),
            "number": 999
        }

        print(f"\nUpserting new item with ID: {test_item_2['id']}")

        try:
            upserted_item = await cosmos_client.upsert_item(
                container_name=TEST_CONTAINER,
                item=test_item_2
            )
            print(f"[OK] New item created via upsert!")
            print(f"  - ID: {upserted_item.get('id')}")
            print(f"  - Message: {upserted_item.get('message')}")
        except Exception as e:
            print(f"[FAIL] Failed to upsert new item: {e}")
            print(f"  Error type: {type(e).__name__}")

        # Test 5: Query Items
        print("\n" + "=" * 80)
        print("TEST 5: QUERY ITEMS")
        print("=" * 80)

        query = "SELECT * FROM c WHERE c.type = @type"
        parameters = [{"name": "@type", "value": "test"}]

        print(f"\nQuerying items with type='test'")
        print(f"Query: {query}")

        try:
            items = await cosmos_client.query_items(
                container_name=TEST_CONTAINER,
                query=query,
                parameters=parameters
            )
            print(f"[OK] Query executed successfully!")
            print(f"  - Found {len(items)} items")
            for item in items:
                print(f"    - ID: {item.get('id')}, Message: {item.get('message')}")
        except Exception as e:
            print(f"[FAIL] Failed to query items: {e}")
            print(f"  Error type: {type(e).__name__}")

        # Test 6: Replace Item
        print("\n" + "=" * 80)
        print("TEST 6: REPLACE ITEM")
        print("=" * 80)

        test_item_1["message"] = "Replaced via replace_item"
        test_item_1["replaced_at"] = datetime.utcnow().isoformat()

        print(f"\nReplacing item with ID: {test_item_1['id']}")

        try:
            replaced_item = await cosmos_client.replace_item(
                container_name=TEST_CONTAINER,
                item_id="test_item_1",
                item=test_item_1,
                partition_key_value="test_item_1"
            )
            print(f"[OK] Item replaced successfully!")
            print(f"  - ID: {replaced_item.get('id')}")
            print(f"  - Message: {replaced_item.get('message')}")
        except Exception as e:
            print(f"[FAIL] Failed to replace item: {e}")
            print(f"  Error type: {type(e).__name__}")

        # Test 7: Delete Items
        print("\n" + "=" * 80)
        print("TEST 7: DELETE ITEMS")
        print("=" * 80)

        for item_id in ["test_item_1", "test_item_2"]:
            print(f"\nDeleting item with ID: {item_id}")
            try:
                await cosmos_client.delete_item(
                    container_name=TEST_CONTAINER,
                    item_id=item_id,
                    partition_key_value=item_id
                )
                print(f"[OK] Item deleted successfully!")
            except Exception as e:
                print(f"[FAIL] Failed to delete item: {e}")
                print(f"  Error type: {type(e).__name__}")

        # Test 8: Verify deletion
        print("\n" + "=" * 80)
        print("TEST 8: VERIFY DELETION")
        print("=" * 80)

        print(f"\nTrying to read deleted item: test_item_1")
        try:
            read_item = await cosmos_client.read_item(
                container_name=TEST_CONTAINER,
                item_id="test_item_1",
                partition_key_value="test_item_1"
            )
            if read_item is None:
                print(f"[OK] Item correctly returns None (deleted)")
            else:
                print(f"[FAIL] Item still exists! {read_item}")
        except Exception as e:
            print(f"[FAIL] Error reading deleted item: {e}")
            print(f"  Error type: {type(e).__name__}")

    finally:
        # Cleanup
        print("\n" + "=" * 80)
        print("CLEANUP")
        print("=" * 80)
        await cosmos_client.close()
        print("[OK] CosmosDBClient closed")

    print("\n" + "=" * 80)
    print("TEST COMPLETE")
    print("=" * 80)


async def test_unified_service_pattern():
    """Test the pattern used by unified_service.py"""
    print("\n\n" + "=" * 80)
    print("UNIFIED SERVICE PATTERN TEST")
    print("=" * 80)

    settings = get_settings()
    cosmos_client = CosmosDBClient(settings.cosmos)

    try:
        # Simulate what unified_service does
        session_id = "test_session_123"
        user_id = "test_user@example.com"

        # Create a conversation turn like unified_service does
        turn_data = {
            "id": f"turn_{session_id}_1",
            "session_id": session_id,
            "user_id": user_id,
            "turn_number": 1,
            "user_message": "Hello, world!",
            "assistant_message": "Hi there!",
            "created_at": datetime.utcnow().isoformat(),
            "doc_type": "conversation_turn"
        }

        print(f"\nCreating conversation turn:")
        print(f"  - Session ID: {session_id}")
        print(f"  - User ID: {user_id}")
        print(f"  - Turn Number: 1")

        try:
            # This is what unified_service.py does
            result = await cosmos_client.create_item(
                container_name=TEST_CONTAINER,
                item=turn_data
            )
            print(f"[OK] Conversation turn created!")
            print(f"  - Document ID: {result.get('id')}")

            # Try to read it back
            print(f"\nReading conversation turn back...")
            read_result = await cosmos_client.read_item(
                container_name=TEST_CONTAINER,
                item_id=turn_data["id"],
                partition_key_value=session_id  # unified_service uses session_id as partition key
            )

            if read_result:
                print(f"[OK] Successfully read back conversation turn!")
                print(f"  - User message: {read_result.get('user_message')}")
                print(f"  - Assistant message: {read_result.get('assistant_message')}")
            else:
                print(f"[FAIL] Could not read back conversation turn")

            # Cleanup
            await cosmos_client.delete_item(
                container_name=TEST_CONTAINER,
                item_id=turn_data["id"],
                partition_key_value=session_id
            )
            print(f"\n[OK] Test data cleaned up")

        except Exception as e:
            print(f"\n[FAIL] Unified service pattern test failed: {e}")
            print(f"  Error type: {type(e).__name__}")
            import traceback
            traceback.print_exc()

    finally:
        await cosmos_client.close()


async def main():
    """Run all tests."""
    try:
        await test_cosmos_operations()
        await test_unified_service_pattern()
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
    except Exception as e:
        print(f"\n\n[FAIL] FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
