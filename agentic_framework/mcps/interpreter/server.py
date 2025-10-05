"""
Code Interpreter MCP Server using Azure OpenAI Assistants API.

This MCP enables code execution for math, graphs, and data analysis tasks
that LLMs struggle with. Uses Azure OpenAI Code Interpreter for sandboxed execution.
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
# MCP CONFIGURATION & MAGIC VARIABLES
# ============================================================================
# Server Configuration
MCP_SERVER_NAME = "Code Interpreter MCP Server"
TRANSPORT = "http"  # MCP transport protocol
HOST = "0.0.0.0"  # Server host
MCP_SERVER_PORT = 8003  # Server port

# Agent Configuration
AGENT_TYPE = "interpreter"
PROMPT_ID = "interpreter_agent_system"
DEFAULT_TIMEOUT = 300  # 5 minutes for code execution

# Azure OpenAI Assistants API Configuration
ASSISTANTS_API_VERSION = "2024-05-01-preview"
ASSISTANT_NAME = "Code Executor"
ASSISTANT_INSTRUCTIONS = "You are a Python code execution assistant. Execute code to solve math, data analysis, and visualization problems. Always return both the code executed and the result."
ASSISTANT_TOOL_TYPE = "code_interpreter"  # Azure OpenAI tool type
CODE_EXECUTION_TIMEOUT = 60  # seconds
POLLING_INTERVAL = 1  # seconds
LOG_INTERVAL = 10  # Log status every N seconds

# Response Configuration
SOURCE_NAME = "azure_code_interpreter"  # Source identifier in responses
CODE_FALLBACK_MESSAGE = "Code executed internally"  # Message when code blocks not extracted

logger = structlog.get_logger(__name__)
settings = get_settings()

# Create auth provider
auth_provider = create_auth_provider()

# Create MCP server
mcp = FastMCP(MCP_SERVER_NAME, auth=auth_provider)

# Global clients
aoai_client: Optional[AzureOpenAIClient] = None
cosmos_client: Optional[CosmosDBClient] = None
assistants_client: Optional[Any] = None  # Azure OpenAI Assistants client
assistant_id: Optional[str] = None  # Pre-warmed assistant

# Caches
_system_prompt_cache: Optional[str] = None
_agent_tools_cache: Optional[List[Dict[str, Any]]] = None


async def initialize_clients():
    """Initialize all required clients."""
    global aoai_client, cosmos_client, assistants_client, assistant_id

    if aoai_client is None:
        aoai_client = AzureOpenAIClient(settings.aoai)
    if cosmos_client is None:
        cosmos_client = CosmosDBClient(settings.cosmos)

    # Initialize Azure OpenAI Assistants client
    if assistants_client is None:
        from azure.identity import DefaultAzureCredential, get_bearer_token_provider
        from openai import AsyncAzureOpenAI

        credential = DefaultAzureCredential()
        token_provider = get_bearer_token_provider(
            credential,
            "https://cognitiveservices.azure.com/.default"
        )

        assistants_client = AsyncAzureOpenAI(
            azure_endpoint=settings.aoai.endpoint.rstrip("/"),
            api_version=ASSISTANTS_API_VERSION,
            azure_ad_token_provider=token_provider,
        )

        logger.info("Initialized Azure OpenAI Assistants client")

    # Pre-warm: Create persistent assistant with code interpreter
    if assistant_id is None:
        assistant = await assistants_client.beta.assistants.create(
            name=ASSISTANT_NAME,
            instructions=ASSISTANT_INSTRUCTIONS,
            model=settings.aoai.chat_deployment,
            tools=[{"type": ASSISTANT_TOOL_TYPE}]
        )
        assistant_id = assistant.id
        logger.info("Pre-warmed code interpreter assistant", assistant_id=assistant_id)

    logger.info(f"{MCP_SERVER_NAME} clients initialized")


async def get_system_prompt(rbac_context: Optional[Dict[str, Any]] = None) -> str:
    """Get system prompt from Cosmos DB with caching."""
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
            raise Exception(f"Prompt '{PROMPT_ID}' not found in Cosmos DB")

        base_prompt = prompt_items[0].get("content", "")
        if not base_prompt:
            raise Exception(f"Prompt '{PROMPT_ID}' has empty content")

        _system_prompt_cache = base_prompt
        logger.info("System prompt loaded and cached", prompt_id=PROMPT_ID)
    else:
        logger.debug("Using cached system prompt")

    return _system_prompt_cache


async def load_agent_tools() -> List[Dict[str, Any]]:
    """Load tool definitions from Cosmos DB with caching."""
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
        raise Exception(f"No tool definitions found for agent type '{AGENT_TYPE}'")

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


@mcp.tool()
async def interpreter_agent(
    query: str,
    rbac_context: Optional[Dict[str, Any]] = None,
    request: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Execute Python code using Azure Code Interpreter for math, data analysis, and visualizations.
    
    This tool directly uses Azure OpenAI Assistants Code Interpreter to execute
    Python code in a sandboxed environment. No intermediate LLM step needed.
    
    Args:
        query: Natural language query describing what to compute/analyze
        rbac_context: User RBAC context (not used for code execution)
        request: FastAPI Request object (injected by FastMCP)
    
    Returns:
        Dictionary with execution results, including code and outputs
    """
    # Authentication (bypass in dev mode like other MCPs)
    if not settings.dev_mode:
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
                }
        else:
            logger.warning("No request object provided - skipping authentication")
    else:
        logger.warning("No request object provided - skipping authentication")

    import time
    start_time = time.time()

    try:
        await initialize_clients()

        logger.info("📊 INTERPRETER AGENT START", query_preview=query[:100])
        logger.info("🔧 EXECUTING CODE via Azure Assistants API")

        # Create thread and send query directly to assistant
        thread = await assistants_client.beta.threads.create()
        logger.debug("Created thread", thread_id=thread.id)

        # Send query to assistant
        await assistants_client.beta.threads.messages.create(
            thread_id=thread.id,
            role="user",
            content=query
        )

        # Run the assistant
        run = await assistants_client.beta.threads.runs.create(
            thread_id=thread.id,
            assistant_id=assistant_id
        )

        logger.info("🔄 CODE EXECUTION STARTED", run_id=run.id)

        # Wait for completion
        import asyncio
        elapsed = 0

        while run.status in ["queued", "in_progress"] and elapsed < CODE_EXECUTION_TIMEOUT:
            await asyncio.sleep(POLLING_INTERVAL)
            run = await assistants_client.beta.threads.runs.retrieve(
                thread_id=thread.id,
                run_id=run.id
            )
            elapsed += POLLING_INTERVAL

            if elapsed % LOG_INTERVAL == 0:
                logger.debug("Waiting for execution", status=run.status, elapsed=elapsed)

        if run.status != "completed":
            logger.error("Code execution did not complete", status=run.status, elapsed=elapsed)
            return {
                "success": False,
                "error": f"Execution timeout or failed with status: {run.status}",
                "query": query
            }

        # Get run steps to extract actual code executed
        run_steps = await assistants_client.beta.threads.runs.steps.list(
            thread_id=thread.id,
            run_id=run.id,
            order="asc"
        )

        # Get messages from the thread
        messages_response = await assistants_client.beta.threads.messages.list(
            thread_id=thread.id,
            order="asc"
        )

        # Extract code from run steps (actual code executed by code_interpreter)
        code_executed = []
        for step in run_steps.data:
            if step.type == "tool_calls":
                for tool_call in step.step_details.tool_calls:
                    if tool_call.type == "code_interpreter":
                        if hasattr(tool_call.code_interpreter, 'input') and tool_call.code_interpreter.input:
                            code_executed.append(tool_call.code_interpreter.input)
                            logger.debug("Extracted code from run step", 
                                       code_preview=tool_call.code_interpreter.input[:100])

        # Extract results from assistant's messages
        result_text = ""
        output_type = "text"

        for msg in messages_response.data:
            if msg.role == "assistant":
                for content in msg.content:
                    if content.type == "text":
                        text_value = content.text.value
                        result_text += text_value + "\n"

                    elif content.type == "image_file":
                        output_type = "image"
                        result_text += f"\n[Image generated: {content.image_file.file_id}]"

        total_elapsed = int((time.time() - start_time) * 1000)

        logger.info("✅ CODE EXECUTION COMPLETE", 
                   code_blocks=len(code_executed),
                   result_preview=result_text[:300],
                   duration_ms=total_elapsed)

        result = {
            "success": True,
            "code": "\n\n".join(code_executed) if code_executed else CODE_FALLBACK_MESSAGE,
            "result": result_text.strip(),
            "output_type": output_type,
            "execution_time_ms": total_elapsed,
            "source": SOURCE_NAME,
            "thread_id": thread.id,
            "query": query
        }

        # Cleanup: Delete the thread to avoid accumulation
        try:
            await assistants_client.beta.threads.delete(thread.id)
            logger.debug("🧹 Cleaned up thread", thread_id=thread.id)
        except Exception as cleanup_error:
            logger.warning("Failed to cleanup thread", thread_id=thread.id, error=str(cleanup_error))

        return result

    except Exception as e:
        total_elapsed = int((time.time() - start_time) * 1000)
        logger.error("❌ INTERPRETER AGENT FAILED", error=str(e), duration_ms=total_elapsed)
        
        # Try to cleanup thread even on error
        try:
            if 'thread' in locals():
                await assistants_client.beta.threads.delete(thread.id)
                logger.debug("🧹 Cleaned up thread after error", thread_id=thread.id)
        except:
            pass  # Ignore cleanup errors on error path
        
        return {
            "success": False,
            "error": str(e),
            "query": query,
            "execution_time_ms": total_elapsed
        }


# ============================================================================
# SERVER STARTUP & CLEANUP
# ============================================================================
async def cleanup_on_shutdown():
    """Cleanup resources on server shutdown."""
    global assistant_id, assistants_client
    
    if assistant_id and assistants_client:
        try:
            await assistants_client.beta.assistants.delete(assistant_id)
            logger.info("🧹 Cleaned up assistant on shutdown", assistant_id=assistant_id)
        except Exception as e:
            logger.warning("Failed to cleanup assistant on shutdown", error=str(e))


if __name__ == "__main__":
    import os
    
    logger.info(f"Starting {MCP_SERVER_NAME} on {HOST}:{MCP_SERVER_PORT} with transport={TRANSPORT}")
    
    # Set environment variables for FastMCP to use correct host/port
    os.environ["FASTMCP_HOST"] = HOST
    os.environ["FASTMCP_PORT"] = str(MCP_SERVER_PORT)
    
    # Run the MCP server - FastMCP will use the env vars
    mcp.run(transport=TRANSPORT)
