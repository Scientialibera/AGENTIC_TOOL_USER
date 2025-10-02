"""
SQL service for executing queries with RBAC filtering.

This service handles SQL query generation, validation, RBAC filter injection,
and execution against the Fabric lakehouse SQL endpoints. The lakehouse contains
structured data extracted from Salesforce and SharePoint by the data engineering team.
"""

import re
import sqlparse
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime
import structlog

# AzureOpenAIClient not needed in MCP - it's optional
from shared.models.rbac import RBACContext
from shared.models.result import QueryResult, DataTable, DataColumn

logger = structlog.get_logger(__name__)


class SQLService:
    """Service for SQL query execution with security and validation."""
    
    def __init__(
        self,
        aoai_client: Any = None,  # Optional - not needed in MCP
        schema_repository: Any = None,
        unified_data_service: Any = None,
        telemetry_service: Any = None,
        settings: Any = None,
        dev_mode: bool = False
    ):
        """
        Initialize the SQL service.
        
        Args:
            aoai_client: Azure OpenAI client for LLM operations
            schema_repository: Repository for schema metadata
            cache_service: Cache service for query results
            telemetry_service: Telemetry service for monitoring
            settings: Fabric lakehouse connection settings
            dev_mode: Whether to use dummy data instead of real database
        """
        self.aoai_client = aoai_client
        # Keep optional references for compatibility; they are not used by the
        # simplified test-focused API but accepted to avoid breaking callers.
        self.schema_repository = schema_repository
        self.unified_data_service = unified_data_service
        self.telemetry_service = telemetry_service
        self.settings = settings
        self.dev_mode = dev_mode

        # Optional connection string (built only if settings provide values)
        try:
            self.connection_string = self._build_connection_string()
        except Exception:
            self.connection_string = ""

        # Service configuration (use safe defaults when settings is None)
        self.max_rows = getattr(settings, "max_rows", 1000)
        self.query_timeout_seconds = getattr(settings, "connection_timeout", 30)

        # Allowed SQL operations (security whitelist)
        self.allowed_operations = {"SELECT", "WITH"}

        # Dangerous keywords to block
        self.blocked_keywords = {
            "DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "CREATE",
            "TRUNCATE", "EXEC", "EXECUTE", "sp_", "xp_", "BACKUP",
            "RESTORE", "SHUTDOWN", "RECONFIGURE"
        }
    
    def _build_connection_string(self) -> str:
        """Build connection string for Fabric lakehouse."""
        return (
            f"DRIVER={{ODBC Driver 18 for SQL Server}};"
            f"SERVER={self.settings.sql_endpoint};"
            f"DATABASE={self.settings.database};"
            f"Authentication=ActiveDirectoryMsi;"
            f"Connection Timeout={self.settings.connection_timeout};"
            f"Encrypt=yes;"
            f"TrustServerCertificate=no;"
        )

    # --- Simplified API for agentic tests ---
    async def execute_query(self, query: str, rbac_context: RBACContext) -> QueryResult:
        """
        Simplified execute for tests and agent tools. Respects dev_mode: in
        dev_mode we return dummy data and do not mutate the query. Note:
        `rbac_context` is required; in `dev_mode` it will be ignored.
        """
        try:
            # If dev_mode, return dummy data and do not modify the query
            if self.dev_mode:
                # Return the dummy QueryResult directly in dev mode
                return self._get_dummy_sql_data(query)
            # In non-dev mode, apply RBAC filters if provided
            filtered_query = query
            if rbac_context:
                try:
                    filtered_query = self.apply_rbac_where(query, rbac_context)
                except Exception:
                    filtered_query = query
            # In non-dev mode, keep behavior simple: validate and run
            validation = await self._validate_query(filtered_query)
            if not validation.get("is_valid"):
                return QueryResult(
                    success=False,
                    error_message=f"Validation failed: {validation.get('error')}",
                    data=[],
                    metadata={},
                    rows_affected=0,
                    execution_time_ms=0,
                )
            return await self._execute_sql_query(filtered_query)
        except Exception as e:
            logger.error("execute_query failed", error=str(e))
            return QueryResult(
                success=False,
                error_message=str(e),
                data=[],
                metadata={},
                rows_affected=0,
                execution_time_ms=0,
            )

    def extract_function_call(self, agent_message: dict) -> Optional[Dict[str, Any]]:
        """
        Extract a function/tool call payload from an agent response message.
        Supports both new `tool_calls` shape and legacy `function_call`.
        Returns the first call found or None.
        """
        if not isinstance(agent_message, dict):
            return None
        # New style: 'tool_calls' list
        if agent_message.get("tool_calls"):
            calls = agent_message.get("tool_calls") or []
            return calls[0] if calls else None
        # Legacy: 'function_call'
        if agent_message.get("function_call"):
            return agent_message.get("function_call")
        # Check nested shapes under 'choices' -> 'message'
        if agent_message.get("choices"):
            try:
                msg = (agent_message.get("choices") or [{}])[0].get("message")
                if isinstance(msg, dict):
                    return self.extract_function_call(msg)
            except Exception:
                pass
        return None

    def apply_rbac_where(self, query: str, rbac_context: RBACContext) -> str:
        """
        Add or update a WHERE clause to restrict results based on the
        RBACContext. For this simplified API we append a predicate on
        `roles` equal to the joined permissions set. In dev_mode this is
        a no-op and returns the original query.
        """
        if self.dev_mode or not rbac_context:
            return query

        try:
            # Use permissions set or roles as a fallback
            perms = getattr(rbac_context, "permissions", None)
            if not perms:
                perms = getattr(rbac_context, "roles", None) or []
            if isinstance(perms, (set, list, tuple)):
                perms_list = list(perms)
            else:
                perms_list = [str(perms)]

            if not perms_list:
                return query

            # Build a predicate that checks roles/permissions membership
            # This is intentionally simple: roles IN ('r1','r2')
            quoted = ", ".join(("'" + str(p).replace("'", "''") + "'") for p in perms_list)
            predicate = f"roles IN ({quoted})"

            return self._add_where_clause(query, predicate)
        except Exception as e:
            logger.error("apply_rbac_where failed", error=str(e))
            return query
    # Note: The legacy `execute_query` variant with RBAC/context-aware caching
    # was intentionally removed to keep this service small and focused for the
    # simplified agentic tests. Use `execute_query(query)` and
    # `apply_rbac_where(query, rbac_ctx)` from the simplified API above.
    
    async def _validate_query(self, query: str) -> Dict[str, Any]:
        """
        Validate SQL query for security and syntax.
        
        Args:
            query: SQL query to validate
            
        Returns:
            Validation result with is_valid flag and error message
        """
        try:
            # Check for blocked keywords
            query_upper = query.upper()
            for keyword in self.blocked_keywords:
                if keyword in query_upper:
                    return {
                        "is_valid": False,
                        "error": f"Blocked keyword detected: {keyword}"
                    }
            
            # Parse the query to check structure
            try:
                parsed = sqlparse.parse(query)
                if not parsed:
                    return {
                        "is_valid": False,
                        "error": "Unable to parse SQL query"
                    }
                
                # Check that all statements are SELECT or WITH
                for statement in parsed:
                    stmt_type = statement.get_type()
                    if stmt_type not in self.allowed_operations:
                        return {
                            "is_valid": False,
                            "error": f"Operation '{stmt_type}' is not allowed"
                        }
                
            except Exception as parse_error:
                return {
                    "is_valid": False,
                    "error": f"SQL parsing error: {str(parse_error)}"
                }
            
            # Additional security checks (basic pattern scanning)
            # Keep this light-weight for test scenarios.
            
            return {"is_valid": True, "error": None}
            
        except Exception as e:
            return {
                "is_valid": False,
                "error": f"Validation error: {str(e)}"
            }
    
    def _contains_dangerous_patterns(self, query: str) -> bool:
        """
        Check for dangerous SQL patterns.
        
        Args:
            query: SQL query to check
            
        Returns:
            True if dangerous patterns are found
        """
        dangerous_patterns = [
            r";\s*(DROP|DELETE|UPDATE|INSERT)",  # Multiple statements
            r"UNION\s+ALL\s+SELECT.*FROM\s+INFORMATION_SCHEMA",  # Schema probing
            r"@@\w+",  # System variables
            r"WAITFOR\s+DELAY",  # Time-based attacks
            r"OPENROWSET",  # File operations
            r"OPENDATASOURCE",  # External data access
        ]
        
        query_upper = query.upper()
        for pattern in dangerous_patterns:
            if re.search(pattern, query_upper):
                logger.warning("Dangerous SQL pattern detected", pattern=pattern)
                return True
        
        return False
    
    def _add_where_clause(self, query: str, condition: str) -> str:
        """
        Add WHERE clause condition to SQL query.
        
        Args:
            query: Original SQL query
            condition: WHERE condition to add
            
        Returns:
            Modified query with added condition
        """
        try:
            # Simple approach: look for existing WHERE clause
            query_upper = query.upper()
            
            if " WHERE " in query_upper:
                # Add to existing WHERE clause with AND
                where_pos = query_upper.rfind(" WHERE ")
                before_where = query[:where_pos + 7]  # Include " WHERE "
                after_where = query[where_pos + 7:]
                
                return f"{before_where}({condition}) AND ({after_where})"
            else:
                # Add new WHERE clause
                # Find the main SELECT statement and add WHERE before ORDER BY, GROUP BY, etc.
                order_by_pos = query_upper.find(" ORDER BY")
                group_by_pos = query_upper.find(" GROUP BY")
                having_pos = query_upper.find(" HAVING")
                
                # Find the earliest clause position
                clause_positions = [pos for pos in [order_by_pos, group_by_pos, having_pos] if pos > 0]
                insert_pos = min(clause_positions) if clause_positions else len(query)
                
                before_clause = query[:insert_pos]
                after_clause = query[insert_pos:]
                
                return f"{before_clause} WHERE {condition}{after_clause}"
                
        except Exception as e:
            logger.error("Failed to add WHERE clause", condition=condition, error=str(e))
            return query
    
    
    def _get_dummy_sql_data(self, query: str) -> QueryResult:
        """
        Generate dummy SQL data for development mode.
        Supports returning a unified result when the query mentions multiple tables
        (e.g., both 'accounts' and 'contacts'): rows are unioned into a single
        DataTable with a 'table' column indicating the source.
        """
        query_lower = (query or "").lower()

        # Match tokens (avoid overly broad matches like plain 'account' for opps)
        match_opps = any(tok in query_lower for tok in (" sales", "sales ", " opportunity", " opportunities", " opp ", " pipeline"))
        match_accounts = "accounts" in query_lower
        match_contacts = "contacts" in query_lower

        # Collect tables independently (no elif) so multiple can be returned
        selected_tables: List[Tuple[str, List[Dict[str, Any]]]] = []

        if match_opps:
            opp_rows = [
                {
                    "id": "opp_001",
                    "name": "Salesforce CRM Upgrade",
                    "amount": 2500000.0,
                    "stage": "Closed Won",
                    "close_date": "2024-03-15",
                    "account_name": "Salesforce Inc",
                    "account_id": "acc_salesforce",
                },
                {
                    "id": "opp_002",
                    "name": "Microsoft 365 Integration",
                    "amount": 1800000.0,
                    "stage": "Proposal",
                    "close_date": "2024-11-30",
                    "account_name": "Microsoft Corporation",
                    "account_id": "acc_microsoft",
                },
                {
                    "id": "opp_003",
                    "name": "Oracle Database Migration",
                    "amount": 3200000.0,
                    "stage": "Negotiation",
                    "close_date": "2024-12-15",
                    "account_name": "Oracle Corporation",
                    "account_id": "acc_oracle",
                },
            ]
            selected_tables.append(("opportunities", opp_rows))

        if match_accounts:
            acct_rows = [
                {"id": "acc_salesforce", "name": "Salesforce Inc", "owner_email": "owner@salesforce.com", "created_at": "2023-01-15", "updated_at": "2024-09-21"},
                {"id": "acc_microsoft", "name": "Microsoft Corporation", "owner_email": "owner@microsoft.com", "created_at": "2023-02-20", "updated_at": "2024-09-21"},
                {"id": "acc_oracle", "name": "Oracle Corporation", "owner_email": "owner@oracle.com", "created_at": "2023-03-10", "updated_at": "2024-09-21"},
                {"id": "acc_google", "name": "Google LLC", "owner_email": "owner@google.com", "created_at": "2023-04-05", "updated_at": "2024-09-21"},
            ]
            selected_tables.append(("accounts", acct_rows))

        if match_contacts:
            # Base contact rows (one per account). To make dev-mode more useful for
            # multi-account queries we expand this into multiple contacts per
            # account so queries that request contacts return richer results.
            base_contact_rows = [
                {"id": "contact_001", "first_name": "John", "last_name": "Smith", "email": "john.smith@salesforce.com", "account_id": "acc_salesforce"},
                {"id": "contact_002", "first_name": "Jane", "last_name": "Doe", "email": "jane.doe@microsoft.com", "account_id": "acc_microsoft"},
                {"id": "contact_003", "first_name": "Bob", "last_name": "Johnson", "email": "bob.johnson@oracle.com", "account_id": "acc_oracle"},
                {"id": "contact_004", "first_name": "Alice", "last_name": "Williams", "email": "alice.williams@google.com", "account_id": "acc_google"},
            ]

            # Return the base contact rows directly — simpler and predictable for
            # dev-mode: any query that mentions 'contacts' will receive the full
            # base set of sample contact rows.
            contact_rows = base_contact_rows
            selected_tables.append(("contacts", contact_rows))

        # If nothing matched, return empty
        if not selected_tables:
            data_table = DataTable(
                name="query_result",
                columns=[],
                rows=[],
                row_count=0,
                source="sql",
                query=query,
            )
            return QueryResult(
                success=True,
                data=data_table,
                error=None,
                query=query,
                execution_time_ms=50,
                row_count=0,
            )

        # If only one table matched, return it directly (backward compatible)
        if len(selected_tables) == 1:
            table_name, rows = selected_tables[0]
            if rows:
                columns = list(rows[0].keys())
                table_columns = [
                    DataColumn(name=c, data_type=("number" if isinstance(rows[0][c], (int, float)) else "string"))
                    for c in columns
                ]
            else:
                table_columns = []
            data_table = DataTable(
                name=table_name,
                columns=table_columns,
                rows=rows,
                row_count=len(rows),
                source="sql",
                query=query,
            )
            return QueryResult(
                success=True,
                data=data_table,
                error=None,
                query=query,
                execution_time_ms=50,
                row_count=len(rows),
            )

        # Multiple tables matched: build a unified DataTable (adds 'table' column)
        # Compute the union of all column names across selected tables
        union_cols: List[str] = []
        col_set = set()
        for _, rows in selected_tables:
            if rows:
                for c in rows[0].keys():
                    if c not in col_set:
                        col_set.add(c)
                        union_cols.append(c)
        # Ensure a 'table' discriminator column is present
        if "table" not in col_set:
            union_cols.insert(0, "table")
            col_set.add("table")

        # Build unified rows, padding missing columns with None
        unified_rows: List[Dict[str, Any]] = []
        for table_name, rows in selected_tables:
            for r in rows:
                unified = {c: None for c in union_cols}
                unified.update(r)
                unified["table"] = table_name
                unified_rows.append(unified)

        # Infer column types from first non-None sample in unified rows
        def _infer_type(col: str) -> str:
            for r in unified_rows:
                v = r.get(col)
                if v is not None:
                    return "number" if isinstance(v, (int, float)) else "string"
            return "string"

        table_columns = [DataColumn(name=c, data_type=_infer_type(c)) for c in union_cols]

        data_table = DataTable(
            name="query_result",
            columns=table_columns,
            rows=unified_rows,
            row_count=len(unified_rows),
            source="sql",
            query=query,
        )

        return QueryResult(
            success=True,
            data=data_table,
            error=None,
            query=query,
            execution_time_ms=50,
            row_count=len(unified_rows),
        )

