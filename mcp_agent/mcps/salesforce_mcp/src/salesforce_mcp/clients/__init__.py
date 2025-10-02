"""Azure service clients for Salesforce MCP."""

from .fabric_client import FabricLakehouseClient
from .gremlin_client import GremlinClient

__all__ = [
    "FabricLakehouseClient",
    "GremlinClient",
]
