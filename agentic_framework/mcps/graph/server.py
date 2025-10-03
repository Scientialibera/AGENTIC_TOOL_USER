"""
Graph MCP Server for GraphQL/Gremlin interactions.

This MCP server provides graph query capabilities with intelligent query
generation using an internal LLM and RBAC-based filtering.
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
from shared.gremlin_client import GremlinClient
from shared.cosmos_client import CosmosDBClient
from shared.account_resolver import AccountResolverService
from shared.auth_provider import create_auth_provider

# ============================================================================
# CONSTANTS
# ============================================================================
MCP_SERVER_NAME = "Graph MCP Server"
MCP_SERVER_PORT = 8002
PROMPT_ID = "graph_agent_system"
DEFAULT_QUERY_LIMIT = 100
DEFAULT_OUTPUT_FORMAT = "summary"

logger = structlog.get_logger(__name__)

settings = get_settings()

# Initialize auth provider (None in dev mode, JWTVerifier in production)
auth_provider = create_auth_provider()

# Create MCP server with authentication
# In dev mode, auth_provider is None so authentication is disabled
# In production, auth_provider validates JWT tokens from Azure AD
mcp = FastMCP(MCP_SERVER_NAME, auth=auth_provider)

aoai_client: Optional[AzureOpenAIClient] = None
gremlin_client: Optional[GremlinClient] = None
cosmos_client: Optional[CosmosDBClient] = None
account_resolver: Optional[AccountResolverService] = None


async def initialize_clients():
    """Initialize all required clients."""
    global aoai_client, gremlin_client, cosmos_client, account_resolver
    
    if aoai_client is None:
        aoai_client = AzureOpenAIClient(settings.aoai)
    if gremlin_client is None:
        gremlin_client = GremlinClient(settings.gremlin)
    if cosmos_client is None:
        cosmos_client = CosmosDBClient(settings.cosmos)
    if account_resolver is None:
        # Graph server uses real account resolution (no dummy data)
        # Dev mode only affects RBAC filtering
        account_resolver = AccountResolverService(
            fabric_client=None,  # Graph doesn't need Fabric
            dev_mode=settings.dev_mode
        )
    
    logger.info("Graph MCP Server clients initialized")


async def get_system_prompt(rbac_context: Optional[Dict[str, Any]] = None) -> str:
    """Get graph agent system prompt from Cosmos DB.
    
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
    
    if rbac_context:
        user_email = rbac_context.get("email", "")
        base_prompt += f"\n\n## RBAC Context\nUser: {user_email}\nImportant: Filter graph traversals by user access when appropriate."
    
    return base_prompt


async def resolve_accounts(
    account_names: List[str],
    rbac_context: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """Resolve account names using account resolver service."""
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
async def graph_query(
    query: str,
    accounts_mentioned: Optional[List[str]] = None,
    rbac_context: Optional[Dict[str, Any]] = None,
    max_depth: int = 3,
    bindings: Optional[Dict[str, Any]] = None,
    format: str = DEFAULT_OUTPUT_FORMAT,
    edge_labels: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Execute graph queries against knowledge graph.
    
    This tool can accept either:
    1. Natural language query - will use internal LLM to generate Gremlin
    2. Direct Gremlin query - will execute as-is with provided bindings
    
    Args:
        query: Natural language query OR direct Gremlin query string
        accounts_mentioned: List of account names mentioned in query
        rbac_context: User RBAC context for filtering
        max_depth: Maximum traversal depth for generated queries
        bindings: Variable bindings for parameterized Gremlin queries
        format: Output format (default, project, vertices, edges)
        edge_labels: Filter by specific edge labels in traversal
    
    Returns:
        Dictionary with query results, including success status, data, and metadata
    """
    try:
        await initialize_clients()
        
        logger.info("Graph tool called", query=query[:100], has_bindings=bindings is not None)
        
        # Determine if this is a direct Gremlin query or natural language
        is_gremlin_query = query.strip().startswith("g.") or ".V()" in query or ".E()" in query
        
        resolved_accounts = []
        if accounts_mentioned:
            resolved_accounts = await resolve_accounts(accounts_mentioned, rbac_context)
        
        # If direct Gremlin query provided with bindings, use it as-is
        if is_gremlin_query and bindings:
            gremlin_query = query
            query_bindings = bindings
            logger.info("Using direct Gremlin query with bindings", bindings=bindings)
        else:
            # Generate Gremlin query from natural language
            system_prompt = await get_system_prompt(rbac_context)
            
            user_message = f"Generate a Gremlin query for: {query}"
            if resolved_accounts:
                account_names = [acc.get("name", "") for acc in resolved_accounts]
                user_message += f"\n\nAccount context: {', '.join(account_names)}"
            user_message += f"\n\nMax traversal depth: {max_depth}"
            if edge_labels:
                user_message += f"\n\nEdge labels to traverse: {', '.join(edge_labels)}"
            
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ]
            
            response = await aoai_client.create_chat_completion(messages=messages)
            
            assistant_content = response["choices"][0]["message"]["content"]
            
            gremlin_query = assistant_content.strip()
            if "```gremlin" in gremlin_query:
                gremlin_query = gremlin_query.split("```gremlin")[1].split("```")[0].strip()
            elif "```" in gremlin_query:
                gremlin_query = gremlin_query.split("```")[1].split("```")[0].strip()
            
            query_bindings = bindings or {}
            if resolved_accounts and len(resolved_accounts) > 0:
                query_bindings["account_name"] = resolved_accounts[0].get("name", "")
        
        # Execute the Gremlin query (no dev mode dummy data for graph queries)
        results = await gremlin_client.execute_query(gremlin_query, query_bindings)
        logger.info("Graph query executed", result_count=len(results), bindings=query_bindings)
        
        return {
            "success": True,
            "query": gremlin_query,
            "row_count": len(results),
            "data": results,
            "source": "gremlin_graph",
            "resolved_accounts": resolved_accounts,
            "bindings": query_bindings,
            "format": format,
        }
        
    except Exception as e:
        logger.error("Graph tool execution failed", error=str(e))
        return {
            "success": False,
            "error": str(e),
            "query": query,
        }


# Note: Graph queries ALWAYS execute against real Cosmos DB Gremlin database
# Dev mode only disables RBAC context filtering, not the actual query execution


if __name__ == "__main__":
    mcp.run(transport="http", port=MCP_SERVER_PORT)
