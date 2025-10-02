"""
Azure Cosmos DB client with Managed Identity authentication.

This module provides a client for Cosmos DB NoSQL operations using DefaultAzureCredential
for authentication and proper error handling with retry logic.
"""

import asyncio
import logging
from typing import Optional, Dict, Any, List, Union
from azure.identity import DefaultAzureCredential
from azure.cosmos.aio import CosmosClient as AsyncCosmosClient
from azure.cosmos import PartitionKey, exceptions
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)
import structlog

from orchestrator.config.settings import CosmosDBSettings

logger = structlog.get_logger(__name__)


class CosmosDBClient:
    """
    Azure Cosmos DB client with Managed Identity authentication and retry logic.
    
    This client handles:
    - Token-based authentication using DefaultAzureCredential
    - Automatic container creation if needed
    - Retry logic for transient failures
    - Proper error handling and logging
    """
    
    def __init__(self, settings: CosmosDBSettings):
        """
        Initialize the Cosmos DB client.
        
        Args:
            settings: Cosmos DB configuration settings
        """
        self.settings = settings
        self._credential = DefaultAzureCredential()
        self._client: Optional[AsyncCosmosClient] = None
        self._database = None
        self._containers: Dict[str, Any] = {}
        
        logger.info(
            "Initializing Cosmos DB client",
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
        """Get or create database."""
        if self._database is None:
            client = await self._get_client()
            # Attempt to get existing database; if not found, create it.
            try:
                database = client.get_database_client(self.settings.database_name)
                # touch/read to verify existence
                await database.read()
                self._database = database
                logger.debug("Connected to existing database", database=self.settings.database_name)

            except exceptions.CosmosResourceNotFoundError:
                # Database does not exist. The application previously attempted to create
                # databases/containers automatically. That operation requires key-based
                # authorization for Cosmos DB management operations in many setups.
                # Do NOT attempt to auto-provision here; surface a clear error so the
                # operator can pre-create the database (recommended) or provide keys.
                msg = (
                    f"Database '{self.settings.database_name}' not found. "
                    "Auto-provisioning is disabled. Please create the database and required containers "
                    "manually, or run the app with explicit provisioning enabled. See https://aka.ms/cosmos-native-rbac"
                )
                logger.error(msg)
                raise RuntimeError(msg)
            except Exception as e:
                logger.error("Failed to get or create database", database=self.settings.database_name, error=str(e))
                raise
        
        return self._database
    
    async def get_database_client(self, database_name: str):
        """Public method to get database client for repositories."""
        if database_name != self.settings.database_name:
            logger.warning(f"Requested database {database_name} but configured for {self.settings.database_name}")
        
        return await self._get_database()
    
    async def _get_container(self, container_name: str, partition_key: str = "/id"):
        """Get or create container."""
        if container_name not in self._containers:
            database = await self._get_database()
            
            try:
                # Try to get existing container (async SDK pattern)
                container = database.get_container_client(container_name)
                await container.read()
                self._containers[container_name] = container
                logger.debug("Connected to existing container", container=container_name)

            except exceptions.CosmosResourceNotFoundError:
                # Create container if it doesn't exist
                try:
                    # If running in dev mode, avoid management operations that require AAD data-plane permissions.
                    # Container missing. Creating containers requires management permissions
                    # which are often blocked when using AAD tokens for the data plane.
                    # We will NOT auto-create containers here to avoid unexpected management calls.
                    msg = (
                        f"Container '{container_name}' not found in database '{self.settings.database_name}'. "
                        "Auto-creation of containers is disabled. Pre-create the container or enable provisioning explicitly. "
                        "See https://aka.ms/cosmos-native-rbac for details."
                    )
                    logger.error(msg)
                    raise RuntimeError(msg)
                except Exception as e:
                    # Common cause: AAD token cannot perform data-plane management operations.
                    msg = str(e)
                    if "cannot be authorized by AAD token" in msg or "Request blocked by Auth" in msg or (hasattr(e, 'status_code') and getattr(e, 'status_code') == 403):
                        logger.error(
                            "Failed to create container due to AAD data-plane authorization. "
                            "Cosmos may require key auth for management operations or pre-created containers. "
                            "See https://aka.ms/cosmos-native-rbac for details.",
                            container=container_name,
                            error=msg
                        )
                        # If running in dev mode, fall back to an in-memory container instead of failing hard.
                        if getattr(self.settings, 'dev_mode', False):
                            logger.info("Dev mode and AAD forbidden: using in-memory fallback for container", container=container_name)
                            class InMemoryContainer:
                                def __init__(self):
                                    self._items = {}

                                async def create_item(self, body):
                                    _id = body.get('id') or str(len(self._items) + 1)
                                    body['id'] = _id
                                    self._items[_id] = body
                                    return body

                                async def read_item(self, item, partition_key=None):
                                    return self._items.get(item)

                                async def upsert_item(self, body):
                                    _id = body.get('id') or str(len(self._items) + 1)
                                    body['id'] = _id
                                    self._items[_id] = body
                                    return body

                            container = InMemoryContainer()
                            self._containers[container_name] = container
                            logger.info("Created in-memory fallback container for dev after AAD forbidden", container=container_name)
                        else:
                            raise
                    else:
                        logger.error("Failed to create container", container=container_name, error=msg)
                        raise
            except Exception as e:
                logger.error("Failed to get container", container=container_name, error=str(e))
                raise
        
        return self._containers[container_name]

    async def _get_container_for_db(self, database_name: str, container_name: str, partition_key: str = "/id"):
        """Get or create a container on a specific database name.

        This mirrors _get_container but allows specifying a different database than
        the one configured in settings. It returns the underlying container
        object (SDK client or in-memory fallback) so callers can call async
        methods like create_item / query_items on it.
        """
        # If requesting the configured database, reuse existing path
        if database_name == self.settings.database_name:
            return await self._get_container(container_name, partition_key)

        # Use or create a per-database container cache key
        key = f"{database_name}.{container_name}"
        if key in self._containers:
            return self._containers[key]

        client = await self._get_client()
        # Try to get a database client for the requested database
        try:
            database = client.get_database_client(database_name)
            # Touch/read to verify existence
            try:
                await database.read()
            except exceptions.CosmosResourceNotFoundError:
                logger.info("Database not found, creating new database", database=database_name)
                database = await client.create_database(database_name)
                logger.info("Created new database", database=database_name)

                try:
                    container = database.get_container_client(container_name)
                    await container.read()
                    self._containers[key] = container
                    logger.debug("Connected to existing container", database=database_name, container=container_name)
                except exceptions.CosmosResourceNotFoundError:
                    # Create container if missing (respect dev_mode)
                        # Container missing. Creating containers requires management permissions
                        # which are often blocked when using AAD tokens for the data plane.
                        msg = (
                            f"Container '{container_name}' not found in database '{database_name}'. "
                            "Auto-creation of containers is disabled. Pre-create the container or enable provisioning explicitly. "
                            "See https://aka.ms/cosmos-native-rbac for details."
                        )
                        logger.error(msg)
                        raise RuntimeError(msg)

        except Exception as e:
            logger.error("Failed to get or create container for database",
                         database=database_name, container=container_name, error=str(e))
            raise

        return self._containers[key]

    def get_container(self, database_name: str, container_name: str, partition_key: str = "/id"):
        """Public synchronous accessor that returns a proxy container object.

        Many services call get_container(...) synchronously and then await
        methods on the returned object (for example: await container.create_item(...)).
        To preserve that usage pattern we return a ContainerProxy which exposes
        async methods and internally resolves the real container when first used.
        """
        class ContainerProxy:
            def __init__(self, client: "CosmosDBClient", db: str, col: str, pk: str):
                self._client = client
                self._db = db
                self._col = col
                self._pk = pk
                self._resolved = None

            async def _resolve(self):
                if self._resolved is None:
                    self._resolved = await self._client._get_container_for_db(self._db, self._col, self._pk)
                return self._resolved

            async def create_item(self, body):
                container = await self._resolve()
                return await container.create_item(body)

            async def upsert_item(self, body):
                container = await self._resolve()
                return await container.upsert_item(body)

            async def read_item(self, item, partition_key=None):
                container = await self._resolve()
                return await container.read_item(item, partition_key=partition_key)

            async def delete_item(self, item, partition_key=None):
                container = await self._resolve()
                return await container.delete_item(item, partition_key=partition_key)

            async def query_items(self, query, parameters=None, **kwargs):
                container = await self._resolve()
                # Delegate as an async generator
                async for it in container.query_items(query=query, parameters=parameters or [], **kwargs):
                    yield it

        return ContainerProxy(self, database_name, container_name, partition_key)
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((exceptions.CosmosHttpResponseError,)),
    )
    async def create_item(
        self,
        container_name: str,
        item: Dict[str, Any],
        partition_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create an item in the specified container.
        
        Args:
            container_name: Name of the container
            item: Item data to create
            partition_key: Optional partition key path
            
        Returns:
            Created item with metadata
        """
        container = await self._get_container(container_name, partition_key or "/id")
        
        try:
            result = await container.create_item(body=item)
            logger.debug(
                "Item created",
                container=container_name,
                item_id=item.get("id"),
                ru_charge=result.get("_charge", 0),
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
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((exceptions.CosmosHttpResponseError,)),
    )
    async def read_item(
        self,
        container_name: str,
        item_id: str,
        partition_key_value: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Read an item from the specified container.
        
        Args:
            container_name: Name of the container
            item_id: ID of the item to read
            partition_key_value: Value of the partition key
            
        Returns:
            Item data or None if not found
        """
        container = await self._get_container(container_name)
        
        try:
            result = await container.read_item(
                item=item_id,
                partition_key=partition_key_value,
            )
            logger.debug(
                "Item read",
                container=container_name,
                item_id=item_id,
                ru_charge=result.get("_charge", 0),
            )
            return result
            
        except exceptions.CosmosResourceNotFoundError:
            logger.debug("Item not found", container=container_name, item_id=item_id)
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
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((exceptions.CosmosHttpResponseError,)),
    )
    async def upsert_item(
        self,
        container_name: str,
        item: Dict[str, Any],
        partition_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Upsert an item in the specified container.
        
        Args:
            container_name: Name of the container
            item: Item data to upsert
            partition_key: Optional partition key path
            
        Returns:
            Upserted item with metadata
        """
        container = await self._get_container(container_name, partition_key or "/id")
        
        try:
            result = await container.upsert_item(body=item)
            logger.debug(
                "Item upserted",
                container=container_name,
                item_id=item.get("id"),
                ru_charge=result.get("_charge", 0),
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
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((exceptions.CosmosHttpResponseError,)),
    )
    async def delete_item(
        self,
        container_name: str,
        item_id: str,
        partition_key_value: str,
    ) -> bool:
        """
        Delete an item from the specified container.
        
        Args:
            container_name: Name of the container
            item_id: ID of the item to delete
            partition_key_value: Value of the partition key
            
        Returns:
            True if deleted, False if not found
        """
        container = await self._get_container(container_name)
        
        try:
            await container.delete_item(
                item=item_id,
                partition_key=partition_key_value,
            )
            logger.debug("Item deleted", container=container_name, item_id=item_id)
            return True
            
        except exceptions.CosmosResourceNotFoundError:
            logger.debug("Item not found for deletion", container=container_name, item_id=item_id)
            return False
        except Exception as e:
            logger.error(
                "Failed to delete item",
                container=container_name,
                item_id=item_id,
                error=str(e),
            )
            raise
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((exceptions.CosmosHttpResponseError,)),
    )
    async def query_items(
        self,
        container_name: str,
        query: str,
        parameters: Optional[List[Dict[str, Any]]] = None,
        partition_key_value: Optional[str] = None,
        max_item_count: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Query items from the specified container.
        
        Args:
            container_name: Name of the container
            query: SQL query string
            parameters: Optional query parameters
            partition_key_value: Optional partition key for cross-partition query
            max_item_count: Optional maximum number of items to return
            
        Returns:
            List of matching items
        """
        container = await self._get_container(container_name)
        
        try:
            query_options = {}
            if partition_key_value:
                query_options["partition_key"] = partition_key_value
            if max_item_count:
                query_options["max_item_count"] = max_item_count
            
            items = []
            async for item in container.query_items(
                query=query,
                parameters=parameters or [],
                **query_options
            ):
                items.append(item)
            
            logger.debug(
                "Items queried",
                container=container_name,
                query=query,
                result_count=len(items),
            )
            return items
            
        except Exception as e:
            logger.error(
                "Failed to query items",
                container=container_name,
                query=query,
                error=str(e),
            )
            raise
    
    async def close(self):
        """Close the client and clean up resources."""
        if self._client:
            await self._client.close()
            self._client = None
            self._database = None
            self._containers.clear()
        
        logger.info("Cosmos DB client closed")
