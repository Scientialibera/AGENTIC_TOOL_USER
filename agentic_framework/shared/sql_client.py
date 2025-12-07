"""
Unified SQL client supporting both Fabric SQL and Azure SQL with DefaultAzureCredential authentication.
"""

import asyncio
from typing import Optional, Dict, Any, List
import pyodbc
from azure.identity import DefaultAzureCredential
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import structlog

from shared.config import SqlSettings

logger = structlog.get_logger(__name__)


class SqlClient:
    """Unified SQL client for Fabric SQL and Azure SQL."""
    
    def __init__(self, settings: SqlSettings):
        """Initialize the SQL client."""
        self.settings = settings
        self._credential = DefaultAzureCredential()
        
        logger.info(
            "Initialized SQL client",
            engine_type=settings.engine_type,
            endpoint=settings.endpoint,
            database=settings.database,
        )
    
    def _build_connection_string(self, access_token: str) -> str:
        """Build SQL connection string with access token."""
        return (
            f"Driver={{ODBC Driver 18 for SQL Server}};"
            f"Server={self.settings.endpoint};"
            f"Database={self.settings.database};"
            f"Encrypt=yes;"
            f"TrustServerCertificate=no;"
            f"Connection Timeout={self.settings.connection_timeout};"
        )
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((pyodbc.Error,)),
    )
    async def execute_query(
        self,
        query: str,
        parameters: Optional[List[Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Execute a SQL query against Fabric SQL or Azure SQL."""
        try:
            logger.debug("Executing SQL query", query=query[:100], engine=self.settings.engine_type)
            
            # Both Fabric SQL and Azure SQL use the same token scope
            token = self._credential.get_token("https://database.windows.net/.default")
            
            def execute_sync():
                conn_str = self._build_connection_string(token.token)
                
                conn = pyodbc.connect(conn_str, attrs_before={
                    1256: token.token.encode('utf-16-le')
                })
                
                try:
                    cursor = conn.cursor()
                    
                    if parameters:
                        cursor.execute(query, parameters)
                    else:
                        cursor.execute(query)
                    
                    columns = [column[0] for column in cursor.description]
                    results = []
                    
                    for row in cursor.fetchall():
                        results.append(dict(zip(columns, row)))
                    
                    return results
                finally:
                    cursor.close()
                    conn.close()
            
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(None, execute_sync)
            
            logger.debug("SQL query executed", result_count=len(results), engine=self.settings.engine_type)
            return results
            
        except Exception as e:
            logger.error("Failed to execute SQL query", error=str(e), engine=self.settings.engine_type)
            raise
    
    async def get_schema_metadata(self) -> Dict[str, Any]:
        """
        Introspect database schema including tables, columns, types, relationships.
        
        Returns:
            Dictionary with schema metadata including tables, columns, and relationships
        """
        try:
            logger.info("Introspecting database schema", engine=self.settings.engine_type)
            
            # Query for tables and columns
            tables_query = """
            SELECT 
                t.TABLE_SCHEMA,
                t.TABLE_NAME,
                c.COLUMN_NAME,
                c.DATA_TYPE,
                c.IS_NULLABLE,
                c.CHARACTER_MAXIMUM_LENGTH,
                c.NUMERIC_PRECISION,
                c.NUMERIC_SCALE
            FROM INFORMATION_SCHEMA.TABLES t
            INNER JOIN INFORMATION_SCHEMA.COLUMNS c 
                ON t.TABLE_SCHEMA = c.TABLE_SCHEMA 
                AND t.TABLE_NAME = c.TABLE_NAME
            WHERE t.TABLE_TYPE = 'BASE TABLE'
            ORDER BY t.TABLE_SCHEMA, t.TABLE_NAME, c.ORDINAL_POSITION
            """
            
            tables_result = await self.execute_query(tables_query)
            
            # Query for foreign key relationships
            fk_query = """
            SELECT 
                fk.name AS FK_NAME,
                tp.name AS PARENT_TABLE,
                cp.name AS PARENT_COLUMN,
                tr.name AS REFERENCED_TABLE,
                cr.name AS REFERENCED_COLUMN
            FROM sys.foreign_keys fk
            INNER JOIN sys.foreign_key_columns fkc ON fk.object_id = fkc.constraint_object_id
            INNER JOIN sys.tables tp ON fkc.parent_object_id = tp.object_id
            INNER JOIN sys.columns cp ON fkc.parent_object_id = cp.object_id AND fkc.parent_column_id = cp.column_id
            INNER JOIN sys.tables tr ON fkc.referenced_object_id = tr.object_id
            INNER JOIN sys.columns cr ON fkc.referenced_object_id = cr.object_id AND fkc.referenced_column_id = cr.column_id
            """
            
            relationships = []
            try:
                fk_result = await self.execute_query(fk_query)
                relationships = fk_result
            except Exception as e:
                logger.warning("Could not retrieve foreign keys", error=str(e))
            
            # Query for extended properties (descriptions)
            desc_query = """
            SELECT 
                s.name AS SCHEMA_NAME,
                o.name AS TABLE_NAME,
                c.name AS COLUMN_NAME,
                ep.value AS DESCRIPTION
            FROM sys.extended_properties ep
            INNER JOIN sys.objects o ON ep.major_id = o.object_id
            INNER JOIN sys.schemas s ON o.schema_id = s.schema_id
            LEFT JOIN sys.columns c ON ep.major_id = c.object_id AND ep.minor_id = c.column_id
            WHERE ep.name = 'MS_Description'
                AND o.type = 'U'
            """
            
            descriptions = {}
            try:
                desc_result = await self.execute_query(desc_query)
                for row in desc_result:
                    key = f"{row['SCHEMA_NAME']}.{row['TABLE_NAME']}"
                    if row.get('COLUMN_NAME'):
                        key = f"{key}.{row['COLUMN_NAME']}"
                    descriptions[key] = row['DESCRIPTION']
            except Exception as e:
                logger.warning("Could not retrieve extended properties", error=str(e))
            
            # Organize schema data
            schema_metadata = {
                "tables": {},
                "relationships": relationships,
                "descriptions": descriptions
            }
            
            for row in tables_result:
                table_key = f"{row['TABLE_SCHEMA']}.{row['TABLE_NAME']}"
                if table_key not in schema_metadata["tables"]:
                    schema_metadata["tables"][table_key] = {
                        "schema": row['TABLE_SCHEMA'],
                        "name": row['TABLE_NAME'],
                        "columns": []
                    }
                
                schema_metadata["tables"][table_key]["columns"].append({
                    "name": row['COLUMN_NAME'],
                    "type": row['DATA_TYPE'],
                    "nullable": row['IS_NULLABLE'] == 'YES',
                    "max_length": row.get('CHARACTER_MAXIMUM_LENGTH'),
                    "precision": row.get('NUMERIC_PRECISION'),
                    "scale": row.get('NUMERIC_SCALE')
                })
            
            logger.info("Schema introspection complete", 
                       table_count=len(schema_metadata["tables"]),
                       relationship_count=len(relationships))
            
            return schema_metadata
            
        except Exception as e:
            logger.error("Failed to introspect schema", error=str(e))
            raise
    
    async def get_column_cardinality(
        self, 
        schema: str, 
        table: str, 
        column: str,
        max_distinct: int = 200
    ) -> Dict[str, Any]:
        """
        Get cardinality information for a column.
        
        Args:
            schema: Schema name
            table: Table name
            column: Column name
            max_distinct: Maximum distinct values to retrieve
            
        Returns:
            Dictionary with cardinality info and distinct values if low cardinality
        """
        try:
            # Get distinct count (with limit for performance)
            count_query = f"""
            SELECT COUNT(DISTINCT [{column}]) AS distinct_count
            FROM [{schema}].[{table}]
            """
            
            count_result = await self.execute_query(count_query)
            distinct_count = count_result[0]['distinct_count'] if count_result else 0
            
            result = {
                "schema": schema,
                "table": table,
                "column": column,
                "distinct_count": distinct_count,
                "is_low_cardinality": distinct_count <= max_distinct,
                "distinct_values": []
            }
            
            # If low cardinality, get the actual distinct values
            if distinct_count > 0 and distinct_count <= max_distinct:
                values_query = f"""
                SELECT DISTINCT TOP {max_distinct} [{column}] AS value
                FROM [{schema}].[{table}]
                WHERE [{column}] IS NOT NULL
                ORDER BY [{column}]
                """
                
                values_result = await self.execute_query(values_query)
                result["distinct_values"] = [row['value'] for row in values_result]
            
            return result
            
        except Exception as e:
            logger.error("Failed to get column cardinality", 
                        schema=schema, table=table, column=column, error=str(e))
            raise
