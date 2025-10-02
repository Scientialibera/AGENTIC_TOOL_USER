"""
Simplified Salesforce MCP Server using FastAPI.

This provides a simple HTTP-based MCP server without FastMCP dependency.
"""

import json
import structlog
from typing import Dict, Any, Optional, List
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../.."))

from shared.models.rbac import RBACContext
from salesforce_mcp.config.settings import settings
from salesforce_mcp.clients import FabricLakehouseClient, GremlinClient
from salesforce_mcp.services import SQLService, GraphService

logger = structlog.get_logger(__name__)

# Create FastAPI app
app = FastAPI(title="Salesforce MCP", version="1.0.0")

# Global service instances
sql_service: Optional[SQLService] = None
graph_service: Optional[GraphService] = None


class ToolCallRequest(BaseModel):
    name: str
    arguments: Dict[str, Any]


class ToolListResponse(BaseModel):
    tools: List[Dict[str, Any]]


@app.on_event("startup")
async def startup():
    """Initialize services on startup."""
    global sql_service, graph_service

    logger.info("Starting Salesforce MCP", dev_mode=settings.dev_mode)

    # Initialize clients
    fabric_client = FabricLakehouseClient(
        lakehouse_sql_endpoint=settings.fabric_lakehouse.sql_endpoint,
        lakehouse_database=settings.fabric_lakehouse.database,
        lakehouse_workspace_id=settings.fabric_lakehouse.workspace_id,
        connection_timeout=settings.fabric_lakehouse.connection_timeout,
        dev_mode=settings.dev_mode,
    )

    gremlin_client = None
    if settings.gremlin.endpoint:
        gremlin_client = GremlinClient(settings.gremlin)

    # Initialize services
    sql_service = SQLService(
        aoai_client=None,
        schema_repository=None,
        unified_data_service=None,
        telemetry_service=None,
        settings=settings.fabric_lakehouse,
        dev_mode=settings.dev_mode,
    )

    graph_service = GraphService(
        gremlin_client=gremlin_client,
        dev_mode=settings.dev_mode,
    )

    logger.info("Salesforce MCP started successfully")


@app.on_event("shutdown")
async def shutdown():
    """Cleanup on shutdown."""
    logger.info("Shutting down Salesforce MCP")


@app.post("/mcp/tools/list")
async def list_tools() -> ToolListResponse:
    """List available MCP tools."""
    tools = [
        {
            "name": "query_sql",
            "description": "Execute a SQL query against the Fabric lakehouse",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "SQL query to execute"},
                    "rbac_context": {
                        "type": "object",
                        "description": "RBAC context for access control",
                    },
                },
                "required": ["query"],
            },
        },
        {
            "name": "query_graph",
            "description": "Execute a Gremlin query against the graph database",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "gremlin_query": {
                        "type": "string",
                        "description": "Gremlin query to execute",
                    },
                    "bindings": {
                        "type": "object",
                        "description": "Optional query parameter bindings",
                    },
                    "rbac_context": {
                        "type": "object",
                        "description": "RBAC context for access control",
                    },
                },
                "required": ["gremlin_query"],
            },
        },
    ]

    return ToolListResponse(tools=tools)


@app.post("/mcp/tools/call")
async def call_tool(request: ToolCallRequest) -> Dict[str, Any]:
    """Call an MCP tool."""
    try:
        if request.name == "query_sql":
            return await handle_query_sql(request.arguments)
        elif request.name == "query_graph":
            return await handle_query_graph(request.arguments)
        else:
            raise HTTPException(status_code=404, detail=f"Tool '{request.name}' not found")
    except Exception as e:
        logger.error("Tool call failed", tool=request.name, error=str(e))
        return {"success": False, "error": str(e)}


async def handle_query_sql(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Handle SQL query tool call."""
    query = arguments.get("query", "")
    rbac_context_data = arguments.get("rbac_context")

    # Parse RBAC context
    if rbac_context_data:
        rbac = RBACContext(**rbac_context_data)
    else:
        rbac = RBACContext(
            user_id="system",
            email="system@example.com",
            tenant_id="system",
            object_id="system",
            roles=["admin"],
            is_admin=True,
        )

    # Execute query
    result = await sql_service.execute_query(query, rbac)

    # Format response
    return {
        "success": getattr(result, "success", True),
        "row_count": getattr(result, "row_count", 0),
        "error": getattr(result, "error", None),
        "source": "sql",
        "query": query,
        "data": getattr(result, "data", None),
    }


async def handle_query_graph(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Handle Gremlin query tool call."""
    gremlin_query = arguments.get("gremlin_query", "")
    bindings = arguments.get("bindings", {})
    rbac_context_data = arguments.get("rbac_context")

    # Parse RBAC context
    if rbac_context_data:
        rbac = RBACContext(**rbac_context_data)
    else:
        rbac = RBACContext(
            user_id="system",
            email="system@example.com",
            tenant_id="system",
            object_id="system",
            roles=["admin"],
            is_admin=True,
        )

    # Execute query
    result = await graph_service.execute_query(gremlin_query, rbac, bindings=bindings)

    # Format response
    return {
        "success": getattr(result, "success", True),
        "row_count": getattr(result, "row_count", 0),
        "error": getattr(result, "error", None),
        "source": "gremlin",
        "query": gremlin_query,
        "bindings": bindings,
        "data": getattr(result, "data", None),
    }


if __name__ == "__main__":
    uvicorn.run(
        app,
        host=settings.api_host,
        port=settings.api_port,
        log_level=settings.log_level.lower(),
    )
