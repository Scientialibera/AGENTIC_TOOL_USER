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
MCP_SERVER_PORT = int(os.getenv("MCP_PORT", "8002"))  # Server port (from env or default 8002)
PROMPT_ID = "graph_agent_system"
AGENT_TYPE = "graph"  # Used to match function patterns like graph_*_function
DEFAULT_QUERY_LIMIT = 100

# ============================================================================
# MAGIC VARIABLES (centralized configuration)
# ============================================================================
TRANSPORT = "http"
HOST = "0.0.0.0"
SOURCE_NAME = "graph_mcp"
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

# Caches for prompts and tool definitions
_system_prompt_cache: Optional[str] = None
_agent_tools_cache: Optional[List[Dict[str, Any]]] = None


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
    global _system_prompt_cache

    # Load base prompt from cache or Cosmos
    if _system_prompt_cache is None:
        if cosmos_client is None:
            await initialize_clients()

        logger.info("Loading system prompt from Cosmos (cache miss)", prompt_id=PROMPT_ID)
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

        # Cache the base prompt
        _system_prompt_cache = base_prompt
        logger.info("System prompt loaded and cached", prompt_id=PROMPT_ID)
    else:
        logger.debug("Using cached system prompt")

    prompt = _system_prompt_cache

    # Add RBAC context if provided (not cached since it's user-specific)
    if rbac_context:
        user_email = rbac_context.get("email", "")
        prompt += f"\n\n## RBAC Context\nUser: {user_email}\nImportant: Filter graph traversals by user access when appropriate."

    return prompt


async def load_agent_tools() -> List[Dict[str, Any]]:
    """
    Load all tool definitions for this agent type from Cosmos DB.

    Returns:
        List of tool definitions in OpenAI function format

    Raises:
        Exception: If no tools found for this agent type
    """
    global _agent_tools_cache

    # Return cached tools if available
    if _agent_tools_cache is not None:
        logger.debug("Returning cached agent tools", count=len(_agent_tools_cache))
        return _agent_tools_cache

    if cosmos_client is None:
        await initialize_clients()

    logger.info("Loading agent tools from Cosmos (cache miss)", agent_type=AGENT_TYPE)
    # Load all tool definitions for this agent type from Cosmos DB
    # Pattern: {agent_type}_*_function (e.g., graph_query_function, graph_analysis_function)
    tool_items = await cosmos_client.query_items(
        container_name=settings.cosmos.agent_functions_container,
        query=f"SELECT * FROM c WHERE STARTSWITH(c.id, @prefix) AND ENDSWITH(c.id, '_function')",
        parameters=[{"name": "@prefix", "value": f"{AGENT_TYPE}_"}],
    )
    
    if not tool_items:
        raise Exception(f"No tool definitions found for agent type '{AGENT_TYPE}' in Cosmos DB")

    tools = []
    for tool_def in tool_items:
        tools.append({
            "type": "function",
            "function": {
                "name": tool_def.get("name"),
                "description": tool_def.get("description"),
                "parameters": tool_def.get("parameters"),
            }
        })

    # Cache the tools
    _agent_tools_cache = tools
    logger.info(f"Loaded and cached {len(tools)} tool(s) for agent type '{AGENT_TYPE}'",
               tool_names=[t["function"]["name"] for t in tools])

    return tools


async def resolve_accounts(
    account_names: List[str]
) -> List[Dict[str, Any]]:
    """Resolve account names using account resolver service with fuzzy matching."""
    try:
        if not account_names:
            return []

        if account_resolver is None:
            await initialize_clients()

        accounts = await account_resolver.resolve_account_names(account_names)

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
    edge_labels: Optional[List[str]] = None,
    request: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Execute graph queries against knowledge graph.
    
    This tool accepts ONLY natural language queries and uses an internal LLM 
    to generate the appropriate Gremlin query.
    
    Args:
        query: Natural language query describing what you want to find in the graph
        accounts_mentioned: List of account names mentioned in query for context
        rbac_context: User RBAC context for filtering
        max_depth: Maximum traversal depth for generated queries
        bindings: Optional variable bindings for the generated Gremlin query
        format: Output format (default, project, vertices, edges)
        edge_labels: Filter by specific edge labels in traversal
        request: FastAPI Request object (injected by FastMCP)
    
    Returns:
        Dictionary with query results, including success status, data, and metadata
    """
    # Verify JWT token from request
    from shared.auth_provider import verify_token_from_request
    if request:
        try:
            await verify_token_from_request(request)
            logger.debug("Graph MCP request authenticated")
        except Exception as e:
            logger.error("Graph MCP authentication failed", error=str(e))
            return {
                "success": False,
                "error": f"Authentication failed: {str(e)}",
                "data": []
            }
    else:
        logger.warning("No request object provided - skipping authentication")
    
    try:
        await initialize_clients()
        
        logger.info("Graph tool called", 
                   query_type=type(query).__name__,
                   query_preview=str(query)[:200], 
                   has_bindings=bindings is not None,
                   accounts_mentioned=accounts_mentioned)
        
        # Resolve account names if provided
        resolved_accounts = []
        if accounts_mentioned:
            resolved_accounts = await resolve_accounts(accounts_mentioned)
        
        # ALWAYS generate Gremlin query from natural language using internal LLM
        system_prompt = await get_system_prompt(rbac_context)
        
        user_message = f"Generate a valid Gremlin query for: {query}"
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
        
        # Load tool definitions for this agent
        tools = await load_agent_tools()
        
        logger.debug("LLM request", 
                    messages=json.dumps(messages, indent=2),
                    tools=json.dumps(tools, indent=2))
        
        response = await aoai_client.create_chat_completion(
            messages=messages,
            tools=tools,
            tool_choice="required"
        )
        
        logger.debug("LLM raw response", response=json.dumps(response, indent=2, default=str))
        
        # Extract function/tool call from response
        assistant_message = response["choices"][0]["message"]
        
        # Check for tool_calls (new style) or function_call (legacy)
        function_call = None
        if assistant_message.get("tool_calls"):
            tool_call = assistant_message["tool_calls"][0]
            function_call = tool_call.get("function")
            logger.info("Found tool_call in response", function_name=function_call.get("name"))
        elif assistant_message.get("function_call"):
            function_call = assistant_message["function_call"]
            logger.info("Found function_call in response", function_name=function_call.get("name"))
        else:
            logger.error("NO FUNCTION CALL FOUND IN RESPONSE!", 
                        message_keys=list(assistant_message.keys()),
                        content_preview=str(assistant_message.get("content", ""))[:200])
            raise Exception("LLM did not return a function call - check system prompt configuration")
        
        # Parse the function arguments to get the Gremlin query
        args_str = function_call.get("arguments", "{}")
        args = json.loads(args_str)
        gremlin_query = args.get("query", "")
        query_bindings = args.get("bindings", bindings or {})
        
        # Override with resolved accounts if not in function call
        if resolved_accounts and len(resolved_accounts) > 0 and "name" not in query_bindings:
            query_bindings["name"] = resolved_accounts[0].get("name", "")
        
        logger.info("Extracted Gremlin query", query_preview=gremlin_query[:100], has_bindings=bool(query_bindings))
        
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
            "bindings": query_bindings
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
    import os
    
    logger.info(f"Starting {MCP_SERVER_NAME} on {HOST}:{MCP_SERVER_PORT}")
    
    # Run the MCP server with explicit port configuration
    mcp.run(transport=TRANSPORT, port=MCP_SERVER_PORT, host=HOST)
