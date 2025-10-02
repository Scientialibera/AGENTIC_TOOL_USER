"""
Main orchestrator service for coordinating MCP tool calls.

This service handles the agentic planning loop similar to the original planner_service,
but routes tool calls to appropriate MCP servers based on user roles.
"""

import json
import structlog
from typing import Dict, Any, List, Optional

from orchestrator.clients.aoai_client import AzureOpenAIClient
from orchestrator.services.mcp_loader_service import MCPLoaderService

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../.."))

from shared.models.rbac import RBACContext

logger = structlog.get_logger(__name__)


class OrchestratorService:
    """Main orchestration service for MCP-based agentic planning."""

    def __init__(
        self,
        aoai_client: AzureOpenAIClient,
        mcp_loader: MCPLoaderService,
        system_prompt: Optional[str] = None,
    ):
        """
        Initialize orchestrator service.

        Args:
            aoai_client: Azure OpenAI client for LLM calls
            mcp_loader: MCP loader service for managing MCP connections
            system_prompt: Optional system prompt override
        """
        self.aoai_client = aoai_client
        self.mcp_loader = mcp_loader
        self.system_prompt = system_prompt or self._default_system_prompt()

    def _default_system_prompt(self) -> str:
        """Default system prompt for the orchestrator."""
        return """You are an intelligent orchestrator for a business data assistant.

You have access to various tools provided by different MCP servers. Use these tools to answer user questions accurately.

When the user asks a question:
1. Determine which tools you need to call
2. Make the necessary tool calls to gather information
3. Synthesize the results into a natural, helpful response

Always provide accurate, data-driven answers with proper context."""

    async def plan_and_execute(
        self,
        user_message: str,
        rbac_context: RBACContext,
        accessible_mcps: List[str],
        conversation_history: Optional[List[Dict[str, str]]] = None,
        max_rounds: int = 8,
    ) -> Dict[str, Any]:
        """
        Plan and execute user request using run-until-done loop.

        This implements the agentic planning pattern from the original chatbot:
        1. Discover tools from accessible MCPs
        2. Call LLM with tools to get plan
        3. Execute tool calls via MCPs
        4. Inject results back to LLM
        5. Repeat until LLM provides final answer

        Args:
            user_message: User's question/request
            rbac_context: User's RBAC context
            accessible_mcps: List of MCP names user can access
            conversation_history: Optional conversation history
            max_rounds: Maximum planning rounds

        Returns:
            Dictionary with final response and execution metadata
        """
        try:
            # Step 1: Discover tools from accessible MCPs
            logger.info("Discovering tools from MCPs", mcps=accessible_mcps)
            mcp_tools = await self.mcp_loader.discover_tools(accessible_mcps)

            # Flatten tools into single list for LLM with MCP source tracking
            all_tools = []
            tool_to_mcp = {}  # Map tool name to MCP name

            for mcp_name, tools in mcp_tools.items():
                for tool in tools:
                    tool_name = tool.get("name", "")
                    # Add MCP prefix to avoid name collisions
                    prefixed_name = f"{mcp_name}__{tool_name}"
                    tool_copy = {**tool, "name": prefixed_name}
                    all_tools.append({
                        "type": "function",
                        "function": tool_copy
                    })
                    tool_to_mcp[prefixed_name] = mcp_name

            logger.info("Tool discovery complete", total_tools=len(all_tools), tool_sources=list(mcp_tools.keys()))

            # Step 2: Initialize conversation
            messages = [
                {"role": "system", "content": self.system_prompt},
            ]

            # Add conversation history if provided
            if conversation_history:
                messages.extend(conversation_history[-5:])  # Last 5 turns for context

            # Add current user message
            messages.append({"role": "user", "content": user_message})

            # Step 3: Run-until-done loop
            round_num = 0
            execution_metadata = {
                "rounds": [],
                "total_tool_calls": 0,
                "final_round": None,
            }

            while True:
                round_num += 1

                if round_num > max_rounds:
                    logger.warning("Reached max rounds", max_rounds=max_rounds)
                    break

                # Call LLM with tools
                try:
                    response = await self.aoai_client.create_chat_completion(
                        messages=messages,
                        tools=all_tools if all_tools else None,
                        tool_choice="auto" if all_tools else None,
                    )
                except Exception as e:
                    logger.error("LLM call failed", round=round_num, error=str(e))
                    break

                message = (response.get("choices") or [{}])[0].get("message", {})
                tool_calls = message.get("tool_calls", [])

                round_metadata = {
                    "round": round_num,
                    "tool_calls_count": len(tool_calls),
                    "assistant_content": message.get("content"),
                    "tool_executions": []
                }

                # Add assistant message to conversation
                if message.get("content"):
                    messages.append({"role": "assistant", "content": message["content"]})

                # If no tool calls, we have final answer
                if not tool_calls:
                    if message.get("content"):
                        execution_metadata["final_round"] = round_num
                        execution_metadata["rounds"].append(round_metadata)
                        return {
                            "success": True,
                            "assistant_message": message["content"],
                            "execution_metadata": execution_metadata,
                            "final_answer": True,
                        }
                    break

                # Execute tool calls via MCPs
                tool_results = []
                for tool_call in tool_calls:
                    function_info = tool_call.get("function", {})
                    prefixed_tool_name = function_info.get("name", "")

                    # Determine which MCP to call
                    mcp_name = tool_to_mcp.get(prefixed_tool_name)
                    if not mcp_name:
                        logger.warning("Unknown tool called", tool_name=prefixed_tool_name)
                        continue

                    # Remove MCP prefix to get actual tool name
                    actual_tool_name = prefixed_tool_name.replace(f"{mcp_name}__", "", 1)

                    # Parse arguments
                    try:
                        args = json.loads(function_info.get("arguments", "{}"))
                    except:
                        args = {}

                    # Get MCP client
                    mcp_client = self.mcp_loader.get_client(mcp_name)
                    if not mcp_client:
                        logger.error("MCP client not found", mcp_name=mcp_name)
                        continue

                    # Call tool on MCP
                    try:
                        result = await mcp_client.call_tool(
                            tool_name=actual_tool_name,
                            arguments=args,
                            rbac_context=rbac_context.model_dump(),
                        )

                        tool_results.append({
                            "tool_name": prefixed_tool_name,
                            "mcp_name": mcp_name,
                            "success": result.get("success", True),
                            "result": result,
                        })

                        round_metadata["tool_executions"].append({
                            "tool_name": actual_tool_name,
                            "mcp_name": mcp_name,
                            "success": result.get("success", True),
                            "row_count": result.get("row_count", 0),
                        })

                        execution_metadata["total_tool_calls"] += 1

                    except Exception as e:
                        logger.error("Tool execution failed", tool=actual_tool_name, mcp=mcp_name, error=str(e))
                        tool_results.append({
                            "tool_name": prefixed_tool_name,
                            "mcp_name": mcp_name,
                            "success": False,
                            "error": str(e),
                        })

                # Inject tool results back into conversation
                if tool_results:
                    results_summary = self._build_tool_results_summary(tool_results)
                    messages.append({"role": "assistant", "content": results_summary})
                    messages.append({
                        "role": "user",
                        "content": "Using the information above, provide the final answer."
                    })

                execution_metadata["rounds"].append(round_metadata)

            # If we exit loop without final answer
            logger.warning("Loop ended without final answer", rounds=round_num)
            execution_metadata["final_round"] = round_num

            return {
                "success": False,
                "assistant_message": "I've processed your request but encountered some complexity. Please try asking in a different way.",
                "execution_metadata": execution_metadata,
                "final_answer": False,
                "timeout": True,
            }

        except Exception as e:
            logger.error("Orchestration failed", error=str(e))
            return {
                "success": False,
                "assistant_message": "I apologize, but I encountered an error processing your request.",
                "error": str(e),
            }

    def _build_tool_results_summary(self, tool_results: List[Dict[str, Any]]) -> str:
        """Build a summary of tool execution results for LLM."""
        lines = ["### Tool Execution Results\n"]

        for result in tool_results:
            tool_name = result.get("tool_name", "unknown")
            mcp_name = result.get("mcp_name", "unknown")
            success = result.get("success", False)

            lines.append(f"**Tool**: `{tool_name}` (MCP: `{mcp_name}`)")

            if success:
                result_data = result.get("result", {})
                row_count = result_data.get("row_count", 0)
                lines.append(f"  - Status: Success")
                lines.append(f"  - Rows: {row_count}")

                # Include sample data if available
                if "data" in result_data:
                    data = result_data["data"]
                    if isinstance(data, list) and data:
                        lines.append(f"  - Sample: {json.dumps(data[:3], default=str)}")
            else:
                error = result.get("error", "Unknown error")
                lines.append(f"  - Status: Failed")
                lines.append(f"  - Error: {error}")

            lines.append("")

        return "\n".join(lines)
