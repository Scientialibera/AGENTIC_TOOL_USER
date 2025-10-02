"""
Salesforce MCP Server with HTTP interface.

This provides HTTP endpoints that wrap MCP functionality,
making it deployable as a standalone microservice.
"""

import structlog
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../.."))

from shared.models.rbac import RBACContext
from salesforce_mcp.config.settings import settings
from salesforce_mcp.clients import FabricLakehouseClient, GremlinClient
from salesforce_mcp.services.sql_service import SQLService
from salesforce_mcp.services.graph_service import GraphService

logger = structlog.get_logger(__name__)

# Create FastAPI app
app = FastAPI(title="Salesforce MCP", version="1.0.0")

# Global service instances
sql_service: Optional[SQLService] = None
graph_service: Optional[GraphService] = None
fabric_client: Optional[FabricLakehouseClient] = None
gremlin_client: Optional[GremlinClient] = None


async def resolve_accounts(accounts_mentioned: List[str], rbac_context: RBACContext) -> List[str]:
    """
    Resolve fuzzy account names to exact account names.

    Uses the deterministic AccountResolverService_ for MVP.
    """
    if not accounts_mentioned:
        return []

    try:
        from salesforce_mcp.services.account_resolver_service import AccountResolverService_
        resolved_accounts = await AccountResolverService_.resolve_account_names(
            accounts_mentioned,
            rbac_context
        )

        resolved_names = []
        for acc in resolved_accounts:
            if hasattr(acc, 'name') and acc.name:
                resolved_names.append(acc.name)
            elif isinstance(acc, dict) and acc.get('name'):
                resolved_names.append(acc['name'])

        logger.info("Resolved accounts", input=accounts_mentioned, output=resolved_names)
        return resolved_names

    except Exception as e:
        logger.warning("Account resolution failed", error=str(e))
        return accounts_mentioned  # Fallback to original names


class ToolCallRequest(BaseModel):
    name: str
    arguments: Dict[str, Any]


class ToolListResponse(BaseModel):
    tools: List[Dict[str, Any]]


@app.on_event("startup")
async def startup():
    """Initialize services on startup."""
    global sql_service, graph_service, fabric_client, gremlin_client

    logger.info("Starting Salesforce MCP HTTP server", dev_mode=settings.dev_mode)

    # Initialize clients
    fabric_client = FabricLakehouseClient(
        lakehouse_sql_endpoint=settings.fabric_lakehouse.sql_endpoint,
        lakehouse_database=settings.fabric_lakehouse.database,
        lakehouse_workspace_id=settings.fabric_lakehouse.workspace_id,
        connection_timeout=settings.fabric_lakehouse.connection_timeout,
        dev_mode=settings.dev_mode,
    )

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

    logger.info("Salesforce MCP HTTP server initialized successfully")


@app.on_event("shutdown")
async def shutdown():
    """Cleanup on shutdown."""
    logger.info("Shutting down Salesforce MCP HTTP server")

    if fabric_client:
        await fabric_client.close()
    if gremlin_client:
        await gremlin_client.close()


@app.post("/mcp/tools/list")
async def list_tools() -> ToolListResponse:
    """List available MCP tools."""
    tools = [
        {
            "name": "query_sql",
            "description": "Execute a SQL query against the Fabric lakehouse with RBAC filtering",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "SQL query to execute"
                    },
                    "accounts_mentioned": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of account names mentioned by user (for resolution)"
                    },
                    "rbac_context": {
                        "type": "object",
                        "description": "RBAC context for access control"
                    }
                },
                "required": ["query"]
            }
        },
        {
            "name": "query_graph",
            "description": "Execute a Gremlin query against the graph database with RBAC filtering",
            "parameters": {
                "type": "object",
                "properties": {
                    "gremlin_query": {
                        "type": "string",
                        "description": "Gremlin query to execute"
                    },
                    "bindings": {
                        "type": "object",
                        "description": "Optional query parameter bindings"
                    },
                    "accounts_mentioned": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of account names mentioned by user (for resolution)"
                    },
                    "rbac_context": {
                        "type": "object",
                        "description": "RBAC context for access control"
                    }
                },
                "required": ["gremlin_query"]
            }
        }
    ]

    logger.info("Listing tools", tool_count=len(tools))
    return ToolListResponse(tools=tools)


@app.post("/mcp/tools/call")
async def call_tool(request: ToolCallRequest) -> Dict[str, Any]:
    """Handle tool execution."""
    try:
        logger.info("Tool called", tool=request.name)

        # Parse RBAC context
        rbac_context_data = request.arguments.get("rbac_context", {})
        if rbac_context_data:
            rbac = RBACContext(**rbac_context_data)
        else:
            # Default context for dev mode
            rbac = RBACContext(
                user_id="system",
                email="system@example.com",
                tenant_id="system",
                object_id="system",
                roles=["admin"],
                is_admin=True,
            )

        # Get accounts mentioned
        accounts_mentioned = request.arguments.get("accounts_mentioned", [])

        # Resolve account names (just like original chatbot)
        resolved_account_names = []
        if accounts_mentioned:
            resolved_account_names = await resolve_accounts(accounts_mentioned, rbac)

        if request.name == "query_sql":
            result = await handle_query_sql(
                request.arguments.get("query", ""),
                resolved_account_names,
                rbac
            )
        elif request.name == "query_graph":
            result = await handle_query_graph(
                request.arguments.get("gremlin_query", ""),
                request.arguments.get("bindings", {}),
                resolved_account_names,
                rbac
            )
        else:
            raise HTTPException(status_code=404, detail=f"Tool '{request.name}' not found")

        return result

    except Exception as e:
        logger.error("Tool execution failed", tool=request.name, error=str(e))
        return {"success": False, "error": str(e)}


async def handle_query_sql(
    query: str,
    resolved_account_names: List[str],
    rbac: RBACContext
) -> Dict[str, Any]:
    """
    Handle SQL query with account resolution.

    This follows the same pattern as the original chatbot:
    1. Accounts are resolved before query execution
    2. Resolved names are available for query construction
    """
    try:
        logger.info("Executing SQL query", query=query[:100], accounts=resolved_account_names)

        # Execute query (RBAC filtering happens in sql_service)
        result = await sql_service.execute_query(query, rbac)

        return {
            "success": getattr(result, "success", True),
            "row_count": getattr(result, "row_count", 0),
            "error": getattr(result, "error", None),
            "source": "sql",
            "query": query,
            "resolved_accounts": resolved_account_names,
            "data": getattr(result, "data", None),
        }

    except Exception as e:
        logger.error("SQL query failed", error=str(e))
        return {
            "success": False,
            "error": str(e),
            "source": "sql",
            "query": query,
        }


async def handle_query_graph(
    gremlin_query: str,
    bindings: Dict[str, Any],
    resolved_account_names: List[str],
    rbac: RBACContext
) -> Dict[str, Any]:
    """
    Handle Gremlin query with account resolution.

    This follows the same pattern as the original chatbot.
    """
    try:
        logger.info("Executing Gremlin query", query=gremlin_query[:100], accounts=resolved_account_names)

        # Execute query (RBAC filtering happens in graph_service)
        result = await graph_service.execute_query(gremlin_query, rbac, bindings=bindings)

        return {
            "success": getattr(result, "success", True),
            "row_count": getattr(result, "row_count", 0),
            "error": getattr(result, "error", None),
            "source": "gremlin",
            "query": gremlin_query,
            "bindings": bindings,
            "resolved_accounts": resolved_account_names,
            "data": getattr(result, "data", None),
        }

    except Exception as e:
        logger.error("Gremlin query failed", error=str(e))
        return {
            "success": False,
            "error": str(e),
            "source": "gremlin",
            "query": gremlin_query,
        }


if __name__ == "__main__":
    uvicorn.run(
        app,
        host=settings.api_host,
        port=settings.api_port,
        log_level=settings.log_level.lower(),
    )
