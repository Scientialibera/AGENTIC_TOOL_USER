"""
Salesforce MCP Server implementation using FastMCP.

This module implements an MCP server that provides SQL and Graph query tools
for accessing Salesforce data from Microsoft Fabric lakehouse and Cosmos DB Gremlin.
"""

import json
import structlog
from typing import Dict, Any, Optional
from fastmcp import FastMCP

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../.."))

from shared.models.rbac import RBACContext
from salesforce_mcp.config.settings import settings
from salesforce_mcp.clients import FabricLakehouseClient, GremlinClient
from salesforce_mcp.services import SQLService, GraphService, AccountResolverService

logger = structlog.get_logger(__name__)

# Initialize FastMCP server
mcp = FastMCP("Salesforce MCP")

# Global service instances (initialized on startup)
sql_service: Optional[SQLService] = None
graph_service: Optional[GraphService] = None
account_resolver: Optional[AccountResolverService] = None


@mcp.tool()
async def query_sql(
    query: str,
    rbac_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Execute a SQL query against the Fabric lakehouse.

    Args:
        query: SQL query to execute
        rbac_context: RBAC context for access control

    Returns:
        Query results with row count and data
    """
    global sql_service

    logger.info("Executing SQL query", query=query[:100])

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

    except Exception as e:
        logger.error("SQL query failed", error=str(e))
        return {
            "success": False,
            "error": str(e),
            "row_count": 0,
            "source": "sql",
            "query": query,
        }


@mcp.tool()
async def query_graph(
    gremlin_query: str,
    bindings: Optional[Dict[str, Any]] = None,
    rbac_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Execute a Gremlin query against the graph database.

    Args:
        gremlin_query: Gremlin query to execute
        bindings: Optional query parameter bindings
        rbac_context: RBAC context for access control

    Returns:
        Query results with row count and data
    """
    global graph_service

    logger.info("Executing Gremlin query", query=gremlin_query[:100])

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

        # Execute query
        result = await graph_service.execute_query(
            gremlin_query,
            rbac,
            bindings=bindings or {}
        )

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

    except Exception as e:
        logger.error("Gremlin query failed", error=str(e))
        return {
            "success": False,
            "error": str(e),
            "row_count": 0,
            "source": "gremlin",
            "query": gremlin_query,
        }


@mcp.tool()
async def resolve_account(
    account_name: str,
    rbac_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Resolve a fuzzy account name to exact account IDs.

    Args:
        account_name: Fuzzy account name to resolve
        rbac_context: RBAC context for access control

    Returns:
        Resolved account information
    """
    global account_resolver

    logger.info("Resolving account", account_name=account_name)

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

        # Resolve account (using the deterministic resolver for now)
        from salesforce_mcp.services.account_resolver_service import AccountResolverService_
        accounts = await AccountResolverService_.resolve_account_names([account_name], rbac)

        # Format response
        return {
            "success": True,
            "account_name": account_name,
            "resolved_accounts": [
                {
                    "id": getattr(acc, "id", None) if hasattr(acc, "id") else acc.get("id"),
                    "name": getattr(acc, "name", None) if hasattr(acc, "name") else acc.get("name"),
                    "confidence": getattr(acc, "confidence", 1.0) if hasattr(acc, "confidence") else acc.get("confidence", 1.0),
                }
                for acc in accounts
            ],
        }

    except Exception as e:
        logger.error("Account resolution failed", error=str(e))
        return {
            "success": False,
            "error": str(e),
            "account_name": account_name,
        }


# Startup and shutdown hooks
@mcp.lifespan()
async def lifespan():
    """Initialize and cleanup services."""
    global sql_service, graph_service, account_resolver

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
    # In dev mode, services can work with None dependencies
    sql_service = SQLService(
        aoai_client=None,  # Not needed for basic queries
        schema_repository=None,  # Not needed for basic queries
        unified_data_service=None,  # Not needed for basic queries
        telemetry_service=None,  # Not needed for basic queries
        settings=settings.fabric_lakehouse,
        dev_mode=settings.dev_mode,
    )

    graph_service = GraphService(
        gremlin_client=gremlin_client,
        dev_mode=settings.dev_mode,
    )

    logger.info("Salesforce MCP started successfully")

    yield

    # Cleanup
    logger.info("Shutting down Salesforce MCP")

    if fabric_client:
        await fabric_client.close()

    if gremlin_client:
        await gremlin_client.close()

    logger.info("Salesforce MCP shutdown complete")
