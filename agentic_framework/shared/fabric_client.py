"""
Fabric client with DefaultAzureCredential authentication.
"""

import asyncio
from typing import Optional, Dict, Any, List
import pyodbc
from azure.identity import DefaultAzureCredential
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import structlog

from shared.config import FabricSettings

logger = structlog.get_logger(__name__)


class FabricClient:
    """Microsoft Fabric lakehouse client."""
    
    def __init__(self, settings: FabricSettings):
        """Initialize the Fabric client."""
        self.settings = settings
        self._credential = DefaultAzureCredential()
        
        logger.info(
            "Initialized Fabric client",
            endpoint=settings.sql_endpoint,
            database=settings.database,
        )
    
    def _build_connection_string(self, access_token: str) -> str:
        """Build SQL connection string with access token."""
        return (
            f"Driver={{ODBC Driver 18 for SQL Server}};"
            f"Server={self.settings.sql_endpoint};"
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
        """Execute a SQL query against Fabric lakehouse."""
        try:
            logger.debug("Executing Fabric SQL query", query=query[:100])
            
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
            
            logger.debug("Fabric SQL query executed", result_count=len(results))
            return results
            
        except Exception as e:
            logger.error("Failed to execute Fabric SQL query", error=str(e))
            raise
