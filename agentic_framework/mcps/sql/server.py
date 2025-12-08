"""
SQL MCP Server for Salesforce/Fabric SQL interactions.

This MCP server executes caller-provided T-SQL with optional RBAC-aware context
and cached schema/value metadata for better hints and validation.
"""

import json
import asyncio
from typing import Dict, Any, Optional, List
from fastmcp import FastMCP
import structlog
from tenacity import RetryError

import sys
import os
# Add parent directories to path to import shared modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.config import get_settings
from shared.models import RBACContext
from shared.aoai_client import AzureOpenAIClient
from shared.fabric_client import FabricClient
from shared.cosmos_client import CosmosDBClient
from shared.account_resolver import AccountResolverService
from shared.table_discovery_service import TableDiscoveryService
from shared.value_matching_service import ValueMatchingService
from shared.auth_provider import create_auth_provider

# ============================================================================
# CONSTANTS
# ============================================================================
logger = structlog.get_logger(__name__)
settings = get_settings()

MCP_SERVER_NAME = "SQL MCP Server"
MCP_SERVER_PORT = settings.mcp.base_port + 3  # SQL MCP on base_port + 3 (default 8003)
AGENT_TYPE = "sql"  # Used to match function patterns like sql_*_function
DEFAULT_QUERY_LIMIT = 100  # Default row limit for queries
MAX_RETRY_ATTEMPTS = settings.text_to_sql.max_retry_attempts  # Self-healing retry attempts

# ============================================================================
# MAGIC VARIABLES (centralized configuration)
# ============================================================================
TRANSPORT = "http"
HOST = "0.0.0.0"
SOURCE_NAME = "sql_mcp"

# Initialize auth provider (None in dev mode, JWTVerifier in production)
auth_provider = create_auth_provider()

# Create MCP server with authentication
# In dev mode, auth_provider is None so authentication is disabled
# In production, auth_provider validates JWT tokens from Azure AD
mcp = FastMCP(MCP_SERVER_NAME, auth=auth_provider)

aoai_client: Optional[AzureOpenAIClient] = None
fabric_client: Optional[FabricClient] = None
cosmos_client: Optional[CosmosDBClient] = None
account_resolver: Optional[AccountResolverService] = None
table_discovery_service: Optional[TableDiscoveryService] = None
value_matching_service: Optional[ValueMatchingService] = None

# Caches for prompts, schema, and tool definitions
_sql_schema_cache: Optional[str] = None
_sql_schema_items_cache: Optional[List[Dict[str, Any]]] = None
_system_prompt_cache: Optional[str] = None
_agent_tools_cache: Optional[List[Dict[str, Any]]] = None
_table_metadata_cache: Optional[List[Dict[str, Any]]] = None
_value_mappings_cache: Optional[List[Dict[str, Any]]] = None
_schema_embeddings_cache: Optional[List[Dict[str, Any]]] = None
_value_embeddings_cache: Optional[List[Dict[str, Any]]] = None


async def _ensure_table_metadata_embeddings() -> None:
    """Generate missing embeddings for table and column metadata and cache them."""
    global _table_metadata_cache, _schema_embeddings_cache

    if not settings.text_to_sql.enable_embeddings:
        return

    if aoai_client is None or cosmos_client is None:
        await initialize_clients()

    if not _table_metadata_cache:
        return

    updated_items: List[Dict[str, Any]] = []

    for item in _table_metadata_cache:
        needs_upsert = False
        table_name = item.get("table_name", "")
        schema_name = item.get("schema", "dbo")
        description = item.get("description", "")

        if not item.get("embedding"):
            text = f"{schema_name}.{table_name}. {description}".strip()
            item["embedding"] = await aoai_client.generate_embedding(text or table_name)
            needs_upsert = True

        for col in item.get("columns", []):
            if not col.get("embedding"):
                col_text = f"{col.get('name', '')}. {col.get('description', '')}".strip()
                col["embedding"] = await aoai_client.generate_embedding(col_text or col.get("name", ""))
                needs_upsert = True

        if needs_upsert:
            await cosmos_client.upsert_item(settings.cosmos.table_metadata_container, item)

        updated_items.append({
            "table_name": table_name,
            "schema": schema_name,
            "embedding": item.get("embedding"),
            "columns": item.get("columns", []),
        })

    _schema_embeddings_cache = updated_items
    logger.info(
        "Schema embeddings ensured",
        table_count=len(_schema_embeddings_cache or []),
    )


async def _ensure_value_embeddings() -> None:
    """Generate missing embeddings for low-cardinality values and cache them."""
    global _value_mappings_cache, _value_embeddings_cache

    if not settings.text_to_sql.enable_embeddings:
        return

    if aoai_client is None or cosmos_client is None:
        await initialize_clients()

    if not _value_mappings_cache:
        return

    updated_items: List[Dict[str, Any]] = []

    for item in _value_mappings_cache:
        needs_upsert = False
        for value_entry in item.get("values", []):
            if not value_entry.get("embedding"):
                value_text = value_entry.get("value", "")
                value_entry["embedding"] = await aoai_client.generate_embedding(value_text)
                needs_upsert = True

        if needs_upsert:
            await cosmos_client.upsert_item(settings.cosmos.value_mappings_container, item)

        updated_items.append(item)

    _value_embeddings_cache = updated_items
    logger.info(
        "Value embeddings ensured",
        mapping_count=len(_value_embeddings_cache or []),
    )


async def ensure_embedding_caches() -> None:
    """Ensure embedding caches are populated for tables and value catalogs."""
    try:
        await _ensure_table_metadata_embeddings()
    except Exception as e:
        logger.warning("Table embedding preload failed", error=str(e))

    try:
        await _ensure_value_embeddings()
    except Exception as e:
        logger.warning("Value embedding preload failed", error=str(e))


def _builtin_tool_definitions() -> List[Dict[str, Any]]:
    """Fallback tool definitions when Cosmos metadata is unavailable."""
    return [
        {
            "type": "function",
            "function": {
                "name": "sql_query",
                "description": "Execute a provided T-SQL query against Azure SQL. Caller MUST supply valid T-SQL (use TOP instead of LIMIT; bracket reserved identifiers like [Case]).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "T-SQL statement to execute (SELECT-only).",
                        },
                        "value_mappings": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "table": {"type": "string"},
                                    "column": {"type": "string"},
                                    "user_value": {"type": "string"},
                                    "matched_value": {"type": "string"},
                                },
                                "required": ["table", "column", "user_value", "matched_value"],
                            },
                            "description": "Optional array of value mappings for low-cardinality columns. Each mapping resolves a user-provided value to its exact database value.",
                        },
                        "accounts_mentioned": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Optional account names referenced in the request (metadata only).",
                        },
                        "rbac_context": {
                            "type": "object",
                            "description": "Optional RBAC context (e.g., user email).",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Optional row cap; if provided and query lacks TOP, enforce using TOP <limit>.",
                            "default": DEFAULT_QUERY_LIMIT,
                        },
                    },
                    "required": ["query"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_tables",
                "description": "List available tables from cached schema metadata.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_columns",
                "description": "List columns for a given table name using schema metadata.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "table": {
                            "type": "string",
                            "description": "Table name to describe.",
                        }
                    },
                    "required": ["table"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_schema",
                "description": "Return full schema text plus table/column map.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
    ]


async def initialize_clients():
    """Initialize all required clients."""
    global aoai_client, fabric_client, cosmos_client, account_resolver
    global table_discovery_service, value_matching_service
    
    if aoai_client is None:
        aoai_client = AzureOpenAIClient(settings.aoai)
    if fabric_client is None:
        fabric_client = FabricClient(settings.fabric, sql_settings=settings.azure_sql)
    if cosmos_client is None:
        cosmos_client = CosmosDBClient(settings.cosmos)
    if account_resolver is None:
        account_resolver = AccountResolverService(
            fabric_client=fabric_client,
            dev_mode=settings.dev_mode
        )
    if table_discovery_service is None:
        table_discovery_service = TableDiscoveryService(cosmos_client, aoai_client)
    if value_matching_service is None:
        value_matching_service = ValueMatchingService(cosmos_client, aoai_client)
    
    logger.info("SQL MCP Server clients initialized")
    await preload_metadata()


async def get_sql_schema() -> str:
    """Load SQL schema from Cosmos DB."""
    global _sql_schema_cache, _sql_schema_items_cache

    # Return cached schema if available
    if _sql_schema_cache is not None:
        logger.debug("Returning cached SQL schema")
        return _sql_schema_cache

    try:
        if cosmos_client is None:
            await initialize_clients()

        logger.info("Loading SQL schema from Cosmos (cache miss)")
        items = await cosmos_client.query_items(
            container_name=SQL_SCHEMA_CONTAINER,
            query="SELECT * FROM c",
        )

        # Cache raw items for other tools
        _sql_schema_items_cache = items

        if not items:
            return "No schema available"

        schema_parts = []
        for item in items:
            table_name = item.get("table_name", "unknown")
            columns = item.get("columns", [])
            schema_parts.append(f"Table: {table_name}\nColumns: {', '.join(columns)}")

        schema = "\n\n".join(schema_parts)

        # Cache the schema
        _sql_schema_cache = schema
        logger.info("SQL schema loaded and cached", table_count=len(items))
        return schema
    except Exception as e:
        logger.error("Failed to load SQL schema", error=str(e))
        return "Schema unavailable"


async def preload_metadata():
    """Preload schema and related metadata into memory on startup."""
    global _table_metadata_cache, _value_mappings_cache

    try:
        await get_sql_schema()
    except Exception as e:
        logger.warning("Schema preload failed", error=str(e))

    # Preload table metadata (if available)
    try:
        if cosmos_client is None:
            await initialize_clients()
        _table_metadata_cache = await cosmos_client.query_items(
            container_name=settings.cosmos.table_metadata_container,
            query="SELECT * FROM c",
        )
        logger.info(
            "Loaded table metadata",
            item_count=len(_table_metadata_cache or []),
            container=settings.cosmos.table_metadata_container,
        )
    except Exception as e:
        logger.warning(
            "Table metadata preload failed",
            error=str(e),
            container=getattr(settings.cosmos, "table_metadata_container", "table_metadata"),
        )

    # Preload low-cardinality value mappings (if available)
    try:
        if cosmos_client is None:
            await initialize_clients()
        _value_mappings_cache = await cosmos_client.query_items(
            container_name=settings.cosmos.value_mappings_container,
            query="SELECT * FROM c",
        )
        logger.info(
            "Loaded value mappings",
            item_count=len(_value_mappings_cache or []),
            container=settings.cosmos.value_mappings_container,
        )
    except Exception as e:
        logger.warning(
            "Value mappings preload failed",
            error=str(e),
            container=getattr(settings.cosmos, "value_mappings_container", "value_mappings"),
        )

    # Ensure embeddings are present for table metadata and value catalogs
    try:
        await ensure_embedding_caches()
    except Exception as e:
        logger.warning("Embedding cache warmup failed", error=str(e))


async def get_schema_items() -> List[Dict[str, Any]]:
    """Return schema items as a list of dicts with table_name and columns."""
    global _sql_schema_items_cache

    if _sql_schema_items_cache is not None:
        return _sql_schema_items_cache

    # Populate via get_sql_schema (which will set the cache)
    await get_sql_schema()
    return _sql_schema_items_cache or []


async def get_system_prompt(rbac_context: Optional[Dict[str, Any]] = None) -> str:
    """Get SQL agent system prompt with schema from Cosmos DB.

    Raises:
        Exception: If prompt cannot be loaded from Cosmos DB
    """
    global _system_prompt_cache

    # Load base prompt from cache or Cosmos with a safe default fallback
    if _system_prompt_cache is None:
        base_prompt = DEFAULT_SYSTEM_PROMPT

        if cosmos_client is None:
            await initialize_clients()

        try:
            logger.info("Loading system prompt from Cosmos (cache miss)", prompt_id=PROMPT_ID)
            prompt_items = await cosmos_client.query_items(
                container_name=settings.cosmos.prompts_container,
                query="SELECT * FROM c WHERE c.id = @prompt_id",
                parameters=[{"name": "@prompt_id", "value": PROMPT_ID}],
            )

            if prompt_items:
                candidate = prompt_items[0].get("content", "")
                if candidate:
                    base_prompt = candidate
                    logger.info("System prompt loaded and cached", prompt_id=PROMPT_ID)
                else:
                    logger.warning("Prompt content empty, using default prompt", prompt_id=PROMPT_ID)
            else:
                logger.warning(
                    "Prompt not found in Cosmos, using default prompt",
                    prompt_id=PROMPT_ID,
                    container=settings.cosmos.prompts_container,
                )
        except Exception as e:
            logger.warning("Falling back to default system prompt", error=str(e))

        _system_prompt_cache = base_prompt
    else:
        logger.debug("Using cached system prompt")

    # Get schema (also cached)
    schema = await get_sql_schema()
    prompt = f"{_system_prompt_cache}\n\n## Database Schema\n{schema}"

    # Add RBAC context if provided (not cached since it's user-specific)
    if rbac_context:
        user_email = rbac_context.get("email", "")
        prompt += f"\n\n## RBAC Context\nUser: {user_email}\nImportant: Add WHERE clause to filter by user access (e.g., WHERE owner_email = '{user_email}' or assigned_to = '{user_email}')"

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

    tools: List[Dict[str, Any]] = []

    logger.info("Loading agent tools from Cosmos (cache miss)", agent_type=AGENT_TYPE)
    try:
        tool_items = await cosmos_client.query_items(
            container_name=settings.cosmos.agent_functions_container,
            query=f"SELECT * FROM c WHERE STARTSWITH(c.id, @prefix) AND ENDSWITH(c.id, '_function')",
            parameters=[{"name": "@prefix", "value": f"{AGENT_TYPE}_"}],
        )
    except Exception as e:
        logger.warning(
            "Failed to load tools from Cosmos, using built-in defaults",
            error=str(e),
            container=settings.cosmos.agent_functions_container,
        )
        tools = _builtin_tool_definitions()
        _agent_tools_cache = tools
        return tools

    if not tool_items:
        logger.warning(
            "No tool definitions found in Cosmos, using built-in defaults",
            agent_type=AGENT_TYPE,
            container=settings.cosmos.agent_functions_container,
        )
        tools = _builtin_tool_definitions()
    else:
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
    logger.info(
        f"Loaded and cached {len(tools)} tool(s) for agent type '{AGENT_TYPE}'",
        tool_names=[t["function"]["name"] for t in tools],
    )

    return tools


async def resolve_accounts(
    account_names: List[str]
) -> List[Dict[str, Any]]:
    """Resolve account names to IDs using fuzzy matching."""
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


async def retry_with_llm_feedback(
    original_query: str,
    error_message: str,
    attempt: int,
    system_prompt: str,
    tools: List[Dict[str, Any]],
    previous_sql: Optional[str] = None
) -> Optional[str]:
    """
    Ask the LLM to fix the SQL query based on the error message.
    
    Args:
        original_query: The original natural language query
        error_message: The error from the failed SQL execution
        attempt: Current retry attempt number
        system_prompt: System prompt for the LLM
        tools: Tool definitions for function calling
        previous_sql: The SQL that failed
        
    Returns:
        Corrected SQL query or None if LLM couldn't fix it
    """
    logger.info("SELF-HEALING RETRY", attempt=attempt, error_preview=error_message[:100])
    
    feedback_message = f"""The previous SQL query failed with this error:

ERROR: {error_message}

Previous SQL: {previous_sql}

Original request: {original_query}

Please analyze the error and generate a CORRECTED SQL query that fixes the issue. Common fixes:
- Fix table/column names if they don't exist
- Adjust syntax for the SQL dialect
- Fix data type mismatches
- Correct JOIN conditions
- Fix aggregation or GROUP BY clauses"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": feedback_message},
    ]
    
    try:
        response = await aoai_client.create_chat_completion(
            messages=messages,
            tools=tools,
            tool_choice="required"
        )
        
        assistant_message = response["choices"][0]["message"]
        
        # Extract the corrected SQL
        function_call = None
        if assistant_message.get("tool_calls"):
            function_call = assistant_message["tool_calls"][0].get("function")
        elif assistant_message.get("function_call"):
            function_call = assistant_message["function_call"]
        
        if not function_call:
            logger.error("LLM didn't return a corrected query")
            return None
            
        args = json.loads(function_call.get("arguments", "{}"))
        corrected_sql = args.get("query", "")
        
        logger.info("LLM generated corrected SQL", query_preview=corrected_sql[:100])
        return corrected_sql
        
    except Exception as e:
        logger.error("Failed to get LLM correction", error=str(e))
        return None


async def _build_table_hints(user_query: str) -> List[str]:
    """Return a concise list of relevant tables using embeddings (with fallback to cached metadata)."""
    if not settings.text_to_sql.enable_table_discovery:
        return []

    hints: List[str] = []

    try:
        if table_discovery_service is None:
            await initialize_clients()

        tables = await table_discovery_service.discover_tables(
            user_query,
            max_tables=settings.text_to_sql.max_tables_per_query,
        )

        for table in tables:
            col_names = [col.name for col in (table.columns or [])][:8]
            hints.append(f"{table.schema}.{table.table_name} (cols: {', '.join(col_names)})")

        if hints:
            return hints
    except Exception as e:
        logger.warning("Table discovery failed, falling back to cached metadata", error=str(e))

    # Fallback: use cached metadata when discovery fails or returns nothing
    if _table_metadata_cache:
        for item in _table_metadata_cache[: settings.text_to_sql.max_tables_per_query]:
            cols = [col.get("name", "") for col in item.get("columns", [])][:8]
            hints.append(f"{item.get('schema', 'dbo')}.{item.get('table_name', 'unknown')} (cols: {', '.join(cols)})")

    return hints


def _build_value_hints(max_items: int = 5, max_values: int = 6) -> List[str]:
    """Return low-cardinality value hints to keep the LLM on canonical values."""
    if not settings.text_to_sql.enable_value_matching:
        return []

    hints: List[str] = []
    for item in (_value_mappings_cache or [])[:max_items]:
        values = [val.get("value", "") for val in item.get("values", [])][:max_values]
        if not values:
            continue
        hints.append(f"{item.get('table')}.{item.get('column')}: {', '.join(values)}")

    return hints


@mcp.tool()
async def sql_query(
    query: str,
    limit: int = DEFAULT_QUERY_LIMIT,
    request: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Execute T-SQL SELECT query against Azure SQL with automatic value matching.

    The MCP automatically corrects casing for low-cardinality column values by matching
    them against the value_mappings cache in Cosmos DB. For example, 'closed won' will
    be automatically corrected to 'Closed Won' before query execution.

    Args:
        query: T-SQL SELECT statement. Use natural language values - they will be auto-corrected.
               Use TOP instead of LIMIT. Bracket reserved identifiers (e.g., [Case]).
        limit: Maximum number of rows to return
        request: FastAPI Request object (injected by FastMCP for authentication)

    Returns:
        Dictionary with query results, including success status, data, and metadata
    """
    # Verify JWT token from request
    from shared.auth_provider import verify_token_from_request
    if request:
        try:
            await verify_token_from_request(request)
            logger.debug("SQL MCP request authenticated")
        except Exception as e:
            logger.error("SQL MCP authentication failed", error=str(e))
            return {
                "success": False,
                "error": f"Authentication failed: {str(e)}",
                "data": []
            }
    else:
        logger.warning("No request object provided - skipping authentication")

    import time
    start_time = time.time()

    try:
        await initialize_clients()

        logger.info("SQL QUERY RECEIVED", query=query[:200], limit=limit)

        # Basic safety: only allow SELECT queries
        if not query.strip().lower().startswith("select"):
            return {
                "success": False,
                "error": "Only SELECT statements are allowed",
                "query": query,
            }

        # Automatically apply value matching using cached value_mappings from Cosmos
        sql_to_run = query
        if settings.text_to_sql.enable_value_matching and _value_mappings_cache:
            logger.info("Auto-matching values from cache", cached_mappings=len(_value_mappings_cache))

            for value_map_item in _value_mappings_cache:
                table = value_map_item.get("table", "")
                column = value_map_item.get("column", "")
                values = value_map_item.get("values", [])

                for value_obj in values:
                    db_value = value_obj.get("value", "")
                    if not db_value:
                        continue

                    # Try matching lowercase and mixed case variants
                    user_variants = [
                        db_value.lower(),
                        db_value.title(),
                        db_value,
                    ]

                    for user_val in user_variants:
                        if user_val == db_value:
                            continue  # Skip if already exact match

                        # Replace user value with exact database value
                        replacements = [
                            (f"'{user_val}'", f"'{db_value}'"),
                            (f'"{user_val}"', f'"{db_value}"'),
                        ]

                        for old, new in replacements:
                            if old in sql_to_run:
                                sql_to_run = sql_to_run.replace(old, new)
                                logger.info(
                                    "Auto-corrected value",
                                    table=table,
                                    column=column,
                                    user_value=user_val,
                                    db_value=db_value,
                                )
        else:
            logger.debug("Value matching disabled or no mappings cached")

        # Enforce TOP if user provided a limit and no TOP is present
        if limit and " top " not in sql_to_run.lower() and "top(" not in sql_to_run.lower():
            # naive inject after SELECT
            sql_to_run = sql_to_run.replace("SELECT", f"SELECT TOP {int(limit)}", 1)

        results = None
        last_error = None

        for attempt in range(1, MAX_RETRY_ATTEMPTS + 1):
            try:
                logger.info("EXECUTING SQL QUERY", query=sql_to_run[:200], attempt=attempt)
                sql_start = time.time()
                results = await fabric_client.execute_query(sql_to_run)
                sql_elapsed = int((time.time() - sql_start) * 1000)
                logger.info("SQL QUERY COMPLETE", duration_ms=sql_elapsed, row_count=len(results), attempt=attempt)
                break
            except Exception as sql_error:
                last_error = str(sql_error)
                logger.warning(
                    "SQL execution failed",
                    attempt=attempt,
                    max_attempts=MAX_RETRY_ATTEMPTS,
                    error=last_error[:200],
                )
                if attempt >= MAX_RETRY_ATTEMPTS:
                    raise

        if results is None:
            raise Exception(f"SQL execution failed after {MAX_RETRY_ATTEMPTS} attempts: {last_error}")

        total_elapsed = int((time.time() - start_time) * 1000)
        logger.info("SQL QUERY SUCCESS", row_count=len(results), duration_ms=total_elapsed)

        return {
            "success": True,
            "query": sql_to_run,
            "row_count": len(results),
            "data": results,
            "source": "azure_sql" if not settings.dev_mode else "mock_sql",
        }

    except RetryError as e:
        total_elapsed = int((time.time() - start_time) * 1000)
        root_err = str(getattr(e.last_attempt, "exception", lambda: e)()) if getattr(e, "last_attempt", None) else str(e)
        logger.error("SQL TOOL FAILED (retry)", error=root_err, total_duration_ms=total_elapsed)
        return {
            "success": False,
            "error": root_err,
            "query": query,
        }
    except Exception as e:
        total_elapsed = int((time.time() - start_time) * 1000)
        logger.error("SQL TOOL FAILED", error=str(e), total_duration_ms=total_elapsed)
        return {
            "success": False,
            "error": str(e),
            "query": query,
        }


@mcp.tool()
async def list_tables() -> Dict[str, Any]:
    """List available tables from cached schema metadata."""
    try:
        await initialize_clients()
        items = await get_schema_items()
        tables = [item.get("table_name", "unknown") for item in items]
        return {"success": True, "tables": tables}
    except Exception as e:
        logger.error("Failed to list tables", error=str(e))
        return {"success": False, "error": str(e)}


@mcp.tool()
async def list_columns(table: str) -> Dict[str, Any]:
    """List columns for a given table name using schema metadata."""
    try:
        await initialize_clients()
        items = await get_schema_items()
        for item in items:
            if item.get("table_name") == table:
                return {
                    "success": True,
                    "table": table,
                    "columns": item.get("columns", []),
                }
        return {"success": False, "error": f"Table '{table}' not found"}
    except Exception as e:
        logger.error("Failed to list columns", table=table, error=str(e))
        return {"success": False, "error": str(e)}


@mcp.tool()
async def get_schema() -> Dict[str, Any]:
    """Return full schema as text plus table/column map."""
    try:
        await initialize_clients()
        schema_text = await get_sql_schema()
        items = await get_schema_items()
        table_map = {item.get("table_name", "unknown"): item.get("columns", []) for item in items}
        return {
            "success": True,
            "schema": schema_text,
            "tables": table_map,
        }
    except Exception as e:
        logger.error("Failed to get schema", error=str(e))
        return {"success": False, "error": str(e)}


def _get_dummy_sql_data(query: str, limit: int = 100) -> List[Dict[str, Any]]:
    """Generate dummy SQL data for dev mode. Returns ALL data from all tables."""
    # Always return a comprehensive dataset combining accounts, contacts, and opportunities
    all_data = [
        # Accounts
        {
            "table": "accounts",
            "id": "1",
            "name": "Microsoft Corporation",
            "category": "Enterprise",
            "industry": "Technology",
            "address": "One Microsoft Way, Redmond, WA 98052",
            "notes": "Strategic partner for cloud solutions. Previous projects: AI Chatbot PoC (2023), Fabric Deployment (2024).",
        },
        {
            "table": "accounts",
            "id": "2",
            "name": "Salesforce Inc",
            "category": "Enterprise",
            "industry": "CRM Software",
            "address": "415 Mission Street, San Francisco, CA 94105",
            "notes": "Long-term customer. Recent engagement: Service Chatbot Rollout (2023). Interested in Dynamics integration.",
        },
        {
            "table": "accounts",
            "id": "3",
            "name": "Google LLC",
            "category": "Strategic",
            "industry": "Technology",
            "address": "1600 Amphitheatre Parkway, Mountain View, CA 94043",
            "notes": "New customer as of 2024. Potential for large-scale chatbot deployment.",
        },
        {
            "table": "accounts",
            "id": "4",
            "name": "Oracle Corporation",
            "category": "Enterprise",
            "industry": "Enterprise Software",
            "address": "2300 Oracle Way, Austin, TX 78741",
            "notes": "Data migration project in progress. Looking for additional database modernization opportunities.",
        },
        {
            "table": "accounts",
            "id": "5",
            "name": "SAP SE",
            "category": "Mid-Market",
            "industry": "ERP Software",
            "address": "3999 West Chester Pike, Newtown Square, PA 19073",
            "notes": "Completed Fabric PoV in 2023. Exploring field service chatbot solutions.",
        },
        {
            "table": "accounts",
            "id": "6",
            "name": "Amazon Web Services",
            "category": "Competitor",
            "industry": "Cloud Computing",
            "address": "410 Terry Avenue North, Seattle, WA 98109",
            "notes": "Competitor relationship. Previous internal helpdesk bot project (2022).",
        },
        # Contacts
        {
            "table": "contacts",
            "account_id": "1",
            "account_name": "Microsoft Corporation",
            "first_name": "Sarah",
            "last_name": "Chen",
            "email": "sarah.chen@microsoft.com",
            "title": "VP of Digital Transformation",
        },
        {
            "table": "contacts",
            "account_id": "1",
            "account_name": "Microsoft Corporation",
            "first_name": "Michael",
            "last_name": "Rodriguez",
            "email": "mrodriguez@microsoft.com",
            "title": "Director of AI Solutions",
        },
        {
            "table": "contacts",
            "account_id": "2",
            "account_name": "Salesforce Inc",
            "first_name": "Jennifer",
            "last_name": "Martinez",
            "email": "jmartinez@salesforce.com",
            "title": "VP of Customer Success",
        },
        {
            "table": "contacts",
            "account_id": "2",
            "account_name": "Salesforce Inc",
            "first_name": "David",
            "last_name": "Kim",
            "email": "dkim@salesforce.com",
            "title": "Senior Solutions Architect",
        },
        {
            "table": "contacts",
            "account_id": "3",
            "account_name": "Google LLC",
            "first_name": "Emily",
            "last_name": "Thompson",
            "email": "ethompson@google.com",
            "title": "Head of Customer Support Engineering",
        },
        {
            "table": "contacts",
            "account_id": "4",
            "account_name": "Oracle Corporation",
            "first_name": "Robert",
            "last_name": "Anderson",
            "email": "randerson@oracle.com",
            "title": "Chief Data Officer",
        },
        {
            "table": "contacts",
            "account_id": "5",
            "account_name": "SAP SE",
            "first_name": "Lisa",
            "last_name": "Patel",
            "email": "lpatel@sap.com",
            "title": "Director of Innovation",
        },
        # Opportunities
        {
            "table": "opportunities",
            "account_id": "1",
            "account_name": "Microsoft Corporation",
            "opportunity_name": "Teams Integration Chatbot",
            "amount": 450000.0,
            "stage": "Proposal",
            "close_date": "2025-03-15",
            "probability": 75,
        },
        {
            "table": "opportunities",
            "account_id": "1",
            "account_name": "Microsoft Corporation",
            "opportunity_name": "Azure OpenAI Service Expansion",
            "amount": 320000.0,
            "stage": "Negotiation",
            "close_date": "2025-02-28",
            "probability": 80,
        },
        {
            "table": "opportunities",
            "account_id": "2",
            "account_name": "Salesforce Inc",
            "opportunity_name": "Dynamics 365 Integration Phase 2",
            "amount": 280000.0,
            "stage": "Closed Won",
            "close_date": "2024-12-15",
            "probability": 100,
        },
        {
            "table": "opportunities",
            "account_id": "2",
            "account_name": "Salesforce Inc",
            "opportunity_name": "Service Cloud AI Assistant",
            "amount": 195000.0,
            "stage": "Qualification",
            "close_date": "2025-04-30",
            "probability": 50,
        },
        {
            "table": "opportunities",
            "account_id": "3",
            "account_name": "Google LLC",
            "opportunity_name": "Multilingual Support Chatbot",
            "amount": 580000.0,
            "stage": "Proposal",
            "close_date": "2025-03-31",
            "probability": 70,
        },
        {
            "table": "opportunities",
            "account_id": "4",
            "account_name": "Oracle Corporation",
            "opportunity_name": "Database Migration Consulting",
            "amount": 420000.0,
            "stage": "Discovery",
            "close_date": "2025-05-15",
            "probability": 40,
        },
        {
            "table": "opportunities",
            "account_id": "5",
            "account_name": "SAP SE",
            "opportunity_name": "Field Service Chatbot Deployment",
            "amount": 240000.0,
            "stage": "Proposal",
            "close_date": "2025-02-15",
            "probability": 65,
        },
        {
            "table": "opportunities",
            "account_id": "5",
            "account_name": "SAP SE",
            "opportunity_name": "Microsoft Fabric Analytics Platform",
            "amount": 175000.0,
            "stage": "Closed Won",
            "close_date": "2024-11-30",
            "probability": 100,
        },
    ]

    return all_data[:limit]


if __name__ == "__main__":
    import os

    logger.info("=" * 80)
    logger.info(f"{MCP_SERVER_NAME} STARTING")
    logger.info("=" * 80)
    logger.info("Server Configuration",
                host=HOST,
                port=MCP_SERVER_PORT,
                transport=TRANSPORT)
    logger.info("Authentication",
                auth_enabled=not settings.bypass_token,
                tenant_id=settings.azure_tenant_id if settings.azure_tenant_id else "N/A")
    logger.info("RBAC Configuration",
                rbac_enabled=settings.rbac.enabled,
                check_role=settings.rbac.check_role,
                required_role=settings.rbac.required_role if settings.rbac.check_role else "N/A",
                enforcement_mode=settings.rbac.enforcement_mode)
    logger.info("Text-to-SQL Features",
                auto_value_matching=settings.text_to_sql.enable_value_matching,
                table_discovery=settings.text_to_sql.enable_table_discovery,
                embeddings=settings.text_to_sql.enable_embeddings)
    logger.info("Available Tools",
                tool_count=4,
                tools=["sql_query", "list_tables", "list_columns", "get_schema"])
    logger.info("Database Connection",
                azure_sql_enabled=settings.azure_sql.enabled,
                server=settings.azure_sql.server if settings.azure_sql.enabled else "N/A",
                database=settings.azure_sql.database if settings.azure_sql.enabled else "N/A")
    logger.info("=" * 80)
    logger.info(f"{MCP_SERVER_NAME} READY - Listening on {HOST}:{MCP_SERVER_PORT}")
    logger.info("=" * 80)

    # Run the MCP server with explicit port configuration
    mcp.run(transport=TRANSPORT, port=MCP_SERVER_PORT, host=HOST)
