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

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((exceptions.CosmosHttpResponseError,)),
    )
    async def read_item(
        self,
        container_name: str,
        item_id: str,
        partition_key: Optional[str] = None,
        partition_key_value: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Read a single item from a container."""
        try:
            container = await self.get_container(container_name)

            # Use partition_key_value if provided, otherwise partition_key, otherwise item_id
            pk = partition_key_value or partition_key or item_id

            item = await container.read_item(
                item=item_id,
                partition_key=pk,
            )

            logger.debug(
                "Read item",
                container=container_name,
                item_id=item_id,
            )
            return item

        except exceptions.CosmosResourceNotFoundError:
            logger.debug(
                "Item not found",
                container=container_name,
                item_id=item_id,
            )
            return None
        except Exception as e:
            logger.error(
                "Failed to read item",
                container=container_name,
                item_id=item_id,
                error=str(e),
            )
            raise

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((exceptions.CosmosHttpResponseError,)),
    )
    async def create_item(
        self,
        container_name: str,
        item: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Create a new item in a container."""
        try:
            container = await self.get_container(container_name)

            result = await container.create_item(body=item)

            logger.debug(
                "Created item",
                container=container_name,
                item_id=item.get("id"),
            )
            return result

        except Exception as e:
            logger.error(
                "Failed to create item",
                container=container_name,
                item_id=item.get("id"),
                error=str(e),
            )
            raise

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((exceptions.CosmosHttpResponseError,)),
    )
    async def upsert_item(
        self,
        container_name: str,
        item: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Insert or update an item in a container."""
        try:
            container = await self.get_container(container_name)

            result = await container.upsert_item(body=item)

            logger.debug(
                "Upserted item",
                container=container_name,
                item_id=item.get("id"),
            )
            return result

        except Exception as e:
            logger.error(
                "Failed to upsert item",
                container=container_name,
                item_id=item.get("id"),
                error=str(e),
            )
            raise

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((exceptions.CosmosHttpResponseError,)),
    )
    async def replace_item(
        self,
        container_name: str,
        item_id: str,
        item: Dict[str, Any],
        partition_key: Optional[str] = None,
        partition_key_value: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Replace an existing item in a container."""
        try:
            container = await self.get_container(container_name)

            # The replace_item in Azure Cosmos SDK doesn't accept partition_key parameter
            # It infers the partition key from the item body
            # Just ensure the item has the correct partition key value in its fields
            result = await container.replace_item(
                item=item_id,
                body=item,
            )

            logger.debug(
                "Replaced item",
                container=container_name,
                item_id=item_id,
            )
            return result

        except Exception as e:
            logger.error(
                "Failed to replace item",
                container=container_name,
                item_id=item_id,
                error=str(e),
            )
            raise

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((exceptions.CosmosHttpResponseError,)),
    )
    async def delete_item(
        self,
        container_name: str,
        item_id: str,
        partition_key: Optional[str] = None,
        partition_key_value: Optional[str] = None,
    ) -> None:
        """Delete an item from a container."""
        try:
            container = await self.get_container(container_name)

            # Use partition_key_value if provided, otherwise partition_key, otherwise item_id
            pk = partition_key_value or partition_key or item_id

            await container.delete_item(
                item=item_id,
                partition_key=pk,
            )

            logger.debug(
                "Deleted item",
                container=container_name,
                item_id=item_id,
            )

        except exceptions.CosmosResourceNotFoundError:
            logger.debug(
                "Item not found (already deleted)",
                container=container_name,
                item_id=item_id,
            )
        except Exception as e:
            logger.error(
                "Failed to delete item",
                container=container_name,
                item_id=item_id,
                error=str(e),
            )
            raise

    async def close(self):
        """Close the client and cleanup resources."""
        if self._client:
            await self._client.close()
            self._client = None
