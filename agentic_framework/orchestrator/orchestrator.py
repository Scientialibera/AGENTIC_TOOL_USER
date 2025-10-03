"""
Orchestrator Agent.

The main orchestrator that discovers MCPs, loads their tools, and coordinates
execution using Azure OpenAI for planning and tool selection.
"""

import json
import asyncio
from typing import Dict, Any, List, Optional
from fastmcp import Client
import structlog

from shared.config import get_settings
from shared.models import RBACContext, MCPDefinition, ToolDefinition
from shared.aoai_client import AzureOpenAIClient
from shared.cosmos_client import CosmosDBClient
from orchestrator.discovery_service import MCPDiscoveryService

# ============================================================================
# CONSTANTS
# ============================================================================
PROMPT_ID = "planner_system"
DEFAULT_MAX_ROUNDS = 10

logger = structlog.get_logger(__name__)


class OrchestratorAgent:
    """
    Central orchestrator agent that coordinates MCP servers.
    
    This agent:
    1. Discovers available MCPs from Cosmos DB
    2. Loads tool definitions with RBAC filtering
    3. Uses Azure OpenAI to plan and select tools
    4. Calls MCP servers and aggregates results
    """
    
    def __init__(
        self,
        aoai_client: AzureOpenAIClient,
        cosmos_client: CosmosDBClient,
        discovery_service: MCPDiscoveryService,
        unified_service,
        settings=None
    ):
        """Initialize the orchestrator agent."""
        self.aoai_client = aoai_client
        self.cosmos_client = cosmos_client
        self.discovery_service = discovery_service
        self.unified_service = unified_service
        self.settings = settings or get_settings()
        
        self.mcp_clients: Dict[str, Client] = {}
        
        logger.info("Orchestrator Agent initialized")
    
    async def process_request(
        self,
        user_query: str,
        rbac_context: RBACContext,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        max_rounds: int = DEFAULT_MAX_ROUNDS,
        session_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Process a user request with multi-round planning and execution.
        
        Args:
            user_query: User's natural language query
            rbac_context: User RBAC context
            conversation_history: Optional conversation history
            max_rounds: Maximum planning rounds
            session_id: Optional session ID for tracking
        
        Returns:
            Dictionary with response and execution metadata
        """
        try:
            logger.info("Processing request", query=user_query[:100], user=rbac_context.user_id)
            
            mcps = await self.discovery_service.discover_mcps(rbac_context)
            
            if not mcps:
                return {
                    "success": False,
                    "error": "No MCPs available for user",
                    "response": "I don't have access to any tools to answer your question.",
                }
            
            available_tools = await self._load_all_tools(mcps, rbac_context)
            
            if not available_tools:
                return {
                    "success": False,
                    "error": "No tools available",
                    "response": "I don't have the necessary tools to answer your question.",
                }
            
            system_prompt = await self._get_orchestrator_prompt()
            
            messages = [
                {"role": "system", "content": system_prompt},
            ]
            
            if conversation_history:
                messages.extend(conversation_history)
            
            messages.append({"role": "user", "content": user_query})
            
            execution_records = []
            
            for round_num in range(max_rounds):
                logger.info("Planning round", round=round_num + 1)
                
                response = await self.aoai_client.create_chat_completion(
                    messages=messages,
                    tools=available_tools,
                    tool_choice="auto",
                )
                
                assistant_msg = response["choices"][0]["message"]
                tool_calls = assistant_msg.get("tool_calls")
                
                if not tool_calls:
                    final_response = assistant_msg.get("content", "")
                    logger.info("Planning complete", rounds=round_num + 1)
                    
                    return {
                        "success": True,
                        "response": final_response,
                        "rounds": round_num + 1,
                        "execution_records": execution_records,
                        "mcps_used": list(set([rec["mcp_id"] for rec in execution_records])),
                    }
                
                messages.append(assistant_msg)
                
                tool_results = await self._execute_tool_calls(
                    tool_calls, mcps, rbac_context
                )
                
                execution_records.extend(tool_results)
                
                for tool_result in tool_results:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_result["tool_call_id"],
                        "content": json.dumps(tool_result["result"]),
                    })
            
            logger.warning("Max rounds reached", max_rounds=max_rounds)
            
            return {
                "success": False,
                "error": "Max planning rounds reached",
                "response": "I wasn't able to complete your request within the allowed planning rounds.",
                "rounds": max_rounds,
                "execution_records": execution_records,
            }
            
        except Exception as e:
            logger.error("Failed to process request", error=str(e))
            return {
                "success": False,
                "error": str(e),
                "response": "An error occurred while processing your request.",
            }
    
    async def _load_all_tools(
        self,
        mcps: List[Dict[str, Any]],
        rbac_context: RBACContext
    ) -> List[Dict[str, Any]]:
        """Load all tool definitions from MCPs."""
        # Get all tools directly from discovery service
        all_tools_raw = await self.discovery_service.get_all_available_tools()
        
        all_tools = []
        for tool in all_tools_raw:
            tool_schema = {
                "type": "function",
                "function": {
                    "name": tool.get("name"),
                    "description": tool.get("description"),
                    "parameters": tool.get("parameters"),
                }
            }
            all_tools.append(tool_schema)
        
        return all_tools

    async def _execute_tool_calls(
        self,
        tool_calls: List[Dict[str, Any]],
        mcps: List[Dict[str, Any]],
        rbac_context: RBACContext
    ) -> List[Dict[str, Any]]:
        """Execute tool calls by routing to appropriate MCPs."""
        results = []
        
        for tool_call in tool_calls:
            tool_name = tool_call["function"]["name"]
            arguments_str = tool_call["function"]["arguments"]
            logger.debug("Raw tool arguments from OpenAI", tool_name=tool_name, arguments_str=arguments_str[:200])
            arguments = json.loads(arguments_str)

            # Keep original LLM arguments for logging
            llm_arguments = arguments.copy()

            arguments["rbac_context"] = rbac_context.to_dict()
            logger.debug("Calling tool with arguments", tool_name=tool_name, arguments_keys=list(arguments.keys()))

            mcp_id = await self._find_mcp_for_tool(tool_name, mcps)

            if not mcp_id:
                logger.warning("No MCP found for tool", tool_name=tool_name)
                results.append({
                    "tool_call_id": tool_call["id"],
                    "tool_name": tool_name,
                    "mcp_id": None,
                    "arguments": llm_arguments,  # Add LLM arguments
                    "result": {"success": False, "error": "Tool not found"},
                })
                continue

            try:
                result = await self._call_mcp_tool(mcp_id, tool_name, arguments, mcps)
                results.append({
                    "tool_call_id": tool_call["id"],
                    "tool_name": tool_name,
                    "mcp_id": mcp_id,
                    "arguments": llm_arguments,  # Add LLM arguments
                    "result": result,
                })
            except Exception as e:
                logger.error("Tool execution failed", tool_name=tool_name, error=str(e))
                results.append({
                    "tool_call_id": tool_call["id"],
                    "tool_name": tool_name,
                    "mcp_id": mcp_id,
                    "arguments": llm_arguments,  # Add LLM arguments
                    "result": {"success": False, "error": str(e)},
                })
        
        return results
    
    async def _find_mcp_for_tool(
        self,
        tool_name: str,
        mcps: List[Dict[str, Any]]
    ) -> Optional[str]:
        """Find which MCP provides a specific tool."""
        # Get tools and find which MCP provides this tool
        all_tools = await self.discovery_service.get_all_available_tools()
        
        for tool in all_tools:
            if tool.get("name") == tool_name:
                return tool.get("mcp_id")
        
        # Fallback: check MCP definitions
        for mcp in mcps:
            mcp_id = mcp.get("id") if isinstance(mcp, dict) else mcp.id
            tools = mcp.get("tools", []) if isinstance(mcp, dict) else mcp.tools
            if tool_name in tools:
                return mcp_id
        
        tools = await self.cosmos_client.query_items(
            container_name=self.settings.cosmos.agent_functions_container,
            query="SELECT c.mcp_id FROM c WHERE c.name = @tool_name",
            parameters=[{"name": "@tool_name", "value": tool_name}],
        )
        
        if tools:
            return tools[0].get("mcp_id")
        
        return None
    
    async def _call_mcp_tool(
        self,
        mcp_id: str,
        tool_name: str,
        arguments: Dict[str, Any],
        mcps: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Call a tool on an MCP server."""
        # Handle both dict and MCPDefinition objects
        mcp_def = None
        for m in mcps:
            m_id = m.get("id") if isinstance(m, dict) else m.id
            if m_id == mcp_id:
                mcp_def = m
                break

        if not mcp_def:
            raise ValueError(f"MCP not found: {mcp_id}")

        # Get endpoint from dict or object
        endpoint = mcp_def.get("endpoint") if isinstance(mcp_def, dict) else mcp_def.endpoint

        if mcp_id not in self.mcp_clients:
            client = Client(endpoint)
            self.mcp_clients[mcp_id] = client

        client = self.mcp_clients[mcp_id]

        async with client:
            result = await client.call_tool(tool_name, arguments)

            # Extract data from CallToolResult
            # The result has .data attribute with the actual tool response
            if hasattr(result, 'data'):
                return result.data
            elif hasattr(result, 'content') and result.content:
                # Fallback: extract from text content
                import json
                for content_item in result.content:
                    if hasattr(content_item, 'text'):
                        return json.loads(content_item.text)

            return result
    
    async def _get_orchestrator_prompt(self) -> str:
        """Get orchestrator system prompt from Cosmos DB.
        
        Raises:
            Exception: If prompt cannot be loaded from Cosmos DB
        """
        items = await self.cosmos_client.query_items(
            container_name=self.settings.cosmos.prompts_container,
            query="SELECT * FROM c WHERE c.id = @prompt_id",
            parameters=[{"name": "@prompt_id", "value": PROMPT_ID}],
        )
        
        if not items:
            raise Exception(f"Prompt '{PROMPT_ID}' not found in Cosmos DB container '{self.settings.cosmos.prompts_container}'")
        
        content = items[0].get("content", "")
        if not content:
            raise Exception(f"Prompt '{PROMPT_ID}' has empty content")
        
        return content
    
    async def close(self):
        """Clean up resources."""
        for client in self.mcp_clients.values():
            try:
                await client.__aexit__(None, None, None)
            except:
                pass
        
        self.mcp_clients.clear()
