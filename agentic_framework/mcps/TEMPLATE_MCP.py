"""
MCP Server Template - Copy this file to create a new MCP.

CUSTOMIZATION STEPS:
1. Copy this file to mcps/<your_mcp_name>/server.py
2. Replace all TEMPLATE placeholders with your specific values
3. Implement your custom tool logic in the @mcp.tool() function
4. Upload your tool definitions and prompts to Cosmos DB
5. Add your MCP endpoint to MCP_ENDPOINTS environment variable

That's it! The orchestrator will automatically discover and use your MCP.
"""

import json
from typing import Dict, Any, List, Optional
from fastmcp import FastMCP
import structlog

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from shared.config import get_settings
from shared.aoai_client import AzureOpenAIClient
from shared.cosmos_client import CosmosDBClient
from shared.auth_provider import create_auth_provider

# ============================================================================
# CUSTOMIZATION REQUIRED: Update these constants for your MCP
# ============================================================================
MCP_SERVER_NAME = "TEMPLATE MCP Server"  # CHANGE ME: Human-readable name
AGENT_TYPE = "template"  # CHANGE ME: Used to load prompts and tools from Cosmos (e.g., "sql", "graph", "custom")
PROMPT_ID = "template_agent_system"  # CHANGE ME: ID of your system prompt in Cosmos DB prompts container
DEFAULT_QUERY_LIMIT = 100  # CHANGE ME: Default limit for query results

# ============================================================================
# BOILERPLATE - NO CHANGES NEEDED BELOW THIS LINE
# ============================================================================
logger = structlog.get_logger(__name__)
settings = get_settings()

# Create auth provider (None in dev mode, JWT validator in production)
auth_provider = create_auth_provider()

# Create MCP server with authentication
mcp = FastMCP(MCP_SERVER_NAME, auth=auth_provider)

# Global clients (initialized once, reused across requests)
aoai_client: Optional[AzureOpenAIClient] = None
cosmos_client: Optional[CosmosDBClient] = None
# ADD MORE CLIENTS HERE AS NEEDED (e.g., fabric_client, gremlin_client, etc.)

# Caches for prompts, schema, and tool definitions
_system_prompt_cache: Optional[str] = None
_agent_tools_cache: Optional[List[Dict[str, Any]]] = None
# ADD MORE CACHES HERE AS NEEDED (e.g., _schema_cache, _config_cache, etc.)


async def initialize_clients():
    """Initialize all required clients."""
    global aoai_client, cosmos_client  # ADD MORE CLIENTS TO GLOBAL LIST AS NEEDED

    if aoai_client is None:
        aoai_client = AzureOpenAIClient(settings.aoai)
    if cosmos_client is None:
        cosmos_client = CosmosDBClient(settings.cosmos)

    # CUSTOMIZATION: Add your client initialization here
    # Example:
    # if fabric_client is None:
    #     fabric_client = FabricClient(settings.fabric)

    logger.info(f"{MCP_SERVER_NAME} clients initialized")


async def get_system_prompt(rbac_context: Optional[Dict[str, Any]] = None) -> str:
    """Get system prompt from Cosmos DB with caching.

    BOILERPLATE - No changes needed unless you need custom prompt augmentation.
    """
    global _system_prompt_cache

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

        _system_prompt_cache = base_prompt
        logger.info("System prompt loaded and cached", prompt_id=PROMPT_ID)
    else:
        logger.debug("Using cached system prompt")

    prompt = _system_prompt_cache

    # CUSTOMIZATION: Add any RBAC or context augmentation here
    if rbac_context:
        user_email = rbac_context.get("email", "")
        prompt += f"\n\n## RBAC Context\nUser: {user_email}\n"
        # Add your custom RBAC instructions here

    return prompt


async def load_agent_tools() -> List[Dict[str, Any]]:
    """Load tool definitions from Cosmos DB with caching.

    BOILERPLATE - No changes needed.
    """
    global _agent_tools_cache

    if _agent_tools_cache is not None:
        logger.debug("Returning cached agent tools", count=len(_agent_tools_cache))
        return _agent_tools_cache

    if cosmos_client is None:
        await initialize_clients()

    logger.info("Loading agent tools from Cosmos (cache miss)", agent_type=AGENT_TYPE)
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

    _agent_tools_cache = tools
    logger.info(f"Loaded and cached {len(tools)} tool(s) for agent type '{AGENT_TYPE}'",
               tool_names=[t["function"]["name"] for t in tools])

    return tools


# ============================================================================
# CUSTOMIZATION REQUIRED: Implement your MCP tool below
# ============================================================================
@mcp.tool()
async def template_query(
    query: str,
    rbac_context: Optional[Dict[str, Any]] = None,
    limit: int = DEFAULT_QUERY_LIMIT,
    request: Optional[Any] = None
) -> Dict[str, Any]:
    """
    CUSTOMIZATION REQUIRED: Replace this with your tool implementation.

    This template shows the standard pattern:
    1. Authenticate request (optional)
    2. Initialize clients
    3. Get system prompt with RBAC context
    4. Use LLM to process user query
    5. Execute backend operation (database, API, etc.)
    6. Return structured result

    Args:
        query: Natural language query from user
        rbac_context: User RBAC context for security filtering
        limit: Maximum results to return
        request: FastAPI Request object (injected by FastMCP)

    Returns:
        Dictionary with success status, data, and metadata
    """
    # OPTIONAL: JWT authentication (auto-bypassed in dev mode)
    from shared.auth_provider import verify_token_from_request
    if request:
        try:
            await verify_token_from_request(request)
            logger.debug(f"{MCP_SERVER_NAME} request authenticated")
        except Exception as e:
            logger.error(f"{MCP_SERVER_NAME} authentication failed", error=str(e))
            return {
                "success": False,
                "error": f"Authentication failed: {str(e)}",
                "data": []
            }

    import time
    start_time = time.time()

    try:
        await initialize_clients()

        logger.info(f"📊 {AGENT_TYPE.upper()} TOOL START", query=query[:100])

        # CUSTOMIZATION: Add your pre-processing here (e.g., account resolution, data validation)

        # Get system prompt with RBAC context
        system_prompt = await get_system_prompt(rbac_context)

        # Build user message
        user_message = f"Process this query: {query}"
        # CUSTOMIZATION: Add any context or constraints to the user message
        user_message += f"\n\nLimit results to {limit} items."

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        # Load tool definitions for this agent
        tools = await load_agent_tools()

        # Call LLM to process query
        response = await aoai_client.create_chat_completion(
            messages=messages,
            tools=tools,
            tool_choice="required"
        )

        # Extract function/tool call from response
        assistant_message = response["choices"][0]["message"]

        function_call = None
        if assistant_message.get("tool_calls"):
            tool_call = assistant_message["tool_calls"][0]
            function_call = tool_call.get("function")
            logger.info("Found tool_call in response", function_name=function_call.get("name"))
        elif assistant_message.get("function_call"):
            function_call = assistant_message["function_call"]
            logger.info("Found function_call in response", function_name=function_call.get("name"))
        else:
            raise Exception("LLM did not return a function call - check system prompt configuration")

        # Parse function arguments
        args_str = function_call.get("arguments", "{}")
        args = json.loads(args_str)

        # CUSTOMIZATION: Extract and process the LLM's response
        # Example for SQL:
        # generated_query = args.get("query", "")
        # logger.info("Generated query", query_preview=generated_query[:100])

        # CUSTOMIZATION: Execute your backend operation
        if settings.dev_mode:
            # Return dummy data in dev mode
            results = _get_dummy_data(query, limit)
            logger.info("Dev mode: using dummy data", result_count=len(results))
        else:
            # CUSTOMIZATION: Execute real operation
            # Example:
            # results = await your_client.execute_operation(generated_query)
            # logger.info("Operation executed", result_count=len(results))
            results = []  # REPLACE THIS

        total_elapsed = int((time.time() - start_time) * 1000)
        logger.info(f"✅ {AGENT_TYPE.upper()} TOOL COMPLETE", result_count=len(results), total_duration_ms=total_elapsed)

        return {
            "success": True,
            "data": results[:limit],
            "row_count": len(results),
            "source": f"{AGENT_TYPE}_backend",
            # CUSTOMIZATION: Add any metadata you want to return
        }

    except Exception as e:
        total_elapsed = int((time.time() - start_time) * 1000)
        logger.error(f"❌ {AGENT_TYPE.upper()} TOOL FAILED", error=str(e), total_duration_ms=total_elapsed)
        return {
            "success": False,
            "error": str(e),
            "query": query,
        }


def _get_dummy_data(query: str, limit: int = 100) -> List[Dict[str, Any]]:
    """
    CUSTOMIZATION: Generate dummy data for dev mode.

    Replace this with your own dummy data that matches your backend schema.
    """
    return [
        {
            "id": "1",
            "name": "Sample Result 1",
            "description": "This is dummy data for dev mode",
        },
        {
            "id": "2",
            "name": "Sample Result 2",
            "description": "Replace this with your own test data",
        },
    ][:limit]


# ============================================================================
# SERVER STARTUP - NO CHANGES NEEDED
# ============================================================================
if __name__ == "__main__":
    import uvicorn

    # CUSTOMIZATION: Change port if needed (default pattern: 8001, 8002, 8003, etc.)
    PORT = 8003

    logger.info(f"Starting {MCP_SERVER_NAME} on port {PORT}")
    uvicorn.run(mcp.run(transport="http"), host="0.0.0.0", port=PORT)
