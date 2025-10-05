"""
Test script for Interpreter MCP Server.

This script tests the Code Interpreter MCP server with math, calculation,
and data analysis tasks.
"""

import asyncio
import json
from fastmcp import Client


async def test_simple_math():
    """Test with a simple math calculation."""
    
    async with Client("http://localhost:8000/mcp") as client:
        print("\n" + "="*70)
        print(" Testing simple math calculation")
        print("="*70)
        
        # Simple math query
        task = "Calculate the revenue per employee if we sold $10,000 and have 2 employees"
        
        rbac_context = {
            "user_id": "test_user",
            "email": "test@example.com",
            "tenant_id": "test_tenant",
            "object_id": "test_object",
            "roles": ["admin"],
            "access_scope": {
                "account_ids": [],
                "all_accounts": True,
                "owned_only": False,
                "team_access": False
            }
        }
        
        print(f"\n  Task: {task}")
        
        try:
            result = await client.call_tool(
                "interpreter_agent",
                arguments={
                    "query": task,
                    "rbac_context": rbac_context
                }
            )
            
            print("\n✓ Calculation executed!")
            print("\n Result:")
            print(json.dumps(result, indent=2, default=str))
            
        except Exception as e:
            print(f"\n✗ Error: {e}")
            import traceback
            traceback.print_exc()


async def test_complex_calculation():
    """Test with a more complex calculation."""
    
    async with Client("http://localhost:8000/mcp") as client:
        print("\n" + "="*70)
        print(" Testing complex calculation")
        print("="*70)
        
        # Complex calculation
        task = """
        Calculate the compound annual growth rate (CAGR) if:
        - Starting revenue: $100,000
        - Ending revenue: $250,000
        - Time period: 5 years
        
        Also show me the revenue for each year with this growth rate.
        """
        
        rbac_context = {
            "user_id": "test_user",
            "email": "test@example.com",
            "tenant_id": "test_tenant",
            "object_id": "test_object",
            "roles": ["admin"],
            "access_scope": {
                "account_ids": [],
                "all_accounts": True,
                "owned_only": False,
                "team_access": False
            }
        }
        
        print(f"\n  Task: {task}")
        
        try:
            result = await client.call_tool(
                "interpreter_agent",
                arguments={
                    "query": task,
                    "rbac_context": rbac_context
                }
            )
            
            print("\n✓ Complex calculation executed!")
            print("\n Result:")
            print(json.dumps(result, indent=2, default=str))
            
        except Exception as e:
            print(f"\n✗ Error: {e}")
            import traceback
            traceback.print_exc()


async def test_data_analysis():
    """Test with data analysis task."""
    
    async with Client("http://localhost:8000/mcp") as client:
        print("\n" + "="*70)
        print(" Testing data analysis")
        print("="*70)
        
        # Data analysis task
        task = """
        Analyze these monthly revenues and calculate:
        1. Total revenue
        2. Average monthly revenue
        3. Standard deviation
        4. Month with highest revenue
        
        Data: [45000, 52000, 48000, 61000, 59000, 67000, 72000, 68000, 71000, 75000, 80000, 85000]
        """
        
        rbac_context = {
            "user_id": "test_user",
            "email": "test@example.com",
            "tenant_id": "test_tenant",
            "object_id": "test_object",
            "roles": ["admin"],
            "access_scope": {
                "account_ids": [],
                "all_accounts": True,
                "owned_only": False,
                "team_access": False
            }
        }
        
        print(f"\n  Task: {task}")
        
        try:
            result = await client.call_tool(
                "interpreter_agent",
                arguments={
                    "query": task,
                    "rbac_context": rbac_context
                }
            )
            
            print("\n✓ Data analysis executed!")
            print("\n Result:")
            print(json.dumps(result, indent=2, default=str))
            
        except Exception as e:
            print(f"\n✗ Error: {e}")
            import traceback
            traceback.print_exc()


async def main():
    """Run all tests."""
    print("="*70)
    print(" Testing Code Interpreter MCP Server")
    print("="*70)
    
    # Test 1: Simple math
    await test_simple_math()
    
    # Test 2: Complex calculation
    await test_complex_calculation()
    
    # Test 3: Data analysis
    await test_data_analysis()
    
    print("\n" + "="*70)
    print(" All tests completed!")
    print("="*70)


if __name__ == "__main__":
    asyncio.run(main())
