"""
Fabric client with DefaultAzureCredential authentication.
"""

import asyncio
import struct
from typing import Optional, Dict, Any, List
import pyodbc
from azure.identity import DefaultAzureCredential
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import structlog

from shared.config import FabricSettings

logger = structlog.get_logger(__name__)


class FabricClient:
    """Microsoft Fabric lakehouse client."""
    
    def __init__(self, settings: FabricSettings, sql_settings=None):
        """Initialize the Fabric client."""
        self.settings = settings
        self.sql_settings = sql_settings
        self._credential = DefaultAzureCredential()
        self._driver = self._resolve_driver()
        self._server, self._database, self._token_scope = self._resolve_target()
        self._server = self._normalize_server(self._server)
        
        logger.info(
            "Initialized Fabric client",
            endpoint=self._server,
            database=self._database,
            driver=self._driver,
        )
    
    def _resolve_target(self):
        """Pick server/db/scope from Azure SQL settings when available; otherwise use Fabric settings."""
        server = None
        database = None
        token_scope = None

        # Prefer Azure SQL settings if provided
        if self.sql_settings and getattr(self.sql_settings, "enabled", False):
            server = getattr(self.sql_settings, "server", None)
            database = getattr(self.sql_settings, "database", None)
            token_scope = getattr(self.sql_settings, "token_scope", None)

        # Fallback to Fabric settings
        if not server:
            server = self.settings.sql_endpoint
        if not database:
            database = self.settings.database
        if not token_scope:
            token_scope = self.settings.token_scope

        return server, database, token_scope

    def _normalize_server(self, server: str) -> str:
        """Ensure server string is in tcp:host,1433 format for Azure SQL."""
        if not server:
            return server
        s = server.strip()
        # If already includes a comma or tcp prefix, leave as-is
        if s.lower().startswith("tcp:"):
            return s
        if "," in s:
            return s
        return f"tcp:{s},1433"

    def _resolve_driver(self) -> str:
        """Pick an available ODBC driver with fallbacks (18 -> 17 -> SQL Server)."""
        available = {d.lower(): d for d in pyodbc.drivers()}
        preferred = [
            self.settings.driver,
            "ODBC Driver 18 for SQL Server",
            "ODBC Driver 17 for SQL Server",
            "SQL Server",
        ]

        for name in preferred:
            if not name:
                continue
            key = name.lower()
            if key in available:
                chosen = available[key]
                logger.info("Using ODBC driver", driver=chosen)
                return chosen

        raise RuntimeError(
            "No supported ODBC driver found. Install 'ODBC Driver 17 for SQL Server' or 'ODBC Driver 18 for SQL Server'."
        )

    def _build_connection_string(self, access_token: str) -> str:
        """Build SQL connection string with access token."""
        return (
            f"Driver={{{self._driver}}};"
            f"Server={self._server};"
            f"Database={self._database};"
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
            
            token = self._credential.get_token(self._token_scope)
            
            def execute_sync():
                conn_str = self._build_connection_string(token.token)
                token_bytes = token.token.encode('utf-16-le')
                token_struct = struct.pack('<I', len(token_bytes)) + token_bytes

                conn = pyodbc.connect(conn_str, attrs_before={
                    1256: token_struct
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
