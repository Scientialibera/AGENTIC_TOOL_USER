"""
Azure Cosmos DB client with DefaultAzureCredential authentication.
"""

from typing import Optional, Dict, Any, List
from azure.identity import DefaultAzureCredential
from azure.cosmos.aio import CosmosClient as AsyncCosmosClient
from azure.cosmos import exceptions
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import structlog

from shared.config import CosmosDBSettings

logger = structlog.get_logger(__name__)


class CosmosDBClient:
    """Azure Cosmos DB client with managed identity authentication."""
    
    def __init__(self, settings: CosmosDBSettings):
        """Initialize the Cosmos DB client."""
        self.settings = settings
        self._credential = DefaultAzureCredential()
        self._client: Optional[AsyncCosmosClient] = None
        self._database = None
        self._containers: Dict[str, Any] = {}
        
        logger.info(
            "Initialized Cosmos DB client",
            endpoint=settings.endpoint,
            database=settings.database_name,
        )
    
    async def _get_client(self) -> AsyncCosmosClient:
        """Get or create Cosmos DB client."""
        if self._client is None:
            self._client = AsyncCosmosClient(
                url=self.settings.endpoint,
                credential=self._credential,
            )
            logger.info("Created Cosmos DB client with managed identity")
        return self._client
    
    async def _get_database(self):
        """Get database reference."""
        if self._database is None:
            client = await self._get_client()
            try:
                database = client.get_database_client(self.settings.database_name)
                await database.read()
                self._database = database
                logger.debug("Connected to database", database=self.settings.database_name)
            except exceptions.CosmosResourceNotFoundError:
                msg = f"Database '{self.settings.database_name}' not found"
                logger.error(msg)
                raise RuntimeError(msg)
        return self._database
    
    async def get_container(self, container_name: str):
        """Get container reference."""
        if container_name not in self._containers:
            database = await self._get_database()
            container = database.get_container_client(container_name)
            self._containers[container_name] = container
            logger.debug("Got container reference", container=container_name)
        return self._containers[container_name]
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((exceptions.CosmosHttpResponseError,)),
    )
    async def query_items(
        self,
        container_name: str,
        query: str,
        parameters: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """Query items from a container."""
        try:
            container = await self.get_container(container_name)
            
            items = []
            async for item in container.query_items(
                query=query,
                parameters=parameters or [],
            ):
                items.append(item)
            
            logger.debug(
                "Queried items",
                container=container_name,
                result_count=len(items),
            )
            return items
            
        except Exception as e:
            logger.error(
                "Failed to query items",
                container=container_name,
                error=str(e),
            )
            raise

    async def close(self):
        """Close the client and cleanup resources."""
        if self._client:
            await self._client.close()
            self._client = None
