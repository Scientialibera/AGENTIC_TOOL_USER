"""
SQL MCP Server for Salesforce/Fabric SQL interactions.

This MCP server provides SQL query capabilities with intelligent query
generation using an internal LLM and RBAC-based row-level security.
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
from shared.models import RBACContext, SchemaMetadata, QueryPlan, FilterCondition
from shared.aoai_client import AzureOpenAIClient
from shared.fabric_client import FabricClient
from shared.sql_client import SqlClient
from shared.cosmos_client import CosmosDBClient
from shared.account_resolver import AccountResolverService
from shared.auth_provider import create_auth_provider

# ============================================================================
# CONSTANTS
# ============================================================================
MCP_SERVER_NAME = "SQL MCP Server"
MCP_SERVER_PORT = int(os.getenv("MCP_PORT", "8003"))  # Server port (from env or default 8003)
PROMPT_ID = "sql_agent_system"
AGENT_TYPE = "sql"  # Used to match function patterns like sql_*_function
SQL_SCHEMA_CONTAINER = "sql_schema"  # Container name for SQL schema metadata
DEFAULT_QUERY_LIMIT = 100
MAX_RETRY_ATTEMPTS = int(os.getenv("MCP_MAX_RETRIES", "3"))  # Self-healing retry attempts

# ============================================================================
# MAGIC VARIABLES (centralized configuration)
# ============================================================================
TRANSPORT = "http"
HOST = "0.0.0.0"
SOURCE_NAME = "sql_mcp"

logger = structlog.get_logger(__name__)

settings = get_settings()

# Initialize auth provider (None in dev mode, JWTVerifier in production)
auth_provider = create_auth_provider()

# Create MCP server with authentication
# In dev mode, auth_provider is None so authentication is disabled
# In production, auth_provider validates JWT tokens from Azure AD
mcp = FastMCP(MCP_SERVER_NAME, auth=auth_provider)

aoai_client: Optional[AzureOpenAIClient] = None
fabric_client: Optional[FabricClient] = None
sql_client: Optional[SqlClient] = None
cosmos_client: Optional[CosmosDBClient] = None
account_resolver: Optional[AccountResolverService] = None

# Caches for prompts, schema, and tool definitions
_sql_schema_cache: Optional[str] = None
_system_prompt_cache: Optional[str] = None
_agent_tools_cache: Optional[List[Dict[str, Any]]] = None


async def initialize_clients():
    """Initialize all required clients."""
    global aoai_client, fabric_client, sql_client, cosmos_client, account_resolver
    
    if aoai_client is None:
        aoai_client = AzureOpenAIClient(settings.aoai)
    if fabric_client is None:
        fabric_client = FabricClient(settings.fabric)
    if sql_client is None:
        sql_client = SqlClient(settings.sql)
    if cosmos_client is None:
        cosmos_client = CosmosDBClient(settings.cosmos)
    if account_resolver is None:
        account_resolver = AccountResolverService(
            fabric_client=fabric_client,
            dev_mode=settings.dev_mode
        )
    
    logger.info("SQL MCP Server clients initialized")


async def get_sql_schema() -> str:
    """Load SQL schema from Cosmos DB."""
    global _sql_schema_cache

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


async def get_system_prompt(rbac_context: Optional[Dict[str, Any]] = None) -> str:
    """Get SQL agent system prompt with schema from Cosmos DB.

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

    logger.info("Loading agent tools from Cosmos (cache miss)", agent_type=AGENT_TYPE)
    # Load all tool definitions for this agent type from Cosmos DB
    # Pattern: {agent_type}_*_function (e.g., sql_query_function, sql_analysis_function)
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
    logger.info("🔧 SELF-HEALING RETRY", attempt=attempt, error_preview=error_message[:100])
    
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
        
        logger.info("✅ LLM generated corrected SQL", query_preview=corrected_sql[:100])
        return corrected_sql
        
    except Exception as e:
        logger.error("Failed to get LLM correction", error=str(e))
        return None


@mcp.tool()
async def sql_query(
    query: str,
    accounts_mentioned: Optional[List[str]] = None,
    rbac_context: Optional[Dict[str, Any]] = None,
    limit: int = DEFAULT_QUERY_LIMIT,
    request: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Execute SQL queries against Salesforce/Fabric data.
    
    This tool uses an internal LLM to generate SQL from natural language,
    resolves account mentions, and enforces RBAC row-level security.
    
    Args:
        query: Natural language query description
        accounts_mentioned: List of account names mentioned in query
        rbac_context: User RBAC context for row-level security
        limit: Maximum number of rows to return
        request: FastAPI Request object (injected by FastMCP)
    
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

        logger.info("📊 SQL TOOL START", query=query[:100], accounts_mentioned=accounts_mentioned)

        resolved_accounts = []
        if accounts_mentioned:
            logger.info("🔍 Resolving account names", count=len(accounts_mentioned))
            resolve_start = time.time()
            resolved_accounts = await resolve_accounts(accounts_mentioned)
            resolve_elapsed = int((time.time() - resolve_start) * 1000)
            logger.info("✅ Accounts resolved", count=len(resolved_accounts), duration_ms=resolve_elapsed)
        
        system_prompt = await get_system_prompt(rbac_context)
        
        user_message = f"Generate a SQL query for: {query}"
        if resolved_accounts:
            account_names = [acc["name"] for acc in resolved_accounts]
            user_message += f"\n\nAccount context: {', '.join(account_names)}"
        user_message += f"\n\nLimit results to {limit} rows."
        
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
        
        # Parse the function arguments to get the SQL query
        args_str = function_call.get("arguments", "{}")
        args = json.loads(args_str)
        sql_query = args.get("query", "")
        
        logger.info("Extracted SQL query", query_preview=sql_query[:100])

        # Self-healing retry loop: Execute SQL with automatic error correction
        results = None
        last_error = None
        
        for attempt in range(1, MAX_RETRY_ATTEMPTS + 1):
            try:
                if settings.dev_mode:
                    results = _get_dummy_sql_data(sql_query, limit)
                    logger.info("Dev mode: using dummy SQL data", result_count=len(results))
                else:
                    logger.info("🗃️ EXECUTING SQL QUERY", query=sql_query[:200], attempt=attempt)
                    sql_start = time.time()
                    results = await fabric_client.execute_query(sql_query)
                    sql_elapsed = int((time.time() - sql_start) * 1000)
                    logger.info("✅ SQL QUERY COMPLETE", duration_ms=sql_elapsed, row_count=len(results), attempt=attempt)
                
                # Success! Break out of retry loop
                break
                
            except Exception as sql_error:
                last_error = str(sql_error)
                logger.warning(f"❌ SQL execution failed", 
                             attempt=attempt, 
                             max_attempts=MAX_RETRY_ATTEMPTS,
                             error=last_error[:200])
                
                # If this was the last attempt, raise the error
                if attempt >= MAX_RETRY_ATTEMPTS:
                    logger.error("🚨 All retry attempts exhausted", attempts=attempt)
                    raise
                
                # Ask LLM to fix the query based on the error
                corrected_sql = await retry_with_llm_feedback(
                    original_query=query,
                    error_message=last_error,
                    attempt=attempt,
                    system_prompt=system_prompt,
                    tools=tools,
                    previous_sql=sql_query
                )
                
                if corrected_sql:
                    sql_query = corrected_sql
                    logger.info("🔄 Retrying with corrected SQL", attempt=attempt + 1)
                else:
                    logger.error("LLM couldn't generate a correction, giving up")
                    raise Exception(f"SQL execution failed and LLM couldn't correct it: {last_error}")
        
        # If we got here without results, something went wrong
        if results is None:
            raise Exception(f"SQL execution failed after {MAX_RETRY_ATTEMPTS} attempts: {last_error}")

        total_elapsed = int((time.time() - start_time) * 1000)
        logger.info("✅ SQL TOOL COMPLETE", row_count=len(results), total_duration_ms=total_elapsed)

        return {
            "success": True,
            "query": sql_query,
            "row_count": len(results),
            "data": results,
            "source": "fabric_sql" if not settings.dev_mode else "dummy_sql",
            "resolved_accounts": resolved_accounts,
        }

    except Exception as e:
        total_elapsed = int((time.time() - start_time) * 1000)
        logger.error("❌ SQL TOOL FAILED", error=str(e), total_duration_ms=total_elapsed)
        return {
            "success": False,
            "error": str(e),
            "query": query,
        }


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


@mcp.tool()
async def discover_schema(
    request: Optional[Any] = None,
    rbac_context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Discover and introspect database schema including tables, columns, relationships.
    
    This tool performs a full schema discovery, detects low-cardinality columns,
    and stores metadata in Cosmos DB for later use in semantic search.
    
    Args:
        request: FastAPI Request object (injected by FastMCP)
        rbac_context: User RBAC context (optional)
    
    Returns:
        Dictionary with discovered schema information
    """
    from shared.auth_provider import verify_token_from_request
    if request:
        try:
            await verify_token_from_request(request)
            logger.debug("Schema discovery request authenticated")
        except Exception as e:
            logger.error("Schema discovery authentication failed", error=str(e))
            return {
                "success": False,
                "error": f"Authentication failed: {str(e)}"
            }
    
    try:
        await initialize_clients()
        
        if settings.dev_mode:
            return {
                "success": True,
                "message": "Dev mode: schema discovery skipped",
                "tables": ["accounts", "contacts", "opportunities"]
            }
        
        logger.info("🔍 Starting schema discovery")
        
        # Get schema metadata from SQL
        schema_data = await sql_client.get_schema_metadata()
        
        # Process each table
        table_count = 0
        column_count = 0
        low_card_count = 0
        
        for table_key, table_info in schema_data["tables"].items():
            table_count += 1
            schema_name = table_info["schema"]
            table_name = table_info["name"]
            
            # Build table description for embedding
            columns_desc = []
            for col in table_info["columns"]:
                col_key = f"{table_key}.{col['name']}"
                col_desc = f"{col['name']} ({col['type']})"
                
                # Add description from extended properties if available
                if col_key in schema_data["descriptions"]:
                    col_desc += f": {schema_data['descriptions'][col_key]}"
                
                columns_desc.append(col_desc)
                column_count += 1
            
            table_desc_text = f"Table: {table_key}\nColumns: {', '.join(columns_desc)}"
            
            # Add table description if available
            if table_key in schema_data["descriptions"]:
                table_desc_text += f"\nDescription: {schema_data['descriptions'][table_key]}"
            
            # Generate embedding for the table
            table_embedding = None
            try:
                table_embedding = await aoai_client.create_embedding(table_desc_text)
            except Exception as e:
                logger.warning("Failed to create embedding for table", table=table_key, error=str(e))
            
            # Store table metadata
            table_metadata = SchemaMetadata(
                id=f"table:{table_key}",
                kind="table",
                schema_name=schema_name,
                table_name=table_name,
                description=schema_data["descriptions"].get(table_key),
                relationships=[],
                embedding=table_embedding,
                metadata={
                    "columns": table_info["columns"],
                    "column_count": len(table_info["columns"])
                }
            )
            
            # Save to Cosmos
            try:
                await cosmos_client.upsert_item(
                    container_name=settings.cosmos.schema_metadata_container,
                    item=table_metadata.model_dump()
                )
            except Exception as e:
                logger.warning("Failed to save table metadata", table=table_key, error=str(e))
            
            # Check cardinality for each column (sample first 10 columns to avoid long processing)
            for col in table_info["columns"][:10]:
                try:
                    cardinality_info = await sql_client.get_column_cardinality(
                        schema_name, table_name, col["name"]
                    )
                    
                    if cardinality_info["is_low_cardinality"]:
                        low_card_count += 1
                        
                        # Create embeddings for distinct values
                        value_embeddings = []
                        for value in cardinality_info["distinct_values"]:
                            try:
                                value_emb = await aoai_client.create_embedding(str(value))
                                value_embeddings.append(value_emb)
                            except Exception:
                                pass
                        
                        # Store column metadata with values
                        col_metadata = SchemaMetadata(
                            id=f"column:{table_key}.{col['name']}",
                            kind="column",
                            schema_name=schema_name,
                            table_name=table_name,
                            column_name=col["name"],
                            data_type=col["type"],
                            is_nullable=col["nullable"],
                            is_low_cardinality=True,
                            distinct_values=cardinality_info["distinct_values"],
                            metadata={
                                "distinct_count": cardinality_info["distinct_count"],
                                "value_embeddings": value_embeddings
                            }
                        )
                        
                        await cosmos_client.upsert_item(
                            container_name=settings.cosmos.schema_metadata_container,
                            item=col_metadata.model_dump()
                        )
                except Exception as e:
                    logger.warning("Failed to check column cardinality", 
                                 column=f"{table_key}.{col['name']}", error=str(e))
        
        logger.info("✅ Schema discovery complete",
                   tables=table_count,
                   columns=column_count,
                   low_cardinality_columns=low_card_count)
        
        return {
            "success": True,
            "tables_discovered": table_count,
            "columns_discovered": column_count,
            "low_cardinality_columns": low_card_count,
            "relationships": len(schema_data["relationships"])
        }
        
    except Exception as e:
        logger.error("❌ Schema discovery failed", error=str(e))
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
async def search_schema(
    question: str,
    top_k: int = 5,
    request: Optional[Any] = None,
    rbac_context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Search schema metadata using embeddings to find relevant tables and columns.
    
    Args:
        question: Natural language question
        top_k: Number of top relevant tables to return
        request: FastAPI Request object (injected by FastMCP)
        rbac_context: User RBAC context (optional)
    
    Returns:
        Dictionary with relevant schema information
    """
    from shared.auth_provider import verify_token_from_request
    if request:
        try:
            await verify_token_from_request(request)
        except Exception as e:
            logger.error("Schema search authentication failed", error=str(e))
            return {
                "success": False,
                "error": f"Authentication failed: {str(e)}"
            }
    
    try:
        await initialize_clients()
        
        if settings.dev_mode:
            return {
                "success": True,
                "message": "Dev mode: returning dummy schema",
                "tables": ["accounts", "contacts", "opportunities"],
                "schema": "Table: accounts (id, name, industry)\nTable: contacts (id, account_id, name)\nTable: opportunities (id, account_id, amount)"
            }
        
        logger.info("🔍 Searching schema", question=question[:100])
        
        # Generate embedding for the question
        question_embedding = await aoai_client.create_embedding(question)
        
        # Query schema metadata from Cosmos
        # Note: For production, this should use Cosmos vector search or Azure AI Search
        # For now, we'll retrieve all and do in-memory similarity
        schema_items = await cosmos_client.query_items(
            container_name=settings.cosmos.schema_metadata_container,
            query="SELECT * FROM c WHERE c.kind = 'table'"
        )
        
        if not schema_items:
            return {
                "success": False,
                "error": "No schema metadata found. Run discover_schema first."
            }
        
        # Calculate cosine similarity for each table
        import numpy as np
        
        def cosine_similarity(a, b):
            return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))
        
        scored_tables = []
        for item in schema_items:
            if item.get("embedding"):
                score = cosine_similarity(question_embedding, item["embedding"])
                scored_tables.append((score, item))
        
        # Sort by similarity and get top_k
        scored_tables.sort(key=lambda x: x[0], reverse=True)
        top_tables = scored_tables[:top_k]
        
        # Build schema description
        schema_parts = []
        relevant_tables = []
        for score, table in top_tables:
            table_name = f"{table['schema_name']}.{table['table_name']}"
            relevant_tables.append(table_name)
            
            columns = table.get("metadata", {}).get("columns", [])
            col_names = [f"{c['name']} ({c['type']})" for c in columns]
            
            schema_part = f"Table: {table_name}\nColumns: {', '.join(col_names)}"
            if table.get("description"):
                schema_part += f"\nDescription: {table['description']}"
            
            schema_parts.append(schema_part)
        
        schema_text = "\n\n".join(schema_parts)
        
        logger.info("✅ Schema search complete", relevant_tables=len(relevant_tables))
        
        return {
            "success": True,
            "relevant_tables": relevant_tables,
            "schema": schema_text,
            "top_k": len(top_tables)
        }
        
    except Exception as e:
        logger.error("❌ Schema search failed", error=str(e))
        return {
            "success": False,
            "error": str(e)
        }


@mcp.tool()
async def plan_sql(
    question: str,
    candidate_schema: Optional[str] = None,
    request: Optional[Any] = None,
    rbac_context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Generate a structured query plan from natural language.
    
    This tool asks the LLM to fill out a structured QueryPlan instead of generating SQL directly.
    
    Args:
        question: Natural language question
        candidate_schema: Optional pre-selected schema (from search_schema)
        request: FastAPI Request object (injected by FastMCP)
        rbac_context: User RBAC context (optional)
    
    Returns:
        Dictionary with query plan
    """
    from shared.auth_provider import verify_token_from_request
    if request:
        try:
            await verify_token_from_request(request)
        except Exception as e:
            logger.error("Query planning authentication failed", error=str(e))
            return {
                "success": False,
                "error": f"Authentication failed: {str(e)}"
            }
    
    try:
        await initialize_clients()
        
        if settings.dev_mode:
            # Return a dummy query plan
            return {
                "success": True,
                "plan": {
                    "tables": ["accounts"],
                    "select_fields": ["id", "name", "industry"],
                    "aggregations": [],
                    "filters": [],
                    "joins": [],
                    "group_by": [],
                    "order_by": [],
                    "limit": 100
                }
            }
        
        logger.info("📋 Planning SQL query", question=question[:100])
        
        # If no candidate schema provided, search for one
        if not candidate_schema:
            search_result = await search_schema(question, top_k=3, request=request, rbac_context=rbac_context)
            if search_result.get("success"):
                candidate_schema = search_result.get("schema", "")
        
        # Build prompt for query planning
        planning_prompt = f"""You are a SQL query planner. Given a natural language question and database schema,
generate a structured query plan (NOT SQL code).

Question: {question}

Available Schema:
{candidate_schema}

Generate a QueryPlan with these fields:
- tables: List of table names to query
- select_fields: List of fields to select (use table.column format)
- aggregations: List of aggregations like [{{"function": "SUM", "field": "amount", "alias": "total"}}]
- filters: List of filter conditions like [{{"table": "accounts", "column": "industry", "operator": "=", "value": "Technology"}}]
- joins: List of join specifications
- group_by: List of GROUP BY fields
- order_by: List of order specifications like [{{"field": "amount", "direction": "DESC"}}]
- limit: Optional row limit

Return a valid JSON QueryPlan object."""
        
        messages = [
            {"role": "system", "content": planning_prompt},
            {"role": "user", "content": question}
        ]
        
        response = await aoai_client.create_chat_completion(messages=messages)
        
        content = response["choices"][0]["message"]["content"]
        
        # Parse the query plan from response
        # Try to extract JSON from the response
        import re
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if json_match:
            plan_dict = json.loads(json_match.group(0))
            
            # Validate with QueryPlan model
            query_plan = QueryPlan(**plan_dict)
            
            logger.info("✅ Query plan generated", tables=query_plan.tables)
            
            return {
                "success": True,
                "plan": query_plan.model_dump()
            }
        else:
            raise Exception("Could not extract JSON query plan from LLM response")
        
    except Exception as e:
        logger.error("❌ Query planning failed", error=str(e))
        return {
            "success": False,
            "error": str(e)
        }


async def normalize_filter_value(
    filter_condition: FilterCondition
) -> str:
    """
    Normalize a filter value using low-cardinality matching if applicable.
    
    Args:
        filter_condition: Filter condition with table, column, operator, and value
    
    Returns:
        Normalized value (or original if not low-cardinality)
    """
    try:
        # Look up column metadata
        col_key = f"column:{filter_condition.table}.{filter_condition.column}"
        
        items = await cosmos_client.query_items(
            container_name=settings.cosmos.schema_metadata_container,
            query="SELECT * FROM c WHERE c.id = @id",
            parameters=[{"name": "@id", "value": col_key}]
        )
        
        if not items or not items[0].get("is_low_cardinality"):
            # Not low cardinality, return original value
            return str(filter_condition.value)
        
        col_metadata = items[0]
        distinct_values = col_metadata.get("distinct_values", [])
        value_embeddings = col_metadata.get("metadata", {}).get("value_embeddings", [])
        
        # First, try case-insensitive exact match
        raw_value = str(filter_condition.value).lower()
        for distinct_val in distinct_values:
            if str(distinct_val).lower() == raw_value:
                logger.info("Exact match found", raw=filter_condition.value, matched=distinct_val)
                return str(distinct_val)
        
        # If no exact match and we have embeddings, use semantic matching
        if value_embeddings:
            import numpy as np
            
            def cosine_similarity(a, b):
                return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))
            
            # Generate embedding for the raw value
            value_embedding = await aoai_client.create_embedding(str(filter_condition.value))
            
            # Find best match
            best_score = 0
            best_match = None
            
            for i, val_emb in enumerate(value_embeddings):
                if val_emb:
                    score = cosine_similarity(value_embedding, val_emb)
                    if score > best_score:
                        best_score = score
                        best_match = distinct_values[i]
            
            # Use match if score is above threshold
            if best_match and best_score > 0.8:
                logger.info("Semantic match found", 
                          raw=filter_condition.value, 
                          matched=best_match, 
                          score=best_score)
                return str(best_match)
        
        # No good match found, return original and log warning
        logger.warning("No good match for filter value",
                      column=filter_condition.column,
                      value=filter_condition.value,
                      available=distinct_values)
        return str(filter_condition.value)
        
    except Exception as e:
        logger.warning("Failed to normalize filter value", error=str(e))
        return str(filter_condition.value)


@mcp.tool()
async def query_sql_from_plan(
    plan: Dict[str, Any],
    request: Optional[Any] = None,
    rbac_context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Execute a SQL query from a structured query plan.
    
    This tool takes a QueryPlan, normalizes low-cardinality values,
    applies RBAC filters, generates safe SQL, and executes it.
    
    Args:
        plan: QueryPlan dictionary
        request: FastAPI Request object (injected by FastMCP)
        rbac_context: User RBAC context for row-level security
    
    Returns:
        Dictionary with query results
    """
    from shared.auth_provider import verify_token_from_request
    if request:
        try:
            await verify_token_from_request(request)
        except Exception as e:
            logger.error("Query execution authentication failed", error=str(e))
            return {
                "success": False,
                "error": f"Authentication failed: {str(e)}"
            }
    
    try:
        await initialize_clients()
        
        # Parse and validate query plan
        query_plan = QueryPlan(**plan)
        
        if settings.dev_mode:
            return {
                "success": True,
                "message": "Dev mode: dummy data",
                "data": _get_dummy_sql_data("", 100),
                "source": "dummy_sql"
            }
        
        logger.info("🗃️ Executing query from plan", tables=query_plan.tables)
        
        # Normalize filter values for low-cardinality columns
        for filter_cond in query_plan.filters:
            original_value = filter_cond.value
            normalized_value = await normalize_filter_value(filter_cond)
            if normalized_value != str(original_value):
                logger.info("Normalized filter value", 
                          column=filter_cond.column,
                          original=original_value,
                          normalized=normalized_value)
                filter_cond.value = normalized_value
        
        # Build SQL from plan using parameterized queries
        # This is a simplified SQL generator - production would need more robust handling
        parameters = []
        
        # Build SELECT clause with TOP for SQL Server/Azure SQL
        select_clause = "SELECT "
        if query_plan.limit:
            # SQL Server/Azure SQL use TOP instead of LIMIT
            select_clause += f"TOP {query_plan.limit} "
        
        if query_plan.select_fields:
            select_clause += ", ".join(query_plan.select_fields)
        else:
            select_clause += "*"
        
        # Add aggregations
        if query_plan.aggregations:
            agg_parts = []
            for agg in query_plan.aggregations:
                agg_expr = f"{agg['function']}({agg['field']})"
                if agg.get('alias'):
                    agg_expr += f" AS {agg['alias']}"
                agg_parts.append(agg_expr)
            if query_plan.select_fields:
                select_clause += ", " + ", ".join(agg_parts)
            else:
                select_clause = "SELECT "
                if query_plan.limit:
                    select_clause += f"TOP {query_plan.limit} "
                select_clause += ", ".join(agg_parts)
        
        from_clause = f" FROM {query_plan.tables[0]}"
        
        # Build WHERE clause with parameterized values
        where_parts = []
        for filter_cond in query_plan.filters:
            # Use parameterized queries to prevent SQL injection
            param_placeholder = "?"
            where_parts.append(f"{filter_cond.column} {filter_cond.operator} {param_placeholder}")
            parameters.append(filter_cond.value)
        
        # Add RBAC filters with parameterized values
        if rbac_context and settings.rbac_enabled:
            user_email = rbac_context.get("email", "")
            if user_email:
                # Use parameterized query for RBAC filter
                where_parts.append(f"(owner_email = ? OR assigned_to = ?)")
                parameters.append(user_email)
                parameters.append(user_email)
        
        where_clause = ""
        if where_parts:
            where_clause = " WHERE " + " AND ".join(where_parts)
        
        # GROUP BY clause
        group_by_clause = ""
        if query_plan.group_by:
            group_by_clause = " GROUP BY " + ", ".join(query_plan.group_by)
        
        # ORDER BY clause
        order_by_clause = ""
        if query_plan.order_by:
            order_parts = [f"{o['field']} {o.get('direction', 'ASC')}" for o in query_plan.order_by]
            order_by_clause = " ORDER BY " + ", ".join(order_parts)
        
        # Combine all parts (no LIMIT clause since we use TOP in SELECT)
        sql_query = select_clause + from_clause + where_clause + group_by_clause + order_by_clause
        
        logger.info("Generated SQL from plan", sql=sql_query[:200], param_count=len(parameters))
        
        # Execute the query with parameters
        results = await sql_client.execute_query(sql_query, parameters=parameters)
        
        logger.info("✅ Query executed from plan", row_count=len(results))
        
        return {
            "success": True,
            "query": sql_query,
            "row_count": len(results),
            "data": results,
            "source": "sql_from_plan"
        }
        
    except Exception as e:
        logger.error("❌ Query execution from plan failed", error=str(e))
        return {
            "success": False,
            "error": str(e)
        }


if __name__ == "__main__":
    import os
    
    logger.info(f"Starting {MCP_SERVER_NAME} on {HOST}:{MCP_SERVER_PORT}")
    
    # Run the MCP server with explicit port configuration
    mcp.run(transport=TRANSPORT, port=MCP_SERVER_PORT, host=HOST)
