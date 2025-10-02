"""
Repository for managing SQL schema metadata and semantic models.

This module handles storage and retrieval of database schema information,
table definitions, column metadata, and join relationships for SQL agent.
"""

from typing import Any, Dict, List, Optional
from datetime import datetime
import structlog

from azure.cosmos import exceptions as cosmos_exceptions
from azure.cosmos.aio import CosmosClient

logger = structlog.get_logger(__name__)


class TableMetadata:
    """Metadata for a database table."""
    
    def __init__(
        self,
        table_name: str,
        schema_name: str,
        description: str,
        columns: List[Dict[str, Any]],
        primary_key: Optional[List[str]] = None,
        foreign_keys: Optional[List[Dict[str, str]]] = None,
        indexes: Optional[List[Dict[str, Any]]] = None
    ):
        self.table_name = table_name
        self.schema_name = schema_name
        self.description = description
        self.columns = columns
        self.primary_key = primary_key or []
        self.foreign_keys = foreign_keys or []
        self.indexes = indexes or []


class SQLSchemaRepository:
    """Repository for managing SQL schema metadata."""
    
    def __init__(self, cosmos_client: CosmosClient, database_name: str, container_name: str):
        """
        Initialize the SQL schema repository.
        
        Args:
            cosmos_client: Azure Cosmos DB client
            database_name: Cosmos database name
            container_name: Container name for schema metadata
        """
        self.cosmos_client = cosmos_client
        self.database_name = database_name
        self.container_name = container_name
        self._container = None
        
    async def _get_container(self):
        """Get or create the container reference."""
        if self._container is None:
            database = await self.cosmos_client.get_database_client(self.database_name)
            self._container = database.get_container_client(self.container_name)
        return self._container
    
    async def save_table_metadata(
        self,
        table_metadata: TableMetadata,
        tenant_id: Optional[str] = None
    ) -> str:
        """
        Save or update table metadata.
        
        Args:
            table_metadata: Table metadata to save
            tenant_id: Optional tenant ID for multi-tenant schemas
            
        Returns:
            Table metadata ID
        """
        try:
            container = await self._get_container()
            
            table_id = f"{table_metadata.schema_name}.{table_metadata.table_name}"
            if tenant_id:
                table_id = f"{tenant_id}.{table_id}"
            
            metadata_doc = {
                "id": table_id,
                "table_name": table_metadata.table_name,
                "schema_name": table_metadata.schema_name,
                "full_name": f"{table_metadata.schema_name}.{table_metadata.table_name}",
                "description": table_metadata.description,
                "columns": table_metadata.columns,
                "primary_key": table_metadata.primary_key,
                "foreign_keys": table_metadata.foreign_keys,
                "indexes": table_metadata.indexes,
                "tenant_id": tenant_id,
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
            }
            
            await container.upsert_item(metadata_doc)
            
            logger.info(
                "Saved table metadata",
                table_id=table_id,
                table_name=table_metadata.table_name,
                schema_name=table_metadata.schema_name,
                tenant_id=tenant_id
            )
            
            return table_id
            
        except Exception as e:
            logger.error(
                "Failed to save table metadata",
                table_name=table_metadata.table_name,
                schema_name=table_metadata.schema_name,
                error=str(e)
            )
            raise
    
    async def get_table_metadata(
        self,
        schema_name: str,
        table_name: str,
        tenant_id: Optional[str] = None
    ) -> Optional[TableMetadata]:
        """
        Get metadata for a specific table.
        
        Args:
            schema_name: Database schema name
            table_name: Table name
            tenant_id: Optional tenant ID
            
        Returns:
            Table metadata or None if not found
        """
        try:
            container = await self._get_container()
            
            table_id = f"{schema_name}.{table_name}"
            if tenant_id:
                table_id = f"{tenant_id}.{table_id}"
            
            item = await container.read_item(
                item=table_id,
                partition_key=table_id
            )
            
            return TableMetadata(
                table_name=item["table_name"],
                schema_name=item["schema_name"],
                description=item["description"],
                columns=item["columns"],
                primary_key=item.get("primary_key", []),
                foreign_keys=item.get("foreign_keys", []),
                indexes=item.get("indexes", [])
            )
            
        except cosmos_exceptions.CosmosResourceNotFoundError:
            logger.warning(
                "Table metadata not found",
                schema_name=schema_name,
                table_name=table_name,
                tenant_id=tenant_id
            )
            return None
        except Exception as e:
            logger.error(
                "Failed to get table metadata",
                schema_name=schema_name,
                table_name=table_name,
                tenant_id=tenant_id,
                error=str(e)
            )
            raise
    
    async def list_tables_in_schema(
        self,
        schema_name: str,
        tenant_id: Optional[str] = None
    ) -> List[TableMetadata]:
        """
        List all tables in a schema.
        
        Args:
            schema_name: Database schema name
            tenant_id: Optional tenant ID
            
        Returns:
            List of table metadata
        """
        try:
            container = await self._get_container()
            
            # Build query with optional tenant filtering
            where_conditions = ["c.schema_name = @schema_name"]
            parameters = [{"name": "@schema_name", "value": schema_name}]
            
            if tenant_id:
                where_conditions.append("c.tenant_id = @tenant_id")
                parameters.append({"name": "@tenant_id", "value": tenant_id})
            else:
                where_conditions.append("NOT IS_DEFINED(c.tenant_id)")
            
            where_clause = " AND ".join(where_conditions)
            query = f"SELECT * FROM c WHERE {where_clause}"
            
            tables = []
            async for item in container.query_items(
                query=query,
                parameters=parameters
            ):
                tables.append(TableMetadata(
                    table_name=item["table_name"],
                    schema_name=item["schema_name"],
                    description=item["description"],
                    columns=item["columns"],
                    primary_key=item.get("primary_key", []),
                    foreign_keys=item.get("foreign_keys", []),
                    indexes=item.get("indexes", [])
                ))
            
            logger.info(
                "Listed tables in schema",
                schema_name=schema_name,
                tenant_id=tenant_id,
                count=len(tables)
            )
            
            return tables
            
        except Exception as e:
            logger.error(
                "Failed to list tables in schema",
                schema_name=schema_name,
                tenant_id=tenant_id,
                error=str(e)
            )
            raise
    
    async def search_tables_by_keyword(
        self,
        keyword: str,
        tenant_id: Optional[str] = None,
        limit: int = 20
    ) -> List[TableMetadata]:
        """
        Search tables by keyword in name or description.
        
        Args:
            keyword: Search keyword
            tenant_id: Optional tenant ID
            limit: Maximum number of results
            
        Returns:
            List of matching table metadata
        """
        try:
            container = await self._get_container()
            
            # Build search query
            where_conditions = [
                "(CONTAINS(LOWER(c.table_name), LOWER(@keyword)) OR CONTAINS(LOWER(c.description), LOWER(@keyword)))"
            ]
            parameters = [{"name": "@keyword", "value": keyword}]
            
            if tenant_id:
                where_conditions.append("c.tenant_id = @tenant_id")
                parameters.append({"name": "@tenant_id", "value": tenant_id})
            else:
                where_conditions.append("NOT IS_DEFINED(c.tenant_id)")
            
            where_clause = " AND ".join(where_conditions)
            query = f"SELECT TOP @limit * FROM c WHERE {where_clause}"
            parameters.append({"name": "@limit", "value": limit})
            
            tables = []
            async for item in container.query_items(
                query=query,
                parameters=parameters
            ):
                tables.append(TableMetadata(
                    table_name=item["table_name"],
                    schema_name=item["schema_name"],
                    description=item["description"],
                    columns=item["columns"],
                    primary_key=item.get("primary_key", []),
                    foreign_keys=item.get("foreign_keys", []),
                    indexes=item.get("indexes", [])
                ))
            
            logger.info(
                "Searched tables by keyword",
                keyword=keyword,
                tenant_id=tenant_id,
                count=len(tables)
            )
            
            return tables
            
        except Exception as e:
            logger.error(
                "Failed to search tables",
                keyword=keyword,
                tenant_id=tenant_id,
                error=str(e)
            )
            raise
    
    async def get_related_tables(
        self,
        schema_name: str,
        table_name: str,
        tenant_id: Optional[str] = None
    ) -> List[TableMetadata]:
        """
        Get tables related through foreign key relationships.
        
        Args:
            schema_name: Database schema name
            table_name: Table name
            tenant_id: Optional tenant ID
            
        Returns:
            List of related table metadata
        """
        try:
            container = await self._get_container()
            
            full_table_name = f"{schema_name}.{table_name}"
            
            # Find tables with foreign keys to this table or tables this table references
            where_conditions = [
                "(ARRAY_CONTAINS(c.foreign_keys, {'referenced_table': @table_name}, true) OR c.full_name IN (SELECT VALUE fk.referenced_table FROM fk IN @table_name.foreign_keys))"
            ]
            parameters = [{"name": "@table_name", "value": full_table_name}]
            
            if tenant_id:
                where_conditions.append("c.tenant_id = @tenant_id")
                parameters.append({"name": "@tenant_id", "value": tenant_id})
            else:
                where_conditions.append("NOT IS_DEFINED(c.tenant_id)")
            
            where_clause = " AND ".join(where_conditions)
            query = f"SELECT * FROM c WHERE {where_clause}"
            
            related_tables = []
            async for item in container.query_items(
                query=query,
                parameters=parameters
            ):
                # Skip the original table
                if item["full_name"] != full_table_name:
                    related_tables.append(TableMetadata(
                        table_name=item["table_name"],
                        schema_name=item["schema_name"],
                        description=item["description"],
                        columns=item["columns"],
                        primary_key=item.get("primary_key", []),
                        foreign_keys=item.get("foreign_keys", []),
                        indexes=item.get("indexes", [])
                    ))
            
            logger.info(
                "Found related tables",
                schema_name=schema_name,
                table_name=table_name,
                tenant_id=tenant_id,
                count=len(related_tables)
            )
            
            return related_tables
            
        except Exception as e:
            logger.error(
                "Failed to get related tables",
                schema_name=schema_name,
                table_name=table_name,
                tenant_id=tenant_id,
                error=str(e)
            )
            raise
    
    async def delete_table_metadata(
        self,
        schema_name: str,
        table_name: str,
        tenant_id: Optional[str] = None
    ) -> bool:
        """
        Delete table metadata.
        
        Args:
            schema_name: Database schema name
            table_name: Table name
            tenant_id: Optional tenant ID
            
        Returns:
            True if deleted successfully
        """
        try:
            container = await self._get_container()
            
            table_id = f"{schema_name}.{table_name}"
            if tenant_id:
                table_id = f"{tenant_id}.{table_id}"
            
            await container.delete_item(
                item=table_id,
                partition_key=table_id
            )
            
            logger.info(
                "Deleted table metadata",
                schema_name=schema_name,
                table_name=table_name,
                tenant_id=tenant_id
            )
            return True
            
        except cosmos_exceptions.CosmosResourceNotFoundError:
            logger.warning(
                "Table metadata not found for deletion",
                schema_name=schema_name,
                table_name=table_name,
                tenant_id=tenant_id
            )
            return False
        except Exception as e:
            logger.error(
                "Failed to delete table metadata",
                schema_name=schema_name,
                table_name=table_name,
                tenant_id=tenant_id,
                error=str(e)
            )
            raise
