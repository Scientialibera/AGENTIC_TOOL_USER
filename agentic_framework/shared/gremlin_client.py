"""
Gremlin client with DefaultAzureCredential authentication.
"""

import asyncio
from typing import Optional, Dict, Any, List
from azure.identity import DefaultAzureCredential
from gremlin_python.driver import client
from gremlin_python.driver import serializer
from urllib.parse import urlparse
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import structlog

from shared.config import GremlinSettings

logger = structlog.get_logger(__name__)


class GremlinClient:
    """Gremlin client with managed identity authentication."""
    
    def __init__(self, settings: GremlinSettings):
        """Initialize the Gremlin client."""
        self.settings = settings
        self._credential = DefaultAzureCredential()
        
        logger.info(
            "Initialized Gremlin client",
            endpoint=settings.endpoint,
            database=settings.database_name,
            graph=settings.graph_name,
        )
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((Exception,)),
    )
    async def execute_query(
        self,
        query: str,
        bindings: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Execute a Gremlin query."""
        try:
            logger.debug("Executing Gremlin query", query=query[:100])
            
            token = self._credential.get_token("https://cosmos.azure.com/.default")
            
            parsed = urlparse(self.settings.endpoint)
            host = parsed.hostname or self.settings.endpoint
            port = parsed.port or 443
            
            gremlin_client = client.Client(
                f"wss://{host}:{port}/gremlin",
                "g",
                username=f"/dbs/{self.settings.database_name}/colls/{self.settings.graph_name}",
                password=token.token,
                message_serializer=serializer.GraphSONSerializersV2d0()
            )
            
            def execute_sync():
                try:
                    rs = gremlin_client.submit(message=query, bindings=(bindings or {}))
                    return rs.all().result()
                finally:
                    gremlin_client.close()
            
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(None, execute_sync)
            
            logger.debug("Gremlin query executed", result_count=len(results))
            return results
            
        except Exception as e:
            logger.error("Failed to execute Gremlin query", error=str(e))
            raise
