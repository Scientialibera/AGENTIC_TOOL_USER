"""
Azure Cosmos DB Gremlin client with Managed Identity authentication.

This module provides a client for Cosmos DB Gremlin API operations using
DefaultAzureCredential for authentication and proper error handling.
"""

import asyncio
import logging
from typing import Optional, Dict, Any, List, Union
from azure.identity import DefaultAzureCredential
from gremlin_python.driver import client
from gremlin_python.driver.aiohttp import transport
from gremlin_python.driver import serializer
from urllib.parse import urlparse
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)
import structlog

from salesforce_mcp.config.settings import GremlinSettings

logger = structlog.get_logger(__name__)


class GremlinClient:
    """
    Azure Cosmos DB Gremlin client with Managed Identity authentication.
    
    This client handles:
    - Token-based authentication using DefaultAzureCredential
    - Query execution with proper error handling and async support
    - Retry logic for transient failures
    """
    
    def __init__(self, settings: GremlinSettings):
        """
        Initialize the Gremlin client.
        
        Args:
            settings: Gremlin configuration settings
        """
        self.settings = settings
        self._credential = DefaultAzureCredential()
        
        logger.info(
            "Initializing Gremlin client",
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
        """
        Execute a Gremlin query and return results.
        
        Args:
            query: Gremlin query string
            bindings: Optional query parameter bindings
            
        Returns:
            List of query results
        """
        try:
            logger.debug("Executing Gremlin query", query=query, bindings=bindings)
            
            # Create a new client for each query to avoid event loop conflicts
            token = self._credential.get_token("https://cosmos.azure.com/.default")
            
            # Parse endpoint URL to get host and port (support https:// or gremlin://)
            parsed = urlparse(self.settings.endpoint)
            host = parsed.hostname or self.settings.endpoint
            port = parsed.port or 443
            
            # Create client with proper configuration
            gremlin_client = client.Client(
                f"wss://{host}:{port}/gremlin",
                "g",
                username=f"/dbs/{self.settings.database_name}/colls/{self.settings.graph_name}",
                password=token.token,
                message_serializer=serializer.GraphSONSerializersV2d0()
            )
            
            # Execute query synchronously in thread pool to avoid event loop conflicts
            def execute_sync():
                try:
                    # Cosmos pattern: submit(...).all().result()
                    rs = gremlin_client.submit(message=query, bindings=(bindings or {}))
                    return rs.all().result()
                finally:
                    # Always close the client
                    try:
                        gremlin_client.close()
                    except:
                        pass
            
            # Run in thread pool to avoid event loop conflicts
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(None, execute_sync)
            
            logger.debug(
                "Gremlin query executed",
                query=query,
                result_count=len(results),
            )
            
            return results
            
        except Exception as e:
            logger.error(
                "Failed to execute Gremlin query",
                query=query,
                error=str(e),
            )
            raise
    
    async def add_vertex(
        self,
        label: str,
        properties: Dict[str, Any],
        vertex_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Add a vertex to the graph.
        
        Args:
            label: Vertex label
            properties: Vertex properties
            vertex_id: Optional vertex ID
            
        Returns:
            Created vertex data
        """
        query_parts = [f"g.addV('{label}')"]
        bindings = {}
        
        if vertex_id:
            query_parts.append(".property('id', id_val)")
            bindings["id_val"] = vertex_id
        
        for key, value in properties.items():
            param_name = f"prop_{key}"
            query_parts.append(f".property('{key}', {param_name})")
            bindings[param_name] = value
        
        query = "".join(query_parts)
        results = await self.execute_query(query, bindings)
        
        return results[0] if results else {}
    
    async def add_edge(
        self,
        from_vertex_id: str,
        to_vertex_id: str,
        label: str,
        properties: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Add an edge between two vertices.
        
        Args:
            from_vertex_id: Source vertex ID
            to_vertex_id: Target vertex ID
            label: Edge label
            properties: Optional edge properties
            
        Returns:
            Created edge data
        """
        query_parts = [
            "g.V(from_id).addE(edge_label).to(g.V(to_id))"
        ]
        bindings = {
            "from_id": from_vertex_id,
            "to_id": to_vertex_id,
            "edge_label": label,
        }
        
        if properties:
            for key, value in properties.items():
                param_name = f"prop_{key}"
                query_parts.append(f".property('{key}', {param_name})")
                bindings[param_name] = value
        
        query = "".join(query_parts)
        results = await self.execute_query(query, bindings)
        
        return results[0] if results else {}
    
    async def find_vertices(
        self,
        label: Optional[str] = None,
        properties: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Find vertices matching the given criteria.
        
        Args:
            label: Optional vertex label filter
            properties: Optional property filters
            limit: Optional result limit
            
        Returns:
            List of matching vertices
        """
        query_parts = ["g.V()"]
        bindings = {}
        
        if label:
            query_parts.append(f".hasLabel('{label}')")
        
        if properties:
            for key, value in properties.items():
                param_name = f"prop_{key}"
                query_parts.append(f".has('{key}', {param_name})")
                bindings[param_name] = value
        
        if limit:
            query_parts.append(f".limit({limit})")
        
        query = "".join(query_parts)
        return await self.execute_query(query, bindings)
    
    async def find_paths(
        self,
        from_vertex_id: str,
        to_vertex_id: str,
        max_hops: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        Find paths between two vertices.
        
        Args:
            from_vertex_id: Source vertex ID
            to_vertex_id: Target vertex ID
            max_hops: Maximum number of hops
            
        Returns:
            List of paths
        """
        query = f"g.V(from_id).repeat(out().simplePath()).until(hasId(to_id)).limit({max_hops}).path()"
        bindings = {
            "from_id": from_vertex_id,
            "to_id": to_vertex_id,
        }
        
        return await self.execute_query(query, bindings)
    
    async def get_vertex_neighbors(
        self,
        vertex_id: str,
        direction: str = "both",
        edge_label: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Get neighbors of a vertex.
        
        Args:
            vertex_id: Vertex ID
            direction: Direction ('in', 'out', 'both')
            edge_label: Optional edge label filter
            limit: Optional result limit
            
        Returns:
            List of neighbor vertices
        """
        direction_map = {
            "in": "in",
            "out": "out",
            "both": "both",
        }
        
        direction_func = direction_map.get(direction, "both")
        query_parts = [f"g.V(vertex_id).{direction_func}()"]
        bindings = {"vertex_id": vertex_id}
        
        if edge_label:
            query_parts[0] = f"g.V(vertex_id).{direction_func}(edge_label)"
            bindings["edge_label"] = edge_label
        
        if limit:
            query_parts.append(f".limit({limit})")
        
        query = "".join(query_parts)
        return await self.execute_query(query, bindings)
    
    async def close(self):
        """Close the client and clean up resources."""
        logger.info("Gremlin client closed")
