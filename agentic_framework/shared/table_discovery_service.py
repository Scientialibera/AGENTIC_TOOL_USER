"""
Table Discovery Service

Uses embeddings to match natural language queries to relevant database tables.
Provides semantic search over table/column metadata to help the LLM
focus on the most relevant schema elements.
"""

import asyncio
import structlog
from typing import List, Optional, Dict, Any
from dataclasses import dataclass
from datetime import datetime

from .aoai_client import AzureOpenAIClient
from .cosmos_client import CosmosDBClient
from .config import get_settings

logger = structlog.get_logger(__name__)
settings = get_settings()


@dataclass
class ColumnMetadata:
    """Column metadata with embeddings."""
    name: str
    type: str
    description: Optional[str]
    is_primary_key: bool = False
    is_foreign_key: bool = False
    is_low_cardinality: bool = False
    cardinality: Optional[int] = None
    sample_values: Optional[List[str]] = None
    embedding: Optional[List[float]] = None


@dataclass
class RelationshipMetadata:
    """Table relationship metadata."""
    type: str  # one_to_many, many_to_one, many_to_many
    target_table: str
    foreign_key: str
    description: Optional[str] = None


@dataclass
class TableMetadata:
    """Table metadata with embeddings."""
    table_name: str
    schema: str = "dbo"
    description: Optional[str] = None
    embedding: Optional[List[float]] = None
    columns: List[ColumnMetadata] = None
    relationships: List[RelationshipMetadata] = None
    row_count: Optional[int] = None
    last_updated: Optional[datetime] = None
    similarity_score: float = 0.0  # Set during search

    def __post_init__(self):
        if self.columns is None:
            self.columns = []
        if self.relationships is None:
            self.relationships = []


class TableDiscoveryService:
    """
    Discovers relevant tables for a user query using semantic embeddings.
    """

    def __init__(
        self,
        cosmos_client: CosmosDBClient,
        aoai_client: AzureOpenAIClient,
    ):
        self.cosmos_client = cosmos_client
        self.aoai_client = aoai_client
        self.container_name = settings.cosmos.table_metadata_container
        self.similarity_threshold = settings.text_to_sql.similarity_threshold
        self.max_tables = settings.text_to_sql.max_tables_per_query
        self.logger = logger.bind(service="table_discovery")

    async def discover_tables(
        self,
        user_query: str,
        max_tables: Optional[int] = None,
        similarity_threshold: Optional[float] = None,
    ) -> List[TableMetadata]:
        """
        Find the most relevant tables for a user query using embeddings.

        Args:
            user_query: Natural language query from the user
            max_tables: Maximum number of tables to return (default from config)
            similarity_threshold: Minimum similarity score (default from config)

        Returns:
            List of TableMetadata objects sorted by relevance
        """
        max_tables = max_tables or self.max_tables
        similarity_threshold = similarity_threshold or self.similarity_threshold

        self.logger.info(
            "Discovering tables for query",
            query=user_query[:100],
            max_tables=max_tables,
            threshold=similarity_threshold,
        )

        # Generate embedding for user query
        query_embedding = await self.aoai_client.generate_embedding(user_query)

        # Search for similar tables using vector search
        # Note: Cosmos DB supports vector search with ORDER BY VectorDistance()
        # This requires the container to have vector indexing enabled
        query = f"""
        SELECT TOP @max_tables *
        FROM c
        ORDER BY VectorDistance(c.embedding, @query_embedding)
        """

        parameters = [
            {"name": "@max_tables", "value": max_tables},
            {"name": "@query_embedding", "value": query_embedding},
        ]

        try:
            results = await self.cosmos_client.query_items(
                self.container_name,
                query,
                parameters=parameters,
            )

            tables = []
            for item in results:
                # Calculate similarity score (cosine similarity)
                similarity = self._cosine_similarity(query_embedding, item.get("embedding", []))

                if similarity < similarity_threshold:
                    continue

                table = self._parse_table_metadata(item)
                table.similarity_score = similarity
                tables.append(table)

            tables.sort(key=lambda t: t.similarity_score, reverse=True)

            self.logger.info(
                "Table discovery complete",
                tables_found=len(tables),
                top_table=tables[0].table_name if tables else None,
                top_score=tables[0].similarity_score if tables else None,
            )

            return tables

        except Exception as e:
            self.logger.error("Table discovery failed", error=str(e))
            return []

    async def get_table_metadata(self, table_name: str, schema: str = "dbo") -> Optional[TableMetadata]:
        """
        Get metadata for a specific table.

        Args:
            table_name: Table name
            schema: Schema name (default: dbo)

        Returns:
            TableMetadata or None if not found
        """
        query = "SELECT * FROM c WHERE c.table_name = @table_name AND c.schema = @schema"
        parameters = [
            {"name": "@table_name", "value": table_name},
            {"name": "@schema", "value": schema},
        ]

        try:
            results = await self.cosmos_client.query_items(
                self.container_name,
                query,
                parameters=parameters,
            )

            if results:
                return self._parse_table_metadata(results[0])

            return None

        except Exception as e:
            self.logger.error("Failed to get table metadata", table=table_name, error=str(e))
            return None

    async def index_table_metadata(
        self,
        table_name: str,
        schema: str,
        description: Optional[str] = None,
        columns: Optional[List[Dict[str, Any]]] = None,
        relationships: Optional[List[Dict[str, Any]]] = None,
    ) -> bool:
        """
        Index or update table metadata with embeddings.

        This should be called when:
        - New tables are added to the database
        - Table descriptions are updated
        - Schema changes occur

        Args:
            table_name: Table name
            schema: Schema name
            description: Table description for embedding generation
            columns: List of column metadata dicts
            relationships: List of relationship metadata dicts

        Returns:
            True if successful
        """
        try:
            # Generate embedding for table
            # Combine table name + description + column names for rich embedding
            embedding_text = f"{table_name}"
            if description:
                embedding_text += f". {description}"
            if columns:
                col_names = ", ".join([c.get("name", "") for c in columns])
                embedding_text += f". Columns: {col_names}"

            table_embedding = await self.aoai_client.generate_embedding(embedding_text)

            # Generate embeddings for columns
            column_metadata = []
            if columns:
                for col in columns:
                    col_embedding_text = f"{col.get('name', '')}"
                    if col.get("description"):
                        col_embedding_text += f". {col['description']}"

                    col_embedding = await self.aoai_client.generate_embedding(col_embedding_text)

                    column_metadata.append(
                        {
                            "name": col.get("name", ""),
                            "type": col.get("type", ""),
                            "description": col.get("description"),
                            "is_primary_key": col.get("is_primary_key", False),
                            "is_foreign_key": col.get("is_foreign_key", False),
                            "is_low_cardinality": col.get("is_low_cardinality", False),
                            "cardinality": col.get("cardinality"),
                            "sample_values": col.get("sample_values"),
                            "embedding": col_embedding,
                        }
                    )

            # Create document
            document = {
                "id": f"{schema}_{table_name}",
                "table_name": table_name,
                "schema": schema,
                "description": description,
                "embedding": table_embedding,
                "columns": column_metadata,
                "relationships": relationships or [],
                "last_updated": datetime.utcnow().isoformat(),
            }

            # Upsert to Cosmos DB
            await self.cosmos_client.upsert_item(self.container_name, document)

            self.logger.info(
                "Table metadata indexed",
                table=table_name,
                columns_count=len(column_metadata),
            )

            return True

        except Exception as e:
            self.logger.error("Failed to index table metadata", table=table_name, error=str(e))
            return False

    def _parse_table_metadata(self, item: Dict[str, Any]) -> TableMetadata:
        """Parse Cosmos DB item into TableMetadata object."""
        columns = []
        for col_data in item.get("columns", []):
            columns.append(
                ColumnMetadata(
                    name=col_data.get("name", ""),
                    type=col_data.get("type", ""),
                    description=col_data.get("description"),
                    is_primary_key=col_data.get("is_primary_key", False),
                    is_foreign_key=col_data.get("is_foreign_key", False),
                    is_low_cardinality=col_data.get("is_low_cardinality", False),
                    cardinality=col_data.get("cardinality"),
                    sample_values=col_data.get("sample_values"),
                    embedding=col_data.get("embedding"),
                )
            )

        relationships = []
        for rel_data in item.get("relationships", []):
            relationships.append(
                RelationshipMetadata(
                    type=rel_data.get("type", ""),
                    target_table=rel_data.get("target_table", ""),
                    foreign_key=rel_data.get("foreign_key", ""),
                    description=rel_data.get("description"),
                )
            )

        last_updated = None
        if item.get("last_updated"):
            try:
                last_updated = datetime.fromisoformat(item["last_updated"])
            except ValueError:
                pass

        return TableMetadata(
            table_name=item.get("table_name", ""),
            schema=item.get("schema", "dbo"),
            description=item.get("description"),
            embedding=item.get("embedding"),
            columns=columns,
            relationships=relationships,
            row_count=item.get("row_count"),
            last_updated=last_updated,
        )

    @staticmethod
    def _cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
        """Calculate cosine similarity between two vectors."""
        if not vec1 or not vec2 or len(vec1) != len(vec2):
            return 0.0

        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        magnitude1 = sum(a * a for a in vec1) ** 0.5
        magnitude2 = sum(b * b for b in vec2) ** 0.5

        if magnitude1 == 0 or magnitude2 == 0:
            return 0.0

        return dot_product / (magnitude1 * magnitude2)
