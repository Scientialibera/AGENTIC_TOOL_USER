"""Test complex SQL queries with value_mappings."""
import asyncio
import json
from fastmcp import Client


async def test_complex_queries():
    """Test complex SQL queries with multiple value mappings."""

    async with Client("http://localhost:8003/mcp") as client:
        print("="*80)
        print("COMPLEX VALUE MAPPINGS TEST")
        print("="*80)
        print("\n[OK] Connected to SQL MCP Server")

        # Test 1: Complex JOIN query with multiple value mappings
        print("\n" + "="*80)
        print("TEST 1: JOIN query with value mappings on multiple tables")
        print("="*80)

        query1 = """
        SELECT
            a.AccountName,
            o.OpportunityName,
            o.Stage,
            o.Amount,
            c.FirstName + ' ' + c.LastName AS ContactName
        FROM Account a
        INNER JOIN Opportunity o ON a.Id = o.AccountId
        LEFT JOIN Contact c ON a.Id = c.AccountId
        WHERE o.Stage IN ('proposal', 'negotiation', 'closed won')
            AND a.Industry = 'technology'
        ORDER BY o.Amount DESC
        """

        value_mappings1 = [
            {
                "table": "Opportunity",
                "column": "Stage",
                "user_value": "proposal",
                "matched_value": "Proposal"
            },
            {
                "table": "Opportunity",
                "column": "Stage",
                "user_value": "negotiation",
                "matched_value": "Negotiation"
            },
            {
                "table": "Opportunity",
                "column": "Stage",
                "user_value": "closed won",
                "matched_value": "Closed Won"
            },
            {
                "table": "Account",
                "column": "Industry",
                "user_value": "technology",
                "matched_value": "Technology"
            }
        ]

        print(f"\nOriginal Query (before value mapping):")
        print(query1)
        print(f"\nValue Mappings ({len(value_mappings1)} mappings):")
        for mapping in value_mappings1:
            print(f"  - {mapping['table']}.{mapping['column']}: '{mapping['user_value']}' -> '{mapping['matched_value']}'")

        try:
            result1 = await client.call_tool(
                "sql_query",
                arguments={
                    "query": query1,
                    "value_mappings": value_mappings1,
                    "limit": 10
                }
            )

            if hasattr(result1, 'data'):
                data = result1.data
                print(f"\nResult:")
                print(f"  Success: {data.get('success')}")
                print(f"  Row Count: {data.get('row_count', 0)}")
                print(f"\n  Executed Query (after value mapping):")
                executed_query = data.get('query', '')
                for line in executed_query.split('\n'):
                    if line.strip():
                        print(f"    {line}")

                if data.get('error'):
                    print(f"\n  Error: {data.get('error')}")
                elif data.get('data'):
                    print(f"\n  Sample Results (first 3 rows):")
                    for i, row in enumerate(data['data'][:3], 1):
                        print(f"    {i}. {json.dumps(row, indent=6)}")
        except Exception as e:
            print(f"  Error: {e}")

        # Test 2: Subquery with value mappings
        print("\n" + "="*80)
        print("TEST 2: Subquery with aggregation and value mappings")
        print("="*80)

        query2 = """
        SELECT
            a.AccountName,
            a.Industry,
            COUNT(o.Id) AS TotalOpportunities,
            SUM(CASE WHEN o.Stage = 'closed won' THEN 1 ELSE 0 END) AS WonCount,
            SUM(o.Amount) AS TotalRevenue
        FROM Account a
        LEFT JOIN Opportunity o ON a.Id = o.AccountId
        WHERE a.Category IN ('enterprise', 'strategic')
            AND (o.Stage IS NULL OR o.Stage IN ('proposal', 'closed won', 'negotiation'))
        GROUP BY a.AccountName, a.Industry
        HAVING SUM(o.Amount) > 100000
        ORDER BY TotalRevenue DESC
        """

        value_mappings2 = [
            {
                "table": "Account",
                "column": "Category",
                "user_value": "enterprise",
                "matched_value": "Enterprise"
            },
            {
                "table": "Account",
                "column": "Category",
                "user_value": "strategic",
                "matched_value": "Strategic"
            },
            {
                "table": "Opportunity",
                "column": "Stage",
                "user_value": "proposal",
                "matched_value": "Proposal"
            },
            {
                "table": "Opportunity",
                "column": "Stage",
                "user_value": "closed won",
                "matched_value": "Closed Won"
            },
            {
                "table": "Opportunity",
                "column": "Stage",
                "user_value": "negotiation",
                "matched_value": "Negotiation"
            }
        ]

        print(f"\nOriginal Query (before value mapping):")
        print(query2)
        print(f"\nValue Mappings ({len(value_mappings2)} mappings):")
        for mapping in value_mappings2:
            print(f"  - {mapping['table']}.{mapping['column']}: '{mapping['user_value']}' -> '{mapping['matched_value']}'")

        try:
            result2 = await client.call_tool(
                "sql_query",
                arguments={
                    "query": query2,
                    "value_mappings": value_mappings2,
                    "limit": 5
                }
            )

            if hasattr(result2, 'data'):
                data = result2.data
                print(f"\nResult:")
                print(f"  Success: {data.get('success')}")
                print(f"  Row Count: {data.get('row_count', 0)}")
                print(f"\n  Executed Query (after value mapping):")
                executed_query = data.get('query', '')
                for line in executed_query.split('\n'):
                    if line.strip():
                        print(f"    {line}")

                if data.get('error'):
                    print(f"\n  Error: {data.get('error')}")
                elif data.get('data'):
                    print(f"\n  Sample Results:")
                    for i, row in enumerate(data['data'], 1):
                        print(f"    {i}. {json.dumps(row, indent=6)}")
        except Exception as e:
            print(f"  Error: {e}")

        # Test 3: CASE statement with value mappings
        print("\n" + "="*80)
        print("TEST 3: Complex CASE statement with value mappings")
        print("="*80)

        query3 = """
        SELECT
            AccountName,
            Stage,
            Amount,
            CASE
                WHEN Stage = 'closed won' THEN 'Won'
                WHEN Stage = 'closed lost' THEN 'Lost'
                WHEN Stage IN ('proposal', 'negotiation') THEN 'Active'
                ELSE 'Other'
            END AS StageCategory,
            CASE
                WHEN Amount > 500000 THEN 'Large'
                WHEN Amount > 200000 THEN 'Medium'
                ELSE 'Small'
            END AS DealSize
        FROM Opportunity
        WHERE Stage IN ('proposal', 'negotiation', 'closed won', 'closed lost')
        ORDER BY Amount DESC
        """

        value_mappings3 = [
            {
                "table": "Opportunity",
                "column": "Stage",
                "user_value": "closed won",
                "matched_value": "Closed Won"
            },
            {
                "table": "Opportunity",
                "column": "Stage",
                "user_value": "closed lost",
                "matched_value": "Closed Lost"
            },
            {
                "table": "Opportunity",
                "column": "Stage",
                "user_value": "proposal",
                "matched_value": "Proposal"
            },
            {
                "table": "Opportunity",
                "column": "Stage",
                "user_value": "negotiation",
                "matched_value": "Negotiation"
            }
        ]

        print(f"\nOriginal Query (before value mapping):")
        print(query3)
        print(f"\nValue Mappings ({len(value_mappings3)} mappings):")
        for mapping in value_mappings3:
            print(f"  - {mapping['table']}.{mapping['column']}: '{mapping['user_value']}' -> '{mapping['matched_value']}'")

        try:
            result3 = await client.call_tool(
                "sql_query",
                arguments={
                    "query": query3,
                    "value_mappings": value_mappings3,
                    "limit": 10
                }
            )

            if hasattr(result3, 'data'):
                data = result3.data
                print(f"\nResult:")
                print(f"  Success: {data.get('success')}")
                print(f"  Row Count: {data.get('row_count', 0)}")
                print(f"\n  Executed Query (after value mapping):")
                executed_query = data.get('query', '')
                for line in executed_query.split('\n'):
                    if line.strip():
                        print(f"    {line}")

                if data.get('error'):
                    print(f"\n  Error: {data.get('error')}")
                elif data.get('data'):
                    print(f"\n  Sample Results (first 5 rows):")
                    for i, row in enumerate(data['data'][:5], 1):
                        print(f"    {i}. {json.dumps(row, indent=6)}")
        except Exception as e:
            print(f"  Error: {e}")

        # Test 4: CTE (Common Table Expression) with value mappings
        print("\n" + "="*80)
        print("TEST 4: CTE (WITH clause) with value mappings")
        print("="*80)

        query4 = """
        WITH ActiveOpportunities AS (
            SELECT
                AccountId,
                COUNT(*) AS ActiveCount,
                SUM(Amount) AS ActiveRevenue
            FROM Opportunity
            WHERE Stage IN ('proposal', 'negotiation', 'qualification')
            GROUP BY AccountId
        ),
        WonOpportunities AS (
            SELECT
                AccountId,
                COUNT(*) AS WonCount,
                SUM(Amount) AS WonRevenue
            FROM Opportunity
            WHERE Stage = 'closed won'
            GROUP BY AccountId
        )
        SELECT
            a.AccountName,
            a.Industry,
            ISNULL(active.ActiveCount, 0) AS ActiveOpportunities,
            ISNULL(active.ActiveRevenue, 0) AS ActiveRevenue,
            ISNULL(won.WonCount, 0) AS WonOpportunities,
            ISNULL(won.WonRevenue, 0) AS WonRevenue
        FROM Account a
        LEFT JOIN ActiveOpportunities active ON a.Id = active.AccountId
        LEFT JOIN WonOpportunities won ON a.Id = won.AccountId
        WHERE a.Category = 'enterprise'
        ORDER BY WonRevenue DESC
        """

        value_mappings4 = [
            {
                "table": "Opportunity",
                "column": "Stage",
                "user_value": "proposal",
                "matched_value": "Proposal"
            },
            {
                "table": "Opportunity",
                "column": "Stage",
                "user_value": "negotiation",
                "matched_value": "Negotiation"
            },
            {
                "table": "Opportunity",
                "column": "Stage",
                "user_value": "qualification",
                "matched_value": "Qualification"
            },
            {
                "table": "Opportunity",
                "column": "Stage",
                "user_value": "closed won",
                "matched_value": "Closed Won"
            },
            {
                "table": "Account",
                "column": "Category",
                "user_value": "enterprise",
                "matched_value": "Enterprise"
            }
        ]

        print(f"\nOriginal Query (before value mapping):")
        print(query4)
        print(f"\nValue Mappings ({len(value_mappings4)} mappings):")
        for mapping in value_mappings4:
            print(f"  - {mapping['table']}.{mapping['column']}: '{mapping['user_value']}' -> '{mapping['matched_value']}'")

        try:
            result4 = await client.call_tool(
                "sql_query",
                arguments={
                    "query": query4,
                    "value_mappings": value_mappings4,
                    "limit": 10
                }
            )

            if hasattr(result4, 'data'):
                data = result4.data
                print(f"\nResult:")
                print(f"  Success: {data.get('success')}")
                print(f"  Row Count: {data.get('row_count', 0)}")
                print(f"\n  Executed Query (after value mapping):")
                executed_query = data.get('query', '')
                for line in executed_query.split('\n'):
                    if line.strip():
                        print(f"    {line}")

                if data.get('error'):
                    print(f"\n  Error: {data.get('error')}")
                elif data.get('data'):
                    print(f"\n  Sample Results:")
                    for i, row in enumerate(data['data'], 1):
                        print(f"    {i}. {json.dumps(row, indent=6)}")
        except Exception as e:
            print(f"  Error: {e}")


async def main():
    """Run all complex query tests."""
    print("\n" + "="*80)
    print("TESTING VALUE MAPPINGS WITH COMPLEX SQL QUERIES")
    print("="*80)
    print("\nThis test suite demonstrates value_mappings working with:")
    print("  - JOIN queries across multiple tables")
    print("  - Aggregations with GROUP BY and HAVING")
    print("  - CASE statements")
    print("  - Common Table Expressions (CTEs)")
    print("  - Subqueries")
    print("  - Multiple value mappings in a single query")

    await test_complex_queries()

    print("\n" + "="*80)
    print("[OK] All complex query tests completed!")
    print("="*80)


if __name__ == "__main__":
    asyncio.run(main())
