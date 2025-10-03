"""
SQL MCP Server for Salesforce/Fabric SQL interactions.

This MCP server provides SQL query capabilities with intelligent query
generation using an internal LLM and RBAC-based row-level security.
"""

import json
import asyncio
from typing import Dict, Any, Optional, List
from fastmcp import FastMCP
import structlog

import sys
import os
# Add parent directories to path to import shared modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.config import get_settings
from shared.models import RBACContext
from shared.aoai_client import AzureOpenAIClient
from shared.fabric_client import FabricClient
from shared.cosmos_client import CosmosDBClient
from shared.account_resolver import AccountResolverService
from shared.auth_provider import create_auth_provider

# ============================================================================
# CONSTANTS
# ============================================================================
MCP_SERVER_NAME = "SQL MCP Server"
MCP_SERVER_PORT = 8001
PROMPT_ID = "sql_agent_system"
DEFAULT_QUERY_LIMIT = 100

logger = structlog.get_logger(__name__)

settings = get_settings()

# Initialize auth provider (None in dev mode, JWTVerifier in production)
auth_provider = create_auth_provider()

# Create MCP server with authentication
# In dev mode, auth_provider is None so authentication is disabled
# In production, auth_provider validates JWT tokens from Azure AD
mcp = FastMCP(MCP_SERVER_NAME, auth=auth_provider)

aoai_client: Optional[AzureOpenAIClient] = None
fabric_client: Optional[FabricClient] = None
cosmos_client: Optional[CosmosDBClient] = None
account_resolver: Optional[AccountResolverService] = None


async def initialize_clients():
    """Initialize all required clients."""
    global aoai_client, fabric_client, cosmos_client, account_resolver
    
    if aoai_client is None:
        aoai_client = AzureOpenAIClient(settings.aoai)
    if fabric_client is None:
        fabric_client = FabricClient(settings.fabric)
    if cosmos_client is None:
        cosmos_client = CosmosDBClient(settings.cosmos)
    if account_resolver is None:
        account_resolver = AccountResolverService(
            fabric_client=fabric_client,
            dev_mode=settings.dev_mode
        )
    
    logger.info("SQL MCP Server clients initialized")


async def get_sql_schema() -> str:
    """Load SQL schema from Cosmos DB."""
    try:
        if cosmos_client is None:
            await initialize_clients()
        
        items = await cosmos_client.query_items(
            container_name="sql_schema",
            query="SELECT * FROM c",
        )
        
        if not items:
            return "No schema available"
        
        schema_parts = []
        for item in items:
            table_name = item.get("table_name", "unknown")
            columns = item.get("columns", [])
            schema_parts.append(f"Table: {table_name}\nColumns: {', '.join(columns)}")
        
        return "\n\n".join(schema_parts)
    except Exception as e:
        logger.error("Failed to load SQL schema", error=str(e))
        return "Schema unavailable"


async def get_system_prompt(rbac_context: Optional[Dict[str, Any]] = None) -> str:
    """Get SQL agent system prompt with schema from Cosmos DB.
    
    Raises:
        Exception: If prompt cannot be loaded from Cosmos DB
    """
    if cosmos_client is None:
        await initialize_clients()
    
    prompt_items = await cosmos_client.query_items(
        container_name=settings.cosmos.prompts_container,
        query="SELECT * FROM c WHERE c.id = @prompt_id",
        parameters=[{"name": "@prompt_id", "value": PROMPT_ID}],
    )
    
    if not prompt_items:
        raise Exception(f"Prompt '{PROMPT_ID}' not found in Cosmos DB container '{settings.cosmos.prompts_container}'")
    
    base_prompt = prompt_items[0].get("content", "")
    if not base_prompt:
        raise Exception(f"Prompt '{PROMPT_ID}' has empty content")
    
    schema = await get_sql_schema()
    prompt = f"{base_prompt}\n\n## Database Schema\n{schema}"
    
    if rbac_context:
        user_email = rbac_context.get("email", "")
        prompt += f"\n\n## RBAC Context\nUser: {user_email}\nImportant: Add WHERE clause to filter by user access (e.g., WHERE owner_email = '{user_email}' or assigned_to = '{user_email}')"
    
    return prompt


async def resolve_accounts(
    account_names: List[str],
    rbac_context: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """Resolve account names to IDs using fuzzy matching."""
    try:
        if not account_names:
            return []
        
        if account_resolver is None:
            await initialize_clients()
        
        rbac_obj = None
        if rbac_context:
            from shared.models import RBACContext, AccessScope
            rbac_obj = RBACContext(
                user_id=rbac_context.get("user_id", "unknown"),
                email=rbac_context.get("email", "unknown"),
                tenant_id=rbac_context.get("tenant_id", "unknown"),
                object_id=rbac_context.get("object_id", "unknown"),
                roles=rbac_context.get("roles", []),
                access_scope=AccessScope(**rbac_context.get("access_scope", {})),
            )
        
        accounts = await account_resolver.resolve_account_names(account_names, rbac_obj)
        
        results = [{"id": acc.id, "name": acc.name} for acc in accounts]
        
        logger.info("Resolved accounts", count=len(results))
        return results
    except Exception as e:
        logger.error("Failed to resolve accounts", error=str(e))
        return []


@mcp.tool()
async def sql_query(
    query: str,
    accounts_mentioned: Optional[List[str]] = None,
    rbac_context: Optional[Dict[str, Any]] = None,
    limit: int = DEFAULT_QUERY_LIMIT
) -> Dict[str, Any]:
    """
    Execute SQL queries against Salesforce/Fabric data.
    
    This tool uses an internal LLM to generate SQL from natural language,
    resolves account mentions, and enforces RBAC row-level security.
    
    Args:
        query: Natural language query description
        accounts_mentioned: List of account names mentioned in query
        rbac_context: User RBAC context for row-level security
        limit: Maximum number of rows to return
    
    Returns:
        Dictionary with query results, including success status, data, and metadata
    """
    try:
        await initialize_clients()
        
        logger.info("SQL tool called", query=query[:100])
        
        resolved_accounts = []
        if accounts_mentioned:
            resolved_accounts = await resolve_accounts(accounts_mentioned, rbac_context)
        
        system_prompt = await get_system_prompt(rbac_context)
        
        user_message = f"Generate a SQL query for: {query}"
        if resolved_accounts:
            account_names = [acc["name"] for acc in resolved_accounts]
            user_message += f"\n\nAccount context: {', '.join(account_names)}"
        user_message += f"\n\nLimit results to {limit} rows."
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]
        
        response = await aoai_client.create_chat_completion(messages=messages)
        
        assistant_content = response["choices"][0]["message"]["content"]
        
        sql_query = assistant_content.strip()
        if "```sql" in sql_query:
            sql_query = sql_query.split("```sql")[1].split("```")[0].strip()
        elif "```" in sql_query:
            sql_query = sql_query.split("```")[1].split("```")[0].strip()
        
        if settings.dev_mode:
            results = _get_dummy_sql_data(sql_query, limit)
            logger.info("Dev mode: using dummy SQL data", result_count=len(results))
        else:
            results = await fabric_client.execute_query(sql_query)
            logger.info("SQL query executed", result_count=len(results))
        
        return {
            "success": True,
            "query": sql_query,
            "row_count": len(results),
            "data": results[:limit],
            "source": "fabric_sql" if not settings.dev_mode else "dummy_sql",
            "resolved_accounts": resolved_accounts,
        }
        
    except Exception as e:
        logger.error("SQL tool execution failed", error=str(e))
        return {
            "success": False,
            "error": str(e),
            "query": query,
        }


def _get_dummy_sql_data(query: str, limit: int = 100) -> List[Dict[str, Any]]:
    """Generate dummy SQL data for dev mode."""
    query_lower = query.lower()
    
    if "contact" in query_lower:
        return [
            {
                "account_name": "Microsoft Corporation",
                "first_name": "Satya",
                "last_name": "Nadella",
                "email": "satya.nadella@microsoft.com",
                "title": "CEO",
            },
            {
                "account_name": "Microsoft Corporation",
                "first_name": "Amy",
                "last_name": "Hood",
                "email": "amy.hood@microsoft.com",
                "title": "CFO",
            },
            {
                "account_name": "Salesforce Inc",
                "first_name": "Marc",
                "last_name": "Benioff",
                "email": "marc@salesforce.com",
                "title": "CEO",
            },
            {
                "account_name": "Salesforce Inc",
                "first_name": "Amy",
                "last_name": "Weaver",
                "email": "aweaver@salesforce.com",
                "title": "CFO",
            },
        ][:limit]
    
    elif "opportunity" in query_lower or "deal" in query_lower:
        return [
            {
                "account_name": "Microsoft Corporation",
                "opportunity_name": "Azure Enterprise Agreement",
                "amount": 5000000.0,
                "stage": "Negotiation",
                "close_date": "2025-03-31",
            },
            {
                "account_name": "Salesforce Inc",
                "opportunity_name": "Einstein AI Expansion",
                "amount": 1500000.0,
                "stage": "Proposal",
                "close_date": "2025-02-28",
            },
            {
                "account_name": "Google LLC",
                "opportunity_name": "Cloud Migration Project",
                "amount": 3000000.0,
                "stage": "Discovery",
                "close_date": "2025-06-30",
            },
        ][:limit]
    
    elif "account" in query_lower:
        return [
            {
                "id": "1",
                "name": "Microsoft Corporation",
                "industry": "Technology",
                "revenue": 211915000000.0,
                "employee_count": 221000,
            },
            {
                "id": "2",
                "name": "Salesforce Inc",
                "industry": "Technology",
                "revenue": 31352000000.0,
                "employee_count": 79390,
            },
            {
                "id": "3",
                "name": "Google LLC",
                "industry": "Technology",
                "revenue": 282836000000.0,
                "employee_count": 182502,
            },
        ][:limit]
    
    else:
        return [
            {
                "id": "1",
                "name": "Sample Record",
                "value": "Demo Data",
                "count": 42,
            }
        ][:limit]


if __name__ == "__main__":
    mcp.run(transport="http", port=MCP_SERVER_PORT)
