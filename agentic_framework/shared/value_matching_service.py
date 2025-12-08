"""
Value Matching Service

Handles fuzzy matching of user-provided values to exact database values.
Critical for low-cardinality fields where exact matches are required for queries to succeed.

Examples:
- User input: "open" -> Database value: "Open"
- User input: "in progress" -> Database value: "In Progress"
- User input: "Microsft" -> Database value: "Microsoft Corporation"
"""

import asyncio
import structlog
from typing import List, Optional, Dict, Any, Tuple
from dataclasses import dataclass
from datetime import datetime
from rapidfuzz import fuzz, process

from .aoai_client import AzureOpenAIClient
from .cosmos_client import CosmosDBClient
from .config import get_settings

logger = structlog.get_logger(__name__)
settings = get_settings()


@dataclass
class ValueMatch:
    """Result of a value matching operation."""
    original_value: str
    matched_value: str
    confidence: float  # 0.0 to 1.0
    match_method: str  # "exact", "fuzzy", "embedding", "alias"


@dataclass
class ValueCatalogEntry:
    """Entry in the value catalog for a low-cardinality column."""
    value: str
    embedding: Optional[List[float]]
    count: int  # Frequency in database
    aliases: List[str] = None  # Known aliases/variations

    def __post_init__(self):
        if self.aliases is None:
            self.aliases = []


class ValueMatchingService:
    """
    Matches user-provided values to exact database values using multiple strategies.
    """

    def __init__(
        self,
        cosmos_client: CosmosDBClient,
        aoai_client: AzureOpenAIClient,
    ):
        self.cosmos_client = cosmos_client
        self.aoai_client = aoai_client
        self.container_name = settings.cosmos.value_mappings_container
        self.match_threshold = settings.text_to_sql.value_match_threshold
        self.logger = logger.bind(service="value_matching")

    async def match_value(
        self,
        table: str,
        column: str,
        user_value: str,
        threshold: Optional[float] = None,
    ) -> Optional[ValueMatch]:
        """
        Match a user-provided value to an exact database value.

        Args:
            table: Table name
            column: Column name
            user_value: Value provided by user (may be fuzzy/incorrect)
            threshold: Minimum confidence threshold (default from config)

        Returns:
            ValueMatch object if a match is found, None otherwise
        """
        threshold = threshold or self.match_threshold

        self.logger.info(
            "Matching value",
            table=table,
            column=column,
            user_value=user_value,
            threshold=threshold,
        )

        # Load value catalog for this column
        catalog = await self._get_value_catalog(table, column)

        if not catalog:
            self.logger.warning("No value catalog found", table=table, column=column)
            return None

        # Strategy 1: Exact match (case-insensitive)
        for entry in catalog:
            if user_value.lower() == entry.value.lower():
                self.logger.info("Exact match found", matched_value=entry.value)
                return ValueMatch(
                    original_value=user_value,
                    matched_value=entry.value,
                    confidence=1.0,
                    match_method="exact",
                )

        # Strategy 2: Alias match
        for entry in catalog:
            for alias in entry.aliases:
                if user_value.lower() == alias.lower():
                    self.logger.info(
                        "Alias match found",
                        matched_value=entry.value,
                        alias=alias,
                    )
                    return ValueMatch(
                        original_value=user_value,
                        matched_value=entry.value,
                        confidence=0.95,
                        match_method="alias",
                    )

        # Strategy 3: Fuzzy string matching
        values_list = [entry.value for entry in catalog]
        fuzzy_result = process.extractOne(
            user_value,
            values_list,
            scorer=fuzz.token_sort_ratio,
        )

        if fuzzy_result:
            matched_value, fuzzy_score, _ = fuzzy_result
            fuzzy_confidence = fuzzy_score / 100.0  # Convert to 0-1 range

            if fuzzy_confidence >= threshold:
                self.logger.info(
                    "Fuzzy match found",
                    matched_value=matched_value,
                    confidence=fuzzy_confidence,
                )
                return ValueMatch(
                    original_value=user_value,
                    matched_value=matched_value,
                    confidence=fuzzy_confidence,
                    match_method="fuzzy",
                )

        # Strategy 4: Embedding-based semantic similarity
        if settings.text_to_sql.enable_embeddings:
            user_embedding = await self.aoai_client.generate_embedding(user_value)

            best_match = None
            best_similarity = 0.0

            for entry in catalog:
                if entry.embedding:
                    similarity = self._cosine_similarity(user_embedding, entry.embedding)
                    if similarity > best_similarity:
                        best_similarity = similarity
                        best_match = entry.value

            if best_similarity >= threshold:
                self.logger.info(
                    "Embedding match found",
                    matched_value=best_match,
                    confidence=best_similarity,
                )
                return ValueMatch(
                    original_value=user_value,
                    matched_value=best_match,
                    confidence=best_similarity,
                    match_method="embedding",
                )

        self.logger.warning("No match found", user_value=user_value)
        return None

    async def match_values_bulk(
        self,
        table: str,
        column: str,
        user_values: List[str],
        threshold: Optional[float] = None,
    ) -> List[Optional[ValueMatch]]:
        """
        Match multiple values in bulk (more efficient).

        Args:
            table: Table name
            column: Column name
            user_values: List of values to match
            threshold: Minimum confidence threshold

        Returns:
            List of ValueMatch objects (None for unmatched values)
        """
        tasks = [
            self.match_value(table, column, value, threshold)
            for value in user_values
        ]
        return await asyncio.gather(*tasks)

    async def build_value_catalog(
        self,
        table: str,
        column: str,
        values: List[str],
        counts: Optional[Dict[str, int]] = None,
        aliases: Optional[Dict[str, List[str]]] = None,
    ) -> bool:
        """
        Build or update the value catalog for a low-cardinality column.

        This should be called:
        - When new distinct values are added to the column
        - Periodically to refresh embeddings
        - When aliases are updated

        Args:
            table: Table name
            column: Column name
            values: List of distinct values in the column
            counts: Optional dict of value -> count (frequency)
            aliases: Optional dict of value -> list of aliases

        Returns:
            True if successful
        """
        try:
            self.logger.info(
                "Building value catalog",
                table=table,
                column=column,
                value_count=len(values),
            )

            # Generate embeddings for all values
            catalog_entries = []
            for value in values:
                embedding = await self.aoai_client.generate_embedding(value)

                entry = {
                    "value": value,
                    "embedding": embedding,
                    "count": counts.get(value, 0) if counts else 0,
                    "aliases": aliases.get(value, []) if aliases else [],
                }

                catalog_entries.append(entry)

            # Create document
            document = {
                "id": f"{table}_{column}",
                "table": table,
                "column": column,
                "cardinality": len(values),
                "values": catalog_entries,
                "last_updated": datetime.utcnow().isoformat(),
            }

            # Upsert to Cosmos DB
            await self.cosmos_client.upsert_item(self.container_name, document)

            self.logger.info(
                "Value catalog built successfully",
                table=table,
                column=column,
                value_count=len(values),
            )

            return True

        except Exception as e:
            self.logger.error(
                "Failed to build value catalog",
                table=table,
                column=column,
                error=str(e),
            )
            return False

    async def _get_value_catalog(
        self,
        table: str,
        column: str,
    ) -> List[ValueCatalogEntry]:
        """
        Load value catalog from Cosmos DB.

        Args:
            table: Table name
            column: Column name

        Returns:
            List of ValueCatalogEntry objects
        """
        query = "SELECT * FROM c WHERE c.table = @table AND c.column = @column"
        parameters = [
            {"name": "@table", "value": table},
            {"name": "@column", "value": column},
        ]

        try:
            results = await self.cosmos_client.query_items(
                self.container_name,
                query,
                parameters=parameters,
            )

            if not results:
                return []

            item = results[0]
            catalog = []

            for value_data in item.get("values", []):
                catalog.append(
                    ValueCatalogEntry(
                        value=value_data.get("value", ""),
                        embedding=value_data.get("embedding"),
                        count=value_data.get("count", 0),
                        aliases=value_data.get("aliases", []),
                    )
                )

            return catalog

        except Exception as e:
            self.logger.error(
                "Failed to load value catalog",
                table=table,
                column=column,
                error=str(e),
            )
            return []

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
