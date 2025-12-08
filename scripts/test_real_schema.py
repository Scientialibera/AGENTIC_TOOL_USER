"""Test with real Azure SQL database schema and value mappings."""
import asyncio
from fastmcp import Client


async def test_real_schema():
    """Test SQL queries with actual database schema."""

    async with Client("http://localhost:8003/mcp") as client:
        print("="*80)
        print("TESTING WITH REAL AZURE SQL SCHEMA")
        print("="*80)
        print("\n[OK] Connected to SQL MCP Server\n")

        # Test 1: Simple query with value mapping (StageName)
        print("="*80)
        print("TEST 1: Opportunities by stage with value mapping")
        print("="*80)

        query1 = """
        SELECT
            o.Name,
            o.StageName,
            o.Amount,
            a.Name AS AccountName
        FROM dbo.Opportunity o
        INNER JOIN dbo.Account a ON o.AccountId = a.Id
        WHERE o.StageName IN ('closed won', 'negotiation')
        ORDER BY o.Amount DESC
        """

        value_mappings1 = [
            {"table": "Opportunity", "column": "StageName", "user_value": "closed won", "matched_value": "Closed Won"},
            {"table": "Opportunity", "column": "StageName", "user_value": "negotiation", "matched_value": "Negotiation"}
        ]

        print(f"\nQuery: Opportunities that are won or in negotiation")
        print(f"Value Mappings: {len(value_mappings1)} mappings")
        for mapping in value_mappings1:
            print(f"  - {mapping['column']}: '{mapping['user_value']}' -> '{mapping['matched_value']}'")

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
                print(f"  Rows: {data.get('row_count', 0)}")

                if data.get('data'):
                    print(f"\n  Top Results:")
                    for i, row in enumerate(data['data'][:5], 1):
                        print(f"    {i}. {row.get('Name')} - Stage: {row.get('StageName')} - Amount: ${row.get('Amount', 0):,.2f} - Account: {row.get('AccountName')}")

                if data.get('error'):
                    print(f"\n  Error: {data.get('error')}")
        except Exception as e:
            print(f"  Error: {e}")

        # Test 2: Complex JOIN with multiple value mappings
        print("\n" + "="*80)
        print("TEST 2: Accounts with opportunities by industry and type")
        print("="*80)

        query2 = """
        SELECT
            a.Name AS AccountName,
            a.Industry,
            a.Type AS AccountType,
            COUNT(o.Id) AS TotalOpportunities,
            SUM(CASE WHEN o.StageName = 'closed won' THEN 1 ELSE 0 END) AS WonCount,
            SUM(o.Amount) AS TotalRevenue
        FROM dbo.Account a
        LEFT JOIN dbo.Opportunity o ON a.AccountId = o.Id
        WHERE a.Type IN ('customer', 'partner')
            AND a.Industry IN ('technology', 'cloud computing')
        GROUP BY a.Name, a.Industry, a.Type
        HAVING SUM(o.Amount) > 0
        ORDER BY TotalRevenue DESC
        """

        value_mappings2 = [
            {"table": "Account", "column": "Type", "user_value": "customer", "matched_value": "Customer"},
            {"table": "Account", "column": "Type", "user_value": "partner", "matched_value": "Partner"},
            {"table": "Account", "column": "Industry", "user_value": "technology", "matched_value": "Technology"},
            {"table": "Account", "column": "Industry", "user_value": "cloud computing", "matched_value": "Cloud Computing"},
            {"table": "Opportunity", "column": "StageName", "user_value": "closed won", "matched_value": "Closed Won"}
        ]

        print(f"\nQuery: Tech/Cloud accounts with revenue")
        print(f"Value Mappings: {len(value_mappings2)} mappings")

        try:
            result2 = await client.call_tool(
                "sql_query",
                arguments={
                    "query": query2,
                    "value_mappings": value_mappings2,
                    "limit": 10
                }
            )

            if hasattr(result2, 'data'):
                data = result2.data
                print(f"\nResult:")
                print(f"  Success: {data.get('success')}")
                print(f"  Rows: {data.get('row_count', 0)}")

                if data.get('data'):
                    print(f"\n  Results:")
                    for i, row in enumerate(data['data'], 1):
                        print(f"    {i}. {row.get('AccountName')} ({row.get('Industry')}) - Revenue: ${row.get('TotalRevenue', 0):,.2f} - Won: {row.get('WonCount', 0)}")

                if data.get('error'):
                    print(f"\n  Error: {data.get('error')}")
        except Exception as e:
            print(f"  Error: {e}")

        # Test 3: Cases query with reserved keyword [Case]
        print("\n" + "="*80)
        print("TEST 3: Open cases by priority (reserved keyword handling)")
        print("="*80)

        query3 = """
        SELECT
            c.CaseNumber,
            c.Subject,
            c.Status,
            c.Priority,
            a.Name AS AccountName
        FROM dbo.[Case] c
        LEFT JOIN dbo.Account a ON c.AccountId = a.Id
        WHERE c.Status IN ('new', 'in progress', 'escalated')
            AND c.Priority IN ('high', 'critical')
        ORDER BY
            CASE c.Priority
                WHEN 'critical' THEN 1
                WHEN 'high' THEN 2
                ELSE 3
            END,
            c.CreatedDate DESC
        """

        value_mappings3 = [
            {"table": "Case", "column": "Status", "user_value": "new", "matched_value": "New"},
            {"table": "Case", "column": "Status", "user_value": "in progress", "matched_value": "In Progress"},
            {"table": "Case", "column": "Status", "user_value": "escalated", "matched_value": "Escalated"},
            {"table": "Case", "column": "Priority", "user_value": "high", "matched_value": "High"},
            {"table": "Case", "column": "Priority", "user_value": "critical", "matched_value": "Critical"}
        ]

        print(f"\nQuery: Urgent open cases")
        print(f"Value Mappings: {len(value_mappings3)} mappings (includes multi-word values)")

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
                print(f"  Rows: {data.get('row_count', 0)}")

                if data.get('data'):
                    print(f"\n  Urgent Cases:")
                    for i, row in enumerate(data['data'][:5], 1):
                        print(f"    {i}. [{row.get('CaseNumber')}] {row.get('Subject')} - {row.get('Priority')} priority - Status: {row.get('Status')}")

                if data.get('error'):
                    print(f"\n  Error: {data.get('error')}")
        except Exception as e:
            print(f"  Error: {e}")

        # Test 4: Leads by source
        print("\n" + "="*80)
        print("TEST 4: Qualified leads by source")
        print("="*80)

        query4 = """
        SELECT
            l.FirstName + ' ' + l.LastName AS LeadName,
            l.Company,
            l.Status,
            l.LeadSource,
            l.Industry
        FROM dbo.Lead l
        WHERE l.Status IN ('qualified', 'contacted')
            AND l.LeadSource IN ('referral', 'web', 'trade show')
        ORDER BY l.CreatedDate DESC
        """

        value_mappings4 = [
            {"table": "Lead", "column": "Status", "user_value": "qualified", "matched_value": "Qualified"},
            {"table": "Lead", "column": "Status", "user_value": "contacted", "matched_value": "Contacted"},
            {"table": "Lead", "column": "LeadSource", "user_value": "referral", "matched_value": "Referral"},
            {"table": "Lead", "column": "LeadSource", "user_value": "web", "matched_value": "Web"},
            {"table": "Lead", "column": "LeadSource", "user_value": "trade show", "matched_value": "Trade Show"}
        ]

        print(f"\nQuery: Active leads from key sources")
        print(f"Value Mappings: {len(value_mappings4)} mappings")

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
                print(f"  Rows: {data.get('row_count', 0)}")

                if data.get('data'):
                    print(f"\n  Leads:")
                    for i, row in enumerate(data['data'][:5], 1):
                        print(f"    {i}. {row.get('LeadName')} @ {row.get('Company')} - Source: {row.get('LeadSource')} - Status: {row.get('Status')}")

                if data.get('error'):
                    print(f"\n  Error: {data.get('error')}")
        except Exception as e:
            print(f"  Error: {e}")

        print("\n" + "="*80)
        print("[OK] All real schema tests completed!")
        print("="*80)


if __name__ == "__main__":
    asyncio.run(test_real_schema())
