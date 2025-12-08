"""
RBAC Service

Implements Row-Based Access Control (RBAC) for SQL queries.
Injects filters and column restrictions based on user roles and policies.
"""

import structlog
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
from enum import Enum
import sqlglot
from sqlglot import exp

from .cosmos_client import CosmosDBClient
from .models import RBACContext
from .config import get_settings

logger = structlog.get_logger(__name__)
settings = get_settings()


class EnforcementMode(Enum):
    """RBAC enforcement mode."""
    SOFT = "soft"  # Log violations, allow query
    HARD = "hard"  # Block queries that violate RBAC


@dataclass
class RBACPolicy:
    """RBAC policy definition."""
    id: str
    role: str  # User role (e.g., "Sales Representative", "Manager")
    table: str  # Table name
    filter_template: str  # SQL WHERE clause template, e.g., "owner_email = '{user_email}'"
    allowed_columns: Optional[List[str]] = None  # Allowed columns (None = all allowed)
    denied_columns: Optional[List[str]] = None  # Denied columns
    priority: int = 0  # Higher priority wins if multiple policies match

    def __post_init__(self):
        if self.allowed_columns is None:
            self.allowed_columns = []
        if self.denied_columns is None:
            self.denied_columns = []


@dataclass
class RBACViolation:
    """RBAC violation record."""
    violation_type: str  # "row_filter", "column_access", "table_access"
    table: str
    column: Optional[str] = None
    message: str = ""


class RBACService:
    """
    Applies RBAC policies to SQL queries.
    """

    def __init__(self, cosmos_client: CosmosDBClient):
        self.cosmos_client = cosmos_client
        self.container_name = settings.cosmos.rbac_policies_container
        self.enabled = settings.rbac.enabled
        self.enforcement_mode = EnforcementMode(settings.rbac.enforcement_mode)
        self.row_level_security = settings.rbac.row_level_security
        self.column_filtering = settings.rbac.enable_column_filtering
        self.logger = logger.bind(service="rbac")

        # Cache for policies
        self._policy_cache: Dict[str, List[RBACPolicy]] = {}

    async def apply_rbac(
        self,
        sql_query: str,
        rbac_context: RBACContext,
    ) -> tuple[str, List[RBACViolation]]:
        """
        Apply RBAC policies to a SQL query.

        Args:
            sql_query: Original SQL query
            rbac_context: User's RBAC context (roles, email, etc.)

        Returns:
            Tuple of (modified_sql, violations)
            - modified_sql: Query with RBAC filters applied
            - violations: List of RBAC violations (empty if none)

        Raises:
            PermissionError: If enforcement_mode is HARD and violations exist
        """
        if not self.enabled:
            self.logger.debug("RBAC disabled, returning original query")
            return sql_query, []

        self.logger.info(
            "Applying RBAC policies",
            user_email=rbac_context.email,
            roles=rbac_context.roles,
        )

        violations = []

        try:
            # Parse SQL query
            parsed = sqlglot.parse_one(sql_query, dialect="tsql")

            # Apply row-level security
            if self.row_level_security:
                parsed, row_violations = await self._apply_row_filters(parsed, rbac_context)
                violations.extend(row_violations)

            # Apply column-level security
            if self.column_filtering:
                parsed, col_violations = await self._apply_column_filters(parsed, rbac_context)
                violations.extend(col_violations)

            # Generate modified SQL
            modified_sql = parsed.sql(dialect="tsql")

            # Handle violations based on enforcement mode
            if violations:
                if self.enforcement_mode == EnforcementMode.HARD:
                    violation_messages = "; ".join([v.message for v in violations])
                    self.logger.error(
                        "RBAC violations detected (hard mode)",
                        violations=violation_messages,
                    )
                    raise PermissionError(f"RBAC policy violations: {violation_messages}")
                else:
                    self.logger.warning(
                        "RBAC violations detected (soft mode)",
                        violations=[v.message for v in violations],
                    )

            return modified_sql, violations

        except Exception as e:
            self.logger.error("RBAC application failed", error=str(e))
            if self.enforcement_mode == EnforcementMode.HARD:
                raise
            return sql_query, violations

    async def _apply_row_filters(
        self,
        parsed_query: exp.Expression,
        rbac_context: RBACContext,
    ) -> tuple[exp.Expression, List[RBACViolation]]:
        """
        Apply row-level security filters to the query.

        Args:
            parsed_query: Parsed SQL expression
            rbac_context: User's RBAC context

        Returns:
            Tuple of (modified_query, violations)
        """
        violations = []

        # Find all table references
        tables = self._extract_tables(parsed_query)

        for table in tables:
            # Get policies for this table and user's roles
            policies = await self._get_policies_for_table(table, rbac_context.roles)

            if not policies:
                continue

            # Use highest priority policy
            policy = max(policies, key=lambda p: p.priority)

            # Render filter template with user context
            filter_clause = self._render_filter_template(
                policy.filter_template,
                rbac_context,
            )

            # Inject filter into WHERE clause
            parsed_query = self._inject_where_clause(parsed_query, table, filter_clause)

            self.logger.info(
                "Row filter applied",
                table=table,
                role=policy.role,
                filter=filter_clause,
            )

        return parsed_query, violations

    async def _apply_column_filters(
        self,
        parsed_query: exp.Expression,
        rbac_context: RBACContext,
    ) -> tuple[exp.Expression, List[RBACViolation]]:
        """
        Apply column-level security (remove denied columns).

        Args:
            parsed_query: Parsed SQL expression
            rbac_context: User's RBAC context

        Returns:
            Tuple of (modified_query, violations)
        """
        violations = []

        # Extract all columns being selected
        for select in parsed_query.find_all(exp.Select):
            for i, expression in enumerate(select.expressions):
                if isinstance(expression, exp.Column):
                    table = expression.table
                    column = expression.name

                    # Get policies
                    policies = await self._get_policies_for_table(table, rbac_context.roles)

                    if not policies:
                        continue

                    policy = max(policies, key=lambda p: p.priority)

                    # Check if column is denied
                    if policy.denied_columns and column in policy.denied_columns:
                        violations.append(
                            RBACViolation(
                                violation_type="column_access",
                                table=table,
                                column=column,
                                message=f"Access denied to column {table}.{column}",
                            )
                        )

                        # Remove column from SELECT (replace with NULL)
                        select.expressions[i] = exp.Null()

                    # Check if column is in allowed list (if specified)
                    elif policy.allowed_columns and column not in policy.allowed_columns:
                        violations.append(
                            RBACViolation(
                                violation_type="column_access",
                                table=table,
                                column=column,
                                message=f"Column {table}.{column} not in allowed list",
                            )
                        )

                        select.expressions[i] = exp.Null()

        return parsed_query, violations

    async def _get_policies_for_table(
        self,
        table: str,
        roles: List[str],
    ) -> List[RBACPolicy]:
        """
        Get RBAC policies for a table and user roles.

        Args:
            table: Table name
            roles: User's roles

        Returns:
            List of applicable policies
        """
        # Check cache first
        cache_key = f"{table}_{'-'.join(sorted(roles))}"
        if cache_key in self._policy_cache:
            return self._policy_cache[cache_key]

        # Query Cosmos DB
        query = """
        SELECT * FROM c
        WHERE c.table = @table
        AND c.role IN (@roles)
        """

        parameters = [
            {"name": "@table", "value": table},
            {"name": "@roles", "value": roles},
        ]

        try:
            results = await self.cosmos_client.query_items(
                self.container_name,
                query,
                parameters=parameters,
            )

            policies = []
            for item in results:
                policies.append(
                    RBACPolicy(
                        id=item.get("id", ""),
                        role=item.get("role", ""),
                        table=item.get("table", ""),
                        filter_template=item.get("filter_template", ""),
                        allowed_columns=item.get("allowed_columns"),
                        denied_columns=item.get("denied_columns"),
                        priority=item.get("priority", 0),
                    )
                )

            # Cache policies
            self._policy_cache[cache_key] = policies

            return policies

        except Exception as e:
            self.logger.error("Failed to get policies", table=table, error=str(e))
            return []

    @staticmethod
    def _extract_tables(parsed_query: exp.Expression) -> List[str]:
        """Extract all table names from parsed query."""
        tables = []
        for table in parsed_query.find_all(exp.Table):
            tables.append(table.name)
        return list(set(tables))  # Remove duplicates

    @staticmethod
    def _render_filter_template(template: str, rbac_context: RBACContext) -> str:
        """
        Render a filter template with user context.

        Template variables:
        - {user_email}: User's email
        - {user_id}: User's ID
        - {tenant_id}: Tenant ID
        - {object_id}: Azure AD object ID

        Example:
        Template: "owner_email = '{user_email}'"
        Result: "owner_email = 'user@company.com'"
        """
        return template.format(
            user_email=rbac_context.email or "",
            user_id=rbac_context.user_id or "",
            tenant_id=rbac_context.tenant_id or "",
            object_id=rbac_context.object_id or "",
        )

    @staticmethod
    def _inject_where_clause(
        parsed_query: exp.Expression,
        table: str,
        filter_clause: str,
    ) -> exp.Expression:
        """
        Inject a WHERE clause filter into the query.

        Args:
            parsed_query: Parsed SQL expression
            table: Table name to filter
            filter_clause: Filter SQL (e.g., "owner_email = 'user@example.com'")

        Returns:
            Modified query
        """
        # Parse the filter clause
        filter_exp = sqlglot.parse_one(f"SELECT * FROM dummy WHERE {filter_clause}", dialect="tsql")
        filter_condition = filter_exp.find(exp.Where).this

        # Find WHERE clause in main query
        where = parsed_query.find(exp.Where)

        if where:
            # AND with existing WHERE
            where.this = exp.And(this=where.this, expression=filter_condition)
        else:
            # Add new WHERE clause
            select = parsed_query.find(exp.Select)
            if select:
                select.where(filter_condition)

        return parsed_query
