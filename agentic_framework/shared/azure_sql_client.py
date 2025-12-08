"""
Azure SQL Database Client

Provides connectivity to Azure SQL Database with Azure AD authentication.
Works alongside Fabric SQL client to support both platforms.
"""

import pyodbc
import struct
import structlog
from typing import List, Dict, Any, Optional
from azure.identity import DefaultAzureCredential
from tenacity import retry, stop_after_attempt, wait_exponential

from .config import get_settings

logger = structlog.get_logger(__name__)
settings = get_settings()


class AzureSQLClient:
    """
    Client for executing queries against Azure SQL Database.
    Uses Azure AD token-based authentication.
    """

    def __init__(self):
        self.server = settings.azure_sql.server
        self.database = settings.azure_sql.database
        self.driver = settings.azure_sql.driver
        self.token_scope = settings.azure_sql.token_scope
        self.credential = DefaultAzureCredential()
        self.logger = logger.bind(service="azure_sql")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def execute_query(
        self,
        query: str,
        parameters: Optional[List[Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Execute a SQL query against Azure SQL Database.

        Args:
            query: SQL query string
            parameters: Optional list of parameters for parameterized queries

        Returns:
            List of dicts (one per row)

        Raises:
            Exception: If query execution fails
        """
        self.logger.info(
            "Executing Azure SQL query",
            query=query[:200],
            has_parameters=parameters is not None,
        )

        try:
            # Get Azure AD access token
            token = await self._get_access_token()

            # Build connection string
            conn_string = self._build_connection_string()

            # Connect with access token
            with pyodbc.connect(
                conn_string,
                attrs_before={1256: token}  # SQL_COPT_SS_ACCESS_TOKEN
            ) as conn:
                with conn.cursor() as cursor:
                    # Execute query
                    if parameters:
                        cursor.execute(query, parameters)
                    else:
                        cursor.execute(query)

                    # Fetch results
                    columns = [column[0] for column in cursor.description] if cursor.description else []
                    rows = cursor.fetchall()

                    # Convert to list of dicts
                    results = []
                    for row in rows:
                        row_dict = {}
                        for i, column in enumerate(columns):
                            value = row[i]
                            # Convert to JSON-serializable types
                            if hasattr(value, 'isoformat'):
                                value = value.isoformat()
                            row_dict[column] = value
                        results.append(row_dict)

                    self.logger.info(
                        "Query executed successfully",
                        row_count=len(results),
                    )

                    return results

        except Exception as e:
            self.logger.error(
                "Query execution failed",
                error=str(e),
                query=query[:200],
            )
            raise

    async def execute_scalar(self, query: str) -> Any:
        """
        Execute a query and return a single scalar value.

        Args:
            query: SQL query that returns a single value

        Returns:
            The scalar value
        """
        results = await self.execute_query(query)
        if results and len(results) > 0:
            first_row = results[0]
            return list(first_row.values())[0]
        return None

    async def get_table_schema(self, table_name: str, schema: str = "dbo") -> List[Dict[str, Any]]:
        """
        Get schema information for a table including extended properties (descriptions).

        Args:
            table_name: Table name
            schema: Schema name (default: dbo)

        Returns:
            List of column metadata dicts
        """
        query = """
        SELECT
            c.COLUMN_NAME as name,
            c.DATA_TYPE as type,
            c.IS_NULLABLE as is_nullable,
            c.CHARACTER_MAXIMUM_LENGTH as max_length,
            c.NUMERIC_PRECISION as precision,
            c.NUMERIC_SCALE as scale,
            CASE
                WHEN pk.COLUMN_NAME IS NOT NULL THEN 1
                ELSE 0
            END as is_primary_key,
            CASE
                WHEN fk.COLUMN_NAME IS NOT NULL THEN 1
                ELSE 0
            END as is_foreign_key,
            ep.value as description
        FROM INFORMATION_SCHEMA.COLUMNS c
        LEFT JOIN (
            SELECT ku.COLUMN_NAME
            FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
            JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE ku
                ON tc.CONSTRAINT_NAME = ku.CONSTRAINT_NAME
            WHERE tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
                AND ku.TABLE_SCHEMA = ?
                AND ku.TABLE_NAME = ?
        ) pk ON c.COLUMN_NAME = pk.COLUMN_NAME
        LEFT JOIN (
            SELECT ku.COLUMN_NAME
            FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
            JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE ku
                ON tc.CONSTRAINT_NAME = ku.CONSTRAINT_NAME
            WHERE tc.CONSTRAINT_TYPE = 'FOREIGN KEY'
                AND ku.TABLE_SCHEMA = ?
                AND ku.TABLE_NAME = ?
        ) fk ON c.COLUMN_NAME = fk.COLUMN_NAME
        LEFT JOIN sys.extended_properties ep
            ON ep.major_id = OBJECT_ID(? + '.' + ?)
            AND ep.minor_id = COLUMNPROPERTY(OBJECT_ID(? + '.' + ?), c.COLUMN_NAME, 'ColumnId')
            AND ep.name = 'MS_Description'
        WHERE c.TABLE_SCHEMA = ?
            AND c.TABLE_NAME = ?
        ORDER BY c.ORDINAL_POSITION
        """

        results = await self.execute_query(
            query,
            parameters=[
                schema, table_name,  # pk subquery
                schema, table_name,  # fk subquery
                schema, table_name,  # extended properties 1
                schema, table_name,  # extended properties 2
                schema, table_name,  # main WHERE
            ],
        )

        return results

    async def get_table_description(self, table_name: str, schema: str = "dbo") -> Optional[str]:
        """
        Get the description (extended property) for a table.

        Args:
            table_name: Table name
            schema: Schema name

        Returns:
            Table description or None
        """
        query = """
        SELECT ep.value
        FROM sys.extended_properties ep
        JOIN sys.tables t ON ep.major_id = t.object_id
        JOIN sys.schemas s ON t.schema_id = s.schema_id
        WHERE ep.minor_id = 0
            AND ep.name = 'MS_Description'
            AND s.name = ?
            AND t.name = ?
        """

        result = await self.execute_scalar(query)
        return result if result else None

    async def get_low_cardinality_columns(
        self,
        table_name: str,
        schema: str = "dbo",
        max_cardinality: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Identify low-cardinality columns (good candidates for value matching).

        Args:
            table_name: Table name
            schema: Schema name
            max_cardinality: Maximum distinct values to be considered low-cardinality

        Returns:
            List of column info dicts with cardinality
        """
        query = f"""
        SELECT
            c.name as column_name,
            t.name as data_type,
            COUNT(DISTINCT v.value) as cardinality
        FROM sys.columns c
        JOIN sys.types t ON c.user_type_id = t.user_type_id
        JOIN sys.tables tab ON c.object_id = tab.object_id
        JOIN sys.schemas s ON tab.schema_id = s.schema_id
        CROSS APPLY (
            SELECT DISTINCT [{c.name}] as value
            FROM [{schema}].[{table_name}]
        ) v
        WHERE s.name = ?
            AND tab.name = ?
        GROUP BY c.name, t.name
        HAVING COUNT(DISTINCT v.value) <= ?
        ORDER BY cardinality
        """

        results = await self.execute_query(
            query,
            parameters=[schema, table_name, max_cardinality],
        )

        return results

    async def get_distinct_values(
        self,
        table_name: str,
        column_name: str,
        schema: str = "dbo",
    ) -> List[str]:
        """
        Get all distinct values for a column.

        Args:
            table_name: Table name
            column_name: Column name
            schema: Schema name

        Returns:
            List of distinct values
        """
        query = f"""
        SELECT DISTINCT [{column_name}] as value
        FROM [{schema}].[{table_name}]
        WHERE [{column_name}] IS NOT NULL
        ORDER BY value
        """

        results = await self.execute_query(query)
        return [row["value"] for row in results]

    async def _get_access_token(self) -> bytes:
        """
        Get Azure AD access token for SQL Database.

        Returns:
            Token in format required by pyodbc
        """
        token_obj = self.credential.get_token(self.token_scope)
        token_bytes = token_obj.token.encode("utf-16-le")

        # Pack token for SQL_COPT_SS_ACCESS_TOKEN
        token_struct = struct.pack(f"<I{len(token_bytes)}s", len(token_bytes), token_bytes)

        return token_struct

    def _build_connection_string(self) -> str:
        """
        Build ODBC connection string.

        Returns:
            Connection string
        """
        return (
            f"DRIVER={{{self.driver}}};"
            f"SERVER={self.server};"
            f"DATABASE={self.database};"
            f"Encrypt=yes;"
            f"TrustServerCertificate=no;"
            f"Connection Timeout=30;"
        )
