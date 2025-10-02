"""
Salesforce MCP Server using FastMCP.

This implements a proper MCP server using the FastMCP framework
with account resolution logic from the original chatbot.
"""

import structlog
from typing import Optional, List, Dict, Any
from mcp.server.fastmcp import FastMCP

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../.."))

from shared.models.rbac import RBACContext
from salesforce_mcp.config.settings import settings
from salesforce_mcp.clients import FabricLakehouseClient, GremlinClient
from salesforce_mcp.services.sql_service import SQLService
from salesforce_mcp.services.graph_service import GraphService

logger = structlog.get_logger(__name__)

# Create FastMCP server
mcp = FastMCP(
    name="salesforce-mcp",
    instructions="Salesforce data access MCP with SQL and Graph query capabilities",
    host=settings.api_host,
    port=settings.api_port,
)

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


@mcp.tool()
async def query_sql(
    query: str,
    accounts_mentioned: List[str] = None,
    rbac_context: Dict[str, Any] = None
) -> Dict[str, Any]:
    """
    Execute a SQL query against the Fabric lakehouse with RBAC filtering.

    Args:
        query: SQL query to execute
        accounts_mentioned: List of account names mentioned by user (for resolution)
        rbac_context: RBAC context for access control

    Returns:
        Query results with row count and data
    """
    try:
        # Parse RBAC context
        if rbac_context:
            rbac = RBACContext(**rbac_context)
        else:
            rbac = RBACContext(
                user_id="system",
                email="system@example.com",
                tenant_id="system",
                object_id="system",
                roles=["admin"],
                is_admin=True,
            )

        # Resolve account names (just like original chatbot)
        resolved_account_names = []
        if accounts_mentioned:
            resolved_account_names = await resolve_accounts(accounts_mentioned, rbac)

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


@mcp.tool()
async def query_graph(
    gremlin_query: str,
    bindings: Dict[str, Any] = None,
    accounts_mentioned: List[str] = None,
    rbac_context: Dict[str, Any] = None
) -> Dict[str, Any]:
    """
    Execute a Gremlin query against the graph database with RBAC filtering.

    Args:
        gremlin_query: Gremlin query to execute
        bindings: Optional query parameter bindings
        accounts_mentioned: List of account names mentioned by user (for resolution)
        rbac_context: RBAC context for access control

    Returns:
        Query results with row count and data
    """
    try:
        # Parse RBAC context
        if rbac_context:
            rbac = RBACContext(**rbac_context)
        else:
            rbac = RBACContext(
                user_id="system",
                email="system@example.com",
                tenant_id="system",
                object_id="system",
                roles=["admin"],
                is_admin=True,
            )

        # Resolve account names
        resolved_account_names = []
        if accounts_mentioned:
            resolved_account_names = await resolve_accounts(accounts_mentioned, rbac)

        logger.info("Executing Gremlin query", query=gremlin_query[:100], accounts=resolved_account_names)

        # Execute query (RBAC filtering happens in graph_service)
        result = await graph_service.execute_query(
            gremlin_query,
            rbac,
            bindings=bindings or {}
        )

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


@mcp.run()
async def main():
    """Initialize services when MCP server starts."""
    global sql_service, graph_service, fabric_client, gremlin_client

    logger.info("Starting Salesforce MCP with FastMCP", dev_mode=settings.dev_mode)

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

    logger.info("Salesforce MCP initialized successfully")


if __name__ == "__main__":
    mcp.run(transport="http", port=settings.api_port, host=settings.api_host)
